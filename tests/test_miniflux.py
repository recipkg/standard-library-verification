"""Exercise a Miniflux candidate against disposable PostgreSQL and HTTP fixtures."""
import base64
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
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

    def test_entry_import_filters_and_pagination(self):
        self.assertEqual(self.request('POST', '/v1/users',
                                      {'username': 'query-fixture', 'password': 'query-password-321',
                                       'is_admin': False})[0], 201)
        credentials = {'user': 'query-fixture', 'password': 'query-password-321'}
        category = self.request('GET', '/v1/categories', **credentials)[1][0]
        status, feed = self.request('POST', '/v1/feeds',
                                    {'feed_url': f'http://127.0.0.1:{self.feed.server_port}/query.xml',
                                     'category_id': category['id']}, **credentials)
        self.assertEqual(status, 201)
        feed_id = feed['feed_id']
        endpoint = f'/v1/feeds/{feed_id}/entries/import'
        status, first = self.request('POST', endpoint,
                                     {'url': 'https://example.invalid/one', 'title': 'Alpha',
                                      'external_id': 'first', 'published_at': 1700000000,
                                      'status': 'unread', 'starred': True,
                                      'content': '<p>Hello</p><script>alert(1)</script>'}, **credentials)
        self.assertEqual(status, 201)
        status, second = self.request('POST', endpoint,
                                      {'url': 'https://example.invalid/two', 'title': 'Beta',
                                       'external_id': 'second', 'published_at': 1700000001}, **credentials)
        self.assertEqual(status, 201)
        status, entry = self.request('GET', f'/v1/entries/{first["id"]}', **credentials)
        self.assertEqual((status, entry['status'], entry['starred']), (200, 'unread', True))
        self.assertNotIn('<script', entry['content'].lower())
        status, duplicate = self.request('POST', endpoint,
                                        {'url': 'https://example.invalid/one', 'title': 'New',
                                         'external_id': 'first', 'status': 'read'}, **credentials)
        self.assertEqual((status, duplicate['id']), (200, first['id']))
        entry = self.request('GET', f'/v1/entries/{first["id"]}', **credentials)[1]
        self.assertEqual((entry['title'], entry['status'], entry['starred']), ('Alpha', 'read', True))
        all_entries = self.request('GET', '/v1/entries', **credentials)[1]['entries']
        self.assertEqual(len(all_entries), 3)
        all_ids = {entry['id'] for entry in all_entries}
        for query, total, ids in [
            ('status=read', 2, {first['id'], second['id']}),
            ('starred=true', 1, {first['id']}),
            ('search=Alpha', 1, {first['id']}),
            ('order=id&direction=asc&limit=1&offset=1', 3, {first['id']}),
            ('starred=bogus', 3, all_ids),
        ]:
            status, result = self.request('GET', '/v1/entries?' + query, **credentials)
            self.assertEqual(status, 200)
            self.assertEqual((result['total'], {entry['id'] for entry in result['entries']}), (total, ids))
        for query in ('status=bogus', 'order=bogus', 'direction=bogus', 'feed_id=999999', 'limit=1001'):
            self.assertEqual(self.request('GET', '/v1/entries?' + query, **credentials)[0], 400)
        self.assertEqual(self.request('GET', '/v1/entries?limit=-1', **credentials)[1]['total'], 3)
        status, ids = self.request('GET', '/v1/entries/ids?starred=true', **credentials)
        self.assertEqual((status, ids['total'], ids['entry_ids']), (200, 1, [first['id']]))
        for query in ('starred=bogus', 'status=bogus'):
            self.assertEqual(self.request('GET', '/v1/entries/ids?' + query, **credentials)[0], 400)

    def test_api_roles_and_authentication_precedence(self):
        admin = self.request('GET', '/v1/me')[1]
        status, user = self.request('POST', '/v1/users',
                                    {'username': 'role-fixture', 'password': 'role-password-321',
                                     'is_admin': False})
        self.assertEqual(status, 201)
        credentials = {'user': 'role-fixture', 'password': 'role-password-321'}
        self.assertEqual(self.request('GET', '/v1/users', **credentials)[0], 403)
        self.assertEqual(self.request('GET', f'/v1/users/{user["id"]}', **credentials)[0], 403)
        self.assertEqual(self.request('POST', '/v1/users',
                                      {'username': 'should-not-exist', 'password': 'fixture-password'},
                                      **credentials)[0], 403)
        status, updated = self.request('PUT', f'/v1/users/{user["id"]}',
                                       {'language': 'en_US'}, **credentials)
        self.assertEqual((status, updated['id'], updated['is_admin']), (201, user['id'], False))
        self.assertEqual(self.request('PUT', f'/v1/users/{user["id"]}',
                                      {'is_admin': True}, **credentials)[0], 400)
        self.assertEqual(self.request('PUT', f'/v1/users/{admin["id"]}',
                                      {'language': 'en_US'}, **credentials)[0], 403)
        self.assertEqual(self.request('DELETE', f'/v1/users/{user["id"]}', **credentials)[0], 403)
        self.assertEqual(self.request('DELETE', f'/v1/users/{admin["id"]}')[0], 400)
        self.assertEqual(self.request('PUT', f'/v1/users/{admin["id"]}/mark-all-as-read',
                                      **credentials)[0], 403)
        self.assertEqual(self.request('PUT', f'/v1/users/{user["id"]}/mark-all-as-read')[0], 403)
        self.assertEqual(self.request('PUT', f'/v1/users/{user["id"]}/mark-all-as-read',
                                      **credentials)[0], 204)

        status, key = self.request('POST', '/v1/api-keys', {'description': 'role-fixture key'})
        self.assertEqual(status, 201)
        self.assertEqual(self.request('GET', '/v1/me', token='invalid-fixture-token')[0], 401)
        status, authenticated = self.request('GET', '/v1/me', user='role-fixture',
                                              password='wrong', token=key['token'])
        self.assertEqual((status, authenticated['id']), (200, admin['id']))
        self.assertEqual(self.request('DELETE', f'/v1/api-keys/{key["id"]}', **credentials)[0], 404)
        self.assertEqual(self.request('GET', '/v1/me', user=None, token=key['token'])[0], 200)
        self.assertEqual(self.request('DELETE', f'/v1/api-keys/{key["id"]}')[0], 204)
        self.assertEqual(self.request('GET', '/v1/me', user=None, token=key['token'])[0], 401)

    @unittest.skipUnless(os.environ.get('RECIPKG_PLAYWRIGHT_CLI'),
                         'set RECIPKG_PLAYWRIGHT_CLI to run the optional real-browser sample')
    def test_browser_login_read_star_and_mobile_navigation(self):
        cli = Path(os.environ['RECIPKG_PLAYWRIGHT_CLI']).expanduser().resolve(strict=True)
        prefix = (['bash', str(cli)] if cli.suffix == '.sh' else [str(cli)])
        session = 'recipkg-miniflux-' + uuid.uuid4().hex

        def run(*args):
            command = prefix + ['-s=' + session, *args]
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=60)
            if result.returncode:
                self.fail(f'browser command {args[0]} failed: {result.stdout[-2000:]} {result.stderr[-500:]}')
            return result.stdout

        def snapshot():
            return run('snapshot')

        def ref(state, role, name):
            match = re.search(r'\b' + re.escape(role) + r' "' + re.escape(name)
                              + r'"[^\n]*\[ref=([^\]]+)\]', state)
            self.assertIsNotNone(match, f'{role} {name!r} missing from snapshot:\n{state}')
            return match.group(1)

        self.addCleanup(lambda: run('close'))
        status, category = self.request('POST', '/v1/categories', {'title': 'Browser fixture'})
        self.assertEqual(status, 201)
        feed_url = f'http://127.0.0.1:{self.feed.server_port}/browser.xml'
        status, feed = self.request('POST', '/v1/feeds',
                                    {'feed_url': feed_url, 'category_id': category['id']})
        self.assertEqual(status, 201)
        feed_id = feed['feed_id']
        entries = self.request('GET', f'/v1/feeds/{feed_id}/entries')[1]['entries']
        self.assertEqual(len(entries), 1)
        entry_id = entries[0]['id']
        run('open', self.base + '/')
        state = snapshot()
        run('fill', ref(state, 'textbox', 'Username'), 'fixture-admin')
        run('fill', ref(state, 'textbox', 'Password'), 'wrong-fixture-password')
        run('click', ref(state, 'button', 'Login'))
        state = snapshot()
        self.assertIn('Invalid username or password.', state)
        run('fill', ref(state, 'textbox', 'Password'), 'fixture-password-321')
        run('click', ref(state, 'button', 'Login'))
        state = snapshot()
        self.assertIn('Fixture entry', state)
        self.assertIn('Browser fixture', state)
        run('click', ref(state, 'button', 'Star'))
        state = snapshot()
        self.assertIsNotNone(ref(state, 'button', 'Unstar'))
        run('click', ref(state, 'link', 'Fixture entry'))
        state = snapshot()
        self.assertIn('Entry body', state)
        self.assertIsNotNone(ref(state, 'button', 'Mark as unread'))
        entry = self.request('GET', f'/v1/entries/{entry_id}')[1]
        self.assertEqual((entry['status'], entry['starred']), ('read', True))
        run('click', ref(state, 'link', 'Unread'))
        state = snapshot()
        self.assertIn('There are no unread entries.', state)
        run('click', ref(state, 'link', 'Starred'))
        state = snapshot()
        self.assertIn('Fixture entry', state)
        run('click', ref(state, 'link', 'Feeds'))
        state = snapshot()
        run('click', ref(state, 'link', 'Add feed'))
        state = snapshot()
        run('fill', ref(state, 'textbox', 'URL'),
            f'http://127.0.0.1:{self.feed.server_port}/browser-second.xml')
        run('select', ref(state, 'combobox', 'Category'), str(category['id']))
        run('click', ref(state, 'button', 'Find a feed'))
        state = snapshot()
        self.assertIn('Fixture Feed', state)
        self.assertIn('Fixture entry', state)
        feeds = self.request('GET', '/v1/feeds')[1]
        added = [item for item in feeds if item['feed_url'].endswith('/browser-second.xml')]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]['category']['id'], category['id'])
        run('resize', '375', '812')
        state = snapshot()
        run('click', ref(state, 'button', 'Menu'))
        state = snapshot()
        self.assertRegex(state, r'button "Menu" \[expanded\]')
        self.assertIsNotNone(ref(state, 'link', 'Feeds'))

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
