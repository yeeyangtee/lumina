"""Generate local JPEG poster frames for indexed videos."""

from __future__ import annotations

from job_lock import single_job

import argparse
import subprocess
import os

import imageio_ffmpeg

from app import BASE_DIRS
from catalog import connect_db, init_db, update_job
from media_cache import poster_cache_file


@single_job('posters')
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--limit',
        type=int,
        default=0,
        help='maximum rows this run; 0 processes all pending videos',
    )
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    init_db()
    statuses = "('pending', 'error')" if args.retry_errors else "('pending')"
    with connect_db() as db:
        total = db.execute(
            f"SELECT COUNT(*) FROM media_items WHERE media_type = 'video' "
            f'AND poster_status IN {statuses}'
        ).fetchone()[0]
        sql = (
            "SELECT id, collection, subpath,size,mtime_ns FROM media_items WHERE media_type = 'video' "
            f'AND poster_status IN {statuses} ORDER BY id'
        )
        if args.limit > 0:
            sql += f' LIMIT {int(args.limit)}'
        rows = [dict(row) for row in db.execute(sql)]
    update_job('posters', 'running', 0, total)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    processed = errors = 0
    for row in rows:
        source = BASE_DIRS[row['collection']] / row['subpath']
        target = poster_cache_file(source)
        temp = target.with_suffix(f'.{os.getpid()}.tmp.jpg')
        try:
            st = source.stat()
            if (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source changed')
            # A valid sub-second video has no frame at t=1;fall back to its start.
            for seek in ('1', '0'):
                result = subprocess.run(
                    [
                        ffmpeg,
                        '-nostdin',
                        '-hide_banner',
                        '-loglevel',
                        'error',
                        '-ss',
                        seek,
                        '-i',
                        str(source),
                        '-frames:v',
                        '1',
                        '-vf',
                        'thumbnail,scale=600:600:force_original_aspect_ratio=decrease',
                        '-q:v',
                        '4',
                        '-y',
                        str(temp),
                    ],
                    timeout=120,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                if result.returncode == 0 and temp.is_file() and temp.stat().st_size:
                    break
                temp.unlink(missing_ok=True)
            else:
                raise OSError('No decodable video poster frame')
            st = source.stat()
            if (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source changed')
            temp.replace(target)
            target.chmod(0o600)
            with connect_db() as db:
                db.execute(
                    "UPDATE media_items SET poster_status = 'ready' WHERE id = ? AND size=? AND mtime_ns=?",
                    (row['id'], row['size'], row['mtime_ns']),
                )
        except Exception as exc:
            errors += 1
            temp.unlink(missing_ok=True)
            with connect_db() as db:
                db.execute(
                    "UPDATE media_items SET poster_status = 'error' WHERE id = ? AND size=? AND mtime_ns=?",
                    (row['id'], row['size'], row['mtime_ns']),
                )
            print(f'poster failed: {row["collection"]}/{row["subpath"]}: {exc}')
        processed += 1
        if processed % 20 == 0:
            update_job('posters', 'running', processed, total)
    update_job(
        'posters', 'ready', processed, total, f'{errors} failed' if errors else None
    )
    print(f'posters: processed {processed}, errors {errors}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
