"""Selected jq getpath behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqGetpathSamples(unittest.TestCase):
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

    def test_nested_and_missing_paths(self):
        cases = [
            ({'a': {'b': 2}}, ['a', 'b'], 2),
            ({'a': {}}, ['a', 'b'], None),
            ({'a': [10, 20]}, ['a', 1], 20),
            ({'a': [10, 20]}, ['a', -1], 20),
            ({'a': [10, 20]}, ['a', 9], None),
            ({'a': 1}, ['missing', 'nested'], None),
            (None, ['a', 0], None),
            ({'a': [10]}, ['a', 0.5], 10),
        ]
        for source, path, expected in cases:
            with self.subTest(source=source, path=path):
                result = self.run_filter(self.target, '. as $pair | $pair.value | getpath($pair.path)',
                                         {'value': source, 'path': path})
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_path_types(self):
        cases = [
            ({'a': 1}, 'a'),
            ({'a': 1}, ['a', 0]),
            ({'a': 1}, [None]),
            ([1], [None]),
        ]
        for source, path in cases:
            with self.subTest(source=source, path=path):
                result = self.run_filter(self.target, '. as $pair | $pair.value | getpath($pair.path)',
                                         {'value': source, 'path': path})
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_multiple_paths_from_comma_generator(self):
        source = {'a': {'b': 0, 'c': 1}}
        result = self.run_filter(self.target,
                                 '[getpath(["a","b"], ["a","c"])]', source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout), [0, 1])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315109)
        pairs = []
        for _ in range(100):
            source = {'root': {'items': [rng.randrange(-100, 101)
                                          for _ in range(rng.randrange(8))],
                               'label': rng.choice(['', 'a', 'é']),
                               'nothing': None}}
            path = rng.choice([
                ['root', 'items', rng.randrange(-10, 10)],
                ['root', 'nothing', 'child'],
                ['root', 'missing', 'child'],
                ['absent', 'child'],
            ])
            pairs.append({'value': source, 'path': path})
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in pairs)
        expression = '. as $pair | $pair.value | getpath($pair.path)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
