import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(tempfile.mkdtemp(prefix='lumina-tests-'))
os.environ['NFS_VIEWER_MEDIA_ROOT'] = str(ROOT / 'media')
os.environ['NFS_VIEWER_DATA_DIR'] = str(ROOT / 'data')
for name in ('media_others', 'media_travel', 'our_wedding'):
    (ROOT / 'media' / name).mkdir(parents=True)
Image.new('RGB', (80, 60), 'purple').save(
    ROOT / 'media' / 'media_others' / 'sunset beach.jpg'
)

import app as application  # noqa: E402
from scanner import scan_collection  # noqa: E402


class GallerySmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, path in application.BASE_DIRS.items():
            scan_collection(name, path)
        cls.client = application.app.test_client()
        setup = cls.client.get('/setup')
        token = re.search(rb'name="_csrf_token" value="([^"]+)', setup.data).group(1).decode()
        created = cls.client.post('/setup', data={
            '_csrf_token': token,
            'display_name': 'Test Owner',
            'username': 'owner',
            'password': 'testpass',
            'password_confirm': 'testpass',
        })
        assert created.status_code == 302

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ROOT)

    def csrf(self):
        page = self.client.get('/')
        return re.search(rb'name="csrf-token" content="([^"]+)', page.data).group(1).decode()

    def test_pages_and_search(self):
        for path in ('/', '/search', '/favorites', '/albums', '/account', '/admin',
                     '/browse/media_others/', '/manifest.webmanifest', '/sw.js'):
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
        album = self.client.post(
            '/api/albums', json={'name': 'Trips'}, headers=headers
        )
        self.assertEqual(album.status_code, 201)
        album_id = album.get_json()['id']
        added = self.client.post(
            f'/api/albums/{album_id}/toggle/media_others/sunset%20beach.jpg',
            headers=headers,
        )
        self.assertEqual(added.status_code, 200)
        self.assertTrue(added.get_json()['added'])
        self.assertEqual(self.client.get(f'/api/albums/{album_id}').get_json()['items'][0]['subpath'],
                         'sunset beach.jpg')
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
