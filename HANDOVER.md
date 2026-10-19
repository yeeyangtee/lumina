# Lumina handover

Current maintenance checkpoint: **2026-10-19, Asia/Singapore**. Read this with
`AGENTS.md`. The owner approved implementation, deployment, full indexing, and
code/documentation review before their final browser review.

## Accepted Git checkpoint — 2026-10-19

The owner reports that the app looks good on their MacBook and explicitly
requested this Git checkpoint. The checkpoint commit titled
`checkpoint: organized library and browsing refinements` captures the previously
uncommitted October integration, the approved UI/navigation changes, the 400px
thumbnail decision, isolated tests and maintenance documentation. It is a source
checkpoint, not a fresh database backup or a remote push. The existing private
deployment journal and SQLite backups retain their separate roles.

Phone acceptance remains pending; do not infer a Safari-specific sign-off from
the MacBook report. Future album-cover task: explore four-image/2×2 album cards,
selection of representative photos and fallback for small albums, using local
400px thumbnails and catalogue queries. No collage implementation is included.
Current library/folder covers choose the first image by full relative path across
descendants; only albums with no images use the first video's poster. Private
My albums instead use the most recently added item. Selection is deterministic,
not based on aesthetic quality or recency of capture.

## 2026-10-19 owner feedback and browse refinement

The owner approved cleaner UI and album covers within collections, chose to keep
numbered folder pages with 100 items, and deferred thumbnail-quality changes.
The refinement uses consistent 4:3 source-album cards on collection roots and
All albums, a compact home, larger mobile targets, and one original-download
action. Nested provider/year folders remain folders. Folder-cover images no
longer start with an empty URL; the shared lazy loader only handles data-src
images, leaving native-lazy source-album covers alone.

Viewer links carry a validated local return_to URL through previous/next, so
Back/Escape retains folder page and sort (or the source Search/Favorites/My albums
page). Folder scroll restores after the async grid renders. Folder pagination
has direct numbered links above and below the grid, 100 items per page. Search
keeps its existing Load more behavior; appended search batches are not rebuilt
on return. Viewer sibling order still follows filename order rather than the
originating search sequence or nondefault folder sort. These are remaining
navigation limitations, not claims of full collection-context viewer navigation.

Verification uses isolated state/media: seven smoke/regression tests, nine archive
integration tests, Python/template/JavaScript checks, and Chromium desktop/mobile
checks of covers, 100-item pages, viewer-next-return, native browser Back and scroll.
Browser fixtures and screenshots are under `/tmp/lumina-ui-review-browser`; no
production accounts or state were used. Browser runtime libraries were extracted
privately there, with no system package installation. The owner accepted MacBook
usability; phone and any further browser-specific review remain pending.

After discussing responsive variants, the owner chose to use only 400px image
thumbnails. Workers prepare that size and cache misses can be generated on demand.
The frontend no longer supplies 240/800px srcset candidates; legacy size requests
normalize to 400px. Existing cache files are retained, with no cache wipe/rebuild.
Video poster sizing is unchanged. Embedded JPEG EXIF thumbnails are still accepted
without ensuring sufficient resolution. A future quality upgrade should version
only thumbnail derivatives and prepare better 400px images in the background,
with a representative benchmark first. No quality rebuild is authorized/running.

Future requests recorded in ROADMAP.md: automatic rotation beyond existing EXIF
orientation support, automatic duplicate handling and similar-photo grouping.
No source rotation, duplicate removal or NAS mutation was performed. Agree desired
orientation/keeper/removal behavior before implementing those future features.
The prior integration and this refinement are captured together in the accepted
checkpoint described above. Preserve later unrelated working-tree changes.

