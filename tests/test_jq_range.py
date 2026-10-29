"""Selected jq range generator behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqRangeSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, data):
        return subprocess.run([executable, '-c', expression], input=data,
                              capture_output=True, text=True, timeout=10)

    def test_common_ranges(self):
        cases = [
            ('[range(4)]', None, [0, 1, 2, 3]),
            ('[range(2; 6)]', None, [2, 3, 4, 5]),
            ('[range(0; 10; 3)]', None, [0, 3, 6, 9]),
            ('[range(4; 0; -2)]', None, [4, 2]),
            ('[range(4; 0)]', None, []),
            ('[range(0; 4; -1)]', None, []),
            ('[range(0; 4; 0)]', None, []),
            ('[range(3.5)]', None, [0, 1, 2, 3]),
            ('[range(0.5; 3.5; 1)]', None, [0.5, 1.5, 2.5]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression,
                                         'null\n' if source is None else json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_arguments(self):
        for expression in ['range("x")', 'range(0; null)', 'range(0; 4; "step")']:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, 'null\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315106)
        values = [{'start': rng.randrange(-10, 11),
                   'stop': rng.randrange(-10, 11),
                   'step': rng.randrange(-4, 5)} for _ in range(100)]
        data = ''.join(json.dumps(value) + '\n' for value in values)
        expression = '[range(.start; .stop; .step)]'
        actual = self.run_filter(self.target, expression, data)
        expected = self.run_filter(reference, expression, data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
