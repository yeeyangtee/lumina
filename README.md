# Lumina

Lumina is a private, fast, mobile-first photo and video library for media stored
on the home NAS. It runs continuously on **yy-visionmini**, accepts local-network
clients only, and keeps all catalogue, account, and ML data on the machine.

Open: **http://192.168.0.110:5050**

## First review

The first visit opens a one-time setup screen. Create the administrator account
with your preferred username and a password of at least 8 characters. There is
no public registration.

After setup:

- Library shows collection totals and recent memories.
- Search supports filenames, folders, collection, year, type, camera, favorites,
  and visual-meaning queries.
- Hearts are private to each account.
- Albums organize media without changing files on the NAS.
- Admin shows users, scans, background processing coverage, and job controls.
- Account lets each user change their password and sign out.

Visual search and video posters progressively improve while their first low-
priority background passes complete. Normal browsing remains available.

## Mobile use

The mobile layout has bottom navigation and a full-screen viewer. Swipe left or
right to navigate, pinch or double-tap to zoom, and drag while zoomed. Viewer
controls fade after a few seconds and return on tap.

The manifest and application icon support a home-screen shortcut. Static offline
caching activates only in a secure context; the current HTTP LAN address remains
fully functional but does not qualify for service-worker installation in all
browsers.

## Architecture

- Flask/Gunicorn web app: port 5050.
- SQLite catalogue: ~/.cache/nfs_image_viewer/library.db.
- SMB share: //192.168.0.12/yeeyang at /mnt/yeeyang.
- Semantic service: MobileCLIP-S1 on loopback port 5051.
- Derived assets: local thumbnails and video posters.
- Scheduled work: media scan, EXIF enrichment, posters, embeddings, backups.

No photo, embedding, search phrase, or account data is sent to a cloud API.
OpenCLIP model weights are downloaded once and used locally.

## Production services

    systemctl --user status nfs-image-viewer.service
    systemctl --user status nfs-image-viewer-semantic.service
    systemctl --user list-timers 'nfs-image-viewer-*'
    journalctl --user -u nfs-image-viewer.service -n 100 --no-pager

Background units:

- nfs-image-viewer-index — discover files every 15 minutes.
- nfs-image-viewer-enrich — read metadata every 30 minutes.
- nfs-image-viewer-posters — extract poster frames hourly.
- nfs-image-viewer-semantic-index — build embeddings hourly.
- nfs-image-viewer-backup — verified database backup daily.

Administrators can also start these jobs from the Admin screen.

## Install dependencies

The production environment uses Python 3.12 and CPU-only PyTorch:

    uv venv --python /usr/bin/python3.12 .venv
    uv pip install --python .venv/bin/python -r requirements-ml.txt
    uv pip install --python .venv/bin/python -r requirements.txt

Run locally:

    .venv/bin/python scanner.py
    .venv/bin/python app.py

The development server listens on 127.0.0.1:5050 with debug mode disabled.

## NAS mount

The persistent /etc/fstab entry on yy-visionmini mounts:

    //192.168.0.12/yeeyang /mnt/yeeyang cifs credentials=/home/yeeyang/.smbcredentials,uid=yeeyang,gid=yeeyang,file_mode=0600,dir_mode=0700,vers=3.0,nosuid,nodev,noexec,nofail,_netdev,x-systemd.automount 0 0

The credentials file is mode 0600 and contains the NAS account. Never commit or
print its password.

Verify:

    findmnt /mnt/yeeyang
    curl http://127.0.0.1:5050/healthz

## Configuration

Optional KEY=value overrides live in ~/.config/nfs-image-viewer/env. See
deploy/env.example. Supported settings include:

- NFS_VIEWER_MEDIA_ROOT
- NFS_VIEWER_COLLECTIONS_JSON
- NFS_VIEWER_DATA_DIR
- NFS_VIEWER_BIND
- NFS_VIEWER_TRUSTED_NETWORKS
- NFS_VIEWER_CLIP_MODEL
- NFS_VIEWER_CLIP_PRETRAINED
- NFS_VIEWER_ML_THREADS

UFW is intentionally not enabled at the owner's request. The application-level
private-network CIDR check remains active. Do not add router port forwarding.

## Backups and recovery

Verified online backups are stored under:

    ~/.cache/nfs_image_viewer/backups/library-YYYYMMDD-HHMMSS.db

Fourteen scheduled copies are retained. A pre-wave migration snapshot is also
kept. To make a fresh backup:

    systemctl --user start nfs-image-viewer-backup.service

Before restoring, stop the web and all database-writing jobs, preserve the current
library.db, copy the selected verified backup into its place with mode 0600, and
restart the services. Do not restore while an index/enrichment job is running.

## Tests

    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python -m py_compile app.py auth.py catalog.py scanner.py enrich.py
    node --check static/gallery.js

The tests use isolated temporary media and data directories; they never touch the
production catalogue.

## Current status

See ROADMAP.md for live first-pass enrichment/poster/embedding progress and
intentionally deferred items such as UFW, trusted local HTTPS, OCR, and faces.
