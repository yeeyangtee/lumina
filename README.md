# Lumina

A private photo/video browser for the organized NAS library. Open
**http://192.168.0.110:5050** and sign in with the existing owner account.

The Library opens Travel, Events and Family Photos. **Library albums** shows the
reviewed album titles, dates, descriptions and subfolders from `album.json`.
**My albums** and Favorites are private personal lists; neither moves files.
Uncategorized is a separate entry, and undated childhood photos stay undated.

Collection pages show the same album-cover cards as Library albums. Folder grids
use numbered pages of 100 photos/videos, with page links above and below the grid.
Closing the viewer returns to the originating page and sort, with folder scroll
restored after the grid loads. The viewer offers one original-download action.

## Media and performance

Originals stay on the NAS. Catalogue, album metadata, thumbnails, video posters,
playback copies and visual-search embeddings stay on yy-visionmini. No photo,
search phrase or embedding is sent to a cloud API. Model weights are downloaded
once and reused locally.

JPEG/PNG/HEIC/GIF and the existing image types are supported, along with Canon
CR2, TIFF/TIF, MP4, MOV and AVI. CR2 embedded JPEGs and TIFFs get local JPEG display
copies; AVI and incompatible MOV files get local MP4 playback copies. Downloads
always offer the original. HEVC originals require a browser with HEVC support.
Sixteen childhood WAV recordings are accessible separately as audio, outside
visual-search counts. Nonmedia scripts are not indexed or executed.

A first run can show previews as pending while the background worker runs. Admin
reports ready/pending/error totals and files needing attention. Invalid media
stays available for original download; errors do not block the rest of the
library. Covers and searches use the local catalogue. Folder browsing performs
one NAS listing, never a recursive request-path traversal.

Image thumbnails use one 400px bounding size for grids and image album covers.
The hourly worker prepares new/changed photos; cache misses can also be generated
on demand. Smaller embedded EXIF previews may still be used. The former 240/800px
variants are no longer requested or generated; existing cache files are retained.

## Configuration and operation

Production source: `/home/yeeyang/projects/lumina`. Use Python 3.12 and the
existing `.venv`. Shared configuration is environment-driven:

- `NFS_VIEWER_MEDIA_ROOT`: parent of `media/`, normally `/mnt/yeeyang`.
- `NFS_VIEWER_COLLECTIONS_JSON`: explicit mapping, overriding defaults.
- `NFS_VIEWER_DATA_DIR`: local app state, normally `~/.cache/nfs_image_viewer`.
- Existing bind, trusted-network and MobileCLIP settings remain supported.

Production overrides live in the private `~/.config/nfs-image-viewer/env`.
Do not print or commit its contents, account hashes or NAS/session credentials.

Services are user systemd units under `deploy/`:

    systemctl --user status nfs-image-viewer.service
    systemctl --user status nfs-image-viewer-semantic.service
    systemctl --user list-timers 'nfs-image-viewer-*'
    curl http://127.0.0.1:5050/healthz
    curl http://127.0.0.1:5051/healthz

Indexing, previews, metadata, posters and embeddings have separate services and
timers. After a reviewed rescan, a full resumable preparation pass is:

    .venv/bin/python integration_jobs.py

Integration and per-worker advisory locks serialize overlapping invocations.
Worker commands and bounded retry procedure are in `HANDOVER.md`. Only use
`scanner.py --allow-prune` after reviewing missing albums/large reductions.
Scanner errors or an unexpected empty source preserve the previous catalogue.

The NAS mount remains the existing CIFS mount. Deployment must verify that its
source is `//192.168.0.12/yeeyang`; no mount/permission changes are needed here.
LAN-only access remains active. Trusted HTTPS and firewall policy remain deferred.

## Backups

The current NAS-media backup is the verified SSD Restic repository managed by
the data-management project. The owner plans to keep the SSD offline after that
broader task is finished. New media-backup scheduling, retention and off-site
work are explicitly deferred.

Lumina's pre-existing daily local SQLite backups retain fourteen copies under
`~/.cache/nfs_image_viewer/backups`. This separate policy is unchanged. Before a
schema/deployment migration, create a dedicated verified SQLite online backup
without pruning prior copies. Thumbnails/posters/playback copies can be rebuilt;
accounts and the session key need careful preservation. Follow `HANDOVER.md`
for a stopped-writer WAL-safe rollback; never overwrite a live database.

## Development checks

    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python tests/integration_checks.py -v
    .venv/bin/python -m py_compile app.py auth.py catalog.py config.py scanner.py \
      enrich.py previews.py library_metadata.py formats.py posters.py \
      semantic_index.py reuse_archive_cache.py integration_jobs.py job_lock.py
    node --check static/gallery.js
    node --check static/sw.js

Compile every Jinja template with isolated `NFS_VIEWER_MEDIA_ROOT` and
`NFS_VIEWER_DATA_DIR` before importing `app`. Tests must never use production
SQLite or its media roots. The standalone integration suite exercises invalid and
interrupted scans, links, UUID collisions, missing albums, private-list
preservation, RAW/TIFF previews, AVI range playback, audio and unknown dates.

Read `HANDOVER.md` and `AGENTS.md` before maintenance. `ROADMAP.md` records shipped
features and deferred scope. The browser pilot covers Chromium desktop/mobile;
the owner accepted MacBook usability on 2026-10-19; phone gestures and any further
browser-specific review remain pending.
