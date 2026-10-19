"""Incrementally catalogue media from the configured SMB collections."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from config import load_base_dirs
from formats import is_media, is_video, AUDIO_EXTS
from library_metadata import read_album
import json
import stat
import subprocess
import sqlite3

BASE_DIRS = load_base_dirs()
from catalog import (
    connect_db,
    init_db,
    mark_scan_finished,
    mark_scan_started,
)


BATCH_SIZE = 250


def _write_batch(conn, collection: str, marker: str, rows: list[tuple]) -> None:
    now = time.time()
    conn.executemany(
        """INSERT INTO media_items
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
                   preview_status = CASE WHEN media_items.size != excluded.size OR media_items.mtime_ns != excluded.mtime_ns THEN 'pending' ELSE media_items.preview_status END,
                   preview_error = CASE WHEN media_items.size != excluded.size OR media_items.mtime_ns != excluded.mtime_ns THEN NULL ELSE media_items.preview_error END,
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
                       THEN NULL ELSE media_items.embedding_model END""",
        [row + (now, marker) for row in rows],
    )


def guard_root(root):
    # Production roots must still be the intended CIFS share, not an empty local mountpoint.
    if str(root).startswith('/mnt/yeeyang/'):
        p = subprocess.run(
            [
                'findmnt',
                '--mountpoint',
                '/mnt/yeeyang',
                '--types',
                'cifs',
                '--json',
                '--output',
                'SOURCE',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if (
            p.returncode
            or json.loads(p.stdout)['filesystems'][0]['source']
            != '//192.168.0.12/yeeyang'
        ):
            raise OSError('Expected NAS mount unavailable')
    if root.is_symlink() or not root.is_dir():
        raise OSError('Collection unavailable')
    for parent in root.parents:
        if parent.is_symlink():
            raise OSError('Symlink collection ancestor')


def scan_collection(collection: str, root: Path, allow_prune=False) -> bool:
    marker = uuid.uuid4().hex
    count = 0
    try:
        guard_root(root)
        mark_scan_started(collection)
        rows = []
        audio = []
        source_albums = []
        # One metadata traversal; originals are never opened here.
        stack = [root]
        device = root.stat().st_dev
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for e in entries:
                    if e.name.startswith('.'):
                        continue
                    if e.is_symlink():
                        raise OSError('Symlink rejected')
                    st = e.stat(follow_symlinks=False)
                    if st.st_dev != device:
                        raise OSError('Filesystem boundary rejected')
                    path = Path(e.path)
                    rel = path.relative_to(root)
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(path)
                    elif not stat.S_ISREG(st.st_mode):
                        raise OSError('Special file rejected')
                    elif e.name == 'album.json' and len(rel.parts) == 2:
                        m = read_album(path)
                        source_albums.append((m, rel.parent.as_posix()))
                    elif is_media(e.name):
                        parent = rel.parent.as_posix()
                        parent = '' if parent == '.' else parent
                        rows.append(
                            (
                                collection,
                                rel.as_posix(),
                                parent,
                                e.name,
                                'video' if is_video(e.name) else 'image',
                                rel.suffix.lower(),
                                st.st_size,
                                st.st_mtime_ns,
                            )
                        )
                        count += 1
                    elif rel.suffix.lower() in AUDIO_EXTS:
                        parent = rel.parent.as_posix()
                        audio.append(
                            (
                                collection,
                                rel.as_posix(),
                                '' if parent == '.' else parent,
                                e.name,
                                st.st_size,
                                st.st_mtime_ns,
                            )
                        )
        guard_root(root)
        with connect_db() as conn:
            previous = conn.execute(
                'SELECT COUNT(*) FROM media_items WHERE collection=?', (collection,)
            ).fetchone()[0]
            if previous and not rows:
                raise OSError('Empty scan held;previous catalogue retained')
            if not allow_prune:
                previous_albums = {
                    r['album_id']: r['media_count']
                    for r in conn.execute(
                        'SELECT album_id,media_count FROM source_albums WHERE collection=?',
                        (collection,),
                    )
                }
                current_albums = {
                    m['album_id']: sum(row[1].startswith(aroot + '/') for row in rows)
                    for m, aroot in source_albums
                }
                if any(
                    k not in current_albums or (v and not current_albums[k])
                    for k, v in previous_albums.items()
                ):
                    raise OSError(
                        'Missing or empty album held;explicit prune approval required'
                    )
                if previous - count > max(25, previous // 20):
                    raise OSError(
                        'Large catalogue reduction held;explicit prune approval required'
                    )
            conn.execute('BEGIN IMMEDIATE')
            for start in range(0, len(rows), BATCH_SIZE):
                _write_batch(conn, collection, marker, rows[start : start + BATCH_SIZE])
            conn.execute(
                'DELETE FROM media_items WHERE collection=? AND last_seen_scan!=?',
                (collection, marker),
            )
            conn.execute('DELETE FROM source_albums WHERE collection=?', (collection,))
            for m, album_root in source_albums:
                conn.execute(
                    'INSERT INTO source_albums VALUES (?,?,?,?,?,?,?,?)',
                    (
                        m['album_id'],
                        collection,
                        album_root,
                        m['title'],
                        m['description'],
                        m['date']['value'],
                        json.dumps(m),
                        sum(row[1].startswith(album_root + '/') for row in rows),
                    ),
                )
            conn.execute('DELETE FROM audio_items WHERE collection=?', (collection,))
            conn.executemany('INSERT INTO audio_items VALUES (?,?,?,?,?,?)', audio)
        mark_scan_finished(collection, 'ready', count)
        print(
            f'{collection}: indexed {count} media files, {len(source_albums)} albums, {len(audio)} audio files',
            flush=True,
        )
        return True
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        mark_scan_finished(collection, 'error', count, str(exc)[:300])
        print(f'{collection}: scan held: {exc}', file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--collection',
        action='append',
        choices=sorted(BASE_DIRS),
        help='scan only this collection (repeatable)',
    )
    parser.add_argument(
        '--allow-prune',
        action='store_true',
        help='explicitly accept reviewed album removals or large catalogue reductions',
    )
    args = parser.parse_args()
    init_db()
    selected = args.collection or list(BASE_DIRS)
    results = [
        scan_collection(name, BASE_DIRS[name], args.allow_prune) for name in selected
    ]
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
