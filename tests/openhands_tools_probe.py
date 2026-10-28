"""Exercise real OpenHands tools only against disposable local data."""
import tempfile
from pathlib import Path

from openhands.tools.file_editor.definition import FileEditorAction
from openhands.tools.file_editor.impl import FileEditorExecutor
from openhands.tools.terminal.definition import TerminalAction
from openhands.tools.terminal.impl import TerminalExecutor


with tempfile.TemporaryDirectory(prefix='recipkg-tools-') as tmp:
    root = Path(tmp)
    workspace = root / 'work'
    workspace.mkdir()
    target = workspace / 'fixture.txt'
    outside = root / 'outside.txt'
    outside.write_text('outside\n', encoding='utf-8')
    editor = FileEditorExecutor(workspace_root=str(workspace))

    def edit(executor, command, path, **kwargs):
        return executor(FileEditorAction(command=command, path=str(path), **kwargs))

    assert not edit(editor, 'create', target, file_text='alpha\nbeta\nalpha\n').is_error
    assert edit(editor, 'create', target, file_text='overwrite').is_error
    assert edit(editor, 'str_replace', target, old_str='alpha', new_str='x').is_error
    assert target.read_text(encoding='utf-8') == 'alpha\nbeta\nalpha\n'
    assert not edit(editor, 'str_replace', target, old_str='beta', new_str='BETA').is_error
    assert not edit(editor, 'insert', target, insert_line=1, new_str='inserted').is_error
    assert target.read_text(encoding='utf-8') == 'alpha\ninserted\nBETA\nalpha\n'
    assert not edit(editor, 'undo_edit', target).is_error
    assert target.read_text(encoding='utf-8') == 'alpha\nBETA\nalpha\n'
    assert edit(editor, 'view', 'fixture.txt').is_error
    assert not edit(editor, 'view', outside).is_error
    assert not edit(editor, 'str_replace', outside, old_str='outside', new_str='changed').is_error
    assert outside.read_text(encoding='utf-8') == 'changed\n'
    restricted = FileEditorExecutor(workspace_root=str(workspace), allowed_edits_files=[str(target)])
    assert not edit(restricted, 'view', outside).is_error
    assert edit(restricted, 'str_replace', outside, old_str='changed', new_str='blocked').is_error
    assert outside.read_text(encoding='utf-8') == 'changed\n'
    assert not edit(restricted, 'str_replace', target, old_str='BETA', new_str='beta').is_error

    terminal = TerminalExecutor(working_dir=str(workspace), terminal_type='subprocess',
                                shell_path='/bin/bash')
    try:
        pwd = terminal(TerminalAction(command='pwd', timeout=10))
        assert pwd.exit_code == 0 and str(workspace) in pwd.text
        setup = terminal(TerminalAction(command='export RECIPKG_FIXTURE_VAR=hello', timeout=10))
        assert setup.exit_code == 0
        read = terminal(TerminalAction(command='printf "%s\\n" "$RECIPKG_FIXTURE_VAR"', timeout=10))
        assert read.exit_code == 0 and 'hello' in read.text
        failed = terminal(TerminalAction(command='false', timeout=10))
        assert failed.exit_code == 1 and not failed.is_error
        running = terminal(TerminalAction(command='sleep 2; printf done', timeout=0.3))
        assert running.exit_code == -1 and not running.is_error
        completed = terminal(TerminalAction(command='', timeout=5))
        assert completed.exit_code == 0 and 'done' in completed.text
        malformed = terminal(TerminalAction(command='["not", "shell"]', timeout=10))
        assert malformed.is_error and malformed.exit_code is None
    finally:
        terminal.close()

print('editor and subprocess terminal fixture passed')
