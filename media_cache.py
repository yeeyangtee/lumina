"""Stable local cache paths for derived media assets."""

import hashlib
from pathlib import Path

from catalog import DATA_DIR


POSTER_CACHE = DATA_DIR / 'posters'
POSTER_CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
POSTER_CACHE.chmod(0o700)


def poster_cache_file(media_path: Path) -> Path:
    try:
        stat = media_path.stat()
        signature = f'{media_path}:{stat.st_size}:{stat.st_mtime_ns}'
    except OSError:
        signature = str(media_path)
    key = hashlib.sha256(signature.encode()).hexdigest()[:32]
    return POSTER_CACHE / f'{key}.jpg'
