"""Compare selected jq conditions and ordering against an explicit reference."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqDifferential(unittest.TestCase):
    def test_conditions_and_json_ordering(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference),
                            'target and reference must be different executables')
        for label, exe in [('target', target), ('reference', reference)]:
            version = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
            self.assertEqual(version.returncode, 0, version.stderr)
            print(label, version.stdout.strip())
        data = [None, False, True, 0, 1, -2, 1.0, '', 'abc', 'é', [], [False], [1],
                {}, {'a': False}, {'a': 1}, {'b': 0}, {'a': [1, None]}]
        randomizer = random.Random(2718)
        cases = [('[.a == .b,.a != .b,.a < .b,.a >= .b]',
                  {'a': randomizer.choice(data), 'b': randomizer.choice(data)}) for _ in range(100)]
        cases.extend(('sort', [randomizer.choice(data) for _ in range(8)]) for _ in range(20))
        cases.extend(('if . then "yes" elif . == false then "false" else "null" end', value)
                     for value in data)
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                outputs = []
                for exe in (reference, target):
                    result = subprocess.run([exe, '-c', expression], input=json.dumps(source, ensure_ascii=False),
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, '')
                    outputs.append([json.dumps(json.loads(line), sort_keys=True, ensure_ascii=False)
                                    for line in result.stdout.splitlines()])
                self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
