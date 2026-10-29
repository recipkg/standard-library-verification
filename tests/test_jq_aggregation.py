"""Selected jq aggregation and key-based ordering against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqAggregationSamples(unittest.TestCase):
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

    def test_key_based_order_and_ties(self):
        entries = [{'a': 1, 'b': 3, 'id': 'first'}, {'a': 1, 'b': 2, 'id': 'middle'},
                   {'a': 1, 'b': 3, 'id': 'last'}]
        cases = [
            ('sort_by((.a,.b))', entries, [entries[1], entries[0], entries[2]]),
            ('group_by((.a,.b))', entries, [[entries[1]], [entries[0], entries[2]]]),
            ('unique_by(.a)', entries, [entries[0]]),
            ('min_by(.a)', entries, entries[0]), ('max_by(.a)', entries, entries[2]),
            ('sort_by(empty)', [2, 1, 3], [2, 1, 3]),
            ('group_by(empty)', [2, 1, 3], [[2, 1, 3]]),
            ('unique_by(empty)', [2, 1, 3], [2]),
            ('min_by(empty)', [2, 1, 3], 2), ('max_by(empty)', [2, 1, 3], 3),
            ('sort_by(.[]?)', [[2], [1, 2], [1], [1, 0]], [[1], [1, 0], [1, 2], [2]]),
            ('group_by(.)', [], []), ('unique', [1, 2, 1, False, None, False], [None, False, 1, 2]),
            ('min', [], None), ('max', [], None), ('min_by(error("bad"))', [], None),
            ('def f(x): sort_by(x); f(.a)', entries, entries),
            ('def unique: 7; unique', [], 7),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for expression, expected in [('min', '1\n'), ('max', '1.0\n'), ('unique', '[1]\n')]:
            with self.subTest(expression=expression, numeric_representation=True):
                result = self.run_filter(expression, [1, 1.0])
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        for expression, source in [('sort_by(.)', {}), ('unique', None), ('max', 3),
                                   ('sort_by(error("bad"))', [1]), ('group_by(.a)', [1])]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stdout), (5, ''))
                self.assertTrue(result.stderr)

    def test_add_and_generator(self):
        cases = [('add', [], None), ('add', {}, None), ('add', [None, None], None),
                 ('add', [False], False), ('add', [1, 2, 3], 6),
                 ('add', {'a': 2, 'b': 3}, 5), ('add', ['a', 'b'], 'ab'),
                 ('add', [[1], [2]], [1, 2]),
                 ('add', [{'a': 1}, {'a': 2, 'b': 3}], {'a': 2, 'b': 3}),
                 ('add((.a,.b))', {'a': 1, 'b': 2}, 3),
                 ('add(empty)', 7, None), ('add(.,.)', 2, 4)]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for expression, source in [('add', None), ('add', [1, False]), ('add(.[])', None)]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stdout), (5, ''))
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(273104)
        values = [None, False, True, -3, 0, 1, 2, '', 'x', [], {}, [1], {'x': 1}]
        arrays = [[rng.choice(values) for _ in range(rng.randrange(8))] for _ in range(100)]
        objects = [[{'a': rng.choice(values), 'b': rng.choice(values), 'id': i}
                    for i in range(rng.randrange(8))] for _ in range(100)]
        cases = [('sort_by(.)', arrays), ('group_by(.)', arrays), ('unique', arrays),
                 ('min', arrays), ('max', arrays),
                 ('sort_by((.a,.b))', objects), ('group_by((.a,.b))', objects),
                 ('unique_by(.a)', objects), ('min_by((.a,.b))', objects),
                 ('max_by((.a,.b))', objects),
                 ('group_by(if .a then .b else empty end)', objects),
                 ('unique_by(empty)', objects)]
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
