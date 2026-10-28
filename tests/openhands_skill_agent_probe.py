"""Drive project-skill invocation through a loopback model and real SDK."""
import http.server
import json
from pathlib import Path
import tempfile
import threading

import openhands_sdk_probe as fixture
from pydantic import SecretStr
from openhands.sdk import Agent
from openhands.sdk.context.agent_context import AgentContext
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.event import ObservationEvent
from openhands.sdk.llm import LLM
from openhands.sdk.tool.builtins.invoke_skill import InvokeSkillTool


class ModelHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers['Content-Length'])
        request = json.loads(self.rfile.read(size))
        self.server.requests.append(request)
        index = len(self.server.requests) - 1
        names = ['alpha', 'alpha', 'missing', 'hidden']
        if index < len(names):
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': f'skill-call-{index}', 'type': 'function',
                'function': {'name': InvokeSkillTool.name,
                             'arguments': json.dumps({'name': names[index]})}}]}
            reason = 'tool_calls'
        else:
            message = {'role': 'assistant', 'content': 'finished'}
            reason = 'stop'
        payload = {'id': 'skill-fixture', 'model': 'gpt-4o-mini', 'created': 0,
                   'object': 'chat.completion', 'choices': [
                       {'index': 0, 'message': message, 'finish_reason': reason}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def run():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
    server.requests = []
    fixture._allowed_port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='recipkg-sdk-model-skill-') as directory:
            work = Path(directory)
            for name, frontmatter, body in [
                ('alpha', '', 'ALPHA_BODY !`printf x >> invocation-count; printf inline-value`'),
                ('hidden', 'disable-model-invocation: true\n', 'HIDDEN_BODY'),
            ]:
                skill = work / '.agents' / 'skills' / name
                skill.mkdir(parents=True)
                (skill / 'SKILL.md').write_text(
                    f'---\nname: {name}\ndescription: {name} description\n{frontmatter}---\n\n{body}\n',
                    encoding='utf-8')
            llm = LLM(model='openai/gpt-4o-mini', api_key=SecretStr('fixture-key'),
                      base_url=f'http://127.0.0.1:{server.server_port}/v1', usage_id='skill-fixture')
            agent = Agent(llm=llm, tools=[], include_default_tools=[],
                          agent_context=AgentContext(load_project_skills=True,
                                                     current_datetime='2026-01-01T00:00:00Z'))
            conversation = LocalConversation(agent=agent, workspace=work, visualizer=None)
            try:
                conversation.send_message('Use the project skill')
                conversation.run()
                assert str(conversation.state.execution_status).endswith('.FINISHED')
                assert len(server.requests) == 5, len(server.requests)
                first = server.requests[0]
                names = [tool['function']['name'] for tool in first['tools']]
                assert InvokeSkillTool.name in names, names
                first_messages = str(first['messages'])
                assert 'alpha description' in first_messages and 'ALPHA_BODY' not in first_messages
                assert 'hidden description' not in first_messages and 'HIDDEN_BODY' not in first_messages
                subsequent = server.requests[-1]['messages']
                results = [str(message.get('content', '')) for message in subsequent
                           if message.get('role') == 'tool']
                assert len(results) == 4, results
                assert all('ALPHA_BODY' in result and 'inline-value' in result for result in results[:2]), results
                assert 'Unknown skill' in results[2] and 'alpha' in results[2], results
                assert 'cannot be invoked directly' in results[3], results
                assert (work / 'invocation-count').read_text(encoding='utf-8') == 'xx'
                assert conversation.state.invoked_skills == ['alpha'], conversation.state.invoked_skills
                observations = [event.observation for event in conversation.state.events
                                if isinstance(event, ObservationEvent)]
                assert [observation.is_error for observation in observations] == [False, False, True, True]
                annotations = InvokeSkillTool.create()[0].annotations
                assert annotations.readOnlyHint is True and annotations.idempotentHint is True
            finally:
                conversation.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        fixture._allowed_port = None
    print('sdk model skill fixture: disclosure, repeated invocation, unknown and disabled passed')


if __name__ == '__main__':
    run()
