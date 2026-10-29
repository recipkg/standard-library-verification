"""Black-box check of the real Canvas recipe's recursive package context."""
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import unittest


class CanvasRecipePackage(unittest.TestCase):
    def test_pinned_recursive_context_and_integrity(self):
        recipe = os.environ.get('RECIPKG_TEST_CANVAS_RECIPE')
        cli = os.environ.get('RECIPKG_TEST_CLI')
        if not recipe and not cli:
            self.skipTest('set RECIPKG_TEST_CANVAS_RECIPE and RECIPKG_TEST_CLI')
        if not recipe or not cli:
            self.fail('both RECIPKG_TEST_CANVAS_RECIPE and RECIPKG_TEST_CLI are required')
        executable = shutil.which(cli)
        root = Path(recipe).resolve()
        self.assertIsNotNone(executable, 'selected Recipkg CLI not found')
        self.assertTrue((root / 'RECIPE.md').is_file(), 'selected Canvas recipe not found')
        manifest_text = (root / 'RECIPE.md').read_text(encoding='utf-8')
        match = re.search(r'```toml\s*\n(.*?)\n```', manifest_text, re.DOTALL)
        self.assertIsNotNone(match)
        manifest = tomllib.loads(match.group(1))
        agent_revision = manifest['dependencies']['agent']['rev']
        self.assertRegex(agent_revision, r'^[0-9a-f]{40}$')
        with tempfile.TemporaryDirectory(prefix='recipkg-canvas-package-') as tmp:
            archive = Path(tmp) / 'canvas.recipe.tar.gz'
            def run(*args):
                return subprocess.run([executable, *map(str, args)], cwd=tmp,
                                      text=True, capture_output=True, timeout=120)
            packed = run('pack', root, '-o', archive)
            self.assertEqual(packed.returncode, 0, packed.stderr)
            checked = run('check', archive)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            with tarfile.open(archive, 'r:gz') as tar:
                members = {member.name: member for member in tar.getmembers() if member.isfile()}
                required = ['.deps/agent/PROJECT-SKILLS-OBSERVED.md',
                            'AUTH-ERROR-BROWSER-OBSERVED.md',
                            '.deps/agent/FAILURE-RECOVERY-OBSERVED.md',
                            '.deps/agent/.deps/quality/BUILD_PROMPT.md',
                            '.deps/design/.deps/foundation/BUILD_PROMPT.md',
                            '.deps/design/AGENT-INTERACTION.md', 'LOCK.md']
                for path in required:
                    self.assertIn(path, members)
                skill_doc = tar.extractfile(members[required[0]]).read()
                failure_doc = tar.extractfile(members['.deps/agent/FAILURE-RECOVERY-OBSERVED.md']).read()
                design_doc = tar.extractfile(members['.deps/design/AGENT-INTERACTION.md']).read()
                lock = tar.extractfile(members['LOCK.md']).read().decode('utf-8')
                self.assertIn(agent_revision, lock)
                self.assertIn(b'fixture-invalid-credential', failure_doc)
                canvas_error_doc = tar.extractfile(members['AUTH-ERROR-BROWSER-OBSERVED.md']).read()
                captured = [(member, tar.extractfile(member).read()) for member in tar.getmembers()
                            if member.isfile()]
            build = run('build', archive)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertIn(skill_doc.decode('utf-8'), build.stdout)
            self.assertIn(canvas_error_doc.decode('utf-8'), build.stdout)
            self.assertIn(failure_doc.decode('utf-8'), build.stdout)
            self.assertIn(design_doc.decode('utf-8'), build.stdout)
            self.assertIn(agent_revision, build.stdout)
            corrupted = Path(tmp) / 'corrupted.recipe.tar.gz'
            with tarfile.open(corrupted, 'w:gz') as tar:
                for member, data in captured:
                    if member.name == required[0]:
                        data += b'\nmodified\n'
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
            failed = run('check', corrupted)
            self.assertNotEqual(failed.returncode, 0, 'tampered dependency was accepted')
            self.assertIn('integrity mismatch', failed.stderr)
            self.assertIn(required[0], failed.stderr)


if __name__ == '__main__':
    unittest.main()
