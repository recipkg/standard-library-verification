"""Selected Vikunja v1 API observations against an explicitly supplied binary."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class VikunjaSamples(unittest.TestCase):
    def setUp(self):
        self.binary = os.environ.get('RECIPKG_TEST_VIKUNJA')
        if not self.binary:
            self.skipTest('set RECIPKG_TEST_VIKUNJA to a disposable test binary')
        self.binary = str(Path(self.binary).resolve(strict=True))
        self.tmp = tempfile.TemporaryDirectory(prefix='recipkg-vikunja-test-')
        self.root = Path(self.tmp.name)
        self.process = None
        self.log = None
        self.addCleanup(self.cleanup_server)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('VIKUNJA_')}
        self.env.update(HOME=str(self.root), TZ='UTC',
                        VIKUNJA_SERVICE_ROOTPATH=str(self.root),
                        VIKUNJA_SERVICE_INTERFACE=f'127.0.0.1:{self.port}',
                        VIKUNJA_SERVICE_PUBLICURL=f'http://127.0.0.1:{self.port}/',
                        VIKUNJA_SERVICE_SECRET='temporary-test-secret-key',
                        VIKUNJA_DATABASE_TYPE='sqlite', VIKUNJA_DATABASE_PATH=str(self.root / 'vikunja.db'),
                        VIKUNJA_FILES_BASEPATH=str(self.root / 'files'),
                        VIKUNJA_SERVICE_ENABLEREGISTRATION='true',
                        VIKUNJA_SERVICE_ENABLEEMAILREMINDERS='false',
                        VIKUNJA_SENTRY_ENABLED='false', VIKUNJA_MAILER_ENABLED='false',
                        VIKUNJA_REDIS_ENABLED='false')
        self.start()

    def start(self):
        self.log = (self.root / 'server.log').open('ab')
        self.process = subprocess.Popen([self.binary, 'web'], cwd=self.root, env=self.env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(120):
            if self.process.poll() is not None:
                self.fail(f'Vikunja exited during startup; inspect {self.root / "server.log"}')
            try:
                status, _ = self.request('GET', '/info')
                if status == 200:
                    return
            except OSError:
                time.sleep(0.25)
        self.fail('Vikunja startup timed out')

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def cleanup_server(self):
        self.stop()
        self.tmp.cleanup()

    def request(self, method, path, data=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        url = self.base + (path if path.startswith('/api/') else '/api/v1' + path)
        request = urllib.request.Request(url, method=method, headers=headers,
                                         data=json.dumps(data).encode() if data is not None else None)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, json.loads(body) if body else None

    def expect(self, status, method, path, data=None, token=None):
        got, body = self.request(method, path, data, token)
        self.assertEqual(got, status, (method, path, body))
        return body

    def test_accounts_tasks_permissions_and_restart(self):
        password = 'Temporary-passphrase-123!'
        tokens = {}
        for name in ('alice', 'bob'):
            self.expect(200, 'POST', '/register', {'username': name, 'password': password,
                                                   'email': f'{name}@example.test'})
            tokens[name] = self.expect(200, 'POST', '/login', {'username': name, 'password': password})['token']
        alice, bob = tokens['alice'], tokens['bob']
        self.expect(401, 'GET', '/projects')
        project = self.expect(201, 'PUT', '/projects', {'title': 'Work'}, alice)
        pid = project['id']
        self.assertEqual({view['view_kind'] for view in project['views']}, {'list', 'gantt', 'table', 'kanban'})
        task = self.expect(201, 'PUT', f'/projects/{pid}/tasks',
                           {'title': 'First task', 'due_date': '2026-12-01T12:00:00Z'}, alice)
        tid = task['id']
        self.assertEqual(task['due_date'], '2026-12-01T12:00:00Z')
        self.expect(403, 'GET', f'/projects/{pid}', token=bob)
        self.expect(403, 'GET', f'/tasks/{tid}', token=bob)
        self.expect(201, 'PUT', f'/projects/{pid}/users', {'username': 'bob', 'permission': 0}, alice)
        self.expect(200, 'GET', f'/tasks/{tid}', token=bob)
        self.expect(403, 'POST', f'/tasks/{tid}', {'title': 'forbidden'}, bob)
        self.expect(200, 'POST', f'/projects/{pid}/users/bob', {'permission': 1}, alice)
        self.expect(200, 'PATCH', f'/api/v2/tasks/{tid}', {'title': 'Edited by Bob'}, bob)
        edited = self.expect(200, 'GET', f'/tasks/{tid}', token=alice)
        self.assertEqual((edited['title'], edited['due_date']), ('Edited by Bob', '2026-12-01T12:00:00Z'))
        self.expect(200, 'POST', f'/projects/{pid}/users/bob', {'permission': 0}, alice)
        self.expect(403, 'PATCH', f'/api/v2/tasks/{tid}', {'title': 'forbidden'}, bob)
        updated = self.expect(200, 'POST', f'/tasks/{tid}', {'done': True}, alice)
        self.assertTrue(updated['done'])
        stored = self.expect(200, 'GET', f'/tasks/{tid}', token=alice)
        self.assertTrue(stored['done'])
        self.assertEqual(stored['due_date'], '0001-01-01T00:00:00Z')
        patch_task = self.expect(201, 'PUT', f'/projects/{pid}/tasks',
                                 {'title': 'Patch task', 'due_date': '2026-12-01T12:00:00Z'}, alice)
        patch_id = patch_task['id']
        self.expect(200, 'PATCH', f'/api/v2/tasks/{patch_id}', {'done': True}, alice)
        patched = self.expect(200, 'GET', f'/tasks/{patch_id}', token=alice)
        self.assertTrue(patched['done'])
        self.assertEqual(patched['due_date'], '2026-12-01T12:00:00Z')
        self.stop()
        self.start()
        alice = self.expect(200, 'POST', '/login', {'username': 'alice', 'password': password})['token']
        bob = self.expect(200, 'POST', '/login', {'username': 'bob', 'password': password})['token']
        self.assertTrue(self.expect(200, 'GET', f'/tasks/{tid}', token=alice)['done'])
        self.expect(200, 'GET', f'/tasks/{tid}', token=bob)
        self.expect(200, 'DELETE', f'/projects/{pid}/users/bob', token=alice)
        self.expect(403, 'GET', f'/tasks/{tid}', token=bob)


if __name__ == '__main__':
    unittest.main()