Deployment: the web user service was restarted on 2026-10-19 after the checks.
Both production health endpoints returned ok; all four roots were available and
semantic readiness remained 26,038. The updated versioned gallery.js was served.
The browser pilot also checked a real synthetic nested-folder cover, direct last
page navigation (100/100/1), mobile touch-swipe return with exact scroll restoration,
and six mobile viewer controls fitting the viewport with at least 44px targets.
The isolated browser fixture server has been stopped; temporary evidence remains.
The 400px follow-up was also deployed by restarting only the web service. An
isolated image check confirmed 240/400/800 requests all reuse one 400px cache entry;
Python/JavaScript syntax and all-template compilation passed. Both live health
endpoints remained ok, with semantic readiness still 26,038.

## Handoff to the next AI agent

The owner has handed Lumina to a separate agent and returned this conversation
to the broader data-management work. Integration through step 3 is deployed and
finished; there is no unfinished full-library processing queue to resume.
The owner accepted MacBook usability on 2026-10-19; phone review remains pending.

Start by reading this file, `AGENTS.md`, `README.md` and `ROADMAP.md`, then inspect
the current Git diff and recheck the two `/healthz` endpoints. The latest live
check on 2026-10-18 showed both services healthy, all four scans ready, and the
coverage recorded below. These are dated observations, not permanent guarantees.

The deployed integration and browsing refinements are checkpointed in
`/home/yeeyang/projects/lumina`. Preserve any later modified and untracked files;
do not reset, clean, recreate the checkout or discard app state. The isolated build
worktree is `/home/yeeyang/data-management/worktrees/lumina-integration`, based
on `61cbe12`. It was byte-matched to the deployed implementation at handoff.
The live checkout subsequently gained browsing/UI/400px-thumbnail changes and
expanded documentation; do not copy the older worktree over production.

Suggested next steps, in order:

1. Help with remaining phone review and concrete feedback. MacBook usability is
   accepted; isolated Chromium desktop/mobile checks passed.
2. Use ROADMAP.md for requested future work: four-image album covers, better
   400px thumbnail quality, auto-rotation and duplicate/similar-photo handling.
   These are recorded tasks, not currently running jobs.
3. Preserve the accepted checkpoint and review subsequent changes separately;
   do not silently include unrelated changes in later commits.
4. If requested, investigate the 24 New Zealand JPEG decoding failures using
   preserved copies. No repair, deletion or replacement of NAS originals is
   authorized by this handover. Their pending embeddings are blocked on failed
   previews, not unfinished eligible work.

The owner reported Chrome local-network access trouble on their Mac and said
they would investigate it themselves. No Mac settings, tunnel automation,
DNS, HTTPS or network configuration was changed. LAN URL:
`http://192.168.0.110:5050`. A manually started Mac SSH forward is an available
option, not an installed service:

    ssh -N -L 5050:127.0.0.1:5050 yeeyang@192.168.0.110

Then open `http://localhost:5050`. The agent on Ubuntu cannot make the Mac's
localhost forward traffic without a cooperating process on that Mac.

Evidence is in the private integration journal named below: `REVIEW.txt`,
`verification.json`, `browser-review.json`, `unit-tests.log`,
`integration-tests.log`, `runtime-health.json`, `final-units.json`,
`deployed-files.json` and `final-implementation.patch`. Three baseline smoke
tests and nine isolated integration tests passed, together with static,
template, JavaScript and representative real-format browser checks. The code
review was primary-agent self-review, not an independent audit.

`rollback-library.db` and the opaque pre-deployment config copy are private
rollback evidence; `post-integration-library.db` is a verified consistent
post-integration checkpoint. Never publish the journal directory or expose
account hashes, private environment values or session-key contents. A SQLite
checkpoint alone is not a matching code/config rollback; follow the stopped-
writer procedure below. The one-off integration systemd unit was transient and
may no longer be listed after completion; `integration_jobs.py` remains in the
repository. Do not rerun it merely because the transient unit is absent.

The existing SSD media backup is accepted for now. New media schedules,
retention/off-site work, cache garbage collection and SSD detachment remain
outside this handoff. In particular, the wider data-management task is still
underway: do not detach its SSD or alter archived documents/other collections
while working on Lumina.

## Current library and owner decisions

NAS originals remain read-only to Lumina. The four configured locations are:

