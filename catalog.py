"""Local SQLite media catalogue.

The catalogue is deliberately local: web searches should never recursively walk
the SMB share. scanner.py owns catalogue refreshes while request handlers only
perform quick SQLite reads.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path


DATA_DIR = Path(
    os.environ.get('NFS_VIEWER_DATA_DIR', '~/.cache/nfs_image_viewer')
).expanduser()
DB_PATH = DATA_DIR / 'library.db'
LEGACY_FAVORITES_DB = DATA_DIR / 'favorites.db'
SCHEMA_VERSION = 2


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The catalogue will eventually contain accounts and semantic metadata, so
    # keep it private even when the launching shell has a permissive umask.
    DATA_DIR.chmod(0o700)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 30000')
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS media_items (
                id INTEGER PRIMARY KEY,
                collection TEXT NOT NULL,
                subpath TEXT NOT NULL,
                parent TEXT NOT NULL,
                name TEXT NOT NULL,
                media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
                extension TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                indexed_at REAL NOT NULL,
                last_seen_scan TEXT NOT NULL,
                captured_at TEXT,
                captured_year INTEGER,
                camera TEXT,
                lens TEXT,
                width INTEGER,
                height INTEGER,
                latitude REAL,
                longitude REAL,
                metadata_status TEXT NOT NULL DEFAULT 'pending',
                metadata_error TEXT,
                poster_status TEXT NOT NULL DEFAULT 'pending',
                embedding BLOB,
                embedding_model TEXT,
                embedding_status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE (collection, subpath)
            );
            CREATE INDEX IF NOT EXISTS media_collection_name
                ON media_items (collection, name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS media_collection_parent
                ON media_items (collection, parent);
            CREATE INDEX IF NOT EXISTS media_last_seen
                ON media_items (collection, last_seen_scan);

            CREATE TABLE IF NOT EXISTS scan_state (
                collection TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at REAL,
                completed_at REAL,
                files_seen INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS favorites (
                collection TEXT NOT NULL,
                subpath TEXT NOT NULL,
                created REAL NOT NULL,
                PRIMARY KEY (collection, subpath)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                last_login_at REAL
            );

            CREATE TABLE IF NOT EXISTS user_favorites (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
                created_at REAL NOT NULL,
                PRIMARY KEY (user_id, media_id)
            );
            CREATE INDEX IF NOT EXISTS user_favorites_created
                ON user_favorites (user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS albums (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (user_id, name)
            );

            CREATE TABLE IF NOT EXISTS album_items (
                album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
                media_id INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
                created_at REAL NOT NULL,
                PRIMARY KEY (album_id, media_id)
            );
            CREATE INDEX IF NOT EXISTS album_items_created
                ON album_items (album_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS schema_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_state (
                job TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at REAL,
                completed_at REAL,
                processed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            '''
        )
        _add_media_columns(conn)
        conn.executescript(
            '''CREATE INDEX IF NOT EXISTS media_captured_year
                   ON media_items (captured_year);
               CREATE INDEX IF NOT EXISTS media_metadata_status
                   ON media_items (metadata_status);
               CREATE INDEX IF NOT EXISTS media_embedding_status
                   ON media_items (embedding_status, embedding_model);
               CREATE INDEX IF NOT EXISTS media_poster_status
                   ON media_items (media_type, poster_status);'''
        )
        conn.execute(
            "INSERT INTO schema_info(key, value) VALUES ('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
    _migrate_legacy_favorites()


def _add_media_columns(conn: sqlite3.Connection) -> None:
    """Idempotently upgrade catalogues created before schema version 2."""
    existing = {row['name'] for row in conn.execute('PRAGMA table_info(media_items)')}
    columns = {
        'captured_at': 'TEXT',
        'captured_year': 'INTEGER',
        'camera': 'TEXT',
        'lens': 'TEXT',
        'width': 'INTEGER',
        'height': 'INTEGER',
        'latitude': 'REAL',
        'longitude': 'REAL',
        'metadata_status': "TEXT NOT NULL DEFAULT 'pending'",
        'metadata_error': 'TEXT',
        'poster_status': "TEXT NOT NULL DEFAULT 'pending'",
        'embedding': 'BLOB',
        'embedding_model': 'TEXT',
        'embedding_status': "TEXT NOT NULL DEFAULT 'pending'",
    }
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE media_items ADD COLUMN {name} {declaration}')


def _migrate_legacy_favorites() -> None:
    """Copy the pre-catalogue favorites database once, without deleting it."""
    if not LEGACY_FAVORITES_DB.exists() or LEGACY_FAVORITES_DB == DB_PATH:
        return
    try:
        old = sqlite3.connect(LEGACY_FAVORITES_DB)
        rows = old.execute(
            'SELECT collection, subpath, created FROM favorites'
        ).fetchall()
        old.close()
    except sqlite3.Error:
        return
    if not rows:
        return
    with connect_db() as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO favorites (collection, subpath, created) '
            'VALUES (?, ?, ?)', rows
        )


def search_media(collection: str, query: str, limit: int) -> tuple[list[str], bool]:
    """Return collection-relative paths matching a filename or folder."""
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    pattern = f'%{escaped}%'
    with connect_db() as conn:
        rows = conn.execute(
            '''SELECT subpath
               FROM media_items
               WHERE collection = ?
                 AND (name LIKE ? ESCAPE '\\' COLLATE NOCASE
                      OR parent LIKE ? ESCAPE '\\' COLLATE NOCASE)
               ORDER BY subpath COLLATE NOCASE
               LIMIT ?''',
            (collection, pattern, pattern, limit + 1),
        ).fetchall()
    return [row['subpath'] for row in rows[:limit]], len(rows) > limit


def search_catalog(query: str = '', collection: str | None = None,
                   year: int | None = None, media_type: str | None = None,
                   camera: str | None = None, favorite_user_id: int | None = None,
                   limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
    """Search indexed paths and metadata, returning lightweight media records."""
    where: list[str] = []
    params: list[object] = []
    joins = ''
    if collection:
        where.append('m.collection = ?')
        params.append(collection)
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f'%{escaped}%'
        where.append(
            "(m.name LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "OR m.parent LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "OR m.camera LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "OR m.lens LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        params.extend((pattern, pattern, pattern, pattern))
    if year:
        where.append('m.captured_year = ?')
        params.append(year)
    if media_type in ('image', 'video'):
        where.append('m.media_type = ?')
        params.append(media_type)
    if camera:
        where.append('m.camera = ?')
        params.append(camera)
    if favorite_user_id is not None:
        joins += ' JOIN user_favorites uf ON uf.media_id = m.id AND uf.user_id = ?'
        params.insert(0, favorite_user_id)
    predicate = ' WHERE ' + ' AND '.join(where) if where else ''
    with connect_db() as conn:
        total = conn.execute(
            f'SELECT COUNT(*) FROM media_items m{joins}{predicate}', params
        ).fetchone()[0]
        rows = conn.execute(
            f'''SELECT m.id, m.collection, m.subpath, m.name, m.media_type,
                       m.captured_at, m.captured_year, m.camera, m.width, m.height
                FROM media_items m{joins}{predicate}
                ORDER BY COALESCE(m.captured_at, '') DESC, m.subpath COLLATE NOCASE
                LIMIT ? OFFSET ?''',
            params + [limit, offset],
        ).fetchall()
    return [dict(row) for row in rows], total


def media_id_for(collection: str, subpath: str) -> int | None:
    with connect_db() as conn:
        row = conn.execute(
            'SELECT id FROM media_items WHERE collection = ? AND subpath = ?',
            (collection, subpath),
        ).fetchone()
    return row['id'] if row else None


def scan_status(collection: str) -> dict | None:
    with connect_db() as conn:
        row = conn.execute(
            'SELECT status, started_at, completed_at, files_seen, error '
            'FROM scan_state WHERE collection = ?', (collection,)
        ).fetchone()
    return dict(row) if row else None


def mark_scan_started(collection: str) -> None:
    now = time.time()
    with connect_db() as conn:
        conn.execute(
            '''INSERT INTO scan_state
                   (collection, status, started_at, completed_at, files_seen, error)
               VALUES (?, 'running', ?, NULL, 0, NULL)
               ON CONFLICT(collection) DO UPDATE SET
                   status = 'running', started_at = excluded.started_at,
                   files_seen = 0, error = NULL''',
            (collection, now),
        )


def mark_scan_finished(collection: str, status: str, files_seen: int,
                       error: str | None = None) -> None:
    with connect_db() as conn:
        conn.execute(
            '''INSERT INTO scan_state
                   (collection, status, started_at, completed_at, files_seen, error)
               VALUES (?, ?, NULL, ?, ?, ?)
               ON CONFLICT(collection) DO UPDATE SET
                   status = excluded.status,
                   completed_at = excluded.completed_at,
                   files_seen = excluded.files_seen,
                   error = excluded.error''',
            (collection, status, time.time(), files_seen, error),
        )


def update_job(job: str, status: str, processed: int = 0, total: int = 0,
               error: str | None = None) -> None:
    now = time.time()
    with connect_db() as conn:
        conn.execute(
            '''INSERT INTO job_state
                   (job, status, started_at, completed_at, processed, total, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job) DO UPDATE SET
                   status = excluded.status,
                   started_at = CASE WHEN excluded.status = 'running'
                                     THEN excluded.started_at ELSE job_state.started_at END,
                   completed_at = CASE WHEN excluded.status IN ('ready', 'error')
                                       THEN excluded.completed_at ELSE NULL END,
                   processed = excluded.processed,
                   total = excluded.total,
                   error = excluded.error''',
            (job, status, now if status == 'running' else None,
             now if status in ('ready', 'error') else None,
             processed, total, error),
        )
