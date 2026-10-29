"""Selected jq object/array entry conversion samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqEntrySamples(unittest.TestCase):
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

    def test_to_entries_objects_and_arrays(self):
        cases = [
            ('{"z":1,"a":2}', [{"key": "z", "value": 1},
                                {"key": "a", "value": 2}]),
            ('["x",null]', [{"key": 0, "value": "x"},
                            {"key": 1, "value": None}]),
            ('{}', []),
            ('[]', []),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'to_entries', source + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for source in ('null', '"text"', '1'):
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'to_entries', source + '\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_from_entries_aliases_and_duplicates(self):
        cases = [
            ('[{"key":"a","value":1},{"Key":"b","Value":2},'
             '{"name":"c","value":3},{"Name":"d","Value":4}]',
             {"a": 1, "b": 2, "c": 3, "d": 4}),
            ('[{"key":"a"}]', {"a": None}),
            ('[{"key":"a","Key":"b","value":null,"Value":2}]',
             {"a": None}),
            ('[{"key":"a","value":1},{"key":"a","value":2}]', {"a": 2}),
            ('[]', {}),
            ('{"left":{"key":"x","value":1},'
             '"right":{"key":"y","value":2}}', {"x": 1, "y": 2}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'from_entries', source + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)
        for source in ('"text"', '[5]', '[null]', '[{"key":7}]'):
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'from_entries', source + '\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_with_entries_maps_filters_and_key_updates(self):
        cases = [
            ('with_entries(.key |= ascii_upcase)', '{"a":1,"b":2}',
             {"A": 1, "B": 2}),
            ('with_entries(.value |= . + 1)', '{"a":1,"b":2}',
             {"a": 2, "b": 3}),
            ('with_entries(select(.value > 1))', '{"a":1,"b":2}',
             {"b": 2}),
            ('with_entries(.)', '{"a":1}', {"a": 1}),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315107)
        objects = [{f'k{index}': rng.randrange(-20, 21)
                    for index in range(rng.randrange(7))} for _ in range(100)]
        data = ''.join(json.dumps(value) + '\n' for value in objects)
        for expression in ('to_entries', 'with_entries(.value |= . + 1)',
                           'with_entries(select(.value > 0))'):
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
        arrays = [[rng.randrange(-5, 6) for _ in range(rng.randrange(7))]
                  for _ in range(100)]
        data = ''.join(json.dumps(value) + '\n' for value in arrays)
        actual = self.run_filter(self.target, 'to_entries', data)
        expected = self.run_filter(reference, 'to_entries', data)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
