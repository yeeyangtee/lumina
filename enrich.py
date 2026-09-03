"""Enrich catalogue rows with EXIF and lightweight file metadata."""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import Image

from app import BASE_DIRS, get_exif_info
from catalog import connect_db, init_db, update_job


def _captured(value: str | None, mtime_ns: int) -> tuple[str, int]:
    if value:
        for pattern in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                parsed = datetime.strptime(value, pattern)
                return parsed.strftime('%Y-%m-%d %H:%M:%S'), parsed.year
            except ValueError:
                pass
    parsed = datetime.fromtimestamp(mtime_ns / 1_000_000_000)
    return parsed.strftime('%Y-%m-%d %H:%M:%S'), parsed.year


def _read_metadata(row: dict) -> tuple:
    path = BASE_DIRS[row['collection']] / row['subpath']
    info = {}
    width = height = None
    if row['media_type'] == 'image':
        info = get_exif_info(path)
        with Image.open(path) as image:
            width, height = image.size
            if not info.get('taken'):
                try:
                    raw_taken = image.getexif().get(36867)
                    if raw_taken:
                        info['taken'] = str(raw_taken)
                except Exception:
                    pass
    captured_at, captured_year = _captured(info.get('taken'), row['mtime_ns'])
    gps = info.get('gps') or {}
    return (
        row['id'], row['mtime_ns'], captured_at, captured_year,
        info.get('camera'), info.get('lens'), width, height,
        gps.get('lat'), gps.get('lon'),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0,
                        help='maximum rows this run; 0 processes all pending rows')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    init_db()
    statuses = "('pending', 'error')" if args.retry_errors else "('pending')"
    with connect_db() as db:
        total = db.execute(
            f'SELECT COUNT(*) FROM media_items WHERE metadata_status IN {statuses}'
        ).fetchone()[0]
        sql = (
            'SELECT id, collection, subpath, media_type, mtime_ns FROM media_items '
            f'WHERE metadata_status IN {statuses} ORDER BY id'
        )
        if args.limit > 0:
            sql += f' LIMIT {int(args.limit)}'
        rows = [dict(row) for row in db.execute(sql)]

    update_job('metadata', 'running', 0, total)
    processed = errors = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = [(row, pool.submit(_read_metadata, row)) for row in rows]
            for row, future in futures:
                try:
                    result = future.result()
                    with connect_db() as db:
                        db.execute(
                            '''UPDATE media_items SET
                                   captured_at = ?, captured_year = ?, camera = ?, lens = ?,
                                   width = ?, height = ?, latitude = ?, longitude = ?,
                                   metadata_status = 'ready', metadata_error = NULL
                               WHERE id = ? AND mtime_ns = ?''',
                            result[2:] + result[:2],
                        )
                except Exception as exc:
                    errors += 1
                    with connect_db() as db:
                        db.execute(
                            "UPDATE media_items SET metadata_status = 'error', metadata_error = ? "
                            'WHERE id = ?', (f'{type(exc).__name__}: {exc}'[:500], row['id'])
                        )
                processed += 1
                if processed % 100 == 0:
                    update_job('metadata', 'running', processed, total)
                    print(f'metadata: {processed}/{len(rows)}', flush=True)
        update_job('metadata', 'ready', processed, total,
                   f'{errors} unreadable files' if errors else None)
        print(f'metadata: processed {processed}, errors {errors}')
        return 0
    except Exception as exc:
        update_job('metadata', 'error', processed, total, str(exc)[:500])
        raise


if __name__ == '__main__':
    raise SystemExit(main())
