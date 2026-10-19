from flask import Flask, render_template, send_file, abort, jsonify, request, g, url_for
from pathlib import Path
from PIL import Image, ImageOps
from werkzeug.exceptions import HTTPException
import piexif
import io
import os
import hashlib
import ipaddress
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

from catalog import (
    DATA_DIR,
    connect_db,
    init_db as init_catalog_db,
    media_id_for,
    search_catalog,
)
from config import load_base_dirs
from auth import init_auth
from media_cache import poster_cache_file
from formats import IMAGE_EXTS, VIDEO_EXTS, DERIVED_IMAGES
from library_metadata import albums as source_albums, context as source_context
from previews import image_path, video_path

_thumb_executor = ThreadPoolExecutor(max_workers=4)

# Cache directory listings for 60s to avoid repeated SMB reads
_dir_cache: dict[str, tuple[float, list]] = {}
_dir_cache_lock = threading.Lock()
DIR_CACHE_TTL = 60

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

app = Flask(__name__)

BASE_DIRS = load_base_dirs()


JPEG_EXTS = {'.jpg', '.jpeg'}
HEIC_EXTS = {'.heic', '.heif'}
EXIF_EXTS = {'.jpg', '.jpeg', '.tiff', '.tif'}

VIDEO_MIMETYPES = {
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.mov': 'video/quicktime',
    '.webm': 'video/webm',
}
THUMB_SIZE = (400, 400)
THUMB_ALLOWED_SIZES = (400,)
# Persistent cache so thumbnails survive reboots.
THUMB_CACHE = DATA_DIR / 'thumbs'
THUMB_CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
THUMB_CACHE.chmod(0o700)
PAGE_SIZE = 100


def _db():
    return connect_db()


init_catalog_db()


def _trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get(
        'NFS_VIEWER_TRUSTED_NETWORKS',
        '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,'
        '::1/128,fc00::/7,fe80::/10',
    )
    return [
        ipaddress.ip_network(value.strip()) for value in raw.split(',') if value.strip()
    ]


TRUSTED_NETWORKS = _trusted_networks()


@app.before_request
def require_lan_client():
    """Reject non-LAN clients even if the host port is accidentally exposed."""
    if os.environ.get('NFS_VIEWER_LAN_ONLY', '1').lower() in ('0', 'false', 'no'):
        return None
    try:
        client = ipaddress.ip_address(request.remote_addr or '')
    except ValueError:
        abort(403)
    if not any(client in network for network in TRUSTED_NETWORKS):
        abort(403)
    return None


init_auth(app)


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault(
        'Permissions-Policy', 'camera=(), microphone=(), geolocation=()'
    )
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
        "style-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self'",
    )
    return response


def is_image(name: str) -> bool:
    p = Path(name)
    return p.suffix.lower() in IMAGE_EXTS and not p.name.startswith('.')


def is_video(name: str) -> bool:
    p = Path(name)
    return p.suffix.lower() in VIDEO_EXTS and not p.name.startswith('.')


def is_media(name: str) -> bool:
    return is_image(name) or is_video(name)


