"""Resumable refresh of ready images into the current local thumbnail cache.

No source or media-row updates. New photos use the existing preview worker.
Per-version thumbnail files provide coverage; errors need --retry-errors.
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import BASE_DIRS, THUMB_CACHE, THUMB_VERSION, _thumb_cache_file, get_or_create_thumb
from catalog import connect_db, update_job
from job_lock import single_job


ERRORS = THUMB_CACHE / 'errors.json'
REPORT = THUMB_CACHE / 'refresh-report.json'


def _write_json(path, value):
    temporary = path.with_suffix(f'.{os.getpid()}.tmp')
    try:
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@single_job('thumbnails')
def refresh(*, limit=0, workers=4, retry_errors=False):
    started = time.monotonic()
    errors = json.loads(ERRORS.read_text()) if ERRORS.exists() else {}
    with connect_db() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT id,collection,subpath,size,mtime_ns FROM media_items "
            "WHERE media_type='image' AND preview_status='ready' ORDER BY id"
        )]
    # Coverage checks only inspect local cache names, not NAS file metadata.
    present = {entry.name for entry in THUMB_CACHE.iterdir() if entry.suffix == '.jpg'}
    pending, cached, held = [], 0, 0
    active_keys = set()
    for row in rows:
        source = BASE_DIRS[row['collection']] / row['subpath']
        target = _thumb_cache_file(source, source_version=(row['size'], row['mtime_ns']))
        key = target.name
        active_keys.add(key)
        if key in present:
            cached += 1
            errors.pop(key, None)
        elif key in errors and not retry_errors:
            held += 1
        else:
            pending.append((row, source, key))
    selected = pending[:limit] if limit > 0 else pending
    update_job('thumbnails', 'running', 0, len(selected))

    def process(item):
        row, source, key = item
        try:
            before = source.stat()
            if (before.st_size, before.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source version changed; wait for the scanner')
            if not get_or_create_thumb(source):
                raise OSError('Thumbnail preparation failed')
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source changed during preparation')
            return key, None
        except Exception as exc:
            return key, {
                'collection': row['collection'], 'subpath': row['subpath'],
                'size': row['size'], 'mtime_ns': row['mtime_ns'],
                'error': f'{type(exc).__name__}: {exc}'[:500],
            }

    generated = failed = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
            futures = [pool.submit(process, item) for item in selected]
            for processed, future in enumerate(as_completed(futures), 1):
                key, error = future.result()
                if error:
                    errors[key] = error
                    failed += 1
                else:
                    errors.pop(key, None)
                    generated += 1
                if processed % 100 == 0:
                    _write_json(ERRORS, errors)
                    update_job('thumbnails', 'running', processed, len(selected))
                    print(f'thumbnails: {processed}/{len(selected)}, errors={failed}', flush=True)
    except BaseException:
        _write_json(ERRORS, errors)
        update_job('thumbnails', 'error', generated + failed, len(selected), 'Interrupted; rerun to resume')
        raise
    _write_json(ERRORS, errors)
    remaining_errors = sum(key in active_keys for key in errors)
    report = {
        'version': THUMB_VERSION, 'eligible_images': len(rows),
        'cached_before': cached, 'generated_this_run': generated,
        'ready': cached + generated, 'errors_this_run': failed,
        'error_count': remaining_errors, 'held_errors': held,
        'remaining_unattempted': len(pending) - len(selected),
        'seconds': round(time.monotonic() - started, 3),
    }
    _write_json(REPORT, report)
    update_job('thumbnails', 'ready', len(selected), len(selected),
               f'{remaining_errors} thumbnail errors' if remaining_errors else None)
    print(json.dumps(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    refresh(limit=args.limit, workers=args.workers, retry_errors=args.retry_errors)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
