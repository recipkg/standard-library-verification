"""Selected jq single-argument math behavior against explicit executables."""
import json
import math
import os
import random
import shutil
import subprocess
import unittest


SAMPLES = {
    'acos': [-1, -0.5, 0, 0.5, 1],
    'acosh': [1, 1.25, 2, 10],
    'asin': [-1, -0.5, 0, 0.5, 1],
    'asinh': [-10, -1, 0, 1, 10],
    'atan': [-10, -1, 0, 1, 10],
    'atanh': [-0.9, -0.5, 0, 0.5, 0.9],
    'cbrt': [-1000, -8, -1, 0, 1, 8, 1000],
    'cos': [-3, -1, 0, 1, 3],
    'cosh': [-5, -1, 0, 1, 5],
    'erf': [-3, -1, 0, 1, 3],
    'erfc': [-3, -1, 0, 1, 3],
    'exp': [-5, -1, 0, 1, 5],
    'exp10': [-5, -1, 0, 1, 5],
    'exp2': [-5, -1, 0, 1, 5],
    'expm1': [-5, -1, 0, 1, 5],
    'fabs': [-10, -0.5, 0, 0.5, 10],
    'gamma': [0.5, 1, 2, 5, 10],
    'lgamma': [0.5, 1, 2, 5, 10],
    'log': [0.001, 0.1, 1, 10, 1000],
    'log10': [0.001, 0.1, 1, 10, 1000],
    'log1p': [-0.99, -0.5, 0, 0.5, 10],
    'log2': [0.001, 0.1, 1, 10, 1000],
    'logb': [-10, -0.75, 0.25, 1, 8],
    'nearbyint': [-2.5, -1.5, -0.5, -0.1, 0, 0.1, 0.5, 1.5, 2.5],
    'rint': [-2.5, -1.5, -0.5, -0.1, 0, 0.1, 0.5, 1.5, 2.5],
    'significand': [-12, -1, -0.5, 0, 0.5, 12],
    'sin': [-3, -1, 0, 1, 3],
    'sinh': [-5, -1, 0, 1, 5],
    'sqrt': [0, 0.1, 1, 2, 100],
    'tan': [-1, -0.5, 0, 0.5, 1],
    'tanh': [-5, -1, 0, 1, 5],
    'tgamma': [0.5, 1, 2, 5, 10],
}

GAMMA_FUNCTIONS = {'gamma', 'lgamma', 'tgamma'}
NON_NUMBERS = ('null\n', 'true\n', '"1"\n', '[]\n', '{}\n')


def seeded_values(function, rng):
    if function in {'acos', 'asin'}:
        return [rng.uniform(-1, 1) for _ in range(100)]
    if function == 'acosh':
        return [rng.uniform(1, 50) for _ in range(100)]
    if function == 'atanh':
        return [rng.uniform(-0.999999, 0.999999) for _ in range(100)]
    if function in {'log', 'log10', 'log2'}:
        return [10 ** rng.uniform(-30, 30) for _ in range(100)]
    if function == 'log1p':
        return [rng.uniform(-0.999999, 100) for _ in range(100)]
    if function in GAMMA_FUNCTIONS:
        return [rng.uniform(0.1, 20) for _ in range(100)]
    if function in {'exp', 'expm1'}:
        return [rng.uniform(-100, 100) for _ in range(100)]
    if function == 'exp10':
        return [rng.uniform(-100, 100) for _ in range(100)]
    if function == 'exp2':
        return [rng.uniform(-1000, 1000) for _ in range(100)]
    if function in {'cosh', 'sinh'}:
        return [rng.uniform(-700, 700) for _ in range(100)]
    if function in {'sin', 'cos', 'tan'}:
        return [rng.uniform(-1.2, 1.2) for _ in range(100)]
    if function in {'sqrt'}:
        return [rng.uniform(0, 1000) for _ in range(100)]
    if function in {'nearbyint', 'rint'}:
        return [rng.uniform(-10000, 10000) for _ in range(100)]
    if function == 'erf' or function == 'erfc':
        return [rng.uniform(-10, 10) for _ in range(100)]
    if function == 'cbrt':
        return [rng.uniform(-1e6, 1e6) for _ in range(100)]
    if function in {'logb', 'significand'}:
        values = [rng.uniform(-1e100, 1e100) for _ in range(99)]
        values.append(rng.choice([-1, 1]) * 2.0 ** rng.randrange(-900, 900))
        return values
    if function == 'fabs':
        return [rng.uniform(-1e100, 1e100) for _ in range(100)]
    if function == 'tanh':
        return [rng.uniform(-50, 50) for _ in range(100)]
    if function in {'asinh', 'atan'}:
        return [rng.uniform(-1e6, 1e6) for _ in range(100)]
    raise AssertionError(f'no generator for {function}')


class JqMathSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, data):
        return subprocess.run([executable, '-c', expression], input=data,
                              capture_output=True, text=True, timeout=10)

    def test_finite_samples_match_reference(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))

        for function, values in SAMPLES.items():
            data = json.dumps(values) + '\n'
            expression = f'[.[] | {function}]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(reference, expression, data)
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                actual_values = json.loads(actual.stdout)
                expected_values = json.loads(expected.stdout)
                self.assertEqual(len(actual_values), len(expected_values))
                for got, want in zip(actual_values, expected_values):
                    if function in GAMMA_FUNCTIONS:
                        self.assertTrue(math.isclose(got, want, rel_tol=5e-15,
                                                     abs_tol=1e-15),
                                        (function, got, want))
                    else:
                        self.assertEqual(got, want, (function, got, want))

    def test_non_numbers_fail(self):
        for function in SAMPLES:
            for source in NON_NUMBERS:
                with self.subTest(function=function, source=source):
                    result = self.run_filter(self.target, function, source)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('number required', result.stderr)

    def test_domain_singular_and_overflow_outputs(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        expression = ('[(2|acos),(0.5|acosh),(2|asin),(-1|sqrt),'
                      '(1|atanh),(-1|atanh),(0|log),(0|log10),(0|log2),'
                      '(-1|log1p),(0|logb),(1000|exp),(2000|exp2),'
                      '(1000|expm1),(1000|cosh),(-1000|sinh),'
                      '(0|gamma),(0|lgamma),(0|tgamma),'
                      '(-0.1|nearbyint),(-0.5|rint),(-0.0|significand)]')
        actual = self.run_filter(self.target, expression, 'null\n')
        expected = self.run_filter(reference, expression, 'null\n')
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual(actual.stdout, expected.stdout)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(902106)

        for function in SAMPLES:
            values = seeded_values(function, rng)
            data = json.dumps(values) + '\n'
            expression = f'[.[] | {function}]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(reference, expression, data)
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                actual_values = json.loads(actual.stdout)
                expected_values = json.loads(expected.stdout)
                self.assertEqual(len(actual_values), 100)
                self.assertEqual(len(expected_values), 100)
                for got, want in zip(actual_values, expected_values):
                    if function in GAMMA_FUNCTIONS:
                        self.assertTrue(math.isclose(got, want, rel_tol=5e-15,
                                                     abs_tol=1e-15),
                                        (function, got, want))
                    else:
                        self.assertEqual(got, want, (function, got, want))


if __name__ == '__main__':
    unittest.main()
