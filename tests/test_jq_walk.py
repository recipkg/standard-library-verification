"""Selected jq walk behavior against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqWalkSamples(unittest.TestCase):
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

    def test_bottom_up_array_transformation(self):
        source = [[4, 1, 7], [8, 5, 2], [3, 6, 9]]
        expression = 'walk(if type == "array" then sort else . end)'
        result = self.run_filter(self.target, expression, source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout),
                         [[1, 4, 7], [2, 5, 8], [3, 6, 9]])

    def test_nested_object_array_and_scalar_transformation(self):
        source = {'a': [1, {'b': 2}], 'c': 3}
        expression = ('walk(if type == "number" then . + 1 '
                      'elif type == "object" and has("b") '
                      'then . + {"seen": true} else . end)')
        result = self.run_filter(self.target, expression, source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout),
                         {'a': [2, {'b': 3, 'seen': True}], 'c': 4})

    def test_array_children_flatten_multiple_filter_results(self):
        expression = '[walk(if type == "number" then ., . + 10 else . end)]'
        result = self.run_filter(self.target, expression, [1, 2])
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout), [[1, 11, 2, 12]])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(813942)

        def make_value(depth=0):
            if depth >= 3 or rng.random() < 0.45:
                return rng.choice([None, True, False, rng.randrange(-20, 21),
                                   rng.choice(['', 'a', 'é'])])
            if rng.random() < 0.5:
                return [make_value(depth + 1) for _ in range(rng.randrange(4))]
            return {rng.choice(['a', 'b', 'c']): make_value(depth + 1)
                    for _ in range(rng.randrange(4))}

        inputs = [make_value() for _ in range(100)]
        data = ''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in inputs)
        expression = 'walk(if type == "number" then . * 2 else . end)'
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
