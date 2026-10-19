# AGENTS.md — Lumina / nfs_image_viewer

Private, authenticated Flask photo/video library hosted on **yy-visionmini**
(Ubuntu). Media is read from a slow SMB mount; every request-path design should
minimize NAS round-trips. Derived data and all user state stay local.

Start every new maintenance session with `HANDOVER.md`; it records the live
deployment state, owner decisions, reviewed limitations, and next-step order.

## Production topology

- Web: Gunicorn on 0.0.0.0:5050, systemd user unit nfs-image-viewer.service.
- Semantic search: one MobileCLIP service on 127.0.0.1:5051 only.
- NAS: //192.168.0.12/yeeyang mounted at /mnt/yeeyang through /etc/fstab.
- Local data: ~/.cache/nfs_image_viewer, mode 0700; files mode 0600.
- LAN-only Flask allowlist remains active. UFW is intentionally on hold.
- User lingering is enabled, so services survive logout.

## Code map

- HANDOVER.md — current deployment snapshot, reviewed risks, and next-step order.
- app.py — routes, browse/viewer, thumbnails, search proxy, favorites/albums.
- auth.py — setup/login/session/CSRF/account/admin and fixed job triggers.
- config.py — environment-driven collection paths.
- catalog.py — schema version, SQLite connections, queries, scan/job state.
- scanner.py — staged media discovery; atomically updates only complete collections.
- formats.py / library_metadata.py — shared format rules and validated NAS album cache.
- previews.py / integration_jobs.py — bounded local display/playback preparation and resumable pipeline.
- refresh_thumbnails.py — resumable, versioned 400px image-thumbnail refresh; new
  photos use the existing previews worker automatically.
- job_lock.py — per-role advisory locks shared by manual, timer and pipeline jobs.
- reuse_archive_cache.py — explicit version-matched, media-only historical derivative reuse.
- enrich.py — background EXIF/date/camera/dimensions/GPS enrichment.
- media_cache.py / posters.py — derived video poster paths and ffmpeg worker.
- semantic_model.py — singleton OpenCLIP MobileCLIP-S1 model helpers.
- semantic_index.py — thumbnail/poster embeddings into SQLite.
- semantic_server.py / semantic_wsgi.py — loopback semantic query service.
- backup.py — online SQLite backup, integrity check, and retention.
- gunicorn.conf.py / wsgi.py — production web entry point.
- templates/ — Jinja views; base.html owns desktop/mobile navigation.
- static/gallery.js — shared safe URLs, CSRF fetch, cards, lazy loading, toast,
  and scroll restoration.
- static/style.css — Lumina visual system and mobile/viewer breakpoints.
- static/manifest.webmanifest, icon.svg, sw.js — PWA shell assets.
- deploy/ — web, scan, enrich, poster, semantic, and backup systemd units/timers.
- tests/test_app.py — isolated standard-library smoke suite.

## Environment and install

Use Python 3.12. PyTorch must be installed from the official CPU wheel index
before the main dependencies:

    uv venv --python /usr/bin/python3.12 .venv
    uv pip install --python .venv/bin/python -r requirements-ml.txt
    uv pip install --python .venv/bin/python -r requirements.txt

Useful environment variables:

- NFS_VIEWER_MEDIA_ROOT (default /mnt/yeeyang on Linux).
- NFS_VIEWER_COLLECTIONS_JSON for a full collection mapping override.
- NFS_VIEWER_DATA_DIR for isolated tests/local state.
- NFS_VIEWER_TRUSTED_NETWORKS for comma-separated LAN CIDRs.
- NFS_VIEWER_CLIP_MODEL / NFS_VIEWER_CLIP_PRETRAINED for explicit rebuilds.
- NFS_VIEWER_ML_THREADS controls CPU inference parallelism.

Production overrides belong in ~/.config/nfs-image-viewer/env. Never store NAS
or account passwords in this repository.

## Authentication invariants

- With no users, only setup, login, static/PWA assets, and health are public.
- The first setup account is administrator; there is no public registration.
- All unsafe methods require a session CSRF token. JavaScript uses apiFetch.
- Never add a mutating endpoint to the auth public-endpoint set.
- Password hashes use Werkzeug scrypt; minimum password length is 8.
- Every media, favorite, and album route is scoped through the current user.
- Admin job execution maps a fixed name to a fixed systemd unit. Never accept a
  unit name or shell command from request data.
