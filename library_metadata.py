"""Validated source-album metadata cached locally during successful scans."""

import json
import uuid
from pathlib import Path
from catalog import connect_db


def read_album(path):
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Unsafe album metadata')
    before = path.stat()
    m = json.loads(path.read_text())
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError('Album metadata changed during scan')
    required = {
        'schema_version',
        'album_id',
        'title',
        'date',
        'description',
        'subfolders',
        'cleanup_tasks',
    }
    if set(m) != required or m['schema_version'] != 1:
        raise ValueError('Invalid album schema')
    if not isinstance(m['album_id'], str):
        raise ValueError('Invalid album identity')
    uuid.UUID(m['album_id'])
    if not isinstance(m['title'], str) or not m['title'].strip():
        raise ValueError('Missing title')
    if m['description'] is not None and not isinstance(m['description'], str):
        raise ValueError('Invalid description')
    if not isinstance(m['date'], dict) or set(m['date']) != {'value', 'source'}:
        raise ValueError('Invalid date')
    import re
    import datetime

    value = m['date']['value']
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}(?:-\d{2}(?:-\d{2})?)?', value
        ):
            raise ValueError('Invalid album date')
        datetime.date.fromisoformat(
            value + ('-01-01' if len(value) == 4 else '-01' if len(value) == 7 else '')
        )
    if m['date']['source'] not in ('owner', 'folder_name', 'filename', 'unknown'):
        raise ValueError('Invalid provenance')
    if not isinstance(m['subfolders'], list) or not isinstance(
        m['cleanup_tasks'], list
    ):
        raise ValueError('Invalid lists')
    for s in m['subfolders']:
        if set(s) != {'path', 'description'} or not isinstance(s['path'], str):
            raise ValueError('Invalid subfolder')
        q = Path(s['path'])
        if q.is_absolute() or '..' in q.parts or not q.parts:
            raise ValueError('Unsafe subfolder')
        if s['description'] is not None and not isinstance(s['description'], str):
            raise ValueError('Invalid subfolder description')
    for t in m['cleanup_tasks']:
        if (
            set(t) != {'id', 'description', 'status'}
            or t['status'] not in ('pending', 'done', 'not_needed')
            or not all(isinstance(t[k], str) for k in t)
        ):
            raise ValueError('Invalid cleanup task')
    return m


def albums(collection=None):
    with connect_db() as db:
        rows = db.execute(
            'SELECT * FROM source_albums'
            + (' WHERE collection=?' if collection else '')
            + " ORDER BY COALESCE(date_value,'') DESC,title COLLATE NOCASE",
            ([collection] if collection else []),
        ).fetchall()
    result = []
    for row in rows:
        a = dict(row)
        a['metadata'] = json.loads(a.pop('body'))
        result.append(a)
    return result


def context(collection, subpath):
    return next(
        (
            a
            for a in albums(collection)
            if subpath == a['root'] or subpath.startswith(a['root'] + '/')
        ),
        None,
    )
