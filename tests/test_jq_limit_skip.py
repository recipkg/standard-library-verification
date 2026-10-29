"""Selected jq limit and skip behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqLimitSkipSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, source):
        return subprocess.run([executable, '-c', expression],
                              input=json.dumps(source, ensure_ascii=False) + '\n',
                              capture_output=True, text=True, timeout=10)

    def test_limit_count_boundaries_and_infinite_recurse(self):
        cases = [
            ('[limit(2; range(0; 5))]', None, [0, 1]),
            ('[limit(1.5; range(0; 5))]', None, [0, 1]),
            ('[limit(0; range(0; 5))]', None, []),
            ('[limit(empty; range(0; 5))]', None, []),
            ('[limit(1, 2; range(0; 3))]', None, [0, 0, 1]),
            ('[limit(5; recurse(. + 1))]', 0, [0, 1, 2, 3, 4]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_skip_count_boundaries_and_infinite_recurse(self):
        cases = [
            ('[skip(2; range(0; 5))]', None, [2, 3, 4]),
            ('[skip(1.5; range(0; 5))]', None, [1, 2, 3, 4]),
            ('[skip(0.5; range(0; 5))]', None, [0, 1, 2, 3, 4]),
            ('[skip(3; range(0; 2))]', None, []),
            ('[skip(1, 2; range(0; 5))]', None, [1, 2, 3, 4, 2, 3, 4]),
            ('[limit(3; skip(3; recurse(. + 1)))]', 0, [3, 4, 5]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_counts_fail(self):
        for expression in ('limit(-1; range(0; 3))', 'skip(-1; range(0; 3))',
                           'limit("2"; range(0; 3))', 'skip(false; range(0; 3))'):
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, None)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(652941)
        cases = [{'items': [rng.randrange(-50, 51) for _ in range(rng.randrange(9))],
                  'count': rng.choice([0, 0.2, 1, 1.5, 4, 8])}
                 for _ in range(100)]
        data = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in cases)
        expression = ('. as $arg | {limited: [limit($arg.count; $arg.items[])], '
                      'skipped: [skip($arg.count; $arg.items[])]}')
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
