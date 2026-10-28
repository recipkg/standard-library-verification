"""Finite RESP2 contract samples against an explicitly selected Valkey server."""
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


NULL_BULK = object()
NULL_ARRAY = object()


class RespError:
    def __init__(self, value):
        self.value = value


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        try:
            self.socket.connect(str(path))
        except OSError:
            self.socket.close()
            raise
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
                return NULL_BULK
            payload = self.reader.read(size + 2)
            if len(payload) != size + 2 or payload[-2:] != b'\r\n':
                raise RuntimeError('incomplete RESP bulk reply')
            return payload[:-2]
        if kind == b'*':
            size = int(value)
            return NULL_ARRAY if size == -1 else [self.read() for _ in range(size)]
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

    def start(self, *, appendonly=False, tcp_port=0):
        self.process = subprocess.Popen([
            self.server, '--port', str(tcp_port), '--bind', '127.0.0.1',
            '--unixsocket', str(self.path), '--unixsocketperm', '700',
            '--daemonize', 'no', '--protected-mode', 'yes', '--save', '',
            '--appendonly', 'yes' if appendonly else 'no', '--appendfsync', 'always',
            '--repl-diskless-sync-delay', '0',
            '--dir', str(self.directory), '--dbfilename', 'snapshot.rdb', '--loglevel', 'warning',
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail(f'server exited during startup: {self.process.returncode}')
            if self.path.exists():
                try:
                    client = self.client()
                    reply = client.command('PING')
                    if reply == b'PONG':
                        return
                    if isinstance(reply, RespError) and reply.value.startswith(b'LOADING'):
                        client.close()
                        self.clients.remove(client)
                    else:
                        self.fail(f'unexpected server readiness reply: {getattr(reply, "value", reply)!r}')
                except (ConnectionRefusedError, FileNotFoundError):
                    pass
            time.sleep(0.02)
        self.fail('server Unix socket did not become ready')

    def client(self):
        client = Client(self.path)
        self.clients.append(client)
        return client

    def stop(self, *, require_clean=False):
        for client in self.clients:
            client.close()
        self.clients = []
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if require_clean:
                self.assertEqual(self.process.returncode, 0, 'server did not stop normally')
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
        self.assertIs(c.command('GET', key), NULL_BULK)
        self.assertEqual(c.command('PTTL', key), -2)
        self.assertEqual(c.command('HSET', 'hash', 'a', '1', 'b', '2'), 2)
        self.assertEqual(c.command('HGET', 'hash', 'a'), b'1')

    def test_set_conditions_and_ttl(self):
        c = self.client()
        self.assertIs(c.command('GET', 'cache'), NULL_BULK)
        self.assertEqual(c.command('PTTL', 'cache'), -2)
        self.assertEqual(c.command('SET', 'cache', 'first', 'PX', '60000', 'NX'), b'OK')
        before = c.command('PTTL', 'cache')
        self.assertTrue(0 < before <= 60000, before)
        self.assertIs(c.command('SET', 'cache', 'ignored', 'NX'), NULL_BULK)
        self.assertEqual(c.command('GET', 'cache'), b'first')
        self.assertEqual(c.command('SET', 'cache', 'second', 'XX', 'KEEPTTL'), b'OK')
        after = c.command('PTTL', 'cache')
        self.assertTrue(0 < after <= before, (before, after))
        self.assertEqual(c.command('GET', 'cache'), b'second')
        self.assertEqual(c.command('SET', 'cache', 'permanent'), b'OK')
        self.assertEqual(c.command('PTTL', 'cache'), -1)
        self.assertIs(c.command('SET', 'missing', 'ignored', 'XX'), NULL_BULK)
        self.assertEqual(c.command('PTTL', 'missing'), -2)

    def test_transaction_and_watch_conflict(self):
        a, b = self.client(), self.client()
        self.assertEqual(a.command('SET', 'counter', '1'), b'OK')
        self.assertEqual(a.command('WATCH', 'counter'), b'OK')
        self.assertEqual(b.command('SET', 'counter', '4'), b'OK')
        self.assertEqual(a.command('MULTI'), b'OK')
        self.assertEqual(a.command('INCR', 'counter'), b'QUEUED')
        self.assertIs(a.command('EXEC'), NULL_ARRAY)
        self.assertEqual(a.command('GET', 'counter'), b'4')
        self.assertEqual(a.command('MULTI'), b'OK')
        self.assertEqual(a.command('INCR', 'counter'), b'QUEUED')
        self.assertEqual(a.command('GET', 'counter'), b'QUEUED')
        self.assertEqual(a.command('EXEC'), [5, b'5'])

    def test_transaction_queue_and_execution_errors(self):
        c = self.client()
        self.assertEqual(c.command('MULTI'), b'OK')
        self.assertEqual(c.command('SET', 'discarded', 'x'), b'QUEUED')
        queue_error = c.command('NOT_A_REAL_COMMAND')
        self.assertIsInstance(queue_error, RespError)
        self.assertTrue(queue_error.value.startswith(b'ERR'))
        aborted = c.command('EXEC')
        self.assertIsInstance(aborted, RespError)
        self.assertTrue(aborted.value.startswith(b'EXECABORT'))
        self.assertIs(c.command('GET', 'discarded'), NULL_BULK)

        self.assertEqual(c.command('SET', 'typed', 'string'), b'OK')
        self.assertEqual(c.command('MULTI'), b'OK')
        self.assertEqual(c.command('HSET', 'typed', 'field', 'value'), b'QUEUED')
        self.assertEqual(c.command('SET', 'later', 'ran'), b'QUEUED')
        results = c.command('EXEC')
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], RespError)
        self.assertTrue(results[0].value.startswith(b'WRONGTYPE'))
        self.assertEqual(results[1], b'OK')
        self.assertEqual(c.command('GET', 'typed'), b'string')
        self.assertEqual(c.command('GET', 'later'), b'ran')

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
        self.stop(require_clean=True)
        self.start()
        c = self.client()
        self.assertEqual(c.command('GET', 'persistent'), b'\x00\xff')
        self.assertEqual(c.command('HGET', 'settings', 'mode'), b'manual')

    def test_acl_key_patterns(self):
        admin, restricted = self.client(), self.client()
        self.assertEqual(admin.command('SET', 'public:item', 'visible'), b'OK')
        self.assertEqual(admin.command('SET', 'private:item', 'protected'), b'OK')
        self.assertEqual(admin.command('ACL', 'SETUSER', 'scoped', 'on', '>dummy-pass',
                                       '~public:*', '+get', '+set', '+ping'), b'OK')
        self.assertEqual(restricted.command('AUTH', 'scoped', 'dummy-pass'), b'OK')
        self.assertEqual(restricted.command('GET', 'public:item'), b'visible')
        self.assertEqual(restricted.command('SET', 'public:item', 'updated'), b'OK')
        for command in [('GET', 'private:item'), ('SET', 'private:item', 'changed')]:
            denied = restricted.command(*command)
            self.assertIsInstance(denied, RespError)
            self.assertTrue(denied.value.startswith(b'NOPERM'))
        self.assertEqual(admin.command('GET', 'private:item'), b'protected')
        self.assertEqual(admin.command('GET', 'public:item'), b'updated')

    def test_aof_normal_restart(self):
        self.stop(require_clean=True)
        self.start(appendonly=True)
        c = self.client()
        self.assertEqual(c.command('CONFIG', 'GET', 'appendonly'), [b'appendonly', b'yes'])
        self.assertEqual(c.command('SET', 'stored', b'\x00\xff'), b'OK')
        self.assertEqual(c.command('HSET', 'hash', 'name', 'value'), 1)
        self.assertEqual(c.command('SET', 'removed', 'temporary'), b'OK')
        self.assertEqual(c.command('DEL', 'removed'), 1)
        self.stop(require_clean=True)
        self.assertFalse((self.directory / 'snapshot.rdb').exists())
        self.start(appendonly=True)
        c = self.client()
        self.assertEqual(c.command('GET', 'stored'), b'\x00\xff')
        self.assertEqual(c.command('HGET', 'hash', 'name'), b'value')
        self.assertIs(c.command('GET', 'removed'), NULL_BULK)

    def test_aof_acknowledged_writes_after_process_kill(self):
        self.stop(require_clean=True)
        self.start(appendonly=True)
        c = self.client()
        self.assertEqual(c.command('CONFIG', 'GET', 'appendfsync'), [b'appendfsync', b'always'])
        self.assertEqual(c.command('SET', 'stored', b'\x00\xff'), b'OK')
        self.assertEqual(c.command('HSET', 'hash', 'name', 'value'), 1)
        self.assertEqual(c.command('SET', 'removed', 'temporary'), b'OK')
        self.assertEqual(c.command('DEL', 'removed'), 1)
        process = self.process
        process.kill()
        self.assertEqual(process.wait(timeout=5), -signal.SIGKILL)
        self.stop()
        self.assertFalse((self.directory / 'snapshot.rdb').exists())
        self.start(appendonly=True)
        c = self.client()
        self.assertEqual(c.command('GET', 'stored'), b'\x00\xff')
        self.assertEqual(c.command('HGET', 'hash', 'name'), b'value')
        self.assertIs(c.command('GET', 'removed'), NULL_BULK)

    def test_replication_initial_sync_and_live_changes(self):
        self.stop(require_clean=True)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            primary_port = reservation.getsockname()[1]
        self.start(tcp_port=primary_port)
        primary = self.client()
        self.assertEqual(primary.command('SET', 'before-sync', b'\x00\xff'), b'OK')
        self.assertEqual(primary.command('HSET', 'hash', 'field', 'before'), 1)

        replica_directory = self.directory / 'replica'
        replica_directory.mkdir()
        replica_path = replica_directory / 'server.sock'
        replica_args = [
            self.server, '--port', '0', '--unixsocket', str(replica_path), '--unixsocketperm', '700',
            '--daemonize', 'no', '--protected-mode', 'yes', '--save', '', '--appendonly', 'no',
            '--dir', str(replica_directory), '--replicaof', '127.0.0.1', str(primary_port),
            '--loglevel', 'warning',
        ]

        def launch_replica():
            return subprocess.Popen(replica_args, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        replica_process = launch_replica()

        def stop_replica():
            if replica_process.poll() is None:
                replica_process.terminate()
                try:
                    replica_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    replica_process.kill()
                    replica_process.wait(timeout=5)
        self.addCleanup(stop_replica)
        def connect_replica():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if replica_process.poll() is not None:
                    self.fail(f'replica exited during startup: {replica_process.returncode}')
                try:
                    connection = Client(replica_path)
                    self.clients.append(connection)
                    return connection
                except (ConnectionRefusedError, FileNotFoundError):
                    time.sleep(0.02)
            self.fail('replica Unix socket did not become ready')

        replica = connect_replica()

        def wait_for(command, expected):
            deadline = time.monotonic() + 15
            last = None
            while time.monotonic() < deadline:
                if replica_process.poll() is not None:
                    self.fail(f'replica exited during sync: {replica_process.returncode}')
                last = replica.command(*command)
                if last == expected:
                    return
                if isinstance(last, RespError) and not last.value.startswith(b'LOADING'):
                    self.fail(f'unexpected replica response: {last.value!r}')
                time.sleep(0.02)
            self.fail(f'replica did not reach expected state for {command!r}; got {last!r}')

        wait_for(('GET', 'before-sync'), b'\x00\xff')
        wait_for(('HGET', 'hash', 'field'), b'before')
        readonly = replica.command('SET', 'forbidden', 'value')
        self.assertIsInstance(readonly, RespError)
        self.assertTrue(readonly.value.startswith(b'READONLY'))
        self.assertEqual(primary.command('SET', 'live', 'updated'), b'OK')
        self.assertEqual(primary.command('DEL', 'before-sync'), 1)
        wait_for(('GET', 'live'), b'updated')
        wait_for(('GET', 'before-sync'), NULL_BULK)
        self.assertIs(primary.command('GET', 'forbidden'), NULL_BULK)
        self.assertEqual(primary.command('SET', 'delete-while-offline', 'old'), b'OK')
        wait_for(('GET', 'delete-while-offline'), b'old')

        replica.close()
        self.clients.remove(replica)
        stop_replica()
        self.assertEqual(replica_process.returncode, 0, 'replica did not stop normally')
        self.assertEqual(primary.command('SET', 'live', 'offline-update'), b'OK')
        self.assertEqual(primary.command('HSET', 'hash', 'field', 'offline-update'), 0)
        self.assertEqual(primary.command('SET', 'offline-new', 'present'), b'OK')
        self.assertEqual(primary.command('DEL', 'delete-while-offline'), 1)
        replica_process = launch_replica()
        replica = connect_replica()
        wait_for(('GET', 'live'), b'offline-update')
        wait_for(('HGET', 'hash', 'field'), b'offline-update')
        wait_for(('GET', 'offline-new'), b'present')
        wait_for(('GET', 'delete-while-offline'), NULL_BULK)

        self.assertEqual(replica.command('REPLICAOF', 'NO', 'ONE'), b'OK')
        self.assertEqual(replica.command('SET', 'live', 'promoted'), b'OK')
        self.assertEqual(replica.command('GET', 'live'), b'promoted')
        self.assertEqual(primary.command('GET', 'live'), b'offline-update')


if __name__ == '__main__':
    unittest.main()
