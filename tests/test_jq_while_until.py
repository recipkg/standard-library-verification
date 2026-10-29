"""Selected jq while and until generator behavior."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqWhileUntilSamples(unittest.TestCase):
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

    def test_while_stop_position_and_update_branches(self):
        cases = [
            ('[while(. < 5; . + 1)]', 0, [0, 1, 2, 3, 4]),
            ('[while(. < 0; . + 1)]', 0, []),
            ('[while(. < 3; (.+1, .+2))]', 0, [0, 1, 2, 2]),
            ('[while((. < 2, . < 1); . + 1)]', 0, [0, 1, 0, 1]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_until_stop_position_and_update_branches(self):
        cases = [
            ('[until(. >= 5; . + 1)]', 0, [5]),
            ('[until(. >= 0; . + 1)]', 0, [0]),
            ('[until(. >= 3; (.+1, .+2))]', 0, [3, 4, 3, 3, 4]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_filter(self.target, expression, source)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(json.loads(result.stdout), expected)

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(883174)
        cases = []
        for _ in range(100):
            start = rng.randrange(-30, 31)
            limit = start + rng.randrange(0, 31)
            step = rng.randrange(1, 6)
            cases.append({'start': start, 'limit': limit, 'step': step})
        data = ''.join(json.dumps(item) + '\n' for item in cases)
        expression = ('. as $arg | {while: [$arg.start | while(. < $arg.limit; '
                      '. + $arg.step)], until: [$arg.start | until(. >= $arg.limit; '
                      '. + $arg.step)]}')
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
