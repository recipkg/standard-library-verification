"""Selected jq type and JSON conversion filters against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqConversionSamples(unittest.TestCase):
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

    def test_type_names(self):
        values = [None, False, True, 0, 1.5, 'é', [], {}, [1], {'x': 1}]
        result = self.run_filter('[.[] | type]', values)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(json.loads(result.stdout), [
            'null', 'boolean', 'boolean', 'number', 'number',
            'string', 'array', 'object', 'array', 'object'])

    def test_tostring_and_tojson(self):
        source = [1, 'foo', [1], {'x': 'é'}, None, True]
        expected_tostring = ['1', 'foo', '[1]', '{"x":"é"}', 'null', 'true']
        expected_tojson = ['1', '"foo"', '[1]', '{"x":"é"}', 'null', 'true']
        for expression, expected in [('[.[] | tostring]', expected_tostring),
                                     ('[.[] | tojson]', expected_tojson)]:
            with self.subTest(expression=expression):
                result = self.run_filter(expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        result = self.run_filter('tostring', 'already text')
        self.assertEqual(json.loads(result.stdout), 'already text')
        result = self.run_filter('tojson', 'already text')
        self.assertEqual(json.loads(result.stdout), '"already text"')

    def test_fromjson_valid_and_invalid_inputs(self):
        valid = ['null', 'true', '123', '"é"', '[1,{"x":2}]', ' { "x" : 1 } ']
        for text in valid:
            with self.subTest(text=text):
                result = self.run_filter('fromjson', text)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                expected = json.loads(text)
                self.assertEqual(json.loads(result.stdout), expected)
        invalid = ['not-json', '1 2', '', None, 5]
        for source in invalid:
            with self.subTest(source=source):
                result = self.run_filter('fromjson', source)
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
        rng = random.Random(631907)
        atoms = [None, False, True, -5, 0, 1, 2, '', 'é', 'x"y']
        values = list(atoms)
        values.extend([[rng.choice(atoms) for _ in range(rng.randrange(5))]
                       for _ in range(40)])
        values.extend([{f'k{i}': rng.choice(atoms) for i in range(rng.randrange(1, 5))}
                       for _ in range(40)])
        for expression in ('type', 'tostring', 'tojson'):
            data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in values)
            actual = subprocess.run([self.target, '-c', expression], input=data,
                                    text=True, capture_output=True, timeout=30)
            expected = subprocess.run([reference, '-c', expression], input=data,
                                      text=True, capture_output=True, timeout=30)
            with self.subTest(expression=expression):
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual(actual.stdout, expected.stdout)

        texts = [json.dumps(value, ensure_ascii=False) for value in values]
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in texts)
        actual = subprocess.run([self.target, '-c', 'fromjson'], input=data,
                                text=True, capture_output=True, timeout=30)
        expected = subprocess.run([reference, '-c', 'fromjson'], input=data,
                                  text=True, capture_output=True, timeout=30)
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual(actual.stdout, expected.stdout)


if __name__ == '__main__':
    unittest.main()
