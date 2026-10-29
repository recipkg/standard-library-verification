"""Selected jq output-stream selectors against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqGeneratorSamples(unittest.TestCase):
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

    def test_array_selectors(self):
        cases = [
            ('first', [10, 20, 30], [10]),
            ('last', [10, 20, 30], [30]),
            ('nth(1)', [10, 20, 30], [20]),
            ('nth(1.5)', [10, 20, 30], [20]),
            ('nth(-1)', [10, 20, 30], [30]),
            ('nth(9)', [10, 20, 30], [None]),
            ('first', [], [None]),
            ('last', [], [None]),
            ('nth(0)', [], [None]),
            ('first', None, [None]),
            ('isempty(.[])', [], [True]),
            ('isempty(.[])', [None], [False]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                actual = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(actual, expected)

    def test_generator_selectors(self):
        source = [None, False, 'middle', 9]
        cases = [('first(.[])', [None]), ('last(.[])', [9]),
                 ('nth(2; .[])', ['middle']), ('nth(8; .[])', []),
                 ('isempty(.[])', [False]), ('isempty(empty)', [True])]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                actual = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(actual, expected)

    def test_invalid_index_and_receiver(self):
        for expression, source in [('nth(-1; .[])', [1]), ('first', 'abc'),
                                   ('last', 7), ('nth(0)', {})]:
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
        rng = random.Random(315104)
        atoms = [None, False, True, -3, 0, 4, '', 'x']
        values = [[rng.choice(atoms) for _ in range(rng.randrange(8))]
                  for _ in range(100)]
        data = ''.join(json.dumps(value) + '\n' for value in values)
        expressions = ['first', 'last', 'nth(0)', 'nth(3)', 'nth(12)',
                       'nth(-1)', 'nth(-12)',
                       'first(.[])', 'last(.[])', 'nth(0; .[])',
                       'nth(3; .[])', 'nth(12; .[])', 'isempty(.[])']
        for expression in expressions:
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
