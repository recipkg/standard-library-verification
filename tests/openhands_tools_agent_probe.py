"""Drive the real editor and terminal through an SDK conversation."""
import http.server
import json
from pathlib import Path
import tempfile
import threading

import openhands_sdk_probe as fixture
from pydantic import SecretStr
from openhands.sdk import Agent
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.llm import LLM
from openhands.sdk.tool import Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


class ScriptedModel(fixture.ModelFixture):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        self.server.requests.append((self.path, json.loads(self.rfile.read(length))))
        index = len(self.server.requests)
        if index == 1:
            name = FileEditorTool.name
            arguments = {'command': 'create', 'path': str(self.server.target),
                         'file_text': 'fixture-body\n'}
        elif index == 2:
            name = TerminalTool.name
            arguments = {'command': 'cat fixture.txt', 'timeout': 10}
        else:
            name, arguments = None, None
        message = {'role': 'assistant', 'content': 'done'}
        if name:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': f'fixture-{index}', 'type': 'function',
                 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
        payload = {'id': f'fixture-response-{index}', 'model': 'gpt-4o-mini', 'created': 0,
                   'object': 'chat.completion', 'choices': [
                       {'index': 0, 'message': message,
                        'finish_reason': 'tool_calls' if name else 'stop'}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


with tempfile.TemporaryDirectory(prefix='recipkg-tools-agent-') as tmp:
    root = Path(tmp)
    work, persist = root / 'work', root / 'persist'
    work.mkdir()
    persist.mkdir()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ScriptedModel)
    server.requests = []
    server.target = work / 'fixture.txt'
    fixture._allowed_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        llm = LLM(model='openai/gpt-4o-mini', api_key=SecretStr('fixture-key'),
                  base_url=f'http://127.0.0.1:{server.server_port}/v1', usage_id='fixture')
        agent = Agent(llm=llm, tools=[Tool(name=FileEditorTool.name),
                                      Tool(name=TerminalTool.name,
                                           params={'terminal_type': 'subprocess', 'shell_path': '/bin/bash'})])
        conversation = LocalConversation(agent=agent, workspace=work,
                                         persistence_dir=persist, visualizer=None)
        try:
            conversation.send_message('Create and read the fixture file')
            conversation.run()
            events = list(conversation.state.events)
            actions = [event.tool_name for event in events if type(event).__name__ == 'ActionEvent']
            observations = [event for event in events if type(event).__name__ == 'ObservationEvent']
            assert actions == [FileEditorTool.name, TerminalTool.name], actions
            assert len(observations) == 2
            assert not observations[0].observation.is_error
            assert observations[1].observation.exit_code == 0
            assert 'fixture-body' in observations[1].observation.text
            assert server.target.read_text(encoding='utf-8') == 'fixture-body\n'
            assert len(server.requests) == 3
            assert str(conversation.state.execution_status).endswith('.FINISHED')
        finally:
            conversation.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        fixture._allowed_port = None

print('agent used editor and terminal fixture passed')
