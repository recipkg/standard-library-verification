"""Exercise project skill loading without a model or non-local network."""
from pathlib import Path
import socket
import subprocess
import tempfile


def block_network(*args, **kwargs):
    raise OSError('network disabled by fixture')


socket.socket.connect = block_network
socket.socket.connect_ex = block_network

from openhands.sdk.agent import Agent
from openhands.sdk.context.agent_context import AgentContext
from openhands.sdk.conversation.impl.local_conversation import LocalConversation
from openhands.sdk.event import SystemPromptEvent
from openhands.sdk.llm import Message, TextContent
from openhands.sdk.skills import Skill, load_project_skills
from openhands.sdk.testing import TestLLM
from openhands.sdk.tool.builtins.invoke_skill import InvokeSkillAction, InvokeSkillExecutor


def git(cwd, *args):
    subprocess.run(['git', '-c', 'protocol.file.allow=always', *args], cwd=cwd,
                   check=True, capture_output=True, text=True, timeout=20)


def write_skill(root, directory, name, description, body):
    path = root / directory / name
    path.mkdir(parents=True, exist_ok=True)
    (path / 'SKILL.md').write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n\n{body}\n', encoding='utf-8')
    return path


def run():
    with tempfile.TemporaryDirectory(prefix='recipkg-sdk-skill-') as tmp:
        root = Path(tmp)
        project, upstream = root / 'project', root / 'upstream'
        project.mkdir()
        upstream.mkdir()
        for repo in (project, upstream):
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.name', 'Fixture')
            git(repo, 'config', 'user.email', 'fixture@example.invalid')
        (upstream / 'SKILL.md').write_text(
            '---\nname: subskill\ndescription: SUBSKILL_DESCRIPTION\n---\n\nSUBSKILL_BODY\n'
            '!`printf inline-value; touch inline-marker`\n'
            '```\n!`touch fenced-marker`\n```\n', encoding='utf-8')
        (upstream / 'scripts').mkdir()
        (upstream / 'scripts' / 'fixture.sh').write_text('#!/bin/sh\ntouch SHOULD_NOT_EXIST\n', encoding='utf-8')
        git(upstream, 'add', 'SKILL.md', 'scripts/fixture.sh')
        git(upstream, 'commit', '-qm', 'fixture skill')
        write_skill(project, '.agents/skills', 'shared', 'ROOT_DESCRIPTION', 'ROOT_BODY')
        write_skill(project, '.openhands/skills', 'shared', 'LEGACY_DESCRIPTION', 'LEGACY_BODY')
        git(project, 'submodule', 'add', '-q', str(upstream), '.agents/skills/subskill')
        git(project, 'add', '.')
        git(project, 'commit', '-qm', 'fixture project')
        work = project / 'nested'
        work.mkdir()
        write_skill(work, '.agents/skills', 'shared', 'NESTED_DESCRIPTION', 'NESTED_BODY')
        (work / 'AGENTS.md').write_text('PROJECT_INSTRUCTIONS', encoding='utf-8')
        root_skills = {s.name: s for s in load_project_skills(project)}
        assert 'ROOT_BODY' in root_skills['shared'].content
        skills = {s.name: s for s in load_project_skills(work)}
        assert 'NESTED_BODY' in skills['shared'].content
        assert 'SUBSKILL_BODY' in skills['subskill'].content
        assert (project / '.agents/skills/subskill/scripts/fixture.sh').is_file()

        def create(enabled, disabled):
            context = AgentContext(
                skills=[Skill(name='subskill', content='EXPLICIT_OLD_CONTENT'),
                        Skill(name='keep', content='EXPLICIT_KEEP')],
                load_project_skills=enabled, disabled_skills=disabled,
                current_datetime='2026-01-01T00:00:00Z')
            agent = Agent(llm=TestLLM.from_messages([
                Message(role='assistant', content=[TextContent(text='ok')])]),
                tools=[], include_default_tools=[], agent_context=context)
            conversation = LocalConversation(agent=agent, workspace=work, visualizer=None)
            conversation.send_message('fixture message')
            return conversation

        conversation = create(True, [])
        try:
            loaded = {s.name: s for s in conversation.agent.agent_context.skills}
            assert 'SUBSKILL_BODY' in loaded['subskill'].content
            assert loaded['keep'].content == 'EXPLICIT_KEEP'
            prompt = next(e for e in conversation.state.events if isinstance(e, SystemPromptEvent))
            text = prompt.dynamic_context.text
            assert 'PROJECT_INSTRUCTIONS' in text
            assert 'SUBSKILL_DESCRIPTION' in text and 'NESTED_DESCRIPTION' in text
            assert 'SUBSKILL_BODY' not in text and 'NESTED_BODY' not in text
            assert 'EXPLICIT_OLD_CONTENT' not in text
            assert 'invoke_skill' in text and 'SKILL.md' not in text
            assert not (work / 'inline-marker').exists()
            observation = InvokeSkillExecutor()(InvokeSkillAction(name='subskill'), conversation)
            assert not observation.is_error and 'SUBSKILL_BODY' in observation.text
            assert 'inline-value' in observation.text and 'This skill is located at' in observation.text
            assert (work / 'inline-marker').exists() and not (work / 'fenced-marker').exists()
            assert 'subskill' in conversation.state.invoked_skills
        finally:
            conversation.close()
        conversation = create(True, ['shared', 'subskill'])
        try:
            names = {s.name for s in conversation.agent.agent_context.skills}
            assert 'keep' in names and 'shared' not in names and 'subskill' not in names
        finally:
            conversation.close()
        conversation = create(False, [])
        try:
            loaded = {s.name: s for s in conversation.agent.agent_context.skills}
            assert 'shared' not in loaded and loaded['subskill'].content == 'EXPLICIT_OLD_CONTENT'
        finally:
            conversation.close()
        assert not any(root.rglob('SHOULD_NOT_EXIST'))
    print('sdk project skill fixture: submodule, precedence, disclosure, disable and flag passed')


if __name__ == '__main__':
    run()
