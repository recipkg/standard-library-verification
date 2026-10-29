"""Black-box Gitea issue, permissions, Git HTTP and normal-restart sample."""
import base64
import json
import os
import shutil
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class GiteaSamples(unittest.TestCase):
    password = 'fixture-password-12345'

    def setUp(self):
        binary = os.environ.get('RECIPKG_TEST_GITEA')
        if not binary:
            self.skipTest('set RECIPKG_TEST_GITEA to the candidate Gitea executable')
        self.binary = str(Path(binary).resolve(strict=True))
        self.root = Path(tempfile.mkdtemp(prefix='recipkg-gitea-test-'))
        self.process = None
        self.log = None
        self.addCleanup(self.cleanup_server)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.work = self.root / 'work'
        self.work.mkdir()
        static = Path(os.environ.get('RECIPKG_TEST_GITEA_STATIC_ROOT', self.work)).resolve()
        self.config = self.root / 'app.ini'
        self.config.write_text(f'''APP_NAME = Fixture
RUN_MODE = prod
WORK_PATH = {self.work}
[server]
HTTP_ADDR = 127.0.0.1
HTTP_PORT = {self.port}
ROOT_URL = {self.base}/
STATIC_ROOT_PATH = {static}
DISABLE_SSH = true
LFS_START_SERVER = false
[database]
DB_TYPE = sqlite3
PATH = {self.root / 'gitea.db'}
[repository]
ROOT = {self.root / 'repositories'}
[security]
INSTALL_LOCK = true
SECRET_KEY = fixture-secret-key-not-for-production
INTERNAL_TOKEN = fixture-internal-token-not-for-production
[service]
DISABLE_REGISTRATION = true
[mailer]
ENABLED = false
[picture]
DISABLE_GRAVATAR = true
[log]
MODE = console
''')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('GITEA_', 'GIT_', 'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'all_proxy'))}
        self.env.update(HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
                        NO_PROXY='127.0.0.1,localhost')
        self.start()

    def command(self, *args):
        return subprocess.run([self.binary, '--config', str(self.config), '--work-path', str(self.work), *args],
                              cwd=self.work, env=self.env, text=True, capture_output=True, timeout=90, check=True)

    def start(self):
        self.log = (self.root / 'server.log').open('ab')
        self.process = subprocess.Popen([self.binary, '--config', str(self.config), '--work-path', str(self.work), 'web'],
                                        cwd=self.work, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(240):
            if self.process.poll() is not None:
                self.fail('Gitea exited during startup: ' + (self.root / 'server.log').read_text(errors='replace')[-4000:])
            try:
                status, _ = self.request('GET', '/version')
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.25)
        self.fail('Gitea startup timed out: ' + (self.root / 'server.log').read_text(errors='replace')[-4000:])

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def cleanup_server(self):
        self.stop()
        shutil.rmtree(self.root)

    def request(self, method, path, data=None, user=None):
        headers = {'Content-Type': 'application/json'}
        if user:
            encoded = base64.b64encode(f'{user}:{self.password}'.encode()).decode()
            headers['Authorization'] = 'Basic ' + encoded
        request = urllib.request.Request(self.base + '/api/v1' + path, method=method, headers=headers,
                                         data=json.dumps(data).encode() if data is not None else None)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode(errors='replace')[:500]
            return response.status, body

    def expect(self, status, method, path, data=None, user=None):
        got, body = self.request(method, path, data, user)
        self.assertEqual(got, status, (method, path, body))
        return body

    def git(self, *args, user=None, cwd=None, check=True):
        command = ['git']
        if user:
            encoded = base64.b64encode(f'{user}:{self.password}'.encode()).decode()
            command += ['-c', 'http.extraHeader=Authorization: Basic ' + encoded]
        return subprocess.run([*command, *args], cwd=cwd or self.root, env=self.env, text=True,
                              capture_output=True, timeout=60, check=check)

    def test_private_repository_issue_versions_git_and_restart(self):
        for user in ('alice', 'bob'):
            self.command('admin', 'user', 'create', '--username', user, '--password', self.password,
                         '--email', f'{user}@example.test', '--must-change-password=false')
        self.expect(201, 'POST', '/user/repos', {'name': 'demo', 'private': True}, 'alice')
        repo = '/repos/alice/demo'
        self.expect(404, 'GET', repo)
        self.expect(404, 'GET', repo, user='bob')
        self.expect(404, 'POST', repo + '/issues', {'title': 'not allowed'}, 'bob')
        self.expect(200, 'GET', repo, user='alice')
        self.expect(422, 'POST', repo + '/issues', {'body': 'missing title'}, 'alice')
        label = self.expect(201, 'POST', repo + '/labels', {'name': 'bug', 'color': '#ff0000'}, 'alice')
        path = self.root / 'client'
        self.git('init', '-b', 'main', str(path))
        self.git('config', 'user.name', 'Fixture', cwd=path)
        self.git('config', 'user.email', 'fixture@example.test', cwd=path)
        (path / 'file.txt').write_text('fixture contents\n')
        self.git('add', 'file.txt', cwd=path)
        self.git('commit', '-m', 'fixture', cwd=path)
        head = self.git('rev-parse', 'HEAD', cwd=path).stdout.strip()
        remote = self.base + '/alice/demo.git'
        self.git('push', remote, 'main', user='alice', cwd=path)
        self.assertNotEqual(self.git('clone', remote, str(self.root / 'denied'), user='bob', check=False).returncode, 0)
        self.expect(204, 'PUT', repo + '/collaborators/bob', {'permission': 'read'}, 'alice')
        self.expect(200, 'GET', repo, user='bob')
        reader_issue = self.expect(201, 'POST', repo + '/issues',
                                   {'title': 'Reader issue', 'body': 'reader', 'labels': [label['id']]}, 'bob')
        reader_url = repo + '/issues/' + str(reader_issue['number'])
        self.assertEqual(reader_issue['labels'], [])
        self.assertEqual(self.expect(200, 'GET', reader_url, user='alice')['labels'], [])
        self.expect(403, 'POST', reader_url + '/labels', {'labels': [label['id']]}, 'bob')
        self.assertEqual(self.expect(201, 'PATCH', reader_url, {'body': 'reader edit'}, 'bob')['body'], 'reader edit')
        self.git('clone', '-b', 'main', remote, str(self.root / 'clone'), user='bob')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.root / 'clone').stdout.strip(), head)
        self.assertEqual((self.root / 'clone' / 'file.txt').read_text(), 'fixture contents\n')
        issue = self.expect(201, 'POST', repo + '/issues', {'title': 'Fixture', 'body': 'first'}, 'alice')
        url = repo + '/issues/' + str(issue['number'])
        version = issue['content_version']
        self.expect(403, 'PATCH', url, {'body': 'not allowed'}, 'bob')
        edited = self.expect(201, 'PATCH', url, {'body': 'second', 'content_version': version}, 'alice')
        self.assertEqual(edited['body'], 'second')
        self.assertGreater(edited['content_version'], version)
        self.expect(409, 'PATCH', url, {'body': 'stale', 'content_version': version}, 'alice')
        self.assertEqual(self.expect(200, 'GET', url, user='alice')['body'], 'second')
        no_version = self.expect(201, 'PATCH', url, {'body': 'third'}, 'alice')
        self.assertEqual(no_version['body'], 'third')
        self.stop()
        self.start()
        self.assertEqual(self.expect(200, 'GET', url, user='bob')['body'], 'third')
        self.assertEqual(self.expect(200, 'GET', reader_url, user='bob')['body'], 'reader edit')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.root / 'clone').stdout.strip(), head)
        self.git('clone', '-b', 'main', remote, str(self.root / 'after-restart'), user='bob')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.root / 'after-restart').stdout.strip(), head)


if __name__ == '__main__':
    unittest.main()
