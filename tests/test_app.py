import os
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from PIL import Image


ROOT = Path(tempfile.mkdtemp(prefix='lumina-tests-'))
os.environ['NFS_VIEWER_MEDIA_ROOT'] = str(ROOT / 'media')
os.environ['NFS_VIEWER_DATA_DIR'] = str(ROOT / 'data')
os.environ['NFS_VIEWER_COLLECTIONS_JSON'] = json.dumps(
    {
        name: str(ROOT / 'media' / name)
        for name in ('media_others', 'media_travel', 'our_wedding')
    }
)
for name in ('media_others', 'media_travel', 'our_wedding'):
    (ROOT / 'media' / name).mkdir(parents=True)
Image.new('RGB', (80, 60), 'purple').save(
    ROOT / 'media' / 'media_others' / 'sunset beach.jpg'
)

import app as application  # noqa: E402
from scanner import scan_collection  # noqa: E402


class AnchorParser(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.anchors = {}
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('id'):
            self.anchors[attrs['id']] = attrs.get('href')


class GallerySmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, path in application.BASE_DIRS.items():
            scan_collection(name, path)
        cls.client = application.app.test_client()
        setup = cls.client.get('/setup')
        token = (
            re.search(rb'name="_csrf_token" value="([^"]+)', setup.data)
            .group(1)
            .decode()
        )
        created = cls.client.post(
            '/setup',
            data={
                '_csrf_token': token,
                'display_name': 'Test Owner',
                'username': 'owner',
                'password': 'testpass',
                'password_confirm': 'testpass',
            },
        )
        assert created.status_code == 302

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ROOT)

    def csrf(self):
        page = self.client.get('/')
        return (
            re.search(rb'name="csrf-token" content="([^"]+)', page.data)
            .group(1)
            .decode()
        )

    @contextmanager
    def media_folder(self, count):
        folder = ROOT / 'media' / 'media_others' / 'navigation-fixture'
        folder.mkdir()
        source = ROOT / 'media' / 'media_others' / 'sunset beach.jpg'
        try:
            for index in range(count):
                shutil.copyfile(source, folder / f'photo-{index:03d}.jpg')
            yield folder
        finally:
            shutil.rmtree(folder)

    def test_numbered_gallery_pages_have_100_items(self):
        with self.media_folder(201):
            pages = [
                self.client.get(
                    '/api/files/media_others/navigation-fixture',
                    query_string={'page': page},
                ).get_json()
                for page in (1, 2, 3)
            ]
            self.assertEqual([len(page['images']) for page in pages], [100, 100, 1])
            self.assertEqual([page['page'] for page in pages], [1, 2, 3])
            for page in pages:
                self.assertEqual(page['total_images'], 201)
                self.assertEqual(page['total_pages'], 3)
            names = [name for page in pages for name in page['images']]
            self.assertEqual(names, [f'photo-{index:03d}.jpg' for index in range(201)])

    def test_viewer_preserves_origin_through_previous_and_next(self):
        origins = (
            '/browse/media_others/?page=3&sort=name&order=desc',
            '/search?q=sunset%20beach&mode=catalog',
            '/favorites',
            '/albums',
            '/albums/123',
            '/',
        )
        with self.media_folder(3):
            for origin in origins:
                with self.subTest(origin=origin):
                    response = self.client.get(
                        '/view/media_others/navigation-fixture/photo-001.jpg',
                        query_string={'return_to': origin},
                    )
                    self.assertEqual(response.status_code, 200)
                    anchors = AnchorParser(response.get_data(as_text=True)).anchors
                    self.assertEqual(anchors['backBtn'], origin)
                    for button, filename in (
                        ('prevBtn', 'photo-000.jpg'),
                        ('nextBtn', 'photo-002.jpg'),
                    ):
                        target = urlsplit(anchors[button])
                        self.assertTrue(target.path.endswith('/' + filename))
                        self.assertEqual(parse_qs(target.query)['return_to'], [origin])
                        next_response = self.client.get(anchors[button])
                        self.assertEqual(next_response.status_code, 200)
                        next_anchors = AnchorParser(
                            next_response.get_data(as_text=True)
                        ).anchors
                        self.assertEqual(next_anchors['backBtn'], origin)

    def test_viewer_rejects_unsafe_return_destinations(self):
        origins = (
            None,
            'https://example.com/search',
            '//example.com/search',
            '/\\example.com/search',
            '/search\r\nLocation: https://example.com',
            '/search\x00',
            '/admin',
            '/api/search',
            '/view/media_others/sunset%20beach.jpg',
        )
        for origin in origins:
            with self.subTest(origin=origin):
                response = self.client.get(
                    '/view/media_others/sunset%20beach.jpg',
                    query_string={} if origin is None else {'return_to': origin},
                )
                self.assertEqual(response.status_code, 200)
                anchors = AnchorParser(response.get_data(as_text=True)).anchors
                self.assertEqual(anchors['backBtn'], '/browse/media_others/')

    def test_viewer_escapes_return_query_in_html(self):
        origin = '/search?q="><script>alert(1)</script>&year=2026'
        response = self.client.get(
            '/view/media_others/sunset%20beach.jpg',
            query_string={'return_to': origin},
        )
        markup = response.get_data(as_text=True)
        self.assertEqual(AnchorParser(markup).anchors['backBtn'], origin)
        self.assertIn('&amp;year=2026', markup)
        self.assertNotIn('<script>alert(1)</script>', markup)

    def test_thumbnail_uses_source_resolution_and_preserves_legacy_cache(self):
        import piexif
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            source = Path(directory) / 'oriented.jpg'
            embedded = io.BytesIO()
            Image.new('RGB', (160, 120), 'red').save(embedded, format='JPEG')
            exif = piexif.dump({'0th': {piexif.ImageIFD.Orientation: 6},
                                'thumbnail': embedded.getvalue(), '1st': {}})
            Image.new('RGB', (1200, 900), 'green').save(source, exif=exif)
            cache = application._thumb_cache_file(source)
            legacy = application.THUMB_CACHE.parent / cache.name
            legacy.write_bytes(embedded.getvalue())
            try:
                data = application.get_or_create_thumb(source)
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.size, (300, 400))
                self.assertEqual(legacy.read_bytes(), embedded.getvalue())
                self.assertEqual(application.get_or_create_thumb(source, 800), data)
                self.assertEqual(application.get_or_create_thumb(source, 240), data)
                self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
                with Image.open(source) as original:
                    self.assertEqual(original.size, (1200, 900))
            finally:
                legacy.unlink(missing_ok=True)
                cache.unlink(missing_ok=True)

    def test_thumbnail_does_not_publish_if_source_changes_during_decode(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            source = Path(directory) / 'changing.png'
            Image.new('RGB', (1200, 900), 'green').save(source)
            cache = application._thumb_cache_file(source)
            encode = application._to_jpeg_bytes

            def replace_source(image, quality=80):
                result = encode(image, quality)
                Image.new('RGB', (1201, 901), 'blue').save(source)
                return result

            with patch.object(application, '_to_jpeg_bytes', side_effect=replace_source):
                self.assertEqual(application.get_or_create_thumb(source), b'')
            self.assertFalse(cache.exists())

    def test_pages_and_search(self):
        for path in (
            '/',
            '/search',
            '/favorites',
            '/albums',
            '/account',
            '/admin',
            '/browse/media_others/',
            '/manifest.webmanifest',
            '/sw.js',
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()
        search = self.client.get('/api/search?q=sunset').get_json()
        self.assertEqual(search['count'], 1)
        self.assertEqual(search['results'][0]['subpath'], 'sunset beach.jpg')

    def test_favorite_and_album(self):
        headers = {'X-CSRF-Token': self.csrf()}
        favorite = self.client.post(
            '/api/favorite/media_others/sunset%20beach.jpg', headers=headers
        )
        self.assertEqual(favorite.status_code, 200)
        self.assertTrue(favorite.get_json()['favorited'])
        album = self.client.post('/api/albums', json={'name': 'Trips'}, headers=headers)
        self.assertEqual(album.status_code, 201)
        album_id = album.get_json()['id']
        added = self.client.post(
            f'/api/albums/{album_id}/toggle/media_others/sunset%20beach.jpg',
            headers=headers,
        )
        self.assertEqual(added.status_code, 200)
        self.assertTrue(added.get_json()['added'])
        self.assertEqual(
            self.client.get(f'/api/albums/{album_id}').get_json()['items'][0][
                'subpath'
            ],
            'sunset beach.jpg',
        )
        favorite_search = self.client.get('/api/search?q=sunset&favorites=1').get_json()
        self.assertEqual(favorite_search['count'], 1)

    def test_security_boundaries(self):
        public = self.client.get('/', environ_base={'REMOTE_ADDR': '8.8.8.8'})
        self.assertEqual(public.status_code, 403)
        traversal = self.client.get('/image/media_others/../our_wedding/nope.jpg')
        self.assertEqual(traversal.status_code, 404)
        with application.app.test_client() as anonymous:
            self.assertEqual(anonymous.get('/api/favorites').status_code, 401)


if __name__ == '__main__':
    unittest.main()