def fix_orientation(img: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(img)


def _to_jpeg_bytes(img: Image.Image, quality=80) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def _exif_thumbnail(img_path: Path, thumb_size=THUMB_SIZE) -> bytes | None:
    """Extract an embedded EXIF thumbnail without decoding the full image."""
    try:
        exif = piexif.load(str(img_path))
        raw = exif.get('thumbnail')
        if raw and len(raw) > 500:
            # Decode, correct orientation, resize up to THUMB_SIZE
            img = Image.open(io.BytesIO(raw))
            orientation = exif.get('0th', {}).get(piexif.ImageIFD.Orientation, 1)
            if not img.getexif().get(274):
                img.getexif()[274] = orientation
            img = fix_orientation(img).convert('RGB')
            img.thumbnail(thumb_size, Image.LANCZOS)
            return _to_jpeg_bytes(img, quality=75)
    except Exception:
        pass
    return None


def _ratio(val) -> float | None:
    """piexif rationals are (numerator, denominator) tuples."""
    try:
        num, den = val
        return num / den if den else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _gps_decimal(dms, ref) -> float | None:
    """Convert piexif GPS [(d),(m),(s)] + ref ('N'/'S'/'E'/'W') to signed decimal."""
    try:
        d = _ratio(dms[0])
        m = _ratio(dms[1])
        s = _ratio(dms[2])
        if None in (d, m, s):
            return None
        dec = d + m / 60 + s / 3600
        if isinstance(ref, bytes):
            ref = ref.decode(errors='ignore')
        if ref in ('S', 'W'):
            dec = -dec
        return round(dec, 6)
    except (TypeError, IndexError):
        return None


def _bytes_str(v) -> str:
    return (
        v.decode(errors='ignore').strip('\x00 ')
        if isinstance(v, bytes)
        else str(v).strip()
    )


def get_exif_info(img_path: Path) -> dict:
    """Best-effort EXIF summary for background or explicit metadata requests."""
    info: dict = {}
    if img_path.suffix.lower() in {'.cr2', '.heic', '.heif'}:
        try:
            with Image.open(img_path) as image:
                zero = image.getexif()
                details = zero.get_ifd(34665)
                info['camera'] = ' '.join(
                    str(zero.get(k, '')) for k in (271, 272)
                ).strip()
                info['lens'] = str(details.get(42036, ''))
                if details.get(36867):
                    info['taken'] = str(details[36867])
            return info
        except (OSError, ValueError, TypeError):
            return info
    if img_path.suffix.lower() not in EXIF_EXTS:
        return info
    try:
        exif = piexif.load(str(img_path))
    except Exception:
        return info

    zeroth, exf, gps = exif.get('0th', {}), exif.get('Exif', {}), exif.get('GPS', {})

    make = _bytes_str(zeroth.get(piexif.ImageIFD.Make, ''))
    model = _bytes_str(zeroth.get(piexif.ImageIFD.Model, ''))
    camera = ' '.join(p for p in (make, model) if p)
    if camera:
        info['camera'] = camera

    lens = _bytes_str(exf.get(piexif.ExifIFD.LensModel, ''))
    if lens:
        info['lens'] = lens

    dt = _bytes_str(exf.get(piexif.ExifIFD.DateTimeOriginal, ''))
    if dt:
        info['taken'] = dt

    fnum = _ratio(exf.get(piexif.ExifIFD.FNumber))
    if fnum:
        info['aperture'] = f'f/{fnum:g}'

    exp = _ratio(exf.get(piexif.ExifIFD.ExposureTime))
    if exp:
        info['shutter'] = f'1/{round(1 / exp)}s' if exp < 1 else f'{exp:g}s'

    iso = exf.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso:
        info['iso'] = iso[0] if isinstance(iso, (list, tuple)) else iso

    flen = _ratio(exf.get(piexif.ExifIFD.FocalLength))
    if flen:
        info['focal_length'] = f'{flen:g}mm'

    w = exf.get(piexif.ExifIFD.PixelXDimension)
    h = exf.get(piexif.ExifIFD.PixelYDimension)
    if w and h:
        info['dimensions'] = f'{w} × {h}'

    lat = _gps_decimal(
        gps.get(piexif.GPSIFD.GPSLatitude), gps.get(piexif.GPSIFD.GPSLatitudeRef)
    )
    lon = _gps_decimal(
        gps.get(piexif.GPSIFD.GPSLongitude), gps.get(piexif.GPSIFD.GPSLongitudeRef)
    )
    if lat is not None and lon is not None:
        info['gps'] = {
            'lat': lat,
            'lon': lon,
            'map': f'https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}',
        }

    return info


def _thumb_cache_file(img_path: Path, size=400) -> Path:
    # Key includes size+mtime so a replaced file gets a fresh thumbnail
    # instead of serving the stale cached one forever.
    try:
        st = img_path.stat()
        sig = f'{img_path}:{st.st_size}:{st.st_mtime_ns}:{size}'
    except OSError:
        sig = str(img_path)
    key = hashlib.md5(sig.encode()).hexdigest()
    return THUMB_CACHE / f'{key}.jpg'


def get_or_create_thumb(img_path: Path, size=400) -> bytes:
    size = min(THUMB_ALLOWED_SIZES, key=lambda allowed: abs(allowed - int(size)))
    thumb_size = (size, size)
    cache_file = _thumb_cache_file(img_path, size)
    if cache_file.exists():
        return cache_file.read_bytes()

    # Fast path: EXIF embedded thumbnail (reads only JPEG header, ~50KB)
    if img_path.suffix.lower() in JPEG_EXTS:
        data = _exif_thumbnail(img_path, thumb_size)
        if data:
            _write_cache_file(cache_file, data)
            return data

    # Slow path: decode full image with draft mode
    try:
        if img_path.suffix.lower() in DERIVED_IMAGES:
            cached = image_path(img_path)
            if not cached.is_file():
                return b''
            img = Image.open(cached)
        else:
            img = Image.open(img_path)
        if img_path.suffix.lower() in JPEG_EXTS:
            img.draft('RGB', thumb_size)
        img = fix_orientation(img).convert('RGB')
        img.thumbnail(thumb_size, Image.LANCZOS)
        data = _to_jpeg_bytes(img)
        _write_cache_file(cache_file, data)
        return data
    except Exception:
        return b''


def _write_cache_file(cache_file: Path, data: bytes) -> None:
    """Publish a complete cache entry atomically across threads/workers."""
    temp = cache_file.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        temp.write_bytes(data)
        temp.chmod(0o600)
        temp.replace(cache_file)
    finally:
        temp.unlink(missing_ok=True)


def prewarm_thumbs(paths: list[Path]):
    def _gen(p):
        try:
            get_or_create_thumb(p)
        except Exception:
            pass

    for p in paths:
        _thumb_executor.submit(_gen, p)


def list_dir_names(path: Path) -> list[str]:
    """Return just filenames, cached. Fast — no extra stat calls."""
    key = str(path)
    now = time.monotonic()
    with _dir_cache_lock:
        if key in _dir_cache:
            ts, entries = _dir_cache[key]
            if now - ts < DIR_CACHE_TTL:
                return entries
    entries = sorted(os.listdir(path))
    with _dir_cache_lock:
        _dir_cache[key] = (now, entries)
    return entries


def resolve(collection: str, subpath: str) -> Path:
    """Resolve a collection-relative path, rejecting traversal outside the root."""
    base = BASE_DIRS[collection]
    target = (base / subpath) if subpath else base
    # Guard against ../ escapes. Resolve without requiring existence (strict=False)
    # so unmounted volumes still pass the containment check.
    base_r = base.resolve(strict=False)
    target_r = target.resolve(strict=False)
    if base_r != target_r and base_r not in target_r.parents:
        abort(404)
    return target


def collection_mounted(collection: str) -> bool:
    return BASE_DIRS[collection].exists()


def require_collection(fn):
    """404 if the route's <collection> isn't one we serve."""

    @wraps(fn)
    def wrapper(collection, *args, **kwargs):
        if collection not in BASE_DIRS:
            abort(404)
        return fn(collection, *args, **kwargs)

    return wrapper


def _thumb_response(data: bytes):
    """JPEG response with a 1-day cache header, shared by /thumb and /cover."""
    resp = send_file(io.BytesIO(data), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp


@app.route('/')
def index():
    with _db() as conn:
        counts = {
            row['collection']: row['count']
            for row in conn.execute(
                'SELECT collection, COUNT(*) AS count FROM media_items GROUP BY collection'
            )
        }
        favorite_count = conn.execute(
            'SELECT COUNT(*) FROM user_favorites WHERE user_id = ?', (g.user['id'],)
        ).fetchone()[0]
        album_count = conn.execute(
            'SELECT COUNT(*) FROM albums WHERE user_id = ?', (g.user['id'],)
        ).fetchone()[0]
        recent = conn.execute(
            """SELECT collection, subpath, name, media_type, captured_at
               FROM media_items
               ORDER BY COALESCE(captured_at, '') DESC, mtime_ns DESC LIMIT 12"""
        ).fetchall()
    collections = [
        {'name': name, 'mounted': path.is_dir(), 'count': counts.get(name, 0)}
        for name, path in BASE_DIRS.items()
    ]
    return render_template(
        'index.html',
        collections=collections,
        recent=[dict(row) for row in recent],
        favorite_count=favorite_count,
        album_count=album_count,
        source_album_count=len(source_albums()),
        total_media=sum(counts.values()),
        now_hour=time.localtime().tm_hour,
    )


@app.route('/healthz')
def health():
    """Small service check that does not touch media files."""
    try:
        with _db() as conn:
            conn.execute('SELECT 1').fetchone()
        database = 'ok'
    except Exception:
        database = 'error'
    return jsonify(
        {
            'status': 'ok' if database == 'ok' else 'degraded',
            'database': database,
            'collections': {name: path.is_dir() for name, path in BASE_DIRS.items()},
        }
    ), 200 if database == 'ok' else 503


@app.route('/manifest.webmanifest')
def manifest():
    return send_file(
        Path(app.static_folder) / 'manifest.webmanifest',
        mimetype='application/manifest+json',
    )


@app.route('/sw.js')
def service_worker():
    response = send_file(
        Path(app.static_folder) / 'sw.js', mimetype='application/javascript'
    )
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@app.route('/browse/<collection>/', defaults={'subpath': ''})
@app.route('/browse/<collection>/<path:subpath>')
@require_collection
def browse(collection, subpath):
    # Return shell immediately — JS will fetch /api/files/ for the actual listing
    breadcrumbs = []
    if subpath:
        parts = Path(subpath).parts
        for i, part in enumerate(parts):
            breadcrumbs.append({'name': part, 'subpath': str(Path(*parts[: i + 1]))})
    album = source_context(collection, subpath)
    if album and breadcrumbs:
        breadcrumbs[0]['name'] = album['title']
    folder_note = None
    if album and subpath != album['root']:
        relative = subpath[len(album['root']) + 1 :]
        folder_note = next(
            (
                s['description']
                for s in album['metadata']['subfolders']
                if s['path'] == relative
            ),
            None,
        )
    return render_template(
        'gallery.html',
        collection=collection,
        subpath=subpath,
        breadcrumbs=breadcrumbs,
        source_album=album,
        source_albums=source_albums(collection) if not subpath else [],
        folder_note=folder_note,
    )


@app.route('/api/files/<collection>/', defaults={'subpath': ''})
@app.route('/api/files/<collection>/<path:subpath>')
@require_collection
def api_files(collection, subpath):
    if not collection_mounted(collection):
        return jsonify(
            {
                'unmounted': True,
                'collection': collection,
                'folders': [],
                'images': [],
                'page': 1,
                'total_pages': 1,
                'total_images': 0,
            }
        )
    current = resolve(collection, subpath)
    if not current.is_dir():
        abort(404)

    page = max(1, request.args.get('page', 1, type=int))
    sort = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')
    if sort not in ('name', 'mtime'):
        sort = 'name'

    # Single directory enumeration over the mount: names + dir flags, plus mtime
    # only when sorting by it (stat() is a per-entry round-trip on SMB).
    want_mtime = sort == 'mtime'
    folders: list[str] = []
    media: list[str] = []
    mtimes: dict[str, float] = {}
    try:
        with os.scandir(current) as it:
            for e in it:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith('.'):
                        folders.append(e.name)
                elif is_media(e.name):
                    media.append(e.name)
                    if want_mtime:
                        try:
                            mtimes[e.name] = e.stat().st_mtime
                        except OSError:
                            mtimes[e.name] = 0.0
    except OSError:
        return jsonify(
            {
                'unmounted': True,
                'folders': [],
                'images': [],
                'audio': [],
                'page': 1,
                'total_pages': 1,
                'total_images': 0,
            }
        ), 503

    folders.sort()
    if sort == 'mtime':
        media.sort(key=lambda n: mtimes.get(n, 0.0))
    else:
        media.sort()
    if order == 'desc':
        media.reverse()

    total_pages = max(1, (len(media) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    page_media = media[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    page_videos = [n for n in page_media if is_video(n)]

    # Prewarm thumbnails for this page in background (images only — videos have none)
    prewarm_thumbs([current / name for name in page_media if is_image(name)])

    favset = favorites_for(collection, g.user['id'])
    page_favorites = [
        n for n in page_media if (f'{subpath}/{n}' if subpath else n) in favset
    ]

    with _db() as db:
        audio = [
            dict(r)
            for r in db.execute(
                'SELECT name,subpath FROM audio_items WHERE collection=? AND parent=? ORDER BY name',
                (collection, subpath),
            )
        ]
    details = {
        a['root']: dict(title=a['title'], description=a['description'])
        for a in source_albums(collection)
    }
    return jsonify(
        {
            'audio': audio,
            'folder_details': details,
            'folders': folders,
            'images': page_media,  # combined image+video listing
            'videos': page_videos,  # which of the above are videos (for play badge)
            'favorites': page_favorites,
            'page': page,
            'page_size': PAGE_SIZE,
            'total_pages': total_pages,
            'total_images': len(media),
        }
    )


SEARCH_MAX_RESULTS = 1000


@app.route('/search/<collection>')
@require_collection
def search_page(collection):
    q = request.args.get('q', '')
    return render_template('search.html', collection=collection, query=q)


@app.route('/search')
def global_search_page():
    return render_template(
        'search.html', collection='', query=request.args.get('q', '')
    )


@app.route('/api/search/options')
def api_search_options():
    with _db() as conn:
        years = [
            row[0]
            for row in conn.execute(
                'SELECT DISTINCT captured_year FROM media_items '
                'WHERE captured_year IS NOT NULL ORDER BY captured_year DESC'
            )
        ]
        cameras = [
            row[0]
            for row in conn.execute(
                "SELECT camera FROM media_items WHERE camera IS NOT NULL AND camera != '' "
                'GROUP BY camera ORDER BY COUNT(*) DESC, camera LIMIT 50'
            )
        ]
    return jsonify(
        {
            'collections': [
                {'value': name, 'label': name.replace('_', ' ').title()}
                for name in BASE_DIRS
            ],
            'years': years,
            'cameras': cameras,
        }
    )


def _catalog_search_response(forced_collection: str | None = None):
    collection = forced_collection or request.args.get('collection') or None
    if collection and collection not in BASE_DIRS:
        abort(404)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(200, max(24, request.args.get('limit', 120, type=int)))
    year = request.args.get('year', type=int)
    media_type = request.args.get('type') or None
    camera = request.args.get('camera') or None
    favorites_only = request.args.get('favorites') == '1'
    results, total = search_catalog(
        query=request.args.get('q', '').strip(),
        collection=collection,
        year=year,
        media_type=media_type,
        camera=camera,
        favorite_user_id=g.user['id'] if favorites_only else None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    with _db() as conn:
        favorite_ids = {
            row[0]
            for row in conn.execute(
                'SELECT media_id FROM user_favorites WHERE user_id = ?', (g.user['id'],)
            )
        }
    for item in results:
        item['favorite'] = item['id'] in favorite_ids
    return jsonify(
        {
            'results': results,
            'count': total,
            'page': page,
            'total_pages': max(1, (total + per_page - 1) // per_page),
        }
    )


@app.route('/api/search')
def api_global_search():
    return _catalog_search_response()


@app.route('/api/semantic-search')
def api_semantic_search():
    params = request.args.to_dict(flat=True)
    params['user_id'] = str(g.user['id'])
    url = 'http://127.0.0.1:5051/search?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        return exc.read(), exc.code, {'Content-Type': 'application/json'}
    except (urllib.error.URLError, TimeoutError):
        return jsonify(
            {'error': 'Visual search is warming up. Try filename search for now.'}
        ), 503
    data = app.json.loads(payload)
    with _db() as conn:
        favorite_ids = {
            row[0]
            for row in conn.execute(
                'SELECT media_id FROM user_favorites WHERE user_id = ?', (g.user['id'],)
            )
        }
    for item in data.get('results', []):
        item['favorite'] = item['id'] in favorite_ids
    return jsonify(data)


@app.route('/api/search/<collection>')
@require_collection
def api_search(collection):
    return _catalog_search_response(collection)


def favorites_for(collection: str, user_id: int) -> set[str]:
    """All subpaths favorited by one user within a collection."""
    with _db() as conn:
        rows = conn.execute(
            """SELECT m.subpath
               FROM user_favorites f
               JOIN media_items m ON m.id = f.media_id
               WHERE f.user_id = ? AND m.collection = ?""",
            (user_id, collection),
        ).fetchall()
    return {r['subpath'] for r in rows}


def is_favorite(collection: str, subpath: str, user_id: int) -> bool:
    with _db() as conn:
        row = conn.execute(
            """SELECT 1
               FROM user_favorites f
               JOIN media_items m ON m.id = f.media_id
               WHERE f.user_id = ? AND m.collection = ? AND m.subpath = ?""",
            (user_id, collection, subpath),
        ).fetchone()
    return row is not None


@app.route('/api/favorite/<collection>/<path:subpath>', methods=['POST'])
@require_collection
def api_toggle_favorite(collection, subpath):
    """Toggle a favorite. Returns the new state."""
    media_path = resolve(collection, subpath)
    if not media_path.is_file() or not is_media(media_path.name):
        abort(404)
    media_id = media_id_for(collection, subpath)
    if media_id is None:
        return jsonify({'error': 'media is not indexed yet'}), 409
    with _db() as conn:
        existing = conn.execute(
            'SELECT 1 FROM user_favorites WHERE user_id = ? AND media_id = ?',
            (g.user['id'], media_id),
        ).fetchone()
        if existing:
            conn.execute(
                'DELETE FROM user_favorites WHERE user_id = ? AND media_id = ?',
                (g.user['id'], media_id),
            )
            state = False
        else:
            conn.execute(
                'INSERT INTO user_favorites (user_id, media_id, created_at) VALUES (?, ?, ?)',
                (g.user['id'], media_id, time.time()),
            )
            state = True
    return jsonify({'favorited': state})


@app.route('/library-albums')
def library_albums_page():
    return render_template('library_albums.html', source_albums=source_albums())


@app.route('/audio/<collection>/<path:subpath>')
@require_collection
def audio_file(collection, subpath):
    source = resolve(collection, subpath)
    if source.suffix.lower() != '.wav' or not source.is_file():
        abort(404)
    with _db() as db:
        row = db.execute(
            'SELECT 1 FROM audio_items WHERE collection=? AND subpath=?',
            (collection, subpath),
        ).fetchone()
    if not row:
        abort(404)
    return send_file(
        source,
        mimetype='audio/wav',
        conditional=True,
        as_attachment=request.args.get('download') == '1',
    )


@app.route('/favorites')
def favorites_page():
    return render_template('favorites.html')


@app.route('/api/favorites')
def api_favorites():
    """Current user's favorites across collections, newest first."""
    with _db() as conn:
        rows = conn.execute(
            """SELECT m.collection, m.subpath, m.media_type, m.captured_at
               FROM user_favorites f
               JOIN media_items m ON m.id = f.media_id
               WHERE f.user_id = ?
               ORDER BY f.created_at DESC""",
            (g.user['id'],),
        ).fetchall()
    items = [dict(row) for row in rows]
    return jsonify({'favorites': items, 'count': len(items)})


@app.route('/albums')
def albums_page():
    return render_template('albums.html')


@app.route('/albums/<int:album_id>')
def album_page(album_id):
    with _db() as conn:
        album = conn.execute(
            'SELECT id, name, description FROM albums WHERE id = ? AND user_id = ?',
            (album_id, g.user['id']),
        ).fetchone()
    if not album:
        abort(404)
    return render_template('album.html', album=dict(album))


@app.route('/api/albums', methods=['GET', 'POST'])
def api_albums():
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        name = str(payload.get('name', '')).strip()
        description = str(payload.get('description', '')).strip()
        if not name or len(name) > 80:
            return jsonify({'error': 'Album name must be 1–80 characters.'}), 400
        try:
            with _db() as conn:
                cursor = conn.execute(
                    """INSERT INTO albums (user_id, name, description, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (g.user['id'], name, description[:500], time.time(), time.time()),
                )
                album_id = cursor.lastrowid
        except Exception as exc:
            if 'UNIQUE constraint failed' in str(exc):
                return jsonify(
                    {'error': 'You already have an album with that name.'}
                ), 409
            raise
        return jsonify({'id': album_id, 'name': name}), 201

    with _db() as conn:
        rows = conn.execute(
            """SELECT a.id, a.name, a.description, a.updated_at,
                      COUNT(ai.media_id) AS count,
                      (SELECT m.collection FROM album_items x
                       JOIN media_items m ON m.id = x.media_id
                       WHERE x.album_id = a.id ORDER BY x.created_at DESC LIMIT 1) AS cover_collection,
                      (SELECT m.subpath FROM album_items x
                       JOIN media_items m ON m.id = x.media_id
                       WHERE x.album_id = a.id ORDER BY x.created_at DESC LIMIT 1) AS cover_subpath,
                      (SELECT m.media_type FROM album_items x
                       JOIN media_items m ON m.id = x.media_id
                       WHERE x.album_id = a.id ORDER BY x.created_at DESC LIMIT 1) AS cover_media_type
               FROM albums a
               LEFT JOIN album_items ai ON ai.album_id = a.id
               WHERE a.user_id = ?
               GROUP BY a.id
               ORDER BY a.updated_at DESC""",
            (g.user['id'],),
        ).fetchall()
    return jsonify({'albums': [dict(row) for row in rows]})


@app.route('/api/albums/<int:album_id>', methods=['GET', 'DELETE'])
def api_album(album_id):
    with _db() as conn:
        album = conn.execute(
            'SELECT id, name, description FROM albums WHERE id = ? AND user_id = ?',
            (album_id, g.user['id']),
        ).fetchone()
        if not album:
            abort(404)
        if request.method == 'DELETE':
            conn.execute('DELETE FROM albums WHERE id = ?', (album_id,))
            return '', 204
        rows = conn.execute(
            """SELECT m.collection, m.subpath, m.media_type, m.captured_at
               FROM album_items ai
               JOIN media_items m ON m.id = ai.media_id
               WHERE ai.album_id = ?
               ORDER BY ai.created_at DESC""",
            (album_id,),
        ).fetchall()
    return jsonify({'album': dict(album), 'items': [dict(row) for row in rows]})


@app.post('/api/albums/<int:album_id>/toggle/<collection>/<path:subpath>')
@require_collection
def api_toggle_album_item(collection, subpath, album_id):
    media_path = resolve(collection, subpath)
    if not media_path.is_file() or not is_media(media_path.name):
        abort(404)
    media_id = media_id_for(collection, subpath)
    if media_id is None:
        return jsonify({'error': 'media is not indexed yet'}), 409
    with _db() as conn:
        album = conn.execute(
            'SELECT id FROM albums WHERE id = ? AND user_id = ?',
            (album_id, g.user['id']),
        ).fetchone()
        if not album:
            abort(404)
        exists = conn.execute(
            'SELECT 1 FROM album_items WHERE album_id = ? AND media_id = ?',
            (album_id, media_id),
        ).fetchone()
        if exists:
            conn.execute(
                'DELETE FROM album_items WHERE album_id = ? AND media_id = ?',
                (album_id, media_id),
            )
            added = False
        else:
            conn.execute(
                'INSERT INTO album_items (album_id, media_id, created_at) VALUES (?, ?, ?)',
                (album_id, media_id, time.time()),
            )
            added = True
        conn.execute(
            'UPDATE albums SET updated_at = ? WHERE id = ?', (time.time(), album_id)
        )
    return jsonify({'added': added})


@app.route('/thumb/<collection>/<path:subpath>')
@require_collection
def thumbnail(collection, subpath):
    img_path = resolve(collection, subpath)
    if not img_path.exists() or not is_image(img_path.name):
        abort(404)
    if img_path.suffix.lower() in DERIVED_IMAGES and not image_path(img_path).is_file():
        abort(503, description='Preview pending')
    data = get_or_create_thumb(img_path, request.args.get('size', 400, type=int))
    if not data:
        abort(500)
    return _thumb_response(data)


@app.route('/poster/<collection>/<path:subpath>')
@require_collection
def video_poster(collection, subpath):
    video_path = resolve(collection, subpath)
    if not video_path.is_file() or not is_video(video_path.name):
        abort(404)
    poster = poster_cache_file(video_path)
    if not poster.is_file():
        abort(404)
    return _thumb_response(poster.read_bytes())


@app.route('/api/exif/<collection>/<path:subpath>')
@require_collection
def api_exif(collection, subpath):
    img_path = resolve(collection, subpath)
    if not img_path.exists() or not is_image(img_path.name):
        return jsonify({})
    return jsonify(get_exif_info(img_path))


@app.route('/cover/<collection>/<path:subpath>')
@require_collection
def folder_cover(collection, subpath):
    """Thumbnail of the first image inside a folder, for use as its cover."""
    folder = resolve(collection, subpath)
    if not folder.is_dir():
        abort(404)
    prefix = subpath + '/' if subpath else ''
    with _db() as db:
        row = db.execute(
            "SELECT subpath,media_type FROM media_items WHERE collection=? AND substr(subpath,1,?)=? ORDER BY CASE WHEN media_type='image' THEN 0 ELSE 1 END,subpath LIMIT 1",
            (collection, len(prefix), prefix),
        ).fetchone()
    if not row:
        abort(404)
    source = resolve(collection, row['subpath'])
    if row['media_type'] == 'video':
        cached = poster_cache_file(source)
        if not cached.is_file():
            abort(404)
        return _thumb_response(cached.read_bytes())
    data = get_or_create_thumb(source, request.args.get('size', 400, type=int))
    if not data:
        abort(404)
    return _thumb_response(data)


@app.route('/image/<collection>/<path:subpath>')
@require_collection
def serve_image(collection, subpath):
    img_path = resolve(collection, subpath)
    if not img_path.is_file() or not is_media(img_path.name):
        abort(404)
    ext = img_path.suffix.lower()
    if request.args.get('download') == '1':
        return send_file(img_path, as_attachment=True, conditional=True)
    if ext in DERIVED_IMAGES:
        cached = image_path(img_path)
        if not cached.is_file():
            abort(
                503,
                description='Preview is being prepared;original remains available for download.',
            )
        return send_file(cached, mimetype='image/jpeg', conditional=True)
    if is_video(img_path.name):
        if ext in ('.avi', '.mov'):
            cached = video_path(img_path)
            if cached.is_file():
                return send_file(cached, mimetype='video/mp4', conditional=True)
            with _db() as db:
                row = db.execute(
                    'SELECT preview_status FROM media_items WHERE collection=? AND subpath=?',
                    (collection, subpath),
                ).fetchone()
            if not row or row['preview_status'] != 'ready' or ext == '.avi':
                abort(
                    503,
                    description='Playback copy is being prepared;download original or try later.',
                )
        # conditional=True enables HTTP range requests so the browser can seek.
        return send_file(
            img_path, mimetype=VIDEO_MIMETYPES.get(ext, 'video/mp4'), conditional=True
        )
    if ext in HEIC_EXTS:
        try:
            img = fix_orientation(Image.open(img_path)).convert('RGB')
            return send_file(io.BytesIO(_to_jpeg_bytes(img)), mimetype='image/jpeg')
        except Exception:
            abort(500)
    return send_file(img_path)


def _viewer_return_url(value, fallback):
    """Only link back to local, read-only library pages."""
    if not value or not value.startswith('/') or len(value) > 8192:
        return fallback
    try:
        parsed = urllib.parse.urlsplit(value)
        decoded_path = urllib.parse.unquote(parsed.path)
        if (
            parsed.scheme or parsed.netloc or parsed.fragment
            or decoded_path.startswith('//')
            or '\\' in decoded_path
            or any(ord(c) < 32 or ord(c) == 127 for c in value + decoded_path)
        ):
            return fallback
        endpoint, _ = app.url_map.bind('').match(decoded_path, method='GET')
    except (ValueError, HTTPException):
        # Routing failures and malformed URLs use the media's containing folder.
        return fallback
    if endpoint not in {
        'index', 'browse', 'library_albums_page', 'global_search_page',
        'search_page', 'favorites_page', 'albums_page', 'album_page',
    }:
        return fallback
    return value


@app.route('/view/<collection>/<path:subpath>')
@require_collection
def view(collection, subpath):
    img_path = resolve(collection, subpath)
    if not img_path.is_file() or not is_media(img_path.name):
        abort(404)

    parent = img_path.parent
    names = list_dir_names(parent)
    siblings = [parent / n for n in names if is_media(n)]
    idx = next((i for i, s in enumerate(siblings) if s == img_path), 0)

    parent_subpath = str(img_path.relative_to(BASE_DIRS[collection]).parent)
    if parent_subpath == '.':
        parent_subpath = ''

    return_to = _viewer_return_url(
        request.args.get('return_to'),
        url_for('browse', collection=collection, subpath=parent_subpath),
    )

    prev_path = (
        str(siblings[idx - 1].relative_to(BASE_DIRS[collection])) if idx > 0 else None
    )
    next_path = (
        str(siblings[idx + 1].relative_to(BASE_DIRS[collection]))
        if idx < len(siblings) - 1
        else None
    )

    media_id = media_id_for(collection, subpath)
    with _db() as conn:
        albums = conn.execute(
            """SELECT a.id, a.name,
                      EXISTS(SELECT 1 FROM album_items ai
                             WHERE ai.album_id = a.id AND ai.media_id = ?) AS contains
               FROM albums a WHERE a.user_id = ? ORDER BY a.name COLLATE NOCASE""",
            (media_id or -1, g.user['id']),
        ).fetchall()

    with _db() as conn:
        preview = conn.execute(
            'SELECT preview_status,preview_error FROM media_items WHERE id=?',
            (media_id,),
        ).fetchone()
    preview_notice = None
    if img_path.suffix.lower() in DERIVED_IMAGES or img_path.suffix.lower() in (
        '.avi',
        '.mov',
    ):
        if not preview or preview['preview_status'] != 'ready':
            preview_notice = (
                'Preview could not be prepared. The original is available below.'
                if preview and preview['preview_status'] == 'error'
                else 'A browser-friendly preview is being prepared. The original is available below.'
            )
    return render_template(
        'viewer.html',
        preview_notice=preview_notice,
        collection=collection,
        subpath=subpath,
        prev_path=prev_path,
        next_path=next_path,
        parent_subpath=parent_subpath,
        return_to=return_to,
        filename=img_path.name,
        is_video=is_video(img_path.name),
        is_favorite=is_favorite(collection, subpath, g.user['id']),
        albums=[dict(album) for album in albums],
        idx=idx + 1,
        total=len(siblings),
    )


if __name__ == '__main__':
    app.run(
        host=os.environ.get('NFS_VIEWER_DEV_HOST', '127.0.0.1'),
        port=int(os.environ.get('NFS_VIEWER_PORT', '5050')),
        debug=os.environ.get('NFS_VIEWER_DEBUG', '0').lower() in ('1', 'true', 'yes'),
        threaded=True,
    )
