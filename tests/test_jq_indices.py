"""Selected jq substring and array index filters against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqIndexSamples(unittest.TestCase):
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

    def test_string_indices_overlap_and_unicode(self):
        cases = [
            ('indices("aa")', 'aaaa', [0, 1, 2]),
            ('index("aa")', 'aaaa', 0),
            ('rindex("aa")', 'aaaa', 2),
            ('indices("é")', 'é🙂é', [0, 2]),
            ('indices("🙂")', 'a🙂🙂', [1, 2]),
            ('indices("")', 'aé', []),
            ('index("")', 'aé', None),
            ('rindex("x")', 'abc', None),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_array_scalar_and_subarray_indices(self):
        cases = [
            ('indices(1)', [0, 1, 2, 1, 3, 1, 4], [1, 3, 5]),
            ('index(1)', [0, 1, 2, 1, 3, 1, 4], 1),
            ('rindex(1)', [0, 1, 2, 1, 3, 1, 4], 5),
            ('indices([1,2])', [0, 1, 2, 3, 1, 2, 6], [1, 4]),
            ('index([1,2])', [0, 1, 2, 3, 1, 2, 6], 1),
            ('rindex([1,2])', [0, 1, 2, 3, 1, 2, 6], 4),
            ('indices([1,1])', [1.0, 1, 1], [0, 1]),
            ('indices([])', [1, 1], []),
            ('index([])', [1, 1], None),
            ('rindex("x")', [1, 1], None),
            ('indices("a")', ['a', 'b', 'a'], [0, 2]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_observed_null_object_and_type_boundaries(self):
        for expression, source, expected in [
                ('indices("x")', None, None),
                ('index("x")', {}, None),
                ('rindex("x")', {}, None)]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for expression, source in [('indices(1)', 'abc'), ('index([])', 'abc'),
                                   ('indices(1)', {}), ('indices([])', None),
                                   ('indices("x")', 1)]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
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
        rng = random.Random(315042)
        pairs = []
        alphabet = ['a', 'b', 'é', '🙂', '']
        for _ in range(60):
            text = ''.join(rng.choice(alphabet[:-1]) for _ in range(rng.randrange(9)))
            needle = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(4)))
            pairs.append([text, needle])
        atoms = [None, False, True, -1, 0, 1, 'a', 'é']
        for _ in range(60):
            array = [rng.choice(atoms) for _ in range(rng.randrange(9))]
            if rng.randrange(2) and array:
                start = rng.randrange(len(array))
                needle = array[start:start + rng.randrange(1, 4)]
            else:
                needle = rng.choice(atoms)
            pairs.append([array, needle])

        data = ''.join(json.dumps(pair, ensure_ascii=False) + '\n' for pair in pairs)
        prefix = '. as [$haystack,$needle] | $haystack | '
        for operation in ('indices($needle)', 'index($needle)', 'rindex($needle)'):
            expression = prefix + operation
            actual = subprocess.run([self.target, '-c', expression], input=data,
                                    text=True, capture_output=True, timeout=30)
            expected = subprocess.run([reference, '-c', expression], input=data,
                                      text=True, capture_output=True, timeout=30)
            with self.subTest(operation=operation):
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)


if __name__ == '__main__':
    unittest.main()
