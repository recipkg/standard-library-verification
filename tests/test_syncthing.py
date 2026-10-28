"""Exercise two disposable Syncthing processes; no existing config is used."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class SyncthingSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('RECIPKG_TEST_SYNCTHING')
        if not path:
            raise unittest.SkipTest('set RECIPKG_TEST_SYNCTHING to a disposable test binary')
        cls.binary = shutil.which(path)
        if not cls.binary:
            raise RuntimeError('RECIPKG_TEST_SYNCTHING executable not found')
        result = subprocess.run([cls.binary, '--version'], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError('could not read Syncthing version')
        print('syncthing target:', result.stdout.strip())

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='recipkg-syncthing-'))
        self.processes = [None, None]
        self.logs = []
        self.addCleanup(self.cleanup_lab)
        self.config_dirs = [self.root / 'a', self.root / 'b']
        self.shares = [self.root / 'folder-a', self.root / 'folder-b']
        ports = []
        while len(ports) < 4:
            candidate = free_port()
            if candidate not in ports:
                ports.append(candidate)
        self.ports, self.guis = ports[:2], ports[2:]
        self.env = {k: os.environ[k] for k in ('PATH', 'HOME') if k in os.environ}
        self.env['LANG'] = 'C.UTF-8'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.ids, self.keys, trees = [], [], []
        for n in range(2):
            self.config_dirs[n].mkdir()
            self.shares[n].mkdir()
            result = subprocess.run([self.binary, '-H', str(self.config_dirs[n]),
                                     'generate', '--no-port-probing'],
                                    capture_output=True, text=True, env=self.env, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            tree = ET.parse(self.config_dirs[n] / 'config.xml')
            config = tree.getroot()
            self.ids.append(config.find('device').get('id'))
            self.keys.append(config.find('gui/apikey').text)
            trees.append(tree)
        for n, tree in enumerate(trees):
            config = tree.getroot()
            config.find('gui/address').text = f'127.0.0.1:{self.guis[n]}'
            options = config.find('options')
            settings = {'globalAnnounceEnabled': 'false', 'localAnnounceEnabled': 'false',
                        'relaysEnabled': 'false', 'natEnabled': 'false', 'startBrowser': 'false',
                        'autoUpgradeIntervalH': '0', 'crashReportingEnabled': 'false',
                        'urAccepted': '-1', 'reconnectionIntervalS': '2'}
            for name, value in settings.items():
                options.find(name).text = value
            for item in options.findall('listenAddress'):
                options.remove(item)
            ET.SubElement(options, 'listenAddress').text = f'tcp://127.0.0.1:{self.ports[n]}'
            peer = ET.Element('device', {'id': self.ids[1-n], 'name': 'peer'})
            ET.SubElement(peer, 'address').text = f'tcp://127.0.0.1:{self.ports[1-n]}'
            config.insert(1, peer)
            folder = ET.Element('folder', {'id': 'fixture', 'label': 'fixture',
                                           'path': str(self.shares[n]), 'type': 'sendreceive',
                                           'rescanIntervalS': '2', 'fsWatcherEnabled': 'false'})
            for device_id in self.ids:
                ET.SubElement(folder, 'device', {'id': device_id})
            config.insert(0, folder)
            tree.write(self.config_dirs[n] / 'config.xml', encoding='utf-8', xml_declaration=True)

    def api(self, node, path, method='GET'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.guis[node]}{path}',
                                         headers={'X-API-Key': self.keys[node]}, method=method)
        with self.opener.open(request, timeout=2) as response:
            payload = response.read()
            return json.loads(payload) if payload else None

    def wait_for(self, description, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for process in self.processes:
                if process is not None and process.poll() is not None:
                    raise RuntimeError(f'test Syncthing exited with status {process.returncode}')
            try:
                if predicate():
                    return
            except (OSError, urllib.error.URLError, ValueError):
                pass
            time.sleep(0.25)
        raise AssertionError(f'timeout waiting for {description}')

    def start(self, node):
        log = (self.root / f'log-{node}.txt').open('a')
        self.logs.append(log)
        self.processes[node] = subprocess.Popen(
            [self.binary, '-H', str(self.config_dirs[node]), 'serve', '--no-browser',
             '--no-restart', '--no-upgrade', '--log-file=-'],
            stdout=log, stderr=subprocess.STDOUT, env=self.env)
        self.wait_for(f'node {node} API', lambda: self.api(node, '/rest/system/status'))

    def stop(self, node):
        process = self.processes[node]
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.processes[node] = None

    def cleanup_lab(self):
        errors = []
        for node in range(2):
            try:
                self.stop(node)
            except Exception as error:
                errors.append(error)
        for log in self.logs:
            log.close()
        if errors:
            raise RuntimeError(f'test processes may still be running; data preserved at {self.root}') from errors[0]
        shutil.rmtree(self.root)

    def connected(self, node):
        return self.api(node, '/rest/system/connections')['connections'][self.ids[1-node]]['connected']

    def idle(self, node):
        return self.api(node, '/rest/db/status?folder=fixture')['state'] == 'idle'

    def scan(self, node):
        self.api(node, '/rest/db/scan?folder=fixture', 'POST')

    def test_two_devices_sync_and_preserve_offline_conflict(self):
        self.start(0)
        self.start(1)
        self.wait_for('connection', lambda: self.connected(0) and self.connected(1))
        self.wait_for('initial scan', lambda: self.idle(0) and self.idle(1))
        (self.shares[0] / 'sample.txt').write_text('initial\n', encoding='utf-8')
        self.scan(0)
        self.wait_for('initial synchronization', lambda: (self.shares[1] / 'sample.txt').exists()
                      and (self.shares[1] / 'sample.txt').read_text() == 'initial\n')
        (self.shares[1] / 'new.txt').write_text('from B\n', encoding='utf-8')
        self.scan(1)
        self.wait_for('reverse synchronization', lambda: (self.shares[0] / 'new.txt').exists()
                      and (self.shares[0] / 'new.txt').read_text() == 'from B\n')
        (self.shares[0] / 'new.txt').unlink()
        self.scan(0)
        self.wait_for('deletion propagation', lambda: not (self.shares[1] / 'new.txt').exists())
        self.stop(0)
        self.stop(1)
        for node, contents in enumerate(('offline A\n', 'offline B\n')):
            (self.shares[node] / 'sample.txt').write_text(contents, encoding='utf-8')
            self.start(node)
            self.scan(node)
            self.wait_for('offline local scan', lambda: self.idle(node))
            self.stop(node)
        self.start(0)
        self.start(1)
        self.wait_for('reconnection', lambda: self.connected(0) and self.connected(1))

        def files(node):
            return {path.name: path.read_text(encoding='utf-8') for path in self.shares[node].iterdir()
                    if path.is_file() and path.name.startswith('sample')}

        def preserved():
            left, right = files(0), files(1)
            return (left == right and len(left) >= 2
                    and set(left.values()) == {'offline A\n', 'offline B\n'})

        self.wait_for('both conflict versions', preserved, timeout=60)
        self.assertTrue(any('.sync-conflict-' in name for name in files(0)))


if __name__ == '__main__':
    unittest.main()
