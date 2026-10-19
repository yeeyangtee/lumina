"""Enrich catalogue rows with EXIF and lightweight file metadata."""

from __future__ import annotations

from job_lock import single_job

import argparse
import re
import subprocess
import imageio_ffmpeg
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PIL import Image

from app import BASE_DIRS, get_exif_info
from catalog import connect_db, init_db, update_job


def _captured(value: str | None, mtime_ns: int):
    # Copy/scan mtimes do not establish when a photograph was taken.
    if value:
        for pattern in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                dt = datetime.strptime(value, pattern)
                return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.year
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.year
        except ValueError:
            pass
    return None, None


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
                    exif = image.getexif()
                    raw_taken = exif.get_ifd(34665).get(36867) or exif.get(36867)
                    if raw_taken:
                        info['taken'] = str(raw_taken)
                except Exception:
                    pass
    else:
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        probe = subprocess.run(
            [ff, '-nostdin', '-hide_banner', '-i', str(path)],
            capture_output=True,
            text=True,
            timeout=45,
        )
        date = re.search(r'creation_time\s*:\s*([^\n]+)', probe.stderr)
        if date:
            info['taken'] = date[1].strip()
    captured_at, captured_year = _captured(info.get('taken'), row['mtime_ns'])
    parts = Path(row['subpath']).parts
    if (
        row['collection'] == 'family_photos'
        and len(parts) > 1
        and parts[0] == 'childhood'
    ):
        if parts[1] == 'unknown_year':
            captured_at = captured_year = None
        elif re.fullmatch(r'(19|20)\d{2}', parts[1]):
            year = int(parts[1])
            if captured_year != year:
                captured_at = None
            captured_year = year

    gps = info.get('gps') or {}
    return (
        row['id'],
        row['mtime_ns'],
        captured_at,
        captured_year,
        info.get('camera'),
        info.get('lens'),
        width,
        height,
        gps.get('lat'),
        gps.get('lon'),
    )


@single_job('metadata')
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--limit',
        type=int,
        default=0,
        help='maximum rows this run; 0 processes all pending rows',
    )
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
                            """UPDATE media_items SET
                                   captured_at = ?, captured_year = ?, camera = ?, lens = ?,
                                   width = ?, height = ?, latitude = ?, longitude = ?,
                                   metadata_status = 'ready', metadata_error = NULL
                               WHERE id = ? AND mtime_ns = ?""",
                            result[2:] + result[:2],
                        )
                except Exception as exc:
                    errors += 1
                    with connect_db() as db:
                        db.execute(
                            "UPDATE media_items SET metadata_status = 'error', metadata_error = ? "
                            'WHERE id = ?',
                            (f'{type(exc).__name__}: {exc}'[:500], row['id']),
                        )
                processed += 1
                if processed % 100 == 0:
                    update_job('metadata', 'running', processed, total)
                    print(f'metadata: {processed}/{len(rows)}', flush=True)
        update_job(
            'metadata',
            'ready',
            processed,
            total,
            f'{errors} unreadable files' if errors else None,
        )
        print(f'metadata: processed {processed}, errors {errors}')
        return 0
    except Exception as exc:
        update_job('metadata', 'error', processed, total, str(exc)[:500])
        raise


if __name__ == '__main__':
    raise SystemExit(main())
