"""Selected jq setpath behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqSetpathSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, expression, source):
        return subprocess.run([self.target, '-c', expression],
                              input=json.dumps(source, ensure_ascii=False) + '\n',
                              capture_output=True, text=True, timeout=10)

    def test_object_array_creation_and_replacement(self):
        cases = [
            (None, ['a', 'b'], 1, {'a': {'b': 1}}),
            (None, [0, 'a'], 1, [{'a': 1}]),
            ([], [2], 'x', [None, None, 'x']),
            ([10, 20], [-1], 99, [10, 99]),
            ({'a': 1}, [], {'z': 2}, {'z': 2}),
            (None, [], 1, 1),
            ({'a': {'items': [1]}}, ['a', 'items', 3], 9,
             {'a': {'items': [1, None, None, 9]}}),
        ]
        expression = '. as $arg | $arg.root | setpath($arg.path; $arg.new)'
        for root, path, new_value, expected in cases:
            source = {'root': root, 'path': path, 'new': new_value}
            with self.subTest(source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_paths_and_containers(self):
        cases = [
            ({'a': 1}, 'a', 2),
            ({'a': 1}, [None], 2),
            ({'a': 1}, [1], 2),
            ([], [-1], 2),
            ({'a': 1}, ['a', 0], 2),
            ({'a': [1]}, ['a', 'x'], 2),
        ]
        expression = '. as $arg | $arg.root | setpath($arg.path; $arg.new)'
        for root, path, new_value in cases:
            source = {'root': root, 'path': path, 'new': new_value}
            with self.subTest(source=source):
                result = self.run_filter(expression, source)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_comma_generator_emits_independent_updates(self):
        source = {'a': 0, 'b': 0}
        result = self.run_filter('[setpath(["a"], ["b"]; 1)]', source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout),
                         [{'a': 1, 'b': 0}, {'a': 0, 'b': 1}])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315110)
        cases = []
        for _ in range(100):
            items = [rng.randrange(-100, 101) for _ in range(rng.randrange(1, 8))]
            root = {'root': {'items': items, 'label': rng.choice(['', 'a', 'é'])}}
            choice = rng.randrange(3)
            if choice == 0:
                path = ['root', 'items', rng.randrange(-len(items), len(items) + 4)]
            elif choice == 1:
                path = ['root', 'label']
            else:
                path = ['root', 'added', 'leaf']
            cases.append({'root': root, 'path': path, 'new': rng.choice([None, 0, 2, 'x'])})
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in cases)
        expression = '. as $arg | $arg.root | setpath($arg.path; $arg.new)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
