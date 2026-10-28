"""Run the tool sample with an explicitly selected candidate environment."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class OpenHandsToolSamples(unittest.TestCase):
    def test_editor_and_terminal(self):
        selected = os.environ.get('RECIPKG_TEST_OPENHANDS_TOOLS_PYTHON')
        if not selected:
            self.skipTest('set RECIPKG_TEST_OPENHANDS_TOOLS_PYTHON to a Python with candidate tools')
        executable = shutil.which(selected)
        if not executable:
            self.fail('RECIPKG_TEST_OPENHANDS_TOOLS_PYTHON executable not found')
        probes = ('openhands_tools_probe.py', 'openhands_tools_agent_probe.py')
        with tempfile.TemporaryDirectory(prefix='recipkg-tools-runner-') as tmp:
            env = {'HOME': tmp, 'PATH': os.defpath, 'LANG': 'C.UTF-8', 'TMPDIR': tmp,
                   'OPENHANDS_SUPPRESS_BANNER': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
                   'LITELLM_TELEMETRY': 'False'}
            for filename in probes:
                with self.subTest(probe=filename):
                    probe = Path(__file__).with_name(filename).resolve()
                    result = subprocess.run([executable, str(probe)], cwd=tmp, env=env,
                                            capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
                    self.assertIn('fixture passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
