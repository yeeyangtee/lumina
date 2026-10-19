"""Reuse version-matched local derivatives after an approved path reorganization.

Only media-derived fields are imported; accounts, keys and user lists are never
read or changed. Pass a verified historical SQLite backup and the reviewed alias
CSV explicitly. All writes stay in local app data.
"""

import argparse
import csv
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
import numpy as np
from PIL import Image
from config import load_base_dirs
from catalog import DATA_DIR, connect_db


def resolve_alias(path, aliases):
    seen = set()
    while path not in seen:
        seen.add(path)
        if path in aliases:
            new = aliases[path]
        else:
            parent = path
            while '/' in parent:
                parent = parent.rsplit('/', 1)[0]
                if parent in aliases:
                    break
            else:
                return path
            new = aliases[parent] + path[len(parent) :]
        if new == path:
            return path
        path = new
    raise ValueError('Alias cycle')


def copy_preview(src, dst):
    if dst.is_file() or not src.is_file():
        return False
    try:
        with Image.open(src) as image:
            image.verify()
    except (OSError, ValueError):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = dst.with_suffix(f'.{os.getpid()}.tmp')
    try:
        shutil.copyfile(src, temp)
        temp.chmod(0o600)
        temp.replace(dst)
    finally:
        temp.unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-db', type=Path, required=True)
    parser.add_argument(
        '--aliases',
        type=Path,
        action='append',
        required=True,
        help='reviewed folder/alias CSVs,in chronological order',
    )
    args = parser.parse_args()
    if args.from_db.is_symlink() or not args.from_db.is_file():
        raise ValueError('Invalid backup path')
    aliases = {}
    for path in args.aliases:
        for r in csv.DictReader(path.open()):
            source = r.get('historical_nas_path', r.get('source'))
            target = r.get('current_nas_path', r.get('target'))
            if not source or not target:
                raise ValueError('Invalid alias CSV')
            aliases[source] = target
    roots = load_base_dirs()
    counts = dict(matched=0, embeddings=0, thumbs=0, posters=0)
    with (
        sqlite3.connect(args.from_db.as_uri() + '?mode=ro', uri=True) as old,
        connect_db() as new,
    ):
        old.row_factory = sqlite3.Row
        current = {
            (r['collection'], r['subpath']): dict(r)
            for r in new.execute(
                'SELECT id,collection,subpath,size,mtime_ns,media_type,embedding_status FROM media_items'
            )
        }
        for r in old.execute(
            'SELECT collection,subpath,size,mtime_ns,media_type,embedding,embedding_model,embedding_status FROM media_items'
        ):
            dest = resolve_alias(r['collection'] + '/' + r['subpath'], aliases)
            parts = Path(dest).parts
            if len(parts) < 4 or parts[:1] != ('media',):
                continue
            key = (parts[1], Path(*parts[2:]).as_posix())
            target = current.get(key)
            if not target or (
                target['size'],
                target['mtime_ns'],
                target['media_type'],
            ) != (r['size'], r['mtime_ns'], r['media_type']):
                continue
            counts['matched'] += 1
            oldpath = Path('/mnt/yeeyang') / r['collection'] / r['subpath']
            newpath = roots[key[0]] / key[1]
            if (
                target['embedding_status'] != 'ready'
                and r['embedding_status'] == 'ready'
                and r['embedding_model'] == 'openclip:MobileCLIP-S1:datacompdr'
                and r['embedding'] is not None
            ):
                v = np.frombuffer(r['embedding'], dtype='<f4')
                if (
                    v.shape == (512,)
                    and np.isfinite(v).all()
                    and 0.98 < float(np.linalg.norm(v)) < 1.02
                ):
                    new.execute(
                        "UPDATE media_items SET embedding=?,embedding_model=?,embedding_status='ready' WHERE id=?",
                        (r['embedding'], r['embedding_model'], target['id']),
                    )
                    counts['embeddings'] += 1
                    target['embedding_status'] = 'ready'
            if r['media_type'] == 'image':
                oldkey = hashlib.md5(
                    f'{oldpath}:{r["size"]}:{int(r["mtime_ns"] / 1e9)}:400'.encode()
                ).hexdigest()
                newkey = hashlib.md5(
                    f'{newpath}:{r["size"]}:{r["mtime_ns"]}:400'.encode()
                ).hexdigest()
                counts['thumbs'] += copy_preview(
                    DATA_DIR / 'thumbs' / f'{oldkey}.jpg',
                    DATA_DIR / 'thumbs' / f'{newkey}.jpg',
                )
            else:
                oldkey = hashlib.sha256(
                    f'{oldpath}:{r["size"]}:{r["mtime_ns"]}'.encode()
                ).hexdigest()[:32]
                newkey = hashlib.sha256(
                    f'{newpath}:{r["size"]}:{r["mtime_ns"]}'.encode()
                ).hexdigest()[:32]
                targetfile = DATA_DIR / 'posters' / f'{newkey}.jpg'
                copied = copy_preview(
                    DATA_DIR / 'posters' / f'{oldkey}.jpg', targetfile
                )
                counts['posters'] += copied
                if targetfile.is_file():
                    new.execute(
                        "UPDATE media_items SET poster_status='ready' WHERE id=?",
                        (target['id'],),
                    )
    print(counts, flush=True)


if __name__ == '__main__':
    main()
