"""Selected jq length and flatten behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqArrayValueSamples(unittest.TestCase):
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

    def test_length_known_values(self):
        values = [None, '', 'é🙂', [], [1, 2], {}, {'a': 1, 'b': 2}, -1.25, 0]
        expected = [0, 0, 2, 0, 2, 0, 2, 1.25, 0]
        result = self.run_filter(self.target, 'map(length)',
                                 json.dumps(values, ensure_ascii=False) + '\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout), expected)

    def test_length_boolean_error(self):
        for value in [True, False]:
            with self.subTest(value=value):
                result = self.run_filter(self.target, 'length',
                                         json.dumps(value) + '\n')
                self.assertEqual(result.returncode, 5)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr)

    def test_flatten_depth_and_error_boundaries(self):
        cases = [
            ('flatten', [1, [2, [3]], [], [4, []]], [1, 2, 3, 4]),
            ('flatten(0)', [1, [2, [3]], []], [1, [2, [3]], []]),
            ('flatten(1)', [1, [2, [3]], []], [1, 2, [3]]),
            ('flatten(2)', [1, [2, [3]], []], [1, 2, 3]),
            ('flatten', [{'x': [1]}, [[{'y': 2}]]], [{'x': [1]}, {'y': 2}]),
            ('flatten', {'a': [1, [2]], 'b': 3}, [1, 2, 3]),
            ('flatten', {}, []),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

        for expression, source in [('flatten', None), ('flatten', 3),
                                   ('flatten', 'x'),
                                   ('flatten(-1)', [1])]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual(result.returncode, 5)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315102)
        atoms = [None, False, True, -2, 0, 3, '', 'é', {'x': 1}]

        def nested(depth=0):
            if depth >= 4 or rng.randrange(3) == 0:
                return rng.choice(atoms)
            return [nested(depth + 1) for _ in range(rng.randrange(5))]

        values = [[nested() for _ in range(rng.randrange(6))] for _ in range(80)]
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in values)
        expression = '[flatten, flatten(0), flatten(1), flatten(2), flatten(3), flatten(4)]'
        actual = self.run_filter(self.target, expression, data)
        expected = self.run_filter(reference, expression, data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])

        values = [None, '', 'é🙂', [], [1, 2], {}, {'a': 1, 'b': 2}, -1.25, 0]
        data = json.dumps(values, ensure_ascii=False) + '\n'
        actual = self.run_filter(self.target, 'map(length)', data)
        expected = self.run_filter(reference, 'map(length)', data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))
