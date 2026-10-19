"""Real isolated fixtures for archive migration;never imports production settings."""

import os, sys, tempfile, json, re, uuid, io, struct, subprocess, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(tempfile.mkdtemp(prefix='lumina-integration-tests-'))
os.environ['NFS_VIEWER_DATA_DIR'] = str(ROOT / 'data')
os.environ['NFS_VIEWER_COLLECTIONS_JSON'] = json.dumps(
    {
        c: str(ROOT / 'media' / c)
        for c in ('travel', 'events', 'family_photos', 'uncategorized')
    }
)
from PIL import Image
import app, scanner, catalog, previews
from enrich import _captured, _read_metadata


def album(path, title='My trip', identity=None):
    path.mkdir(parents=True, exist_ok=True)
    m = dict(
        schema_version=1,
        album_id=identity or str(uuid.uuid4()),
        title=title,
        date=dict(value='2001', source='owner'),
        description='A family holiday.',
        subfolders=[],
        cleanup_tasks=[],
    )
    (path / 'album.json').write_text(json.dumps(m))
    return m


class ArchiveChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in app.BASE_DIRS.values():
            p.mkdir(parents=True)
        cls.folder = app.BASE_DIRS['travel'] / 'journey'
        cls.meta = album(cls.folder, 'Trip <script>unsafe</script>')
        Image.new('RGB', (32, 24), 'blue').save(cls.folder / 'view.jpg')
        assert scanner.scan_collection('travel', app.BASE_DIRS['travel'])
        cls.client = app.app.test_client()
        s = cls.client.get('/setup')
        token = re.search(rb'name="_csrf_token" value="([^"]+)', s.data)[1].decode()
        assert (
            cls.client.post(
                '/setup',
                data={
                    '_csrf_token': token,
                    'display_name': 'Fixture',
                    'username': 'owner',
                    'password': 'testpass',
                    'password_confirm': 'testpass',
                },
            ).status_code
            == 302
        )

    def test_album_ui_search_and_auth(self):
        page = self.client.get('/library-albums')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'&lt;script&gt;', page.data)
        self.assertNotIn(b'Trip <script>', page.data)
        collection_page = self.client.get('/browse/travel/')
        self.assertIn(b'library-album-card', collection_page.data)
        self.assertIn(b'/cover/travel/journey', collection_page.data)
        self.assertIn(b'Trip &lt;script&gt;unsafe&lt;/script&gt;', collection_page.data)
        self.assertEqual(
            self.client.get('/api/search?q=family%20holiday').json['count'], 1
        )
        self.assertIn(
            b'A family holiday.', self.client.get('/browse/travel/journey').data
        )
        with app.app.test_client() as anon:
            self.assertEqual(anon.get('/library-albums').status_code, 302)
        self.assertEqual(
            self.client.get('/image/travel/../../secret.jpg').status_code, 404
        )

    def test_failed_scan_preserves_rows(self):
        token = re.search(
            rb'name="csrf-token" content="([^"]+)', self.client.get('/').data
        )[1].decode()
        headers = {'X-CSRF-Token': token}
        self.assertTrue(
            self.client.post(
                '/api/favorite/travel/journey/view.jpg', headers=headers
            ).json['favorited']
        )
        private = self.client.post(
            '/api/albums', json={'name': 'Keep during failed scans'}, headers=headers
        ).json['id']
        self.client.post(
            '/api/albums/' + str(private) + '/toggle/travel/journey/view.jpg',
            headers=headers,
        )
        with catalog.connect_db() as db:
            old = [tuple(r) for r in db.execute('SELECT id,subpath FROM media_items')]
        p = self.folder / 'album.json'
        body = p.read_bytes()
        p.write_text('{invalid')
        self.assertFalse(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        p.write_bytes(body)
        with catalog.connect_db() as db:
            self.assertEqual(
                old,
                [tuple(r) for r in db.execute('SELECT id,subpath FROM media_items')],
            )
        link = self.folder / 'escaped.jpg'
        link.symlink_to(ROOT / 'outside.jpg')
        self.assertFalse(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        link.unlink()
        original = self.folder / 'view.jpg'
        hold = ROOT / 'held.jpg'
        original.rename(hold)
        self.assertFalse(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        hold.rename(original)
        with patch(
            'scanner.os.scandir', side_effect=PermissionError('fixture interruption')
        ):
            self.assertFalse(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        with catalog.connect_db() as db:
            self.assertEqual(
                old,
                [tuple(r) for r in db.execute('SELECT id,subpath FROM media_items')],
            )
        self.assertTrue(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        with catalog.connect_db() as db:
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM user_favorites').fetchone()[0], 1
            )
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM album_items').fetchone()[0], 1
            )

    def test_duplicate_uuid_rolls_back(self):
        p = app.BASE_DIRS['events'] / 'conflict'
        album(p, identity=self.meta['album_id'])
        Image.new('RGB', (12, 12)).save(p / 'x.jpg')
        self.assertFalse(scanner.scan_collection('events', app.BASE_DIRS['events']))
        with catalog.connect_db() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM media_items WHERE collection='events'"
                ).fetchone()[0],
                0,
            )
        import shutil

        shutil.rmtree(p)

    def test_legacy_derivatives_and_ranges(self):
        f = app.BASE_DIRS['family_photos'] / 'childhood'
        album(f)
        d = f / '2001'
        d.mkdir(exist_ok=True)
        tif = d / 'scan.tif'
        Image.new('RGB', (20, 30), 'red').save(tif)
        avi = d / 'clip.avi'
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ff,
                '-nostdin',
                '-v',
                'error',
                '-f',
                'lavfi',
                '-i',
                'color=red:size=64x64:rate=10',
                '-t',
                '0.4',
                '-c:v',
                'mjpeg',
                '-threads',
                '1',
                '-y',
                str(avi),
            ],
            check=True,
        )
        self.assertTrue(
            scanner.scan_collection('family_photos', app.BASE_DIRS['family_photos'])
        )
        self.assertEqual(
            self.client.get('/image/family_photos/childhood/2001/scan.tif').status_code,
            503,
        )
        previews.prepare(tif)
        previews.prepare(avi)
        with catalog.connect_db() as db:
            db.execute(
                "UPDATE media_items SET preview_status='ready' WHERE collection='family_photos'"
            )
        r = self.client.get('/image/family_photos/childhood/2001/scan.tif')
        self.assertEqual(r.mimetype, 'image/jpeg')
        r.close()
        r = self.client.get(
            '/image/family_photos/childhood/2001/clip.avi',
            headers={'Range': 'bytes=0-31'},
        )
        self.assertEqual(r.status_code, 206)
        self.assertEqual(len(r.data), 32)
        r.close()
        r = self.client.get('/image/family_photos/childhood/2001/scan.tif?download=1')
        self.assertIn('attachment', r.headers['Content-Disposition'])
        r.close()
        self.assertEqual(tif.suffix, '.tif')
        self.assertTrue(avi.is_file())
        from posters import main as build_posters

        with patch('sys.argv', ['posters.py']):
            self.assertEqual(build_posters(), 0)
        with catalog.connect_db() as db:
            self.assertEqual(
                db.execute(
                    "SELECT poster_status FROM media_items WHERE subpath='childhood/2001/clip.avi'"
                ).fetchone()[0],
                'ready',
            )

    def test_missing_album_holds_otherwise_complete_scan(self):
        one = app.BASE_DIRS['events'] / 'one'
        two = app.BASE_DIRS['events'] / 'two'
        album(one)
        album(two)
        Image.new('RGB', (12, 12)).save(one / 'one.jpg')
        Image.new('RGB', (12, 12)).save(two / 'two.jpg')
        self.assertTrue(scanner.scan_collection('events', app.BASE_DIRS['events']))
        held = ROOT / 'held-event'
        two.rename(held)
        self.assertFalse(scanner.scan_collection('events', app.BASE_DIRS['events']))
        with catalog.connect_db() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM media_items WHERE collection='events'"
                ).fetchone()[0],
                2,
            )
        held.rename(two)
        self.assertTrue(scanner.scan_collection('events', app.BASE_DIRS['events']))

    def test_job_lock_serializes_concurrent_runs(self):
        import threading, time
        from concurrent.futures import ThreadPoolExecutor
        from job_lock import single_job

        active = 0
        peak = 0
        guard = threading.Lock()

        @single_job('fixture')
        def work():
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with guard:
                active -= 1

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: work(), range(2)))
        self.assertEqual(peak, 1)

    def test_raw_embedded_jpeg_and_bad_bounds(self):
        image = Image.new('RGB', (20, 16), 'green')
        b = io.BytesIO()
        image.save(b, format='JPEG')
        jpg = b.getvalue()
        entries = [
            (256, 4, 1, 20),
            (257, 4, 1, 16),
            (258, 3, 1, 8),
            (259, 3, 1, 6),
            (262, 3, 1, 2),
            (273, 4, 1, 122),
            (277, 3, 1, 3),
            (278, 4, 1, 16),
            (279, 4, 1, len(jpg)),
        ]
        offset = 8 + 2 + 12 * len(entries) + 4
        entries[5] = (273, 4, 1, offset)
        blob = (
            b'II*\x00'
            + struct.pack('<I', 8)
            + struct.pack('<H', len(entries))
            + b''.join(struct.pack('<HHII', *e) for e in entries)
            + b'\0' * 4
            + jpg
        )
        p = ROOT / 'sample.cr2'
        p.write_bytes(blob)
        im = previews.open_image(p)
        self.assertEqual(im.size, (20, 16))
        im.close()
        p.write_bytes(blob[:offset])
        self.assertRaises(OSError, previews.open_image, p)

    def test_unknown_date_and_owner_year(self):
        self.assertEqual(_captured('0000:00:00 00:00:00', 123456789), (None, None))
        p = app.BASE_DIRS['family_photos'] / 'childhood/unknown_year'
        p.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (10, 10)).save(p / 'u.jpg')
        row = {
            'id': 1,
            'collection': 'family_photos',
            'subpath': 'childhood/unknown_year/u.jpg',
            'media_type': 'image',
            'mtime_ns': 123456789,
        }
        self.assertEqual(_read_metadata(row)[2:4], (None, None))

    def test_thumbnail_refresh_resumes_and_requires_explicit_error_retry(self):
        import refresh_thumbnails as worker

        folder = app.BASE_DIRS['travel'] / 'thumbnail-worker'
        album(folder)
        for name in ('good.jpg', 'retry.jpg'):
            Image.new('RGB', (900, 600), 'green').save(folder / name)
        self.assertTrue(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        with catalog.connect_db() as db:
            db.execute("UPDATE media_items SET preview_status='ready' "
                       "WHERE collection='travel' AND parent='thumbnail-worker'")
        generate = worker.get_or_create_thumb

        def fail_one(source):
            return b'' if source.name == 'retry.jpg' else generate(source)

        with patch.object(worker, 'get_or_create_thumb', side_effect=fail_one):
            first = worker.refresh()
        self.assertGreaterEqual(first['generated_this_run'], 1)
        self.assertEqual(first['error_count'], 1)
        ready_cache = app._thumb_cache_file(folder / 'good.jpg')
        published_at = ready_cache.stat().st_mtime_ns
        second = worker.refresh()
        self.assertEqual(second['generated_this_run'], 0)
        self.assertEqual(second['held_errors'], 1)
        self.assertEqual(second['errors_this_run'], 0)
        retried = worker.refresh(retry_errors=True)
        self.assertEqual(retried['generated_this_run'], 1)
        self.assertEqual(retried['error_count'], 0)
        self.assertEqual(retried['ready'], retried['eligible_images'])
        self.assertEqual(ready_cache.stat().st_mtime_ns, published_at)

    def test_thumbnail_preview_worker_prepares_new_photos_automatically(self):
        import piexif

        source = self.folder / 'new-photo.jpg'
        embedded = io.BytesIO()
        Image.new('RGB', (160, 120), 'red').save(embedded, format='JPEG')
        exif = piexif.dump({'thumbnail': embedded.getvalue(), '1st': {}})
        Image.new('RGB', (1200, 900), 'green').save(source, exif=exif)
        self.assertTrue(scanner.scan_collection('travel', app.BASE_DIRS['travel']))
        result = subprocess.run([sys.executable, 'previews.py'], cwd=Path(app.__file__).parent,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        with catalog.connect_db() as db:
            status = db.execute("SELECT preview_status FROM media_items "
                                "WHERE collection='travel' AND subpath='journey/new-photo.jpg'").fetchone()[0]
        self.assertEqual(status, 'ready')
        with Image.open(app._thumb_cache_file(source)) as image:
            self.assertEqual(image.size, (400, 300))

    def test_audio_is_separate_and_catalogued(self):
        import wave

        p = app.BASE_DIRS['family_photos'] / 'childhood/songs'
        p.mkdir(parents=True, exist_ok=True)
        with wave.open(str(p / 'song.wav'), 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b'\0' * 160)
        self.assertTrue(
            scanner.scan_collection('family_photos', app.BASE_DIRS['family_photos'])
        )
        r = self.client.get('/api/files/family_photos/childhood/songs')
        self.assertEqual(r.json['images'], [])
        self.assertEqual(len(r.json['audio']), 1)
        r = self.client.get(
            '/audio/family_photos/childhood/songs/song.wav',
            headers={'Range': 'bytes=0-15'},
        )
        self.assertEqual(r.status_code, 206)
        r.close()
        with app.app.test_client() as anon:
            self.assertEqual(
                anon.get('/audio/family_photos/childhood/songs/song.wav').status_code,
                302,
            )


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        import shutil

        shutil.rmtree(ROOT)
