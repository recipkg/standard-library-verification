"""Selected jq path and recursive paths generator samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqPathSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, value):
        return subprocess.run([executable, '-c', expression],
                              input=json.dumps(value, ensure_ascii=False) + '\n',
                              capture_output=True, text=True, timeout=10)

    def test_exact_paths(self):
        cases = [
            ('path(.a.b)', {'a': {'b': 1}}, ['a', 'b']),
            ('path(.a.b)', {}, ['a', 'b']),
            ('path(.a.b)', None, ['a', 'b']),
            ('[path(.a[])]', {'a': [10, 20]}, [['a', 0], ['a', 1]]),
            ('[path(.a[])]', {'a': []}, []),
            ('[path(.a[0]), path(.a[-1])]', {'a': [10, 20]},
             [['a', 0], ['a', -1]]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_recursive_paths(self):
        cases = [
            (None, []),
            (1, []),
            ({}, []),
            ([[]], [[0]]),
            ({'a': [1, {}]}, [['a'], ['a', 0], ['a', 1]]),
            ({'x': {'y': 2}, 'z': 3}, [['x'], ['x', 'y'], ['z']]),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, '[paths]', source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        source = {'a': [1, {'b': 2}], 'c': True}
        result = self.run_filter(self.target, '[paths(type == "number")]', source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout), [['a', 0], ['a', 1, 'b']])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315111)
        atoms = [None, False, True, -3, 0, 8, '', 'é']
        def value(depth=0):
            if depth >= 3 or rng.randrange(3) == 0:
                return rng.choice(atoms)
            if rng.randrange(2):
                return [value(depth + 1) for _ in range(rng.randrange(5))]
            return {f'k{i}': value(depth + 1) for i in range(rng.randrange(5))}
        values = [value() for _ in range(100)]
        data = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in values)
        for expression in ('[paths]', '[paths | select(length > 1)]'):
            actual = subprocess.run([self.target, '-c', expression], input=data,
                                    capture_output=True, text=True, timeout=10)
            expected = subprocess.run([reference, '-c', expression], input=data,
                                      capture_output=True, text=True, timeout=10)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