| Collection | NAS root | Visual items | Source albums |
|---|---|---:|---:|
| travel | `/mnt/yeeyang/media/travel` | 14,913 | 20 |
| events | `/mnt/yeeyang/media/events` | 8,186 | 13 |
| family_photos | `/mnt/yeeyang/media/family_photos` | 2,957 | 11 |
| uncategorized | `/mnt/yeeyang/media/uncategorized` | 6 | 0 |

These are checkpoint counts, not permanent scanner limits. The catalogue holds
26,062 visual items (24,441 images and 1,621 videos), plus 16 separately indexed
WAV recordings. Forty-four `album.json` files describe the shared library albums;
one preserved shell script is not indexed or executed. The total NAS scope is
26,123 files. The media cleanup, 31 empty-folder removals, and album-note updates
are complete. Six loose photos and 16 undated childhood photos are deliberately
parked; do not reclassify them as mandatory review work.

Travel, Events and Family Photos are the home categories. A separate small link
opens Uncategorized. Library albums come from NAS metadata and are shared,
read-only organizational records with stable UUIDs. **My albums** and Favorites
are private user lists in SQLite; they do not change NAS files. Provider/camera
folders and childhood years remain inside their parent album.

The owner accepts the existing verified SSD Restic media copy for now. New media
backup schedules, retention design and off-site work are explicitly deferred.
They intend to detach and keep the SSD offline after the entire broader
data-management task finishes. Do not detach it as part of Lumina integration.
The existing daily local SQLite backup and fourteen-copy policy remain unchanged.

## Services and state

Web: `nfs-image-viewer.service`, LAN port 5050. Semantic inference:
`nfs-image-viewer-semantic.service`, loopback port 5051. NAS: the existing CIFS
mount `//192.168.0.12/yeeyang` at `/mnt/yeeyang`. Source repository:
`/home/yeeyang/projects/lumina`; Python environment: `.venv` (Python 3.12).

SQLite, account/session state and all derived assets are local under
`~/.cache/nfs_image_viewer`, with private directory/file permissions. Never print
password hashes, the session key, NAS credentials or the private environment
file. Source collection paths can be overridden with
`NFS_VIEWER_COLLECTIONS_JSON`; all services must share the same mapping.

The integration retained the existing account and session key. There were no
private favorites or user-created albums at deployment. It rebuilt the media
catalogue, retired the three obsolete collection names after full reconciliation,
and reused 21,811 version-matched historical embeddings, 11,452 thumbnails and
1,418 poster files across the two reviewed alias passes. Reuse imported only
media-derived fields; it did not restore old accounts or user lists. Historical
folder/alias ledgers and file size/nanosecond mtime
must match; removed files are never resurrected.

A private deployment journal and verified rollback database/config copies live
in `/home/yeeyang/data-management/inventory/runs/2026-10-18-lumina-integration`.
Treat that directory as sensitive; its opaque SQLite backups contain account
state. The prior source baseline is commit `61cbe12`; do not remove or rewrite the
older `checkpoint-review-ready` tag. Preserve unrelated working-tree changes.

## Indexing and display pipeline

`scanner.py` performs a bounded metadata traversal and reads only top-level
`album.json` metadata, never image/video bodies. It validates the intended NAS
mount, rejects links and filesystem crossings, gathers a complete collection,
and commits media, album metadata and audio in one transaction. Missing roots,
failed traversal, invalid JSON and conflicting UUIDs retain the previous
catalogue. Unexpected empty collections/albums, missing album UUIDs or a large
reduction are held. `--allow-prune` explicitly permits reviewed album removals or
large reductions; it does not bypass mount/traversal or empty-root safety checks.

Background work then runs:

1. `previews.py`: local display JPEGs for CR2/TIFF and H.264/AAC MP4 copies for
   AVI and incompatible MOV files; ordinary image thumbnail preparation.
2. `enrich.py`: EXIF/video metadata and owner year-folder handling. Copy/scan
   mtimes never become capture dates. `childhood/unknown_year` remains undated.
