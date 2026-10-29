"""Selected jq numeric rounding filters against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest
from decimal import Decimal


class JqRoundingSamples(unittest.TestCase):
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

    def test_finite_rounding_values(self):
        cases = [
            ('[.[] | floor]', '[2.7,-2.7,0.5,-0.5]\n', '[2,-3,0,-1]\n'),
            ('[.[] | ceil]', '[2.7,-2.7,0.5,-0.5]\n', '[3,-2,1,-0]\n'),
            ('[.[] | round]', '[2.5,1.5,0.5,-0.5,-1.5,-2.5,0.49,-0.49]\n',
             '[3,2,1,-1,-2,-3,0,-0]\n'),
            ('[.[] | trunc]', '[2.7,-2.7,0.5,-0.5]\n', '[2,-2,0,-0]\n'),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(result.stdout, expected)

    def test_non_numbers_fail(self):
        for function in ('ceil', 'floor', 'round', 'trunc'):
            for source in ('null\n', 'true\n', '"2.5"\n', '[]\n', '{}\n'):
                with self.subTest(function=function, source=source):
                    result = self.run_filter(self.target, function, source)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('number required', result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(481903)
        values = [format(Decimal(rng.randrange(-100_000, 100_001)).scaleb(-1), 'f')
                  for _ in range(100)]
        data = '[' + ','.join(values) + ']\n'
        for function in ('ceil', 'floor', 'round', 'trunc'):
            with self.subTest(function=function):
                expression = f'[.[] | {function}]'
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(reference, expression, data)
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))
