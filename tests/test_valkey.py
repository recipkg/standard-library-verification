"""Finite RESP2 contract samples against an explicitly selected Valkey server."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


class RespError:
    def __init__(self, value):
        self.value = value


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        self.socket.connect(str(path))
        self.reader = self.socket.makefile('rb')

    def close(self):
        self.reader.close()
        self.socket.close()

    def read(self):
        line = self.reader.readline()
        if not line.endswith(b'\r\n'):
            raise RuntimeError('incomplete RESP reply')
        kind, value = line[:1], line[1:-2]
        if kind == b'+':
            return value
        if kind == b'-':
            return RespError(value)
        if kind == b':':
            return int(value)
        if kind == b'$':
            size = int(value)
            if size == -1:
                return None
            payload = self.reader.read(size + 2)
            if len(payload) != size + 2 or payload[-2:] != b'\r\n':
                raise RuntimeError('incomplete RESP bulk reply')
            return payload[:-2]
        if kind == b'*':
            size = int(value)
            return None if size == -1 else [self.read() for _ in range(size)]
        raise RuntimeError(f'unsupported RESP reply: {kind!r}')

    def command(self, *args):
        args = [value if isinstance(value, bytes) else str(value).encode() for value in args]
        packet = b'*%d\r\n' % len(args) + b''.join(b'$%d\r\n' % len(arg) + arg + b'\r\n' for arg in args)
        self.socket.sendall(packet)
        return self.read()


class ValkeySamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        requested = os.environ.get('RECIPKG_TEST_VALKEY_SERVER')
        if not requested:
            raise unittest.SkipTest('set RECIPKG_TEST_VALKEY_SERVER to the server under test')
        cls.server = shutil.which(requested)
        if cls.server is None:
            raise RuntimeError(f'Valkey server not found: {requested!r}')
        result = subprocess.run([cls.server, '--version'], text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise RuntimeError(f'server version command failed: {result.stderr}')
        print('Valkey target:', result.stdout.strip())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recipkg-valkey-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'server.sock'
        self.process = None
        self.clients = []
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        self.process = subprocess.Popen([
            self.server, '--port', '0', '--unixsocket', str(self.path), '--unixsocketperm', '700',
            '--daemonize', 'no', '--protected-mode', 'yes', '--save', '', '--appendonly', 'no',
            '--dir', str(self.directory), '--dbfilename', 'snapshot.rdb', '--loglevel', 'warning',
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail(f'server exited during startup: {self.process.returncode}')
            if self.path.exists():
                try:
                    client = self.client()
                    self.assertEqual(client.command('PING'), b'PONG')
                    return
                except (ConnectionRefusedError, FileNotFoundError):
                    pass
            time.sleep(0.02)
        self.fail('server Unix socket did not become ready')

    def client(self):
        client = Client(self.path)
        self.clients.append(client)
        return client

    def stop(self):
        for client in self.clients:
            client.close()
        self.clients = []
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def test_binary_values_types_and_immediate_expiration(self):
        c = self.client()
        key, value = b'k\x00\xff', b'v\x00\r\n\xff'
        self.assertEqual(c.command('SET', key, value), b'OK')
        self.assertEqual(c.command('GET', key), value)
        error = c.command('HGET', key, 'field')
        self.assertIsInstance(error, RespError)
        self.assertTrue(error.value.startswith(b'WRONGTYPE'))
        self.assertEqual(c.command('PEXPIRE', key, 0), 1)
        self.assertIsNone(c.command('GET', key))
        self.assertEqual(c.command('PTTL', key), -2)
        self.assertEqual(c.command('HSET', 'hash', 'a', '1', 'b', '2'), 2)
        self.assertEqual(c.command('HGET', 'hash', 'a'), b'1')

    def test_transaction_and_watch_conflict(self):
        a, b = self.client(), self.client()
        self.assertEqual(a.command('SET', 'counter', '1'), b'OK')
        self.assertEqual(a.command('WATCH', 'counter'), b'OK')
        self.assertEqual(b.command('SET', 'counter', '4'), b'OK')
        self.assertEqual(a.command('MULTI'), b'OK')
        self.assertEqual(a.command('INCR', 'counter'), b'QUEUED')
        self.assertIsNone(a.command('EXEC'))
        self.assertEqual(a.command('GET', 'counter'), b'4')
        self.assertEqual(a.command('MULTI'), b'OK')
        self.assertEqual(a.command('INCR', 'counter'), b'QUEUED')
        self.assertEqual(a.command('GET', 'counter'), b'QUEUED')
        self.assertEqual(a.command('EXEC'), [5, b'5'])

    def test_acl_command_permission(self):
        admin, restricted = self.client(), self.client()
        self.assertEqual(admin.command('SET', 'secret', 'visible'), b'OK')
        self.assertEqual(admin.command('ACL', 'SETUSER', 'reader', 'on', '>dummy-pass', '~*', '+get', '+ping'), b'OK')
        self.assertEqual(restricted.command('AUTH', 'reader', 'dummy-pass'), b'OK')
        self.assertEqual(restricted.command('GET', 'secret'), b'visible')
        denied = restricted.command('SET', 'secret', 'changed')
        self.assertIsInstance(denied, RespError)
        self.assertTrue(denied.value.startswith(b'NOPERM'))
        self.assertEqual(admin.command('GET', 'secret'), b'visible')

    def test_save_and_restart(self):
        c = self.client()
        self.assertEqual(c.command('SET', 'persistent', b'\x00\xff'), b'OK')
        self.assertEqual(c.command('HSET', 'settings', 'mode', 'manual'), 1)
        self.assertEqual(c.command('SAVE'), b'OK')
        self.stop()
        self.start()
        c = self.client()
        self.assertEqual(c.command('GET', 'persistent'), b'\x00\xff')
        self.assertEqual(c.command('HGET', 'settings', 'mode'), b'manual')


if __name__ == '__main__':
    unittest.main()