- If adding a reverse proxy, explicitly configure trusted proxy handling; do not
  trust arbitrary X-Forwarded-For headers.

## Filesystem and SMB invariants

- resolve(collection, subpath) is the only user-path gate. All path-taking routes
  must use it before filesystem access.
- Scanner catalogue paths are trusted local database values, not request values.
- Default browse performs one os.scandir pass. Mtime sort intentionally adds stat.
- Never recursively walk the NAS inside a web request.
- Image thumbnails use source-derived 400px JPEGs (quality 80), respecting EXIF
  orientation. Bypass tiny embedded EXIF thumbnails. RAW/TIFF use local display
  copies. Publish atomically under thumbs/400-v2; preserve historical cache files.
- A missing mount is expected. Do not clear catalogue rows unless a complete scan
  with its unique marker succeeds.
- Basic scans may read bounded album.json records, but must not open image/video bodies.
  Metadata, previews, posters and ML belong in low-priority background services.
- Keep shared source-album UUIDs separate from private user-created album IDs.
- Do not infer capture dates from copy/scan mtimes; unknown_year is intentional.
- Scanner pruning must retain data on invalid/partial/empty or missing-album scans.
  The explicit --allow-prune option is only for reviewed source changes.
- VIDEO_EXTS also exists in static/gallery.js; keep both lists synchronized.

## SQLite and migration invariants

- library.db uses WAL, foreign keys, a 30-second busy timeout, and schema_info.
- Open a fresh catalog.connect_db connection per operation/thread.
- User favorites and album items reference media_items with cascading deletes.
- Add future columns/tables idempotently in catalog.init_db and increment
  SCHEMA_VERSION. Never require an empty database.
- Take a verified online backup before a risky schema or bulk data migration.
- Embeddings are normalized little-endian float32 blobs and tagged with MODEL_ID.
  A model change must mark mismatched items pending before rebuilding.

## Background services

- nfs-image-viewer-index.timer — media scan every 15 minutes.
- nfs-image-viewer-previews.timer — local image/playback preparation hourly.
- nfs-image-viewer-thumbnails.service — on-demand resumable quality-cache refresh;
  no extra timer, because previews prepares new/changed photos hourly.
- nfs-image-viewer-enrich.timer — metadata enrichment every 30 minutes.
- nfs-image-viewer-posters.timer — video posters hourly.
- nfs-image-viewer-semantic-index.timer — visual embeddings hourly.
- nfs-image-viewer-backup.timer — daily verified backup, 14-copy retention.
- nfs-image-viewer-semantic.service — always-on loopback inference.

All derivation workers are idempotent and normally process only pending rows.
Corrupt files become error state instead of aborting the whole run; errors require
an explicit `--retry-errors` CLI run. A later no-op run may set `job_state` to
`ready 0/0`, so use status-column counts for true coverage. Use Nice and idle I/O
class for NAS/CPU-heavy jobs so browsing stays responsive.

## Current owner backup boundary

The existing verified SSD Restic media copy is accepted for now. Do not introduce
new media-backup schedules, retention or off-site work; the owner explicitly deferred
those. SSD detachment is only after the wider data-management task. Existing daily
app SQLite backups remain unchanged. Preserve accounts/session state; no wholesale
cache/data-directory wipe. See HANDOVER.md for the current 44-album checkpoint.

## Test and verify

    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python -m py_compile app.py auth.py backup.py catalog.py config.py \
      enrich.py media_cache.py posters.py scanner.py semantic_index.py \
      semantic_model.py semantic_server.py
    .venv/bin/python tests/integration_checks.py -v
    node --check static/gallery.js
    node --check static/sw.js
    curl http://127.0.0.1:5050/healthz
    curl http://127.0.0.1:5051/healthz

Compile every Jinja template through app.app.jinja_env when changing templates.
For tests, set NFS_VIEWER_MEDIA_ROOT and NFS_VIEWER_DATA_DIR before importing app.
Never point automated tests at the production database.

## UX rules

- Mobile layouts are first-class: preserve safe-area insets and 44px tap targets.
- Original media is never service-worker cached. Only versioned static shell files
  may be cached.
- Keep image cards lazy and responsive. Search uses local catalogue pagination.
- Use DOM textContent or escapeHtml for filenames/EXIF; never inject raw metadata.
- Viewer gestures must not navigate while an image is zoomed.
- Update ROADMAP.md checklist and changelog with every shipped feature.
