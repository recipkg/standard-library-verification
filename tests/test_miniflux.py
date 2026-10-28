"""Exercise a Miniflux candidate against disposable PostgreSQL and HTTP fixtures."""
import base64
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
import urllib.error
import urllib.request


class FixtureFeed(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        data = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
                b'<title>Fixture Feed</title><link>http://127.0.0.1/</link>'
                b'<description>Test feed</description><item><title>Fixture entry</title>'
                b'<link>http://127.0.0.1/item/1</link><guid>recipkg-entry-1</guid>'
                b'<description>Entry body</description></item></channel></rss>')
        self.send_response(200)
        self.send_header('Content-Type', 'application/rss+xml')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


def unused_local_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class MinifluxSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('RECIPKG_TEST_MINIFLUX')
        if not path:
            raise unittest.SkipTest('set RECIPKG_TEST_MINIFLUX to a disposable test binary')
        cls.binary = shutil.which(path)
        if not cls.binary:
            raise RuntimeError('RECIPKG_TEST_MINIFLUX executable not found')
        for name in ('initdb', 'pg_ctl'):
            if not shutil.which(name):
                raise RuntimeError(f'{name} is required when RECIPKG_TEST_MINIFLUX is set')
        cls.root = Path(tempfile.mkdtemp(prefix='recipkg-miniflux-'))
        cls.db_stopped = True
        cls.addClassCleanup(cls.cleanup_root)
        cls.db = cls.root / 'db'
        cls.feed = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FixtureFeed)
        cls.thread = threading.Thread(target=cls.feed.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_feed)
        result = subprocess.run(['initdb', '-D', str(cls.db), '--auth=trust', '-U', 'recipkg_test',
                                 '--no-locale', '-E', 'UTF8'], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(f'initdb failed: {result.stderr[-600:]}')
        db_port = unused_local_port()
        cls.db_stopped = False
        cls.addClassCleanup(cls.stop_database)
        result = subprocess.run(['pg_ctl', '-D', str(cls.db), '-l', str(cls.root / 'db.log'),
                                 '-o', f"-F -h '' -k {cls.root} -p {db_port}", '-w', 'start'],
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(f'isolated postgres failed: {result.stderr[-600:]}')
        port = unused_local_port()
        cls.base = f'http://127.0.0.1:{port}'
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8',
               'DATABASE_URL': f'host={cls.root} port={db_port} user=recipkg_test dbname=postgres sslmode=disable',
               'RUN_MIGRATIONS': '1', 'CREATE_ADMIN': '1',
               'ADMIN_USERNAME': 'fixture-admin', 'ADMIN_PASSWORD': 'fixture-password-321',
               'LISTEN_ADDR': f'127.0.0.1:{port}', 'BASE_URL': cls.base,
               'FETCHER_ALLOW_PRIVATE_NETWORKS': '1', 'DISABLE_SCHEDULER_SERVICE': '1',
               'LOG_LEVEL': 'error'}
        cls.log = (cls.root / 'miniflux.log').open('w')
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen([cls.binary], stdout=cls.log, stderr=subprocess.STDOUT, env=env)
        cls.addClassCleanup(cls.stop_application)
        for _ in range(150):
            if cls.process.poll() is not None:
                raise RuntimeError('Miniflux exited before readiness; inspect test configuration')
            try:
                with urllib.request.urlopen(cls.base + '/healthcheck', timeout=0.2):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError('Miniflux did not become ready on its temporary port')
        version = subprocess.run([cls.binary, '-version'], capture_output=True, text=True, timeout=10)
        print('miniflux target:', version.stdout.strip() or version.stderr.strip())

    @classmethod
    def stop_application(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)

    @classmethod
    def stop_database(cls):
        status = subprocess.run(['pg_ctl', '-D', str(cls.db), 'status'],
                                capture_output=True, text=True, timeout=10)
        if status.returncode == 0:
            subprocess.run(['pg_ctl', '-D', str(cls.db), '-m', 'fast', '-w', 'stop'],
                           capture_output=True, text=True, timeout=30, check=True)
            status = subprocess.run(['pg_ctl', '-D', str(cls.db), 'status'],
                                    capture_output=True, text=True, timeout=10)
        if status.returncode != 3:
            raise RuntimeError(f'cannot verify test PostgreSQL is stopped: {cls.root}')
        cls.db_stopped = True

    @classmethod
    def cleanup_root(cls):
        if cls.db_stopped:
            shutil.rmtree(cls.root)
        else:
            print(f'Preserved test data because PostgreSQL shutdown was not confirmed: {cls.root}')

    @classmethod
    def stop_feed(cls):
        cls.feed.shutdown()
        cls.feed.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, payload=None, *, user='fixture-admin',
                password='fixture-password-321', raw=None, token=None):
        headers = {}
        if user is not None:
            encoded = base64.b64encode(f'{user}:{password}'.encode()).decode()
            headers['Authorization'] = 'Basic ' + encoded
        if token is not None:
            headers['X-Auth-Token'] = token
        body = raw
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                status, contents = response.status, response.read()
        except urllib.error.HTTPError as error:
            try:
                status, contents = error.code, error.read()
            finally:
                error.close()
        return status, json.loads(contents) if contents else None

    def test_auth_categories_and_user_isolation(self):
        self.assertEqual(self.request('GET', '/v1/categories', user=None)[0], 401)
        self.assertEqual(self.request('GET', '/v1/me', password='wrong')[0], 401)
        status, me = self.request('GET', '/v1/me')
        self.assertEqual(status, 200)
        self.assertEqual(me['username'], 'fixture-admin')
        status, key = self.request('POST', '/v1/api-keys', {'description': 'fixture key'})
        self.assertEqual(status, 201)
        status, token_user = self.request('GET', '/v1/me', user=None, token=key['token'])
        self.assertEqual((status, token_user['id']), (200, me['id']))
        self.assertEqual(self.request('GET', '/v1/me', user=None, token='invalid-fixture-token')[0], 401)
        self.assertEqual(self.request('DELETE', f"/v1/api-keys/{key['id']}")[0], 204)
        self.assertEqual(self.request('GET', '/v1/me', user=None, token=key['token'])[0], 401)
        status, cat = self.request('POST', '/v1/categories',
                                   {'title': 'Black box category', 'hide_globally': True})
        self.assertEqual(status, 201)
        self.assertEqual((cat['user_id'], cat['title'], cat['hide_globally']),
                         (me['id'], 'Black box category', True))
        cid = cat['id']
        self.assertEqual(self.request('POST', '/v1/categories', {'title': ''})[0], 400)
        self.assertEqual(self.request('POST', '/v1/categories', {'title': 'Black box category'})[0], 400)
        self.assertEqual(self.request('POST', '/v1/categories', raw=b'{bad')[0], 400)
        status, updated = self.request('PUT', f'/v1/categories/{cid}',
                                       {'title': 'Renamed category', 'hide_globally': False})
        self.assertEqual(status, 201)
        self.assertEqual((updated['title'], updated['hide_globally']), ('Renamed category', False))
        status, user = self.request('POST', '/v1/users',
                                    {'username': 'fixture-user', 'password': 'fixture-user-password-321',
                                     'is_admin': False})
        self.assertEqual(status, 201)
        status, categories = self.request('GET', '/v1/categories', user='fixture-user',
                                          password='fixture-user-password-321')
        self.assertEqual(status, 200)
        self.assertTrue(all(category['user_id'] == user['id'] for category in categories))
        self.assertNotIn(cid, [category['id'] for category in categories])
        self.assertEqual(self.request('PUT', f'/v1/categories/{cid}', {'title': 'outside'},
                                      user='fixture-user', password='fixture-user-password-321')[0], 404)
        self.assertEqual(self.request('DELETE', f'/v1/categories/{cid}')[0], 204)
        self.assertEqual(self.request('DELETE', f'/v1/categories/{cid}')[0], 404)

    def test_opml_import_export_and_partial_failure(self):
        username, password = 'fixture-opml', 'fixture-opml-password-321'
        status, _ = self.request('POST', '/v1/users',
                                 {'username': username, 'password': password, 'is_admin': False})
        self.assertEqual(status, 201)
        credentials = {'user': username, 'password': password}
        opml = (b'<opml version="2.0"><body><outline text="Technology">'
                b'<outline text="Alpha" xmlUrl="https://example.invalid/a.xml" '
                b'htmlUrl="https://example.invalid/a"/>'
                b'<outline text="Nested"><outline text="Beta" '
                b'xmlUrl="https://example.invalid/b.xml"/></outline></outline>'
                b'<outline text="Loose" xmlUrl="https://example.invalid/loose.xml"/>'
                b'</body></opml>')
        for _ in range(2):
            status, body = self.request('POST', '/v1/import', raw=opml, **credentials)
            self.assertEqual((status, body['message']), (201, 'Feeds imported successfully'))
        status, feeds = self.request('GET', '/v1/feeds', **credentials)
        self.assertEqual(status, 200)
        observed = {feed['feed_url']: (feed['title'], feed['category']['title']) for feed in feeds}
        self.assertEqual(observed, {
            'https://example.invalid/a.xml': ('Alpha', 'Technology'),
            'https://example.invalid/b.xml': ('Beta', 'Nested'),
            'https://example.invalid/loose.xml': ('Loose', 'All'),
        })
        self.assertEqual(len(feeds), 3)
        self.assertEqual(self.request('GET', '/v1/entries', **credentials)[1]['total'], 0)

        auth = base64.b64encode(f'{username}:{password}'.encode()).decode()
        request = urllib.request.Request(self.base + '/v1/export',
                                         headers={'Authorization': 'Basic ' + auth})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers['Content-Type'].startswith('text/xml'))
            exported = response.read()
            document = ET.fromstring(exported)
        self.assertEqual((document.tag, document.get('version')), ('opml', '2.0'))
        groups = {group.get('text'): {item.get('xmlUrl') for item in group.findall('outline')}
                  for group in document.findall('./body/outline')}
        self.assertEqual(groups, {'All': {'https://example.invalid/loose.xml'},
                                  'Nested': {'https://example.invalid/b.xml'},
                                  'Technology': {'https://example.invalid/a.xml'}})
        second = {'user': 'fixture-opml-second', 'password': 'fixture-second-password-321'}
        self.assertEqual(self.request('POST', '/v1/users',
                                      {'username': second['user'], 'password': second['password'],
                                       'is_admin': False})[0], 201)
        self.assertEqual(self.request('POST', '/v1/import', raw=exported, **second)[0], 201)
        status, second_feeds = self.request('GET', '/v1/feeds', **second)
        self.assertEqual(status, 200)
        self.assertEqual({feed['feed_url']: (feed['title'], feed['category']['title'])
                          for feed in second_feeds}, observed)
        self.assertTrue({feed['id'] for feed in feeds}.isdisjoint(
                        {feed['id'] for feed in second_feeds}))

        invalid = (b'<opml><body><outline text="First" xmlUrl="https://example.invalid/first.xml"/>'
                   b'<outline text="Failures"><outline text="Bad" '
                   b'xmlUrl="ftp://example.invalid/bad"/></outline></body></opml>')
        self.assertEqual(self.request('POST', '/v1/import', raw=invalid, **credentials)[0], 500)
        status, feeds = self.request('GET', '/v1/feeds', **credentials)
        self.assertEqual(status, 200)
        self.assertIn('https://example.invalid/first.xml', [feed['feed_url'] for feed in feeds])
        self.assertNotIn('ftp://example.invalid/bad', [feed['feed_url'] for feed in feeds])
        status, categories = self.request('GET', '/v1/categories', **credentials)
        self.assertEqual(status, 200)
        self.assertIn('Failures', [category['title'] for category in categories])
        self.assertEqual(self.request('POST', '/v1/import', raw=b'not xml', **credentials)[0], 500)
        self.assertEqual(self.request('GET', '/v1/feeds', user=None)[0], 401)

    def test_feed_create_read_refresh_and_remove(self):
        status, category = self.request('POST', '/v1/categories', {'title': 'Fixture feeds'})
        self.assertEqual(status, 201)
        url = f'http://127.0.0.1:{self.feed.server_port}/feed.xml'
        status, created = self.request('POST', '/v1/feeds',
                                       {'feed_url': url, 'category_id': category['id']})
        self.assertEqual(status, 201)
        fid = created['feed_id']
        status, feed = self.request('GET', f'/v1/feeds/{fid}')
        self.assertEqual(status, 200)
        self.assertEqual(feed['title'], 'Fixture Feed')
        status, entries = self.request('GET', f'/v1/feeds/{fid}/entries')
        self.assertEqual(status, 200)
        self.assertEqual(entries['total'], 1)
        entry = entries['entries'][0]
        self.assertEqual((entry['title'], entry['status'], entry['starred']),
                         ('Fixture entry', 'unread', False))
        eid = entry['id']
        self.assertEqual(self.request('PUT', '/v1/entries',
                                      {'entry_ids': [eid], 'status': 'read', 'starred': True})[0], 204)
        status, changed = self.request('GET', f'/v1/entries/{eid}')
        self.assertEqual((status, changed['status'], changed['starred']), (200, 'read', True))
        self.assertEqual(self.request('PUT', '/v1/entries', {'entry_ids': [eid], 'status': 'bad'})[0], 400)
        self.assertEqual(self.request('PUT', f'/v1/feeds/{fid}/refresh')[0], 204)
        status, refreshed = self.request('GET', f'/v1/feeds/{fid}/entries')
        self.assertEqual(status, 200)
        self.assertEqual(refreshed['total'], 1)
        self.assertEqual(refreshed['entries'][0]['id'], entry['id'])
        self.assertEqual((refreshed['entries'][0]['status'], refreshed['entries'][0]['starred']), ('read', True))
        self.assertEqual(self.request('DELETE', f'/v1/feeds/{fid}')[0], 204)
        self.assertEqual(self.request('DELETE', f'/v1/categories/{category["id"]}')[0], 204)


if __name__ == '__main__':
    unittest.main()
