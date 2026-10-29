"""Selected jq Bessel math filters against explicit executables."""
import json
import math
import os
import random
import shutil
import subprocess
import unittest


SAMPLES = {
    'j0': [-1e6, -100, -20, -5, -2, -1, -0.5, -0.1, 0,
           0.1, 0.5, 1, 2, 5, 20, 100, 1e6],
    'j1': [-1e6, -100, -20, -5, -2, -1, -0.5, -0.1, 0,
           0.1, 0.5, 1, 2, 5, 20, 100, 1e6],
    'y0': [1e-300, 1e-100, 1e-10, 0.1, 0.5, 1, 2, 5, 20, 100, 1e100, 1e300],
    'y1': [1e-300, 1e-100, 1e-10, 0.1, 0.5, 1, 2, 5, 20, 100, 1e100, 1e300],
}
FUNCTIONS = tuple(SAMPLES)
NON_NUMBERS = ('null\n', 'true\n', '"1"\n', '[]\n', '{}\n')


class JqBesselMathSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        cls.reference = shutil.which(reference)
        if not cls.reference:
            raise RuntimeError(f'jq reference not found: {reference}')
        if os.path.realpath(cls.reference) == os.path.realpath(cls.target):
            raise RuntimeError('candidate and reference must be different executables')

    def run_filter(self, executable, expression, data='null\n'):
        return subprocess.run([executable, '-c', expression], input=data,
                              capture_output=True, text=True, timeout=10)

    def assert_numeric_streams_close(self, actual, expected, function):
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        actual_values = json.loads(actual.stdout)
        expected_values = json.loads(expected.stdout)
        self.assertEqual(len(actual_values), len(expected_values))
        for got, want in zip(actual_values, expected_values):
            self.assertTrue(math.isclose(got, want, rel_tol=5e-14, abs_tol=1e-15),
                            (function, got, want))

    def test_finite_samples_match_reference(self):
        for function, values in SAMPLES.items():
            data = json.dumps(values) + '\n'
            expression = f'[.[] | {function}]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(self.reference, expression, data)
                self.assert_numeric_streams_close(actual, expected, function)

    def test_domain_zero_and_signed_zero_outputs(self):
        expression = ('[(0|j0),(0|j1),(-0.0|j0),(-0.0|j1),'
                      '(0|y0),(0|y1),(-1|y0),(-1|y1)]')
        actual = self.run_filter(self.target, expression)
        expected = self.run_filter(self.reference, expression)
        self.assertEqual((actual.returncode, actual.stderr, actual.stdout),
                         (expected.returncode, expected.stderr, expected.stdout))

    def test_non_numbers_fail(self):
        for function in FUNCTIONS:
            for source in NON_NUMBERS:
                with self.subTest(function=function, source=source):
                    result = self.run_filter(self.target, function, source)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('number required', result.stderr)

    def test_seeded_differential(self):
        rng = random.Random(20261030)
        for function in ('j0', 'j1'):
            values = [rng.uniform(-1e6, 1e6) for _ in range(100)]
            data = json.dumps(values) + '\n'
            expression = f'[.[] | {function}]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(self.reference, expression, data)
                self.assert_numeric_streams_close(actual, expected, function)
        for function in ('y0', 'y1'):
            values = [10 ** rng.uniform(-200, 200) for _ in range(100)]
            data = json.dumps(values) + '\n'
            expression = f'[.[] | {function}]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(self.reference, expression, data)
                self.assert_numeric_streams_close(actual, expected, function)


if __name__ == '__main__':
    unittest.main()
