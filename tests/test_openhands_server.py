"""Exercise a disposable agent-server process and local model fixture."""
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
import urllib.error
import urllib.request
import uuid


class ModelFixture(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, payload))
        response = {'id': 'fixture-response', 'model': 'gpt-4o-mini', 'created': 0,
                    'object': 'chat.completion', 'choices': [
                        {'index': 0, 'message': {'role': 'assistant', 'content': 'fixture reply'},
                         'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class OpenHandsServerSamples(unittest.TestCase):
    def test_auth_conversation_run_and_restart(self):
        selected = os.environ.get('RECIPKG_TEST_OPENHANDS_SERVER_PYTHON')
        if not selected:
            self.skipTest('set RECIPKG_TEST_OPENHANDS_SERVER_PYTHON to a Python with the candidate server')
        executable = shutil.which(selected)
        if not executable:
            self.fail('RECIPKG_TEST_OPENHANDS_SERVER_PYTHON executable not found')

        model = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ModelFixture)
        model.requests = []
        model_thread = threading.Thread(target=model.serve_forever, daemon=True)
        model_thread.start()
        self.addCleanup(model.server_close)
        self.addCleanup(model_thread.join, 5)
        self.addCleanup(model.shutdown)

        with tempfile.TemporaryDirectory(prefix='oh-test-') as temp:
            root = Path(temp)
            (root / 'work').mkdir()
            (root / 'tmux').mkdir()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            env = {'PATH': os.defpath, 'HOME': temp, 'TMPDIR': temp, 'LANG': 'C.UTF-8',
                   'TMUX_TMPDIR': str(root / 'tmux'), 'OPENHANDS_SUPPRESS_BANNER': '1',
                   'OH_ENABLE_VSCODE': 'false', 'OH_PRELOAD_TOOLS': 'false',
                   'OH_CONVERSATIONS_PATH': str(root / 'conversations'),
                   'OH_SESSION_API_KEYS_0': 'fixture-session-key', 'DO_NOT_TRACK': '1',
                   'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'LITELLM_TELEMETRY': 'False'}

            def request(path, *, method='GET', body=None, auth='key'):
                data = json.dumps(body).encode() if body is not None else None
                headers = {'Content-Type': 'application/json'} if data is not None else {}
                if auth == 'key':
                    headers['X-Session-API-Key'] = 'fixture-session-key'
                elif auth == 'wrong':
                    headers['X-Session-API-Key'] = 'wrong-key'
                elif auth == 'bearer':
                    headers['Authorization'] = 'Bearer fixture-session-key'
                req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        status, contents = response.status, response.read()
                except urllib.error.HTTPError as error:
                    with error:
                        status, contents = error.code, error.read()
                return status, json.loads(contents) if contents else None

            def start(log):
                process = subprocess.Popen([executable, '-m', 'openhands.agent_server',
                                            '--host', '127.0.0.1', '--port', str(port)],
                                           cwd=temp, env=env, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 45
                try:
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            self.fail(f'server exited before ready: {process.returncode}')
                        try:
                            if request('/ready', auth=None)[0] == 200:
                                return process
                        except (OSError, urllib.error.URLError):
                            pass
                        time.sleep(0.1)
                    self.fail('server readiness timed out')
                except BaseException:
                    stop(process)
                    raise

            def stop(process):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

            def wait_for_finish(conversation_id):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status, state = request(f'/api/conversations/{conversation_id}')
                    self.assertEqual(status, 200)
                    if state['execution_status'] == 'finished':
                        return state
                    self.assertNotIn(state['execution_status'], ('error', 'stuck'))
                    time.sleep(0.1)
                self.fail('conversation did not finish')

            with (root / 'server.log').open('w+') as log:
                process = start(log)
                try:
                    self.assertEqual(request('/ready', auth=None), (200, {'status': 'ready'}))
                    for auth in (None, 'wrong', 'bearer'):
                        self.assertEqual(request('/api/conversations/search', auth=auth)[0], 401)
                    self.assertEqual(request('/api/conversations/count')[1], 0)
                    payload = {'agent': {'kind': 'Agent',
                                         'llm': {'model': 'openai/gpt-4o-mini', 'api_key': 'fixture-key',
                                                 'base_url': f'http://127.0.0.1:{model.server_port}/v1',
                                                 'usage_id': 'fixture'},
                                         'tools': [], 'include_default_tools': []},
                               'workspace': {'working_dir': str(root / 'work')}, 'autotitle': False}
                    status, conversation = request('/api/conversations', method='POST', body=payload)
                    self.assertEqual(status, 201)
                    conversation_id = conversation['id']
                    self.assertEqual(conversation['execution_status'], 'idle')
                    status, _ = request(f'/api/conversations/{conversation_id}/events', method='POST',
                                        body={'role': 'user', 'content': [{'type': 'text', 'text': 'fixture request'}],
                                              'run': False})
                    self.assertEqual(status, 200)
                    self.assertEqual(len(model.requests), 0)
                    status, events = request(f'/api/conversations/{conversation_id}/events/search')
                    self.assertEqual(status, 200)
                    self.assertTrue(any(e.get('kind') == 'MessageEvent' and e.get('source') == 'user'
                                        for e in events['items']))
                    self.assertEqual(request(f'/api/conversations/{conversation_id}/run', method='POST')[0], 200)
                    wait_for_finish(conversation_id)
                    self.assertEqual(len(model.requests), 1)
                    self.assertEqual(model.requests[0][0], '/v1/chat/completions')
                    status, before = request(f'/api/conversations/{conversation_id}/events/search')
                    self.assertEqual(status, 200)
                    self.assertTrue(any(e.get('kind') == 'MessageEvent' and e.get('source') == 'agent'
                                        for e in before['items']))
                    initial_payload = dict(payload)
                    initial_payload['initial_message'] = {
                        'role': 'user', 'content': [{'type': 'text', 'text': 'initial fixture'}], 'run': False}
                    status, initial_conversation = request('/api/conversations', method='POST',
                                                           body=initial_payload)
                    self.assertEqual(status, 201)
                    initial_id = initial_conversation['id']
                    wait_for_finish(initial_id)
                    self.assertEqual(len(model.requests), 2)
                    self.assertIn('initial fixture', str(model.requests[-1][1]['messages']))
                finally:
                    stop(process)

                process = start(log)
                try:
                    status, restored = request(f'/api/conversations/{conversation_id}')
                    self.assertEqual((status, restored['id']), (200, conversation_id))
                    status, after = request(f'/api/conversations/{conversation_id}/events/search')
                    self.assertEqual(status, 200)
                    self.assertEqual([e['id'] for e in after['items']], [e['id'] for e in before['items']])
                    self.assertEqual(request('/api/conversations/count')[1], 2)
                    missing = str(uuid.uuid4())
                    self.assertEqual(request(f'/api/conversations/{missing}')[0], 404)
                    self.assertEqual(request(f'/api/conversations/{conversation_id}', method='DELETE')[0], 200)
                    self.assertEqual(request(f'/api/conversations/{conversation_id}')[0], 404)
                    self.assertEqual(request(f'/api/conversations/{initial_id}', method='DELETE')[0], 200)
                    self.assertEqual(request('/api/conversations/count')[1], 0)
                finally:
                    stop(process)


if __name__ == '__main__':
    unittest.main()
