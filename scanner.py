"""Incrementally catalogue media from the configured SMB collections."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from app import BASE_DIRS, is_media, is_video
from catalog import (
    connect_db,
    init_db,
    mark_scan_finished,
    mark_scan_started,
)


BATCH_SIZE = 250


def iter_media(root: Path):
    """Yield (relative path, stat) using one scandir traversal."""
    stack = [(root, Path())]
    while stack:
        directory, relative_dir = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                relative = relative_dir / entry.name
                if entry.is_dir(follow_symlinks=False):
                    stack.append((Path(entry.path), relative))
                elif entry.is_file(follow_symlinks=False) and is_media(entry.name):
                    yield relative, entry.stat(follow_symlinks=False)


def _write_batch(collection: str, marker: str, rows: list[tuple]) -> None:
    now = time.time()
    with connect_db() as conn:
        conn.executemany(
            '''INSERT INTO media_items
                   (collection, subpath, parent, name, media_type, extension,
                    size, mtime_ns, indexed_at, last_seen_scan)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(collection, subpath) DO UPDATE SET
                   parent = excluded.parent,
                   name = excluded.name,
                   media_type = excluded.media_type,
                   extension = excluded.extension,
                   size = excluded.size,
                   mtime_ns = excluded.mtime_ns,
                   indexed_at = excluded.indexed_at,
                   last_seen_scan = excluded.last_seen_scan,
                   metadata_status = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN 'pending' ELSE media_items.metadata_status END,
                   metadata_error = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN NULL ELSE media_items.metadata_error END,
                   poster_status = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN 'pending' ELSE media_items.poster_status END,
                   embedding_status = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN 'pending' ELSE media_items.embedding_status END,
                   embedding = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN NULL ELSE media_items.embedding END,
                   embedding_model = CASE
                       WHEN media_items.size != excluded.size
                         OR media_items.mtime_ns != excluded.mtime_ns
                       THEN NULL ELSE media_items.embedding_model END''',
            [row + (now, marker) for row in rows],
        )


def scan_collection(collection: str, root: Path) -> bool:
    if not root.is_dir():
        message = f'not mounted: {root}'
        mark_scan_finished(collection, 'unmounted', 0, message)
        print(f'{collection}: {message}', file=sys.stderr)
        # An unavailable NAS is an expected condition. Record it for the UI but
        # let the timer complete successfully so systemd does not treat it as a
        # crashed indexing process.
        return True

    marker = uuid.uuid4().hex
    mark_scan_started(collection)
    count = 0
    batch: list[tuple] = []
    try:
        for relative, stat in iter_media(root):
            subpath = relative.as_posix()
            parent = relative.parent.as_posix()
            if parent == '.':
                parent = ''
            batch.append((
                collection,
                subpath,
                parent,
                relative.name,
                'video' if is_video(relative.name) else 'image',
                relative.suffix.lower(),
                stat.st_size,
                stat.st_mtime_ns,
            ))
            count += 1
            if len(batch) >= BATCH_SIZE:
                _write_batch(collection, marker, batch)
                batch.clear()
        if batch:
            _write_batch(collection, marker, batch)

        # Only remove missing entries after a completely successful traversal.
        with connect_db() as conn:
            conn.execute(
                'DELETE FROM media_items WHERE collection = ? AND last_seen_scan != ?',
                (collection, marker),
            )
        mark_scan_finished(collection, 'ready', count)
        print(f'{collection}: indexed {count} media files')
        return True
    except OSError as exc:
        message = f'{type(exc).__name__}: {exc}'
        mark_scan_finished(collection, 'error', count, message)
        print(f'{collection}: scan failed after {count} files: {message}', file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--collection', action='append', choices=sorted(BASE_DIRS),
        help='scan only this collection (repeatable)',
    )
    args = parser.parse_args()
    init_db()
    selected = args.collection or list(BASE_DIRS)
    results = [scan_collection(name, BASE_DIRS[name]) for name in selected]
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
