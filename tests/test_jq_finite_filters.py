"""Selected jq finiteness and normal-number filters."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqFiniteFilterSamples(unittest.TestCase):
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

    def test_finite_and_normal_boundaries(self):
        data = ('[null,false,true,-1,0,1,1e-320,'
                '2.2250738585072014e-308,1e-307,1e308,"x",[],{}]\n')
        cases = {
            '[.[] | finites]': [-1, 0, 1, 1e-320, 2.2250738585072014e-308,
                                1e-307, 1e308],
            '[.[] | normals]': [-1, 1, 2.2250738585072014e-308, 1e-307, 1e308],
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, data)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_nan_infinity_and_non_number_inputs(self):
        cases = [
            ('finites', 'NaN\n', 'null\n'),
            ('normals', 'NaN\n', ''),
            ('finites', 'Infinity\n', ''),
            ('normals', 'Infinity\n', ''),
            ('finites', '-Infinity\n', ''),
            ('normals', '-Infinity\n', ''),
            ('type', 'NaN\n', '"number"\n'),
            ('type', 'Infinity\n', '"number"\n'),
            ('1e400 | finites', ''),
            ('1e400 | normals', ''),
        ]
        for case in cases:
            if len(case) == 3:
                expression, input_text, expected_stdout = case
            else:
                expression, expected_stdout = case
                input_text = 'null\n'
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, input_text)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, expected_stdout, ''))

        for expression in ('finites', 'normals'):
            result = self.run_filter(self.target, expression,
                                     '[null,false,true,"x",[],{}]\n')
            with self.subTest(expression=expression, source='non-numbers'):
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, '', ''))

    def test_numeric_filters_reject_arguments(self):
        for expression in ('finites(1)', 'normals(false)'):
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, '1\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315107)
        values = [0.0, -0.0, 1.0, -1.0, 1e-320,
                  2.2250738585072014e-308, 1e-307, 1e308]
        values.extend(rng.uniform(-1e250, 1e250) for _ in range(100))
        values.extend([None, False, True, '', 'x', [], {}])
        data = ''.join(json.dumps(value) + '\n' for value in values)
        for expression in ('finites', 'normals'):
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