3. `posters.py`: versioned video posters, with a start-frame fallback for sub-second clips.
4. `semantic_index.py`: local MobileCLIP embeddings; new work requires a ready
   preview or poster. Existing matching embeddings can be reused.

Canon CR2 uses its embedded JPEG, bounded by the source file size. An unavailable
or invalid embedded preview becomes an explicit error; no RAW development or
original conversion is performed. TIFF/RAW full display and legacy video
conversion run only in the background, not a web request. Original downloads
remain available. MOV with H.264/HEVC and AAC may be served directly; HEVC playback
requires browser support. MP4 originals are retained and served directly.

Advisory per-job locks serialize timer, manual and pipeline invocations.
There are at most four preview workers, low-priority systemd execution, atomic
private derivative publication, version checks, resumable row statuses and
per-file errors. Searches and album metadata use local SQLite; ordinary folder
browsing performs one NAS `scandir`, and folder covers use catalogue descendants.
Heavy media operations never write to the NAS. Audio recordings are separate
from image/video totals and do not receive visual embeddings.

## Operations and progress

Existing timers: index every 15 minutes; metadata every 30 minutes; posters and
semantic indexing hourly; local SQLite backup daily. New:
`nfs-image-viewer-previews.timer` prepares newly indexed previews hourly. The
one-off `nfs-image-viewer-integration.service` runs `integration_jobs.py` in order;
it is resumable by rerunning the command after inspecting any failure.

Admin shows actual ready/pending/error totals and up to 100 files needing
attention. A no-op job's `0/0` is not lifetime coverage. Errors are not silently
retried; inspect them before an explicit bounded retry:

    .venv/bin/python previews.py --retry-errors --limit 20
    .venv/bin/python enrich.py --retry-errors --limit 20
    .venv/bin/python posters.py --retry-errors --limit 20
    .venv/bin/python semantic_index.py --retry-errors --limit 20

Background worker failures remain reported without deleting or hiding source
files. Review the final integration report in the data-management journal for
checkpoint coverage and exceptions; do not reuse September's 23,385-item or
11-poster/24-image error figures as current counts.

Final full-pass checkpoint: 26,038 previews and visual-search embeddings ready;
24 New Zealand JPEGs fail decoding and remain downloadable as originals. These
24 have pending embeddings because their previews are unavailable, not because
a worker is still running. Metadata is ready for all 26,062 visual items and
posters for all 1,621 videos. All 985 CR2 and five TIFF previews are ready.
Regular app timers are restored; the existing daily SQLite backup policy is
unchanged. Owner MacBook usability is accepted; phone acceptance remains pending.

## Verification and rollback

Never point automated tests at production SQLite. Standard smoke tests and
`tests/integration_checks.py` create isolated temporary state/media. The browser
pilot additionally used local copies of nine real format samples and 44 metadata
files, served only on loopback, with a synthetic fixture account.

Run the documented checks in README before another deployment. Test auth, private
lists, path gates, NAS failure behavior, invalid metadata, UUID conflicts, empty
and missing albums, legacy formats, seeking, unknown years and mobile layout.
No code review here constitutes a formal security audit.

Before restoring production, stop the web, semantic service, relevant timers and
all DB-writing jobs. Preserve current state, verify the selected rollback copy
with `PRAGMA integrity_check`, restore it using SQLite backup or remove the old
WAL/SHM safely while every connection is stopped, and restore matching source and
configuration. Keep the session key and account data private. Restart the prior
recorded units and verify health. Never restore over a running WAL database.
Do not invoke `backup.py` to create an integration checkpoint if that would prune
older snapshots; the integration used a dedicated verified online copy instead.

## Scope still deferred

The owner's phone usability review remains pending after MacBook acceptance.
Named-face recognition, OCR, perceptual duplicate browsing, local HTTPS, UFW and
cache garbage collection remain separate decisions. LAN-only access, existing
accounts/authentication and the original media are preserved. New media-backup
policy work is deferred by explicit owner choice, not an unfinished prerequisite.
