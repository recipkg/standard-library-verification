"""Exercise a local SDK conversation against a disposable loopback model."""
import http.server
import json
import os
from pathlib import Path
import socket
import tempfile
import threading

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_allowed_port = None


def _validate_address(address):
    if not (isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1')
            and address[1] == _allowed_port):
        raise OSError('network endpoint is outside the test model')


def _connect(sock, address):
    _validate_address(address)
    return _original_connect(sock, address)


def _connect_ex(sock, address):
    _validate_address(address)
    return _original_connect_ex(sock, address)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex

from pydantic import SecretStr
from openhands.sdk import Agent
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.llm import LLM
from openhands.sdk.security.confirmation_policy import AlwaysConfirm
from openhands.sdk.tool import Action, Observation, Tool, ToolDefinition, ToolExecutor, register_tool


class FixtureAction(Action):
    text: str


class FixtureObservation(Observation):
    result: str = ''


class FixtureExecutor(ToolExecutor[FixtureAction, FixtureObservation]):
    def __call__(self, action, conversation=None):
        path = Path(os.environ['RECIPKG_FIXTURE_WORK']) / 'result.txt'
        path.write_text(action.text, encoding='utf-8')
        return FixtureObservation.from_text('saved', result=action.text)


class FixtureWriter(ToolDefinition[FixtureAction, FixtureObservation]):
    @classmethod
    def create(cls, conv_state=None, **params):
        return [cls(description='Write to a disposable fixture', action_type=FixtureAction,
                    observation_type=FixtureObservation, executor=FixtureExecutor())]


class ModelFixture(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        request = json.loads(self.rfile.read(length))
        self.server.requests.append((self.path, request))
        message = {'role': 'assistant', 'content': 'done'}
        if len(self.server.requests) == 1:
            arguments = {} if self.server.invalid else {'text': 'recipkg fixture'}
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'fixture-call', 'type': 'function',
                 'function': {'name': FixtureWriter.name, 'arguments': json.dumps(arguments)}}]}
        payload = {'id': 'fixture-response', 'model': 'gpt-4o-mini', 'created': 0,
                   'object': 'chat.completion', 'choices': [
                       {'index': 0, 'message': message,
                        'finish_reason': 'tool_calls' if len(self.server.requests) == 1 else 'stop'}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def run_case(invalid, confirm=False, reject=False):
    global _allowed_port
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ModelFixture)
    server.requests, server.invalid = [], invalid
    _allowed_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='recipkg-agent-') as tmp:
            root = Path(tmp)
            work, persist = root / 'work', root / 'persist'
            work.mkdir()
            persist.mkdir()
            os.environ['RECIPKG_FIXTURE_WORK'] = str(work)
            llm = LLM(model='openai/gpt-4o-mini', api_key=SecretStr('fixture-key'),
                      base_url=f'http://127.0.0.1:{server.server_port}/v1', usage_id='fixture')
            agent = Agent(llm=llm, tools=[Tool(name=FixtureWriter.name)])
            conversation = LocalConversation(agent=agent, workspace=work,
                                             persistence_dir=persist, visualizer=None)
            try:
                if confirm:
                    conversation.set_confirmation_policy(AlwaysConfirm())
                conversation.send_message('Write the fixture file')
                conversation.run()
                if confirm:
                    assert str(conversation.state.execution_status).endswith('.WAITING_FOR_CONFIRMATION')
                    assert len(server.requests) == 1
                    assert not (work / 'result.txt').exists()
                    if reject:
                        conversation.reject_pending_actions('fixture rejection')
                    conversation.run()
                conversation_id = conversation.id
                events = [(type(event).__name__, getattr(event, 'source', None),
                           getattr(event, 'tool_name', None)) for event in conversation.state.events]
                assert events == [
                    ('SystemPromptEvent', 'agent', None),
                    ('MessageEvent', 'user', None),
                    ('ActionEvent', 'agent', FixtureWriter.name),
                    ('AgentErrorEvent' if invalid else 'UserRejectObservation' if reject else 'ObservationEvent',
                     'agent' if invalid else 'environment', FixtureWriter.name),
                    ('MessageEvent', 'agent', None),
                ], events
                assert str(conversation.state.execution_status).endswith('.FINISHED')
                assert len(server.requests) == 2
                assert all(path == '/v1/chat/completions' for path, _ in server.requests)
                if invalid or reject:
                    assert not (work / 'result.txt').exists()
                else:
                    assert (work / 'result.txt').read_text(encoding='utf-8') == 'recipkg fixture'
            finally:
                conversation.close()
            restored = LocalConversation(agent=agent, workspace=work, persistence_dir=persist,
                                         conversation_id=conversation_id, visualizer=None)
            try:
                assert restored.id == conversation_id
                assert len(restored.state.events) == len(events)
                restored.send_message('Follow up')
                restored.run()
                assert len(restored.state.events) == len(events) + 2
                assert len(server.requests) == 3
                assert 'Follow up' in str(server.requests[-1][1]['messages'])
            finally:
                restored.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        _allowed_port = None


if __name__ == '__main__':
    register_tool(FixtureWriter.name, FixtureWriter)
    run_case(invalid=False)
    run_case(invalid=True)
    run_case(invalid=False, confirm=True)
    run_case(invalid=False, confirm=True, reject=True)
    print('sdk conversation fixture: valid, invalid, confirmation, rejection, and restore passed')
