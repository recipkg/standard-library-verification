"""Selected jq delpaths simultaneous deletion samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqDelpathsSamples(unittest.TestCase):
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

    expression = '. as $arg | $arg.value | delpaths($arg.paths)'

    def test_object_and_nested_deletions(self):
        cases = [
            ({'a': 1, 'b': 2}, [['a'], ['b']], {}),
            ({'a': {'b': 1, 'c': 2}, 'z': 3}, [['a', 'b'], ['a', 'c']],
             {'a': {}, 'z': 3}),
            ({'a': {'b': 1}}, [['missing', 'b']], {'a': {'b': 1}}),
            ({'a': {'b': 1}}, [['a'], ['a', 'b']], {}),
            ({'a': 1}, [[]], None),
            (None, [['a']], None),
        ]
        for value, paths, expected in cases:
            with self.subTest(value=value, paths=paths):
                result = self.run_filter(self.target, self.expression,
                                         {'value': value, 'paths': paths})
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_simultaneous_array_deletions(self):
        cases = [
            ([0, 1, 2, 3], [[0], [2]], [1, 3]),
            ([0, 1, 2, 3], [[2], [0]], [1, 3]),
            ([0, 1, 2], [[1], [1]], [0, 2]),
            ([0, 1, 2], [[1.5]], [0, 2]),
            ([0, 1, 2], [[8]], [0, 1, 2]),
            ([0, 1, 2], [[-1]], [0, 1]),
            ([0, 1, 2], [[-4]], [0, 1, 2]),
            ([[1, 2], [3, 4]], [[0, 1], [1, 0]], [[1], [4]]),
        ]
        for value, paths, expected in cases:
            with self.subTest(value=value, paths=paths):
                result = self.run_filter(self.target, self.expression,
                                         {'value': value, 'paths': paths})
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_path_shapes_and_containers(self):
        cases = [
            ({'a': 1}, ['a']),
            ({'a': 1}, [1]),
            ({'a': 1}, [[1]]),
            ({'a': 1}, [['a', 0]]),
            (1, [['a']]),
            ('x', [[0]]),
        ]
        for value, paths in cases:
            with self.subTest(value=value, paths=paths):
                result = self.run_filter(self.target, self.expression,
                                         {'value': value, 'paths': paths})
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315112)
        cases = []
        for _ in range(100):
            value = {'root': {'items': [rng.randrange(100) for _ in range(rng.randrange(1, 8))],
                              'a': rng.randrange(100), 'b': rng.randrange(100)}}
            items = value['root']['items']
            paths = rng.sample([['root', 'a'], ['root', 'b']], rng.randrange(3))
            indices = list(range(len(items)))
            chosen = rng.sample(indices, rng.randrange(len(indices) + 1))
            paths.extend([['root', 'items', index] for index in chosen])
            cases.append({'value': value, 'paths': paths})
        data = ''.join(json.dumps(item) + '\n' for item in cases)
        expression = '. as $arg | $arg.value | delpaths($arg.paths)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
