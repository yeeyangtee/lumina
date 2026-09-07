# Lumina handover

Last reviewed: **2026-09-07 SGT** on **yy-visionmini**.

This is the session-start document for the next maintainer or AI agent. Read it
with `AGENTS.md`, then consult `README.md` for operator instructions and
`ROADMAP.md` for product status. Do not ask the owner to repeat the topology or
the decisions recorded here.

## Product intent and owner decisions

Lumina is a private, attractive, fast, mobile-friendly browser for the owner's
photo and video archive. Originals remain on the NAS; local state and derived
data remain on yy-visionmini.

The owner's priorities, in order, are:

1. Friendly browsing and viewing on phone and desktop.
2. Fast interaction despite the slow SMB mount.
3. Private accounts, favorites, albums, and local search.
4. Low-maintenance operation on the existing machine.

Current explicit decisions:

- Keep access on the local network only.
- UFW is intentionally not being changed yet.
- Trusted local HTTPS is deferred because it requires client certificate/CA
  management. Consequently the current LAN HTTP traffic is not encrypted.
- The minimum password length is eight characters, with no complexity rule.
- OCR, named-face recognition, and duplicate review are optional future work.

## First five minutes of a new session

Work from:

    cd /home/yeeyang/projects/lumina
    git status --short
    git log -3 --oneline --decorate
    sed -n '1,240p' AGENTS.md
    sed -n '1,260p' HANDOVER.md

Confirm production without reading originals:

    systemctl --user is-active nfs-image-viewer.service
    systemctl --user is-active nfs-image-viewer-semantic.service
    systemctl --user list-timers 'nfs-image-viewer-*'
    curl http://127.0.0.1:5050/healthz
    curl http://127.0.0.1:5051/healthz
    findmnt /mnt/yeeyang

Do not print `~/.smbcredentials`, account rows, password hashes, the session key,
or private media filenames unless the owner specifically needs one investigated.
Never point tests at the production database.

## Live deployment state

- Project source: `/home/yeeyang/projects/lumina`.
- User-facing URL: `http://192.168.0.110:5050`
- Web: Gunicorn, two threaded workers, user service
  `nfs-image-viewer.service`.
- Semantic inference: loopback-only service on `127.0.0.1:5051`.
- SMB: `//192.168.0.12/yeeyang` mounted at `/mnt/yeeyang` as NAS user
  `teeyeeyang` through `/etc/fstab` and a private credentials file.
- Database: `~/.cache/nfs_image_viewer/library.db`, WAL mode, file mode 0600.
- Session signing key: `~/.cache/nfs_image_viewer/session.key`, mode 0600.
- Cache roots: `~/.cache/nfs_image_viewer/thumbs` and `posters`.
- Backups: `~/.cache/nfs_image_viewer/backups`.
- The source-controlled service files under `deploy/` are symlinked into
  `~/.config/systemd/user/`. User lingering is enabled.

At this review, all seven services/timers were active and the database reported:

| State | Count |
|---|---:|
| Total media | 23,385 |
| Images | 21,779 |
| Videos | 1,606 |
| Metadata ready | 23,385 |
| Video posters ready | 1,595 |
| Video poster errors | 11 |
| Semantic embeddings ready | 23,350 |
| Semantic embedding errors | 24 |
| Semantic pending because poster failed | 11 |
| Accounts | 1 |

The three collection scans are complete: `media_others` 584, `media_travel`
15,199, and `our_wedding` 7,602. Do not treat these figures as constants; run a
fresh read-only query when current counts matter.

The remaining exceptions are 11 MP4 files for which ffmpeg returned without a
poster file and 24 JPG files whose thumbnail decode failed. They are recorded as
errors and do not block normal browsing. Scheduled jobs process new `pending`
rows but do not retry `error` rows.

## Architecture and data flow

The browser never recursively searches the NAS. The flow is:

    SMB originals -> scanner -> local SQLite catalogue
                              -> metadata worker
                              -> thumbnail/poster cache
                              -> MobileCLIP embedding worker

    browser -> Flask/Gunicorn -> SQLite for search/state
                              -> SMB only for requested media/uncached thumbnails
                              -> loopback semantic service for visual search

`resolve(collection, subpath)` in `app.py` is the mandatory gate for every
request-supplied media path. Do not construct a filesystem path directly in a
route. The scanner's incomplete-run marker prevents a transient NAS outage from
deleting catalogue rows.

Accounts, favorites, albums, scan state, metadata, and embeddings share
`library.db`. User-created albums and favorites never modify NAS files.

## Deploying a code change

Run the checks first:

    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python -m py_compile app.py auth.py backup.py catalog.py config.py \
      enrich.py media_cache.py posters.py scanner.py semantic_index.py \
      semantic_model.py semantic_server.py
    node --check static/gallery.js
    node --check static/sw.js

Compile all Jinja templates through `app.app.jinja_env` when templates change.
Then restart only the affected long-running service:

    systemctl --user restart nfs-image-viewer.service
    systemctl --user restart nfs-image-viewer-semantic.service

