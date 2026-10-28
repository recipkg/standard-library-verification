"""Partial OpenClaw Gateway observations with a loopback model fixture."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FixtureModel(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        self.requests.append((self.path, body))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for delta, finish in [({'role': 'assistant', 'content': 'Fixture answer'}, None), ({}, 'stop')]:
            event = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'mock',
                     'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()

    def log_message(self, *args):
        pass


class OpenClawSamples(unittest.TestCase):
    def setUp(self):
        binary = os.environ.get('RECIPKG_TEST_OPENCLAW')
        if not binary:
            self.skipTest('set RECIPKG_TEST_OPENCLAW to a disposable test executable')
        self.binary = str(Path(binary).resolve(strict=True))
        self.tmp = tempfile.TemporaryDirectory(prefix='recipkg-openclaw-test-')
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.model = ThreadingHTTPServer(('127.0.0.1', 0), FixtureModel)
        FixtureModel.requests = []
        self.thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.model.server_close)
        self.addCleanup(self.model.shutdown)
        self.process = None
        self.log = None
        self.addCleanup(self.stop)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        workspace = self.root / 'workspace'
        workspace.mkdir()
        config = {'gateway': {'mode': 'local', 'bind': 'loopback', 'port': self.port,
                              'auth': {'mode': 'token', 'token': 'temporary-test-token'},
                              'controlUi': {'enabled': False}},
                  'discovery': {'mdns': {'mode': 'off'}}, 'cron': {'enabled': False},
                  'browser': {'enabled': False},
                  'agents': {'defaults': {'workspace': str(workspace), 'model': {'primary': 'fixture/mock'},
                                          'heartbeat': {'every': '0m'}}},
                  'models': {'mode': 'merge', 'providers': {'fixture': {
                      'baseUrl': f'http://127.0.0.1:{self.model.server_port}/v1', 'apiKey': 'dummy',
                      'api': 'openai-completions', 'models': [{'id': 'mock', 'name': 'Mock',
                          'reasoning': False, 'input': ['text'],
                          'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
                          'contextWindow': 64000, 'maxTokens': 256}]}}}}
        config_path = self.root / 'config.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        self.env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(self.root), 'LANG': 'C.UTF-8',
                    'OPENCLAW_STATE_DIR': str(self.root / 'state'), 'OPENCLAW_CONFIG_PATH': str(config_path),
                    'OPENCLAW_GATEWAY_TOKEN': 'temporary-test-token',
                    'NODE_COMPILE_CACHE': str(self.root / 'node-cache'), 'OPENCLAW_SKIP_CHANNELS': '1',
                    'OPENCLAW_DISABLE_BONJOUR': '1', 'OPENCLAW_DISABLE_BUNDLED_PLUGINS': '1'}
        self.start()

    def start(self):
        self.log = (self.root / 'gateway.log').open('ab')
        self.process = subprocess.Popen([self.binary, 'gateway', 'run', '--bind', 'loopback',
                                         '--port', str(self.port)], cwd=self.root, env=self.env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(120):
            if self.process.poll() is not None:
                self.fail('Gateway exited during startup')
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.5):
                    return
            except OSError:
                time.sleep(.5)
        self.fail('Gateway startup timed out')

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def run_cli(self, *args):
        result = subprocess.run([self.binary, *args], cwd=self.root, env=self.env, text=True,
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        return json.loads(result.stdout)

    def history(self):
        return self.run_cli('gateway', 'call', 'chat.history', '--params',
                            json.dumps({'sessionKey': 'agent:main:recipkg-fixture'}), '--json')

    def test_gateway_turns_history_and_restart(self):
        health = self.run_cli('gateway', 'call', 'health', '--json')
        self.assertTrue(health['ok'])
        self.assertEqual(health['channels'], {})
        for message in ('first question', 'second question'):
            result = self.run_cli('agent', '--session-key', 'agent:main:recipkg-fixture',
                                  '--message', message, '--json', '--timeout', '30')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['result']['payloads'][0]['text'], 'Fixture answer')
        self.assertEqual(len(FixtureModel.requests), 2)
        self.assertEqual(FixtureModel.requests[0][0], '/v1/chat/completions')
        second_request = json.dumps(FixtureModel.requests[1][1]['messages'])
        for value in ('first question', 'Fixture answer', 'second question'):
            self.assertIn(value, second_request)
        before = self.history()
        self.assertEqual([x['role'] for x in before['messages']], ['user', 'assistant', 'user', 'assistant'])
        session_id = before['sessionId']
        self.stop()
        self.start()
        after = self.history()
        self.assertEqual(after['sessionId'], session_id)
        self.assertEqual([x['role'] for x in after['messages']], ['user', 'assistant', 'user', 'assistant'])
        serialized = json.dumps(after['messages'])
        for value in ('first question', 'second question', 'Fixture answer'):
            self.assertIn(value, serialized)


if __name__ == '__main__':
    unittest.main()
