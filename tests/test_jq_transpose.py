"""Selected jq transpose samples against explicit executables."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqTransposeSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = os.environ.get('RECIPKG_TEST_JQ')
        if not target:
            raise unittest.SkipTest('set RECIPKG_TEST_JQ to the candidate or reference executable')
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f'jq target not found: {target}')

    def run_filter(self, executable, expression, source):
        return subprocess.run([executable, '-c', expression],
                              input=json.dumps(source, ensure_ascii=False) + '\n',
                              capture_output=True, text=True, timeout=10)

    def test_rectangular_and_empty_matrices(self):
        cases = [
            ([], []),
            ([[]], []),
            ([[], []], []),
            ([[1, 2], [3, 4]], [[1, 3], [2, 4]]),
            ([['a', None], [True, {'x': 1}]], [['a', True], [None, {'x': 1}]]),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'transpose', source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_ragged_rows_and_null_rows(self):
        cases = [
            ([[1, 2], [3]], [[1, 3], [2, None]]),
            ([[], [1]], [[None, 1]]),
            ([[1], [2, 3, 4]], [[1, 2], [None, 3], [None, 4]]),
            ([[1], None], [[1, None]]),
            ([None, [1]], [[None, 1]]),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'transpose', source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_rows(self):
        for source in (1, 'text', [[1], 2], [[1], 'text'], [[1], True],
                       [{'x': 1}, [2]]):
            with self.subTest(source=source):
                result = self.run_filter(self.target, 'transpose', source)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315108)
        atoms = [None, False, True, -2, 0, 3, '', 'é']
        matrices = []
        for _ in range(100):
            rows = []
            for _ in range(rng.randrange(7)):
                if rng.randrange(5) == 0:
                    rows.append(None)
                else:
                    rows.append([rng.choice(atoms) for _ in range(rng.randrange(7))])
            matrices.append(rows)
        data = ''.join(json.dumps(value, ensure_ascii=False) + '\n'
                       for value in matrices)
        actual = subprocess.run([self.target, '-c', 'transpose'], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', 'transpose'], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
