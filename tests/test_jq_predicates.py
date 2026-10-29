"""Selected jq any/all predicates against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqPredicateSamples(unittest.TestCase):
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

    def test_array_object_and_empty_inputs(self):
        cases = [
            ('any', [True, False], True),
            ('all', [True, False], False),
            ('any', [], False),
            ('all', [], True),
            ('any', [0], True),
            ('all', [None, False], False),
            ('any', {}, False),
            ('all', {'x': 0, 'y': None}, False),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_conditions_and_generators(self):
        cases = [
            ('any(. > 2)', [1, 3], True),
            ('all(. > 0)', [1, 3], True),
            ('all(. > 2)', [1, 3], False),
            ('any(. > 2)', [], False),
            ('any(.[]; . > 2)', [1, 3], True),
            ('all(.[]; . > 0)', [1, 3], True),
            ('all(.[]; . > 2)', [1, 3], False),
            ('any(.[]; . > 2)', [], False),
            ('all(.[]; . > 2)', [], True),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.run_filter(self.target, expression,
                                         json.dumps(source) + '\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_non_iterable_input_errors(self):
        for expression, source in [('any', None), ('all', 3),
                                   ('any(. > 0)', None), ('all(.[]; .)', 'x')]:
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
        rng = random.Random(315105)
        atoms = [None, False, True, -3, 0, 4, '', 'x']
        values = [[rng.choice(atoms) for _ in range(rng.randrange(8))]
                  for _ in range(100)]
        data = ''.join(json.dumps(value) + '\n' for value in values)
        expressions = ['any', 'all', 'any(. > 0)', 'all(. != null)',
                       'any(.[]; . > 0)', 'all(.[]; . != false)']
        for expression in expressions:
            actual = self.run_filter(self.target, expression, data)
            expected = self.run_filter(reference, expression, data)
            with self.subTest(expression=expression):
                self.assertEqual((actual.returncode, actual.stderr), (0, ''))
                self.assertEqual((expected.returncode, expected.stderr), (0, ''))
                self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                                 [json.loads(line) for line in expected.stdout.splitlines()])
