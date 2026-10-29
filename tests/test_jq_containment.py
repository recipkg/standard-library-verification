"""Selected jq container containment and array reversal samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqContainmentSamples(unittest.TestCase):
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

    def test_contains_and_inside(self):
        source = {'foo': 12, 'bar': [1, 2, {'barp': 12, 'blip': 13}]}
        cases = [
            ('contains("bar")', 'foobar', True),
            ('contains(["baz", "bar"])', ['foobar', 'foobaz', 'blarp'], True),
            ('contains(["bazzzzz", "bar"])', ['foobar', 'foobaz', 'blarp'], False),
            ('contains({"foo":12,"bar":[{"barp":12}]})', source, True),
            ('contains({"foo":12,"bar":[{"barp":15}]})', source, False),
            ('contains([1,1])', [1], True),
            ('contains([[1,2]])', [[1,2]], True),
            ('contains([1,2])', [[1,2]], False),
            ('contains([])', [1, 2], True),
            ('contains({})', {'x': 1}, True),
            ('contains(2)', 1, False),
            ('contains([true])', [False], False),
            ('contains(null)', None, True),
            ('inside(["foobar","foobaz","blarp"])', ['baz', 'bar'], True),
            ('inside({"foo":12,"bar":[1,2,{"barp":12,"blip":13}]})',
             {'foo': 12, 'bar': [{'barp': 12}]}, True),
        ]
        for expression, value, expected in cases:
            with self.subTest(expression=expression, value=value):
                result = self.run_filter(expression, value)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_reverse_arrays_and_errors(self):
        for value, expected in [([], []), ([1, 2, 3], [3, 2, 1]),
                                ([[1, 2], {'x': 1}], [{'x': 1}, [1, 2]])]:
            with self.subTest(value=value):
                result = self.run_filter('reverse', value)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for expression, value in [('reverse', 'abc'), ('contains("x")', 1),
                                  ('inside(1)', 'x'), ('contains(false)', True)]:
            with self.subTest(expression=expression, value=value):
                result = self.run_filter(expression, value)
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
        rng = random.Random(409211)
        atoms = [None, False, True, -2, 0, 3, '', 'a', 'é']

        def value(depth=0):
            if depth >= 2:
                return rng.choice(atoms)
            choice = rng.randrange(3)
            if choice == 0:
                return rng.choice(atoms)
            if choice == 1:
                return [value(depth + 1) for _ in range(rng.randrange(5))]
            return {f'k{i}': value(depth + 1) for i in range(rng.randrange(5))}

        pairs = []
        for _ in range(120):
            container = value()
            if isinstance(container, list):
                needle = [value(1) for _ in range(rng.randrange(5))]
            elif isinstance(container, dict):
                keys = list(container)
                needle = {key: value(1) for key in keys[:rng.randrange(len(keys) + 1)]}
            elif isinstance(container, str):
                needle = ''.join(rng.choice(['a', 'é', '']) for _ in range(3))
            elif isinstance(container, bool):
                needle = container
            elif isinstance(container, int):
                needle = rng.choice(atoms[3:6])
            else:
                needle = None
            pairs.append([container, needle])

        data = ''.join(json.dumps(pair, ensure_ascii=False) + '\n' for pair in pairs)
        expression = '. as [$container,$needle] | $container | contains($needle)'
        for filter_text in (expression,
                            '. as [$container,$needle] | $container | inside($needle)'):
            actual = subprocess.run([self.target, '-c', filter_text], input=data,
                                    text=True, capture_output=True, timeout=30)
            expected = subprocess.run([reference, '-c', filter_text], input=data,
                                      text=True, capture_output=True, timeout=30)
            with self.subTest(expression=filter_text):
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)


if __name__ == '__main__':
    unittest.main()
