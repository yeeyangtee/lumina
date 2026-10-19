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
- ☑ Lazy thumbnails with atomic local cache publication; standardized on a single
  400px image-thumbnail size by owner decision on 2026-10-19.
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

## Wave 5 — Organized NAS integration ☑

- ☑ Canonical Travel, Events, Family Photos and Uncategorized roots.
- ☑ 44 shared source albums from validated album.json, stable UUIDs and subfolder notes.
- ☑ Separate private My albums and Favorites; owner account/session preserved.
- ☑ CR2/TIFF display and AVI/legacy MOV playback copies kept local; originals unchanged.
- ☑ Sixteen separately catalogued audio recordings; unknown-year photos preserved.
- ☑ Atomic scans with mount, link, invalid-metadata and pruning safeguards.
- ☑ Reconciliation of 26,062 visual items, 44 albums and 16 audio files.
- ☑ Historical derivative reuse through reviewed aliases and exact version matching.
- ☑ Persistent preview/error visibility and bounded resumable workers.
- ☑ Isolated regressions and desktop/mobile browser checks across representative formats.
- ☑ Full derived-data pass: 26,038 previews/search embeddings ready; 24 unreadable JPEGs explicitly reported, originals retained. All 1,621 video posters and 26,062 metadata rows ready.
- ☑ Owner's MacBook usability review accepted on 2026-10-19.
- ☐ Owner's phone usability review.
- ⏸ New media-backup schedules, retention and off-site work explicitly deferred.

The September Wave 1–4 counts above are historical milestones, not current
coverage. See HANDOVER.md and Admin for the current checkpoint and processing
states. The existing verified SSD media copy is accepted for now.

## Browse refinements — October 2026

- ☑ Compact home layout and consistent album-cover cards within collections.
- ☑ Native lazy-loaded album covers and corrected folder-cover lazy loading.
- ☑ Numbered folder pages with 100 photos/videos, direct page links and controls
  above and below the grid; no automatic scrolling.
- ☑ Viewer return links preserve the originating page/sort through previous/next;
  folder scroll restores after asynchronous rendering.
- ☑ Larger mobile control targets and a single original-download action.
- ☑ Single 400px image-thumbnail size; retain existing 240/800px cache files.
- ☐ Four-image album covers: explore a 2×2 collage, selection across the album
  rather than just its first file, and fallback for fewer than four usable photos.
  Reuse local 400px thumbnails and catalogue queries; no recursive NAS work in
  page requests. Current library covers use the first image by full relative
  path, or the first video's poster when no image exists.
- ☐ Sharper thumbnails: require adequate embedded-preview resolution and prepare
  better 400px thumbnails in the background. Existing quality remains unchanged;
  benchmark a representative batch before a library-wide upgrade.
- ☐ Automatic rotation/orientation correction beyond existing EXIF handling;
  define desired behavior before implementation.
- ☐ Automatic duplicate detection/deduplication and similar-photo grouping;
  agree keeper/removal behavior before any changes to originals.

## Changelog

- **2026-10-19 — accepted checkpoint:** owner approved the app on MacBook and
  requested a Git checkpoint of the organized-library integration and browsing
  refinements. Phone acceptance remains pending. Four-image album cards added
  to future work, without changing current cover selection.
- **2026-10-19 — thumbnail size:** standardized image thumbnails on 400px,
  removed responsive variant requests and normalized legacy size requests to
  400px. Existing caches are retained; no quality rebuild was started.
- **2026-10-19 — browsing refinements:** simplified the home and album views,
  restored album covers within collections, increased numbered folder pages to
  100 items and preserved viewer return context/scroll. Improved mobile controls
  and consolidated original downloads. Thumbnail-quality upgrades, automatic
  rotation and duplicate/similar-photo handling remain future work.
- **2026-10-18 — organized NAS integration:** deployed canonical roots, 44 shared
  source albums, legacy-format display/playback, audio attachments, owner date
  handling, atomic scan guards, version-matched cache reuse and isolated browser
  tests. Accounts and originals are preserved. Source cleanup is recorded in the
  data-management journals; new media-backup policy work is deferred by the owner.
- **2026-09-07 — project rename:** moved the source folder to
  `/home/yeeyang/projects/lumina`, updated all deployment paths, and preserved
  the local Git history.
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