After editing a file under `deploy/`, run `systemctl --user daemon-reload` before
restarting the relevant unit. Static assets are served directly, but an installed
service worker may retain the shell until its cache version changes in `sw.js`.

## Background work and diagnostics

Normal scheduled work:

- Catalogue scan every 15 minutes.
- Metadata enrichment every 30 minutes.
- Video poster and semantic passes hourly.
- Verified SQLite backup daily around 03:20, retaining up to 14 dated copies.

Admin buttons trigger the same fixed systemd units. A job that finds nothing to
do records `ready 0/0`; that describes the latest run, not lifetime coverage.
Use the Admin headline counts or direct database counts for coverage.

Read logs with:

    journalctl --user -u nfs-image-viewer.service -n 100 --no-pager
    journalctl --user -u nfs-image-viewer-posters.service -n 100 --no-pager
    journalctl --user -u nfs-image-viewer-semantic-index.service -n 100 --no-pager

Error rows can be retried deliberately, preferably with a small limit first:

    .venv/bin/python posters.py --retry-errors --limit 5
    .venv/bin/python semantic_index.py --retry-errors --limit 5
    .venv/bin/python enrich.py --retry-errors --limit 5

These commands read NAS originals and may consume CPU/I/O. Do not run a large
retry interactively while the owner is reviewing the gallery.

## Backups and recovery boundary

The online SQLite backup is consistent and integrity-checked. Existing verified
snapshots include a pre-wave migration copy and a review-build copy. The scheduled
backups are on the same physical host as the live database, so they protect from
bad migrations and local database damage, not total disk or machine loss.

The database backup does not contain thumbnails/posters, the session signing key,
systemd configuration, or NAS credentials. Thumbnails, posters, and embeddings
can be regenerated. Losing the session key signs everyone out but does not lose
accounts. Never restore while any database-writing worker is active. Follow the
recovery procedure in `README.md`, preserve the current database first, and verify
the chosen backup with `PRAGMA integrity_check`.

## Code review findings at this checkpoint

No release-blocking defect was found. The route authorization, CSRF checks,
per-user ownership filters, path traversal gate, fixed systemd job mapping,
SQLite foreign keys, and scanner deletion guard are sound for the intended
trusted-LAN deployment. This was a focused code review, not a formal penetration
test.

Known limitations and maintenance debt, in priority order:

1. **HTTP has no transport encryption.** Passwords, cookies, and media traverse
   the LAN in cleartext. Keep router forwarding disabled. HTTPS is the proper fix
   if the threat model expands beyond a trusted home network.
2. **Error rows are easy to overlook.** Timers skip them, and later no-op jobs
   overwrite `job_state` with `ready 0/0`. The Admin page should eventually show
   pending/error totals and offer an explicit retry action.
3. **Backups are not off-host.** Copy verified backups or the project repository
   to another trusted device if disaster recovery matters.
4. **Semantic search is linear.** Each query loads all matching embedding blobs
   and scores them with NumPy. It took about 0.20 seconds for 23,350 items during
   this review, which is good now; consider an in-memory matrix or vector index if
   the library grows enough for latency to become visible.
5. **Semantic model warm-up is lazy under Gunicorn.** The health endpoint can be
   healthy before the first text embedding initializes the model. A startup hook
   would make readiness more literal if cold-query latency becomes annoying.
6. **The automated suite is intentionally small.** It covers setup, core pages,
   catalogue search, favorites, albums, LAN rejection, traversal, and anonymous
   API rejection. It does not yet cover login throttling, eight-character boundary
   cases, password changes, two-user isolation, video ranges, worker failures, or
   browser-level gestures/layout.
7. **Derived caches have no garbage collector.** Replaced or removed files can
   leave unreachable thumbnails/posters. Add a conservative cache-prune command
   only after measuring disk growth.
8. **Folder browsing still performs one live `scandir`.** This preserves immediate
   folder structure and is acceptable now, but very large flat folders can expose
   SMB latency. Recursive search correctly stays catalogue-backed.

Smaller notes: login throttling is in-memory per Gunicorn worker; setup has a
small concurrent-first-request race; CSP permits inline scripts because templates
currently contain page scripts; HEIC display conversion is not cached.

## Recommended next steps

The best next move is a short owner-led usability pass on both phone and desktop.
Collect concrete friction before adding more ML features. Suggested order:

1. Review library browsing, search quality, viewer gestures, favorites, albums,
   video playback, and Admin status on real devices.
2. Improve error visibility and retry/fallback handling for the 11 MP4 and 24 JPG
   exceptions.
3. Add two-user isolation and password/account lifecycle tests.
4. Arrange an off-host copy of database backups and this Git repository.
5. Decide whether trusted HTTPS is worth the client setup; UFW remains a separate
   owner decision.
6. Only then prioritize OCR, face grouping/naming, duplicate review, or a faster
   vector index based on actual search needs.

## Version-control checkpoint

The repository was initialized on branch `main`. The first full review-ready
source snapshot is commit `6f2f586`, tagged `checkpoint-review-ready`. It is a
local repository only; no remote is configured. Before making changes, inspect
the working tree and preserve unrelated owner edits. Do not rewrite or delete the
checkpoint tag.
