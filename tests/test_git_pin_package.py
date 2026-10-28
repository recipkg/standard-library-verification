"""Opt-in integration test for two published Git recipe revisions."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import unittest


OLD_REV = '1b0d53961d3855d425a85c8c1e4f58a69e0025b3'
NEW_REV = 'd735fba86179ecb87a500a80d1d2ebcbfc5a1014'
QUALITY_REV = '41e5b55c6612a9a5a10e499b5ace6a1a3fed0f2b'
NEW_MARKER = '在同一主从样本中'


def manifest(text):
    match = re.search(r'(?m)^```toml\s*\n(.*?)^```\s*$', text, re.DOTALL)
    if not match:
        raise AssertionError('missing TOML block')
    return tomllib.loads(match.group(1))


class GitPinPackage(unittest.TestCase):
    def test_real_pins_versions_and_offline_install(self):
        if os.environ.get('RECIPKG_TEST_GIT_PIN_NETWORK') != '1':
            self.skipTest('set RECIPKG_TEST_GIT_PIN_NETWORK=1 to allow pinned Git fetches')
        selected = os.environ.get('RECIPKG_TEST_CLI')
        if not selected:
            self.fail('set RECIPKG_TEST_CLI to the executable under test')
        executable = shutil.which(selected)
        self.assertIsNotNone(executable, f'Recipkg CLI not found: {selected!r}')
        with tempfile.TemporaryDirectory(prefix='recipkg-git-pin-') as temporary:
            root = Path(temporary)
            store = root / 'store'
            empty_path = root / 'no-programs'
            empty_path.mkdir()
            env = dict(os.environ, RECIPKG_HOME=str(store))
            offline = dict(env, PATH=str(empty_path), HTTP_PROXY='http://127.0.0.1:9',
                           HTTPS_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9',
                           http_proxy='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9',
                           all_proxy='http://127.0.0.1:9', NO_PROXY='', no_proxy='')

            def run(*args, offline_mode=False):
                return subprocess.run([executable, *map(str, args)], cwd=root,
                                      env=offline if offline_mode else env,
                                      text=True, capture_output=True, timeout=120)

            def ok(*args, offline_mode=False):
                result = run(*args, offline_mode=offline_mode)
                self.assertEqual(result.returncode, 0, (args, result.stderr))
                return result

            archives = []
            for root_version, dep_version, revision in (
                    ('0.1.0', '0.1.2', OLD_REV), ('0.2.0', '0.1.3', NEW_REV)):
                recipe = root / ('recipe-' + root_version)
                recipe.mkdir()
                (recipe / 'RECIPE.md').write_text(
                    '# Integration recipe\n\n```toml\nformat = "recipkg/1"\n'
                    '[package]\nname = "pin-integration"\nversion = "' + root_version + '"\n'
                    'kind = "software"\ndescription = "Git pin test"\nentry = "BUILD_PROMPT.md"\n'
                    '[dependencies.storage]\ngit = "https://github.com/recipkg/valkey.git"\n'
                    'rev = "' + revision + '"\n```\n', encoding='utf-8')
                (recipe / 'BUILD_PROMPT.md').write_text(
                    '# Integration\n\nUse storage as the data store and its quality contract.\n',
                    encoding='utf-8')
                archive = root / (root_version + '.recipe.tar.gz')
                ok('pack', recipe, '-o', archive)
                ok('check', archive, offline_mode=True)
                if root_version == '0.1.0':
                    repeated = root / 'repeated.recipe.tar.gz'
                    ok('pack', recipe, '-o', repeated)
                    self.assertEqual(archive.read_bytes(), repeated.read_bytes())
                with tarfile.open(archive, 'r:gz') as tar:
                    files = {entry.name: tar.extractfile(entry).read() for entry in tar.getmembers()
                             if entry.isfile()}
                dep = manifest(files['.deps/storage/RECIPE.md'].decode())
                self.assertEqual((dep['package']['name'], dep['package']['version']), ('valkey', dep_version))
                self.assertIn('.deps/storage/.deps/quality/BUILD_PROMPT.md', files)
                lock = manifest(files['LOCK.md'].decode())
                packages = {item['path']: item for item in lock['packages']}
                self.assertEqual(packages['.deps/storage']['rev'], revision)
                self.assertEqual(packages['.deps/storage/.deps/quality']['rev'], QUALITY_REV)
                document = files['.deps/storage/OBSERVED.md'].decode()
                self.assertEqual(NEW_MARKER in document, root_version == '0.2.0')
                archives.append((archive, document, revision))

            for archive, _, _ in archives:
                ok('install', archive, offline_mode=True)
            ambiguous = run('build', 'pin-integration', offline_mode=True)
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertEqual(ambiguous.stdout, '')
            for root_version, (archive, document, revision) in zip(('0.1.0', '0.2.0'), archives):
                result = ok('build', 'pin-integration@' + root_version, offline_mode=True)
                self.assertIn(document, result.stdout)
                self.assertIn(revision, result.stdout)
                self.assertEqual(NEW_MARKER in result.stdout, root_version == '0.2.0')


if __name__ == '__main__':
    unittest.main()
