"""Create and verify a consistent local SQLite backup."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime

from catalog import DATA_DIR, DB_PATH, update_job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', type=int, default=14)
    args = parser.parse_args()
    backup_dir = DATA_DIR / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = backup_dir / f'library-{datetime.now():%Y%m%d-%H%M%S}.db'
    update_job('backup', 'running')
    try:
        with sqlite3.connect(DB_PATH) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        destination.chmod(0o600)
        with sqlite3.connect(destination) as check:
            result = check.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise RuntimeError(f'backup integrity check failed: {result}')
        backups = sorted(backup_dir.glob('library-*.db'), reverse=True)
        for old in backups[max(1, args.keep):]:
            old.unlink()
        update_job('backup', 'ready', 1, 1)
        print(destination)
        return 0
    except Exception as exc:
        destination.unlink(missing_ok=True)
        update_job('backup', 'error', error=str(exc)[:500])
        raise


if __name__ == '__main__':
    raise SystemExit(main())
