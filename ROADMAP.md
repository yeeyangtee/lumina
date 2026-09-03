# Lumina / nfs_image_viewer — Roadmap

A private, fast, mobile-first photo and video library hosted on **yy-visionmini**.
Media stays on the SMB NAS; accounts, catalogue data, thumbnails, posters, and ML
embeddings stay on the local machine.

Status: ☐ todo · ◐ building/indexing · ☑ shipped · ⏸ intentionally on hold

## Hosted foundation

- ☑ Gunicorn + persistent systemd user service on port 5050.
- ☑ Private-network request allowlist and path traversal protection.
- ☑ Persistent SMB systemd automount at /mnt/yeeyang.
- ☑ WAL-mode local SQLite catalogue and safe incremental 15-minute scanner.
- ☑ Atomic, private thumbnail cache with embedded-EXIF fast path.
- ☑ Health endpoint and graceful offline collection handling.
- ⏸ UFW host firewall — held by owner; application LAN guard remains active.

## Wave 1 — Accounts, favorites, and albums ☑

- ☑ First-run administrator setup with no public registration.
- ☑ Scrypt password hashing, signed 30-day sessions, secure cookie flags, CSRF
  validation, login throttling, and security response headers.
- ☑ Admin-created accounts, roles, activation/deactivation, and password changes.
- ☑ Authentication required for all library/media/API routes.
- ☑ Per-user favorites linked to indexed media.
- ☑ One-way migration of legacy global favorites to the first administrator.
- ☑ Per-user named albums with add/remove actions from the viewer.
- ☑ Admin dashboard for users, scan state, enrichment coverage, and job triggers.

## Wave 2 — Rich and semantic search ☑

- ☑ Background EXIF enrichment: capture date/year, camera, lens, dimensions, GPS.
- ☑ Initial metadata enrichment completed across all 23,385 items; periodic
  enrichment is installed for new/changed files.
- ☑ Global structured search by filename/folder, collection, year, media type,
  camera, and favorites.
- ☑ Local OpenCLIP MobileCLIP-S1 inference service on loopback only.
- ☑ Normalized 512-dimensional image embeddings stored locally in SQLite.
- ☑ Natural-language visual similarity search with structured filters.
- ☑ Model identity and per-item embedding state support safe rebuilds.
- ☑ Initial semantic pass completed: 23,350 embeddings are ready; 24 unreadable
  JPGs are recorded as errors and 11 videos await posters. New items are handled
  by the hourly timer.
- ☐ Optional future enrichment: OCR and opt-in face naming/clustering.
- ☐ Optional similarity view for perceptual duplicate review.

## Wave 3 — Mobile-first experience ☑

- ☑ New Lumina visual system with glass surfaces, photographic gradients, clear
  hierarchy, polished empty/error/loading states, and accessible focus states.
- ☑ Responsive desktop navigation and safe-area-aware mobile bottom navigation.
- ☑ Two/three-column adaptive mobile grids with direct favorite actions.
- ☑ Catalogue-backed “load more” search pagination.
- ☑ Touch-native viewer with swipe navigation, pinch zoom, double-tap zoom,
  panning, full-screen controls, and automatic control hiding.
- ☑ Grid scroll-position restoration after returning from the viewer.
- ☑ Responsive 240/400/800px thumbnails with srcset, lazy loading, and atomic
  local cache publication.
- ☑ Web manifest, maskable SVG icon, and conservative static-only service worker.
- ⏸ Service-worker activation on LAN IP requires trusted local HTTPS; the HTTP app
  remains fully usable and can still be added as a home-screen shortcut.

## Wave 4 — Operations and media finishing ☑

- ☑ Real video poster generation via bundled local ffmpeg—no apt dependency.
- ☑ Initial poster pass completed: 1,595 of 1,606 videos have posters; 11 MP4s
  that produced no frame are recorded as errors. Hourly processing handles new
  videos.
- ☑ Consistent SQLite online backup with integrity verification and 14-copy
  retention, scheduled daily at approximately 03:20.
- ☑ Admin-visible background-job progress/errors and manual job triggers.
- ☑ Journald logging for every web and background service.
- ☑ Project-local Python 3.12 CPU-ML environment with pinned dependencies.
- ☑ Automated smoke tests for setup/auth, pages, search, favorites, albums,
  traversal rejection, and LAN restriction.
- ⏸ Friendly local HTTPS requires installing a trusted local CA on every client;
  defer until the owner wants that device-management tradeoff.

## Review-build acceptance

- ☑ Live at http://192.168.0.110:5050.
- ☑ One-time admin setup completed; the owner account exists.
- ☑ Existing media catalogue preserved: 23,385 items.
- ☑ Pre-migration and post-migration verified database backups exist.
- ☑ Core test suite, template compilation, JavaScript syntax, health, and live
  semantic query checks pass.
- ☑ First-pass derived data completed. Exceptional files remain isolated in error
  state without blocking normal browsing or review.

## Changelog

- **2026-09-03 — maintenance handover:** reviewed code, documentation, live
  services, database integrity, tests, and remaining media exceptions; added
  `HANDOVER.md` and updated first-pass indexing status.
- **2026-09-03 — simpler passwords:** lowered the minimum account password length
  to eight characters across setup, administration, account changes, and tests.
- **2026-09-03 — review build:** shipped accounts, per-user favorites/albums,
  structured and MobileCLIP semantic search, the Lumina mobile-first interface,
  responsive thumbnails, PWA shell, video posters, backups, admin telemetry,
  security headers, and automated tests. Initial derived-data jobs are running.
- **2026-09-03 — media online:** mounted the NAS persistently and completed the
  first 23,385-item catalogue scan.
- **2026-09-02 — hosted catalogue foundation:** added Linux configuration,
  Gunicorn/systemd hosting, LAN enforcement, health checks, SQLite catalogue,
  scheduled scanner, indexed filename search, and legacy-favorites migration.
