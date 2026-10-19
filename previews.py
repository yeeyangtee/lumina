"""Local display/playback derivatives. Expensive conversions run in the worker only."""

from job_lock import single_job
import io
import os
import subprocess
import threading
import re
from PIL import Image, ImageOps
from catalog import DATA_DIR
from media_cache import poster_cache_file
from formats import DERIVED_IMAGES

ROOT = DATA_DIR / 'previews'


def cache_path(source, suffix):
    # Same versioned signature as posters, different private cache directory.
    return ROOT / (poster_cache_file(source).stem + suffix)


def image_path(source):
    return cache_path(source, '.jpg')


def video_path(source):
    return cache_path(source, '.mp4')


def open_image(source):
    """Decode a regular image or the embedded full-size JPEG inside Canon CR2."""
    if source.suffix.lower() != '.cr2':
        with Image.open(source) as im:
            return ImageOps.exif_transpose(im).convert('RGB')
    with Image.open(source) as raw:
        offset = raw.tag_v2.get(273)
        length = raw.tag_v2.get(279)
        orientation = raw.getexif().get(274, 1)
    offset = (
        offset[0] if isinstance(offset, (tuple, list)) and len(offset) == 1 else offset
    )
    length = (
        length[0] if isinstance(length, (tuple, list)) and len(length) == 1 else length
    )
    if (
        not isinstance(offset, int)
        or not isinstance(length, int)
        or offset < 0
        or not 0 < length <= 32 * 1024 * 1024
        or offset + length > source.stat().st_size
    ):
        raise OSError('No safe embedded RAW preview')
    with source.open('rb') as f:
        f.seek(offset)
        blob = f.read(length)
    if not blob.startswith(b'\xff\xd8'):
        raise OSError('RAW embedded preview is not JPEG')
    with Image.open(io.BytesIO(blob)) as im:
        if not im.getexif().get(274) and orientation != 1:
            im.getexif()[274] = orientation
        return ImageOps.exif_transpose(im).convert('RGB')


def prepare(source):
    """Publish an immutable local derivative, never write to the source."""
    import imageio_ffmpeg

    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    ext = source.suffix.lower()
    before = source.stat()
    target = None
    if ext in DERIVED_IMAGES:
        target = image_path(source)
        if target.is_file():
            return target
        im = open_image(source)
        im.thumbnail((2560, 2560))
        data = io.BytesIO()
        im.save(data, format='JPEG', quality=90)
        im.close()
        temp = target.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
        try:
            temp.write_bytes(data.getvalue())
            temp.chmod(0o600)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise OSError('Source changed')
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return target
    if ext not in ('.avi', '.mov'):
        return source
    target = video_path(source)
    if target.is_file():
        return target
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    if ext == '.mov':
        probe = subprocess.run(
            [ff, '-nostdin', '-hide_banner', '-i', str(source)],
            capture_output=True,
            text=True,
            timeout=45,
        )
        v = re.search(r'Video: (\w+)', probe.stderr)
        a = re.search(r'Audio: (\w+)', probe.stderr)
        if v and v[1] in ('h264', 'hevc') and (not a or a[1] == 'aac'):
            return source
    temp = target.with_suffix(f'.{os.getpid()}.tmp.mp4')
    try:
        p = subprocess.run(
            [
                ff,
                '-nostdin',
                '-v',
                'error',
                '-threads',
                '2',
                '-i',
                str(source),
                '-map',
                '0:v:0',
                '-map',
                '0:a?',
                '-vf',
                'scale=min(1280\\,iw):-2',
                '-c:v',
                'libx264',
                '-threads',
                '2',
                '-preset',
                'fast',
                '-crf',
                '23',
                '-pix_fmt',
                'yuv420p',
                '-c:a',
                'aac',
                '-b:a',
                '128k',
                '-movflags',
                '+faststart',
                '-y',
                str(temp),
            ],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if p.returncode or not temp.is_file() or not temp.stat().st_size:
            raise OSError('Playback conversion failed')
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError('Source changed')
        temp.chmod(0o600)
        temp.replace(target)
        return target
    finally:
        temp.unlink(missing_ok=True)


@single_job('previews')
def main():
    import argparse
    from config import load_base_dirs
    from catalog import connect_db, init_db, update_job
    from app import get_or_create_thumb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    init_db()
    roots = load_base_dirs()
    with connect_db() as db:
        rows = db.execute(
            'SELECT id,collection,subpath,media_type,size,mtime_ns FROM media_items WHERE preview_status IN ('
            + ("'pending','error'" if args.retry_errors else "'pending'")
            + ") ORDER BY CASE WHEN extension IN ('.cr2','.tif','.tiff','.avi','.mov') THEN 0 ELSE 1 END,id"
            + (' LIMIT ?' if args.limit else ''),
            ([args.limit] if args.limit else []),
        ).fetchall()
    update_job('previews', 'running', 0, len(rows))
    errors = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process(row):
        try:
            source = roots[row['collection']] / row['subpath']
            s = source.stat()
            if (s.st_size, s.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source version changed')
            prepare(source)
            if row['media_type'] == 'image' and not get_or_create_thumb(source):
                raise OSError('Image preview failed')
            s = source.stat()
            if (s.st_size, s.st_mtime_ns) != (row['size'], row['mtime_ns']):
                raise OSError('Source version changed')
            with connect_db() as db:
                db.execute(
                    "UPDATE media_items SET preview_status='ready',preview_error=NULL WHERE id=? AND size=? AND mtime_ns=?",
                    (row['id'], row['size'], row['mtime_ns']),
                )
            return 0
        except Exception as e:
            with connect_db() as db:
                db.execute(
                    "UPDATE media_items SET preview_status='error',preview_error=? WHERE id=? AND size=? AND mtime_ns=?",
                    (
                        type(e).__name__ + ': ' + str(e)[:200],
                        row['id'],
                        row['size'],
                        row['mtime_ns'],
                    ),
                )
            return 1

    with ThreadPoolExecutor(max_workers=max(1, min(4, args.workers))) as pool:
        futures = [pool.submit(process, row) for row in rows]
        for n, future in enumerate(as_completed(futures), 1):
            errors += future.result()
            if n % 100 == 0:
                update_job('previews', 'running', n, len(rows))
                print(f'previews:{n}/{len(rows)} errors:{errors}', flush=True)
    update_job(
        'previews',
        'ready',
        len(rows),
        len(rows),
        f'{errors} errors' if errors else None,
    )
    print(f'previews:finished {len(rows)},errors:{errors}', flush=True)


if __name__ == '__main__':
    main()
