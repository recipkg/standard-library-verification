"""Selected jq Unicode string conversions against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqUnicodeSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, data):
        return subprocess.run([executable, '-c', expression], input=data,
                              capture_output=True, text=True, timeout=10)

    def test_utf8_lengths_and_codepoint_roundtrips(self):
        strings = ['', 'ASCII', 'µ', '中', '🙂', 'e\u0301', '\0A']
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in strings)
        cases = [
            ('length', [len(value) for value in strings]),
            ('utf8bytelength', [len(value.encode('utf-8')) for value in strings]),
            ('explode', [[ord(char) for char in value] for value in strings]),
            ('explode | implode', strings),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, data)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in result.stdout.splitlines()],
                                 expected)

    def test_implode_numeric_boundaries(self):
        cases = [
            ([65, 66, 67], 'ABC'),
            ([0, 128578], '\0🙂'),
            ([65.9, -0.2, 128578.1], 'A\0🙂'),
            ([-1, 1114112, 55296], '\ufffd\ufffd\ufffd'),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'implode',
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_type_errors(self):
        for expression, source in [('utf8bytelength', None), ('explode', 7),
                                   ('implode', 'ABC'), ('implode', [True]),
                                   ('explode', {})]:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315103)
        alphabet = ['a', 'Z', '\0', 'é', '中', '🙂', '\u0301', '𐐷']
        strings = [''.join(rng.choice(alphabet) for _ in range(rng.randrange(12)))
                   for _ in range(100)]
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in strings)
        for expression in ('length', 'utf8bytelength', 'explode', 'explode | implode'):
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])

        codepoints = []
        for _ in range(100):
            points = []
            for _ in range(rng.randrange(12)):
                point = rng.randrange(0x110000)
                while 0xD800 <= point <= 0xDFFF:
                    point = rng.randrange(0x110000)
                points.append(point)
            codepoints.append(points)
        data = ''.join(json.dumps(value) + '\n' for value in codepoints)
        actual = self.run_filter(self.target, 'implode', data)
        expected = self.run_filter(reference, 'implode', data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
