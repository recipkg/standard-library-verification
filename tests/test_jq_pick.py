"""Selected jq pick(path_expressions) projection samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqPickSamples(unittest.TestCase):
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

    def test_object_projection_and_missing_paths(self):
        source = {'a': 1, 'b': {'c': 2, 'd': 3}, 'e': 4}
        self.assertEqual(self.outputs('pick(.a, .b.c, .x)', source),
                         [{'a': 1, 'b': {'c': 2}, 'x': None}])
        self.assertEqual(self.outputs('pick(.a.x)', {'a': {'y': 1}, 'b': 2}),
                         [{'a': {'x': None}}])

    def test_array_projection_and_duplicates(self):
        self.assertEqual(self.outputs('pick(.[2], .[0], .[0])', [1, 2, 3, 4]),
                         [[1, None, 3]])
        self.assertEqual(self.outputs('pick(.[0,3])', [1, 2]), [[1, None, None, None]])

    def test_iterator_overlap_root_and_empty(self):
        self.assertEqual(self.outputs('pick(.[])', [1, 2, 3]), [[1, 2, 3]])
        self.assertEqual(self.outputs('pick(.[])', {'a': 1, 'b': 2}), [{'a': 1, 'b': 2}])
        source = {'a': {'b': 1, 'c': 2}, 'z': 3}
        self.assertEqual(self.outputs('pick(.a, .a.b)', source), [{'a': source['a']}])
        self.assertEqual(self.outputs('pick(.)', source), [source])
        self.assertEqual(self.outputs('pick(.[])', []), [None])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315115)
        cases = []
        for _ in range(100):
            cases.append({'root': {
                'items': [rng.randrange(100) for _ in range(rng.randrange(5))],
                'a': rng.randrange(100), 'b': rng.randrange(100), 'keep': True,
            }})
        data = ''.join(json.dumps(item) + '\n' for item in cases)
        expression = 'pick(.root.items[0,2], .root.a, .root.missing)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
