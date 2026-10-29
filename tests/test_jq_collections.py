"""Selected jq collection and key-query behavior against an explicit target."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqCollectionSamples(unittest.TestCase):
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

    def test_mapping_results_and_errors(self):
        cases = [
            ('map((.,.+1))', [1, 2], [[1, 2, 2, 3]]),
            ('map(empty)', [1, 2], [[]]),
            ('def f(x): map(x); f(.+1)', [1, 2], [[2, 3]]),
            ('def map(f): 7; map(.)', [1, 2], [7]),
            ('map(.)', {'b': 2, 'a': 1}, [[2, 1]]),
            ('map_values((.,.+1))', [1, 2], [[1, 2]]),
            ('map_values(if . == 2 then empty else . end)', [1, 2, 3], [[1, 3]]),
            ('map_values(. // empty)', {'a': None, 'b': True, 'c': False}, [{'b': True}]),
            ('map_values((.,error("later")))', {'a': 1}, [{'a': 1}]),
            ('map_values(empty)', {}, [{}]),
            ('map_values(empty)', [], [[]]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in result.stdout.splitlines()], expected)
        for expression, source in [('map((.,error("later")))', [1]),
                                   ('map(.)', None), ('map_values(.)', 'x')]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stdout), (5, ''))
                self.assertTrue(result.stderr)

    def test_keys_and_membership(self):
        cases = [
            ('keys', {'é': 1, 'Z': 2, 'a': 3}, [['Z', 'a', 'é']]),
            ('keys_unsorted', {'z': 1, 'a': 2, 'm': 3}, [['z', 'a', 'm']]),
            ('keys', [10, 20], [[0, 1]]), ('keys_unsorted', [], [[]]),
            ('has(("a","b"))', {'a': None}, [True, False]),
            ('has((-1,-0.5,0,1.9,2))', [1, 2], [False, True, True, True, False]),
            ('has((null,false,0,"x",[],{}))', None, [False] * 6),
            ('has(.wanted)', {'wanted': 'x', 'x': None}, [True]),
            ('in(({}, {"x":null}))', 'x', [False, True]),
            ('in([3,4])', -1, [False]), ('in([3,4])', 0.5, [True]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in result.stdout.splitlines()], expected)
        for expression, source, prior in [('keys', None, ''), ('keys', False, ''),
                                          ('has(null)', {}, ''), ('has("x")', [], ''),
                                          ('has((0,true))', [1], 'true\n'),
                                          ('in(({},[0]))', 'x', 'false\n')]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stdout), (5, prior))
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(119392)
        values = [None, False, True, -3, -1, 0, 1, 2, 4, '', 'x', [], {}]
        arrays = [[rng.choice(values) for _ in range(rng.randrange(7))] for _ in range(100)]
        objects = [{key: rng.choice(values) for key in rng.sample(['a', 'z', 'é', 'x', ''], rng.randrange(6))}
                   for _ in range(100)]
        cases = [
            ('map((.,.))', arrays + objects),
            ('map_values((.,error("later")))', arrays + objects),
            ('map_values(select(.))', arrays + objects),
            ('map_values(if . == null then empty else . end)', arrays + objects),
            ('keys', arrays + objects), ('keys_unsorted', arrays + objects),
            ('[has(("a","z","missing",""))]', objects),
            ('[has((-2,-0.5,0,1,2.9,7))]', arrays),
        ]
        for expression, sources in cases:
            with self.subTest(expression=expression):
                data = ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in sources)
                actual = subprocess.run([self.target, '-c', expression], input=data, text=True,
                                        capture_output=True, timeout=30)
                expected = subprocess.run([reference, '-c', expression], input=data, text=True,
                                          capture_output=True, timeout=30)
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)


if __name__ == '__main__':
    unittest.main()
