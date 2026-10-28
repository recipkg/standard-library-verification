"""Check that target-selection mistakes cannot produce a passing skip."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


class TargetSelection(unittest.TestCase):
    def run_class(self, name, extra_env):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('RECIPKG_TEST_')}
        env.update(extra_env)
        return subprocess.run([sys.executable, '-m', 'unittest', '-q', 'test_recipes.' + name],
                              cwd=Path(__file__).parent, env=env, text=True,
                              capture_output=True, timeout=30)

    def test_explicit_missing_executables_fail(self):
        cases = [
            ('JqSamples', {'RECIPKG_TEST_JQ': '/nonexistent/recipkg-jq'}),
            ('JqSamples', {'RECIPKG_TEST_JQ': ''}),
            ('RipgrepSamples', {'RECIPKG_TEST_RG': '/nonexistent/recipkg-rg'}),
            ('RipgrepSamples', {'RECIPKG_TEST_RG': sys.executable,
                                'RECIPKG_TEST_GIT': '/nonexistent/recipkg-git'}),
            ('RipgrepSamples', {'RECIPKG_TEST_RG': sys.executable, 'PATH': ''}),
            ('FFmpegSamples', {'RECIPKG_TEST_FFMPEG': sys.executable,
                               'RECIPKG_TEST_FFPROBE': '/nonexistent/recipkg-ffprobe'}),
        ]
        for name, env in cases:
            with self.subTest(name=name, env=env):
                result = self.run_class(name, env)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('required executable not found', result.stderr)
                self.assertNotIn('skipped=', result.stderr)

    def test_ffmpeg_candidate_requires_both_programs(self):
        for variable in ('RECIPKG_TEST_FFMPEG', 'RECIPKG_TEST_FFPROBE'):
            with self.subTest(variable=variable):
                result = self.run_class('FFmpegSamples', {variable: sys.executable})
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('set both RECIPKG_TEST_FFMPEG and RECIPKG_TEST_FFPROBE', result.stderr)

    def test_missing_default_is_reported_as_skipped(self):
        result = self.run_class('JqSamples', {'PATH': ''})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('skipped=1', result.stderr)


if __name__ == '__main__':
    unittest.main()
