"""Runtime configuration shared by the web app and catalogue scanner."""

from __future__ import annotations

import json
import os
from pathlib import Path


COLLECTION_NAMES = ('media_others', 'media_travel', 'our_wedding')


def load_base_dirs() -> dict[str, Path]:
    """Load collection paths from JSON or from a common media root.

    NFS_VIEWER_COLLECTIONS_JSON can override every collection, for example:
    {"photos": "/mnt/nas/photos", "family": "/mnt/nas/family"}
    """
    raw = os.environ.get('NFS_VIEWER_COLLECTIONS_JSON')
    if raw:
        values = json.loads(raw)
        if not isinstance(values, dict) or not values:
            raise ValueError('NFS_VIEWER_COLLECTIONS_JSON must be a non-empty object')
        return {str(name): Path(path).expanduser() for name, path in values.items()}

    default_root = '/Volumes/yeeyang' if os.uname().sysname == 'Darwin' else '/mnt/yeeyang'
    root = Path(os.environ.get('NFS_VIEWER_MEDIA_ROOT', default_root)).expanduser()
    return {name: root / name for name in COLLECTION_NAMES}
