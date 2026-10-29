"""Selected jq C math signatures and argument streams against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


PAIR_SAMPLES = {
    'atan2': [(1, 2), (-1, 2), (0.0, -0.0)],
    'copysign': [(-3, 2), (3, -2), (-0.0, -1)],
    'drem': [(5.3, 2), (-5.3, 2), (7, 2)],
    'fdim': [(2, 3), (3, 2), (-3, -5)],
    'fmax': [(2, 3), (-4, -2), (0, -1)],
    'fmin': [(2, 3), (-4, -2), (0, -1)],
    'fmod': [(5.3, 2), (-5.3, 2), (7, 2)],
    'hypot': [(3, 4), (-3, 4), (0, 0)],
    'jn': [(0, 1.5), (2, 1.5), (-1, 4), (2.9, 1.5)],
    'ldexp': [(1.5, 3), (-0.75, 5), (1, -3), (1.5, 3.9)],
    'nextafter': [(0, 1), (1, 0), (-0.0, -1)],
    'nexttoward': [(0, 1), (1, 0), (-0.0, -1)],
    'pow': [(2, 3), (2, -3), (-2, 3)],
    'remainder': [(5.3, 2), (-5.3, 2), (7, 2)],
    'scalb': [(1.5, 3), (-0.75, 5), (1, -3)],
    'scalbln': [(1.5, 3), (-0.75, 5), (1, -3), (1.5, 3.9)],
    'yn': [(0, 1.5), (2, 1.5), (-1, 4), (2.9, 1.5)],
}
TERNARY_SAMPLES = {
    'fma': [(1.1, 2.2, 3.3), (-2.5, 4, 1.25), (1, 0, -1)],
}
UNARY_INPUTS = [-12.5, -0.0, 0.0, 0.125, 3.75]
NON_NUMBERS = ('null\n', 'true\n', '"1"\n', '[]\n', '{}\n')


def seeded_pairs(function, rng):
    if function in {'atan2', 'copysign', 'fdim', 'fmax', 'fmin', 'hypot'}:
        return [(rng.uniform(-1e50, 1e50), rng.uniform(-1e50, 1e50))
                for _ in range(100)]
    if function in {'drem', 'fmod', 'remainder'}:
        return [(rng.uniform(-1e50, 1e50), rng.choice((-1, 1)) *
                 rng.uniform(0.1, 1e3)) for _ in range(100)]
    if function in {'jn', 'yn'}:
        low, high = (0.1, 100) if function == 'yn' else (-100, 100)
        return [(rng.randint(-8, 8), rng.uniform(low, high))
                for _ in range(100)]
    if function in {'ldexp', 'scalb', 'scalbln'}:
        return [(rng.uniform(-10, 10), rng.randint(-50, 50))
                for _ in range(100)]
    if function in {'nextafter', 'nexttoward'}:
        return [(rng.uniform(-1e100, 1e100), rng.uniform(-1e100, 1e100))
                for _ in range(100)]
    if function == 'pow':
        return [(rng.uniform(0.01, 100), rng.uniform(-10, 10))
                for _ in range(100)]
    raise AssertionError(f'no pair generator for {function}')


class JqMathMultiSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, data='null\n'):
        return subprocess.run([executable, '-c', expression], input=data,
                              capture_output=True, text=True, timeout=10)

    def reference(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        return reference

    def assert_matches(self, expression, data):
        reference = self.reference()
        actual = self.run_filter(self.target, expression, data)
        expected = self.run_filter(reference, expression, data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))

    def test_frexp_and_modf_return_the_c_out_parameter(self):
        data = json.dumps(UNARY_INPUTS) + '\n'
        for function in ('frexp', 'modf'):
            with self.subTest(function=function):
                self.assert_matches(f'[.[] | {function}]', data)

    def test_binary_and_ternary_math_samples(self):
        cases_by_function = {**PAIR_SAMPLES, **TERNARY_SAMPLES}
        for function, cases in cases_by_function.items():
            data = json.dumps(cases) + '\n'
            arguments = '; '.join(f'.[{index}]'
                                  for index in range(len(cases[0])))
            expression = f'[.[] | {function}({arguments})]'
            with self.subTest(function=function):
                self.assert_matches(expression, data)

    def test_zero_domain_and_signed_zero_boundaries(self):
        expression = ('[(1 | frexp), (0 | frexp), (-0.0 | frexp),'
                      '(3.25 | modf), (-0.0 | modf), fdim(2;3),'
                      'nextafter(0;1), nexttoward(0;-1), fmod(1;0),'
                      'drem(1;0), remainder(1;0), pow(-1;0.5)]')
        self.assert_matches(expression, 'null\n')

    def test_seeded_binary_and_ternary_differential(self):
        reference = self.reference()
        rng = random.Random(902107)
        cases_by_function = {
            function: seeded_pairs(function, rng) for function in PAIR_SAMPLES
        }
        cases_by_function['fma'] = [
            (rng.uniform(-1e50, 1e50), rng.uniform(-1e50, 1e50),
             rng.uniform(-1e50, 1e50)) for _ in range(100)
        ]

        for function, cases in cases_by_function.items():
            data = json.dumps(cases) + '\n'
            arguments = '; '.join(f'.[{index}]'
                                  for index in range(len(cases[0])))
            expression = f'[.[] | {function}({arguments})]'
            with self.subTest(function=function):
                actual = self.run_filter(self.target, expression, data)
                expected = self.run_filter(reference, expression, data)
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual(json.loads(actual.stdout),
                                 json.loads(expected.stdout))

    def test_argument_generators_keep_jq_order(self):
        expression = '[pow((1,2);(3,4)), fma((1,2);(3,4);(5,6))]'
        self.assert_matches(expression, 'null\n')
        actual = self.run_filter(self.target, expression)
        self.assertEqual(json.loads(actual.stdout),
                         [1, 8, 1, 16, 8, 11, 9, 13, 9, 12, 10, 14])
        empty = self.run_filter(self.target, 'pow(empty;2)')
        self.assertEqual((empty.returncode, empty.stdout, empty.stderr), (0, '', ''))

    def test_non_numbers_fail_in_each_argument_position(self):
        reference = self.reference()
        arities = {function: 2 for function in PAIR_SAMPLES}
        arities.update({function: 3 for function in TERNARY_SAMPLES})
        for function, arity in arities.items():
            for bad_index in range(arity):
                arguments = ['1'] * arity
                arguments[bad_index] = '"x"'
                expression = f'{function}(' + ';'.join(arguments) + ')'
                with self.subTest(function=function, bad_index=bad_index):
                    result = self.run_filter(self.target, expression)
                    expected = self.run_filter(reference, expression)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotEqual(expected.returncode, 0)
                    self.assertIn('number required', result.stderr)
                    self.assertIn('number required', expected.stderr)

        for function in ('frexp', 'modf'):
            for source in NON_NUMBERS:
                with self.subTest(function=function, source=source):
                    result = self.run_filter(self.target, function, source)
                    expected = self.run_filter(reference, function, source)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotEqual(expected.returncode, 0)
                    self.assertIn('number required', result.stderr)
                    self.assertIn('number required', expected.stderr)


if __name__ == '__main__':
    unittest.main()
