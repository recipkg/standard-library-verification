"""Selected jq type filters against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqTypeFilterSamples(unittest.TestCase):
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

    def test_selects_values_by_json_type(self):
        source = [None, False, True, 0, 1.5, '', 'x', [], [None], {}, {'x': 1}]
        cases = {
            'arrays': [[], [None]],
            'objects': [{}, {'x': 1}],
            'iterables': [[], [None], {}, {'x': 1}],
            'booleans': [False, True],
            'numbers': [0, 1.5],
            'strings': ['', 'x'],
            'nulls': [None],
            'values': [False, True, 0, 1.5, '', 'x', [], [None], {}, {'x': 1}],
            'scalars': [None, False, True, 0, 1.5, '', 'x'],
        }
        data = json.dumps(source) + '\n'
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, f'[.[] | {expression}]', data)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_empty_results_and_null_boolean_distinction(self):
        for expression, source in [('1 | arrays', '1'),
                                   ('null | values', 'null'),
                                   ('[] | objects', '[]')]:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source + '\n')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, '', ''))

        result = self.run_filter(self.target, 'values', 'null\nfalse\n0\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()],
                         [False, 0])

    def test_type_filters_reject_arguments(self):
        for expression in ('arrays(true)', 'values(0)'):
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, '[]\n')
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

        rng = random.Random(315106)
        atoms = [None, False, True, -3, 0, 4, '', 'x']

        def value(depth=0):
            if depth >= 3:
                return rng.choice(atoms)
            kind = rng.randrange(4)
            if kind == 0:
                return [value(depth + 1) for _ in range(rng.randrange(5))]
            if kind == 1:
                return {f'k{i}': value(depth + 1)
                        for i in range(rng.randrange(5))}
            return rng.choice(atoms)

        data = ''.join(json.dumps(value()) + '\n' for _ in range(100))
        for expression in ('arrays', 'objects', 'iterables', 'booleans',
                           'numbers', 'strings', 'nulls', 'values', 'scalars'):
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
