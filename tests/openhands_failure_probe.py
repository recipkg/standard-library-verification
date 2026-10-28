"""Observe agent recovery after an explicit simulated model authentication failure."""
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading

# Reuse the existing process-level loopback guard; it is not an OS sandbox.
import openhands_sdk_probe as guard
from pydantic import SecretStr
from openhands.sdk import Agent
from openhands.sdk.conversation.exceptions import ConversationRunError
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.event.conversation_error import ConversationErrorEvent
from openhands.sdk.llm import LLM
from openhands.sdk.llm.exceptions import LLMAuthenticationError
from openhands.sdk.tool import Action, Observation, Tool, ToolDefinition, ToolExecutor, register_tool


class CountAction(Action):
    text: str


class CountObservation(Observation):
    result: str = ''


class CountExecutor(ToolExecutor[CountAction, CountObservation]):
    def __call__(self, action, conversation=None):
        with open(os.environ['RECIPKG_FIXTURE_COUNTER'], 'a', encoding='utf-8') as output:
            output.write(action.text + '\n')
        return CountObservation.from_text('fixture observation recorded', result=action.text)


class FixtureCounter(ToolDefinition[CountAction, CountObservation]):
    @classmethod
    def create(cls, conv_state=None, **params):
        return [cls(description='Append a marker to a disposable file', action_type=CountAction,
                    observation_type=CountObservation, executor=CountExecutor())]


class FailureModel(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, request))
        number = len(self.server.requests)
        if number == self.server.fail_at:
            payload = {'error': {'message': 'fixture-invalid-credential',
                                 'type': 'authentication_error', 'code': 'invalid_api_key'}}
            status = 401
        else:
            if self.server.fail_at == 2 and number == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'fixture-count-call', 'type': 'function', 'function': {
                        'name': FixtureCounter.name, 'arguments': json.dumps({'text': 'once'})}}]}
            else:
                message = {'role': 'assistant', 'content': 'recovered'}
            payload = {'id': 'fixture-response', 'model': 'gpt-4o-mini', 'created': 0,
                       'object': 'chat.completion', 'choices': [{'index': 0, 'message': message,
                       'finish_reason': 'tool_calls' if number == 1 and self.server.fail_at == 2 else 'stop'}],
                       'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
            status = 200
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def run_case(fail_at):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FailureModel)
    server.requests, server.fail_at = [], fail_at
    guard._allowed_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='recipkg-sdk-auth-') as temporary:
            work = Path(temporary) / 'workspace'
            work.mkdir()
            persist = Path(temporary) / 'persist'
            counter = work / 'calls.txt'
            os.environ['RECIPKG_FIXTURE_COUNTER'] = str(counter)
            llm = LLM(model='openai/gpt-4o-mini', api_key=SecretStr('fixture-key'),
                      base_url=f'http://127.0.0.1:{server.server_port}/v1',
                      usage_id='fixture', num_retries=0)
            agent = Agent(llm=llm, tools=[Tool(name=FixtureCounter.name)])
            conversation = LocalConversation(agent=agent, workspace=work,
                                             persistence_dir=persist, visualizer=None)
            try:
                conversation.send_message('Record a disposable marker')
                try:
                    conversation.run()
                except ConversationRunError as exc:
                    assert isinstance(exc.__cause__, LLMAuthenticationError), type(exc.__cause__)
                else:
                    raise AssertionError('simulated authentication failure did not fail the run')
                assert str(conversation.state.execution_status).endswith('.ERROR')
                events = list(conversation.state.events)
                errors = [event for event in events if isinstance(event, ConversationErrorEvent)]
                assert len(errors) == 1 and errors[0].code == 'LLMAuthenticationError'
                assert 'invalid or has expired' in errors[0].detail
                assert 'fixture-invalid-credential' not in errors[0].detail
                assert 'fixture-key' not in errors[0].detail
                assert len(server.requests) == fail_at
                if fail_at == 2:
                    assert counter.read_text() == 'once\n'
                else:
                    assert not counter.exists()
                conversation_id = conversation.id
                event_types = [type(event).__name__ for event in events]
            finally:
                conversation.close()

            restored = LocalConversation(agent=agent, workspace=work, persistence_dir=persist,
                                         conversation_id=conversation_id, visualizer=None)
            try:
                assert restored.id == conversation_id
                assert str(restored.state.execution_status).endswith('.ERROR')
                assert [type(event).__name__ for event in restored.state.events] == event_types
                restored.run()
                assert str(restored.state.execution_status).endswith('.FINISHED')
                assert len(server.requests) == fail_at + 1
                assert all(path == '/v1/chat/completions' for path, _ in server.requests)
                if fail_at == 2:
                    assert counter.read_text() == 'once\n'
                    messages = server.requests[-1][1]['messages']
                    observations = [message for message in messages
                                    if message.get('role') == 'tool'
                                    and message.get('tool_call_id') == 'fixture-count-call']
                    assert len(observations) == 1, messages
                    assert 'fixture observation recorded' in str(observations[0])
                    assert sum(type(event).__name__ == 'ActionEvent' for event in restored.state.events) == 1
                else:
                    assert not counter.exists()
                assert len(restored.state.events) == len(events) + 1
            finally:
                restored.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        guard._allowed_port = None


if __name__ == '__main__':
    register_tool(FixtureCounter.name, FixtureCounter)
    run_case(fail_at=1)
    run_case(fail_at=2)
    print('sdk failure fixture: authentication before and after tool, persistence and recovery passed')
