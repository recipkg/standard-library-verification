"""Run the SDK sample using an explicitly selected Python environment."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class OpenHandsSDKSamples(unittest.TestCase):
    def test_conversation_tool_and_restore(self):
        selected = os.environ.get('RECIPKG_TEST_OPENHANDS_PYTHON')
        if not selected:
            self.skipTest('set RECIPKG_TEST_OPENHANDS_PYTHON to a Python with the candidate SDK')
        executable = shutil.which(selected)
        if not executable:
            self.fail('RECIPKG_TEST_OPENHANDS_PYTHON executable not found')
        probe = Path(__file__).with_name('openhands_sdk_probe.py').resolve()
        with tempfile.TemporaryDirectory(prefix='recipkg-sdk-runner-') as tmp:
            env = {'HOME': tmp, 'PATH': os.defpath, 'LANG': 'C.UTF-8',
                   'TMPDIR': tmp, 'OPENHANDS_SUPPRESS_BANNER': '1',
                   'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'LITELLM_TELEMETRY': 'False'}
            result = subprocess.run([executable, str(probe)], cwd=tmp, env=env,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
        self.assertIn('sdk conversation fixture: valid, invalid, confirmation, rejection, and restore passed', result.stdout)

    def test_project_skill_loading(self):
        selected = os.environ.get('RECIPKG_TEST_OPENHANDS_PYTHON')
        if not selected:
            self.skipTest('set RECIPKG_TEST_OPENHANDS_PYTHON to a Python with the candidate SDK')
        executable = shutil.which(selected)
        if not executable:
            self.fail('RECIPKG_TEST_OPENHANDS_PYTHON executable not found')
        probe = Path(__file__).with_name('openhands_skills_probe.py').resolve()
        with tempfile.TemporaryDirectory(prefix='recipkg-sdk-runner-') as tmp:
            env = {'HOME': tmp, 'PATH': os.defpath, 'LANG': 'C.UTF-8', 'TMPDIR': tmp,
                   'OPENHANDS_SUPPRESS_BANNER': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
                   'LITELLM_TELEMETRY': 'False', 'GIT_CONFIG_NOSYSTEM': '1'}
            result = subprocess.run([executable, str(probe)], cwd=tmp, env=env,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
        self.assertIn('sdk project skill fixture: submodule, precedence, disclosure, disable and flag passed', result.stdout)

    def test_model_invokes_project_skill(self):
        selected = os.environ.get('RECIPKG_TEST_OPENHANDS_PYTHON')
        if not selected:
            self.skipTest('set RECIPKG_TEST_OPENHANDS_PYTHON to a Python with the candidate SDK')
        executable = shutil.which(selected)
        if not executable:
            self.fail('RECIPKG_TEST_OPENHANDS_PYTHON executable not found')
        probe = Path(__file__).with_name('openhands_skill_agent_probe.py').resolve()
        with tempfile.TemporaryDirectory(prefix='recipkg-sdk-runner-') as tmp:
            env = {'HOME': tmp, 'PATH': os.defpath, 'LANG': 'C.UTF-8', 'TMPDIR': tmp,
                   'OPENHANDS_SUPPRESS_BANNER': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
                   'LITELLM_TELEMETRY': 'False'}
            result = subprocess.run([executable, str(probe)], cwd=tmp, env=env,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
        self.assertIn('sdk model skill fixture: disclosure, repeated invocation, unknown and disabled passed',
                      result.stdout)


if __name__ == '__main__':
    unittest.main()
