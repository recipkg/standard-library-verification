"""Selected jq string filters checked against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqStringSamples(unittest.TestCase):
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

    def test_prefix_suffix_and_trim_filters(self):
        cases = [
            ('startswith("foo")', 'foobar', True),
            ('startswith("")', 'é🙂', True),
            ('endswith("bar")', 'foobar', True),
            ('endswith("é")', 'xé', True),
            ('ltrimstr("foo")', 'foofoo', 'foo'),
            ('rtrimstr("foo")', 'foofoo', 'foo'),
            ('trimstr("foo")', 'foobarfoo', 'bar'),
            ('trimstr("ab")', 'abab', ''),
            ('ltrimstr("")', 'abc', 'abc'),
            ('rtrimstr("x")', 'abc', 'abc'),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_ascii_case_conversion(self):
        cases = [('ascii_downcase', 'ÄBCéXYZ', 'Äbcéxyz'),
                 ('ascii_upcase', 'Äbcéxyz', 'ÄBCéXYZ')]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_split_and_join(self):
        cases = [
            ('split(",")', 'a,,b,', ['a', '', 'b', '']),
            ('split(",")', '', []),
            ('split(",")', 'abc', ['abc']),
            ('split("")', 'aé🙂', ['a', 'é', '🙂']),
            ('split("aa")', 'aaaaa', ['', '', 'a']),
            ('join(",")', ['a', 2, None, True, False], 'a,2,,true,false'),
            ('join(" ")', ['a', 1, 2.3, True, None, False], 'a 1 2.3 true  false'),
            ('join(",")', {'z': 3, 'a': 4}, '3,4'),
            ('join(",")', [], ''),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_string_filter_type_errors(self):
        cases = [('startswith("x")', 2), ('endswith("x")', None),
                 ('ltrimstr("x")', []), ('split(",")', {}),
                 ('join(",")', 2), ('join(",")', [['nested']])]
        for expression, source in cases:
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
        rng = random.Random(718203)
        alphabet = ['a', 'b', ',', ' ', 'é', '🙂', 'Ä', 'Z', '']
        strings = [''.join(rng.choice(alphabet) for _ in range(rng.randrange(9)))
                   for _ in range(120)]
        cases = [('startswith("a")', strings), ('endswith("é")', strings),
                 ('ltrimstr("ab")', strings), ('rtrimstr("🙂")', strings),
                 ('trimstr("a")', strings), ('ascii_downcase', strings),
                 ('ascii_upcase', strings), ('split(",")', strings),
                 ('split("")', strings)]
        for expression, sources in cases:
            with self.subTest(expression=expression):
                data = ''.join(json.dumps(value, ensure_ascii=False) + '\n'
                               for value in sources)
                actual = subprocess.run([self.target, '-c', expression], input=data,
                                        text=True, capture_output=True, timeout=30)
                expected = subprocess.run([reference, '-c', expression], input=data,
                                          text=True, capture_output=True, timeout=30)
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)

        join_values = [None, False, True, -3, 0, 12, '', 'x', 'é,🙂']
        arrays = [[rng.choice(join_values) for _ in range(rng.randrange(8))]
                  for _ in range(100)]
        objects = [{f'k{index}': rng.choice(join_values)
                    for index in range(rng.randrange(1, 7))}
                   for _ in range(100)]
        for sources in (arrays, objects):
            with self.subTest(expression='join(",")', kind=type(sources[0]).__name__):
                data = ''.join(json.dumps(value, ensure_ascii=False) + '\n'
                               for value in sources)
                actual = subprocess.run([self.target, '-c', 'join(",")'], input=data,
                                        text=True, capture_output=True, timeout=30)
                expected = subprocess.run([reference, '-c', 'join(",")'], input=data,
                                          text=True, capture_output=True, timeout=30)
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)


if __name__ == '__main__':
    unittest.main()
