"""Selected jq del(path_expression) behavior samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqDelSamples(unittest.TestCase):
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

    def outputs(self, expression, source):
        result = self.run_filter(self.target, expression, source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_object_paths_and_missing_fields(self):
        self.assertEqual(self.outputs('del(.foo)', {'foo': 42, 'bar': 9001, 'baz': 42}),
                         [{'bar': 9001, 'baz': 42}])
        self.assertEqual(self.outputs('del(.a, .b)', {'a': 1, 'b': 2, 'c': 3}),
                         [{'c': 3}])
        self.assertEqual(self.outputs('del(.missing)', {'a': 1}), [{'a': 1}])

    def test_simultaneous_array_and_iterator_deletion(self):
        self.assertEqual(self.outputs('del(.[1,2])', ['foo', 'bar', 'baz']), [['foo']])
        self.assertEqual(self.outputs('del(.[-1], .[0])', [0, 1, 2]), [[1]])
        self.assertEqual(self.outputs('del(.[8])', [0, 1]), [[0, 1]])
        self.assertEqual(self.outputs('del(.[])', [1, 2, 3]), [[]])
        self.assertEqual(self.outputs('del(.[])', {'a': 1, 'b': 2}), [{}])

    def test_overlapping_paths_and_root(self):
        self.assertEqual(self.outputs('del(.a, .a.b)', {'a': {'b': 1, 'c': 2}, 'z': 3}),
                         [{'z': 3}])
        self.assertEqual(self.outputs('del(.)', {'a': 1}), [None])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315114)
        cases = []
        for _ in range(100):
            cases.append({'root': {
                'items': [rng.randrange(100) for _ in range(rng.randrange(5))],
                'a': rng.randrange(100), 'b': rng.randrange(100), 'keep': True,
            }})
        data = ''.join(json.dumps(item) + '\n' for item in cases)
        expression = 'del(.root.items[0,2], .root.a, .root.missing)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
