"""Compare selected jq conditions and ordering against an explicit reference."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqDifferential(unittest.TestCase):
    def test_json_relaxed_literals_and_nested_unicode(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        rng = random.Random(1347)
        tokens = ['01', '+2', '-003', '.5', '-.2', '1.', '+1.2', '00012']
        for _ in range(25):
            a, b = rng.choice(tokens), rng.choice(tokens)
            sources = [a, f'[{a},{b}]', f'{{"a":{a},"b":{b}}}', f'{a} {b}']
            for source in sources:
                with self.subTest(source=source):
                    outputs = []
                    for exe in (reference, target):
                        result = subprocess.run([exe, '-c', '.'], input=source.encode(),
                                                capture_output=True, timeout=10)
                        self.assertEqual((result.returncode, result.stderr), (0, b''))
                        outputs.append(result.stdout)
                    self.assertEqual(outputs[0], outputs[1])
        for source in (b'{"\\uDC00":"\\uDC00"}', b'["\\uD800"]',
                       b'"\\uD800\\u0041"', b'2 1..2'):
            with self.subTest(source=source):
                outputs = []
                for exe in (reference, target):
                    result = subprocess.run([exe, '-c', '.'], input=source, capture_output=True, timeout=10)
                    outputs.append((result.returncode, result.stdout, bool(result.stderr)))
                self.assertEqual(outputs[0], outputs[1])

    def test_sequence_recovery_and_stream_modes(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        rng = random.Random(2403)
        segments = ['1\n', '-2\n', 'null\n', '[1,2]\n', '{"x":[true,{}]}\n',
                    '[1,]\n', '{"bad":?}\n', '[]\n', '"hello"\n']
        for _ in range(24):
            source = 'ignored' + ''.join('\x1e' + rng.choice(segments)
                                         for _ in range(rng.randrange(2, 6)))
            for option in ([], ['--stream'], ['--stream-errors']):
                with self.subTest(source=source, option=option):
                    outputs = []
                    for exe in (reference, target):
                        run = subprocess.run([exe, '--seq', '-c', *option, '.'], input=source,
                                             text=True, capture_output=True, timeout=10)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        records = [json.loads(part) for part in run.stdout.split('\x1e') if part.strip()]
                        if option == ['--stream-errors']:
                            for record in records:
                                if isinstance(record, list) and len(record) == 2 and isinstance(record[0], str):
                                    self.assertTrue(record[0])
                                    record[0] = '<error>'
                        outputs.append((records, bool(run.stderr)))
                    self.assertEqual(outputs[0], outputs[1])

    def test_json_stream_records(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        rng = random.Random(6507)

        def data(depth):
            if depth and rng.randrange(3) == 0:
                return [data(depth - 1) for _ in range(rng.randrange(4))]
            if depth and rng.randrange(3) == 0:
                return {f'k{i}': data(depth - 1) for i in range(rng.randrange(4))}
            return rng.choice([None, True, False, rng.randint(-30, 30), '', 'é', 'x\\ny'])

        sources = [data(3) for _ in range(50)]
        sources.append(['a' * 65533 + '😀', {'nested': ['b' * 100, None]}])
        for source in sources:
            for option in ('--stream', '--stream-errors'):
                with self.subTest(option=option, source_type=type(source).__name__):
                    results = []
                    for exe in (reference, target):
                        run = subprocess.run([exe, '-c', option, '.'],
                                             input=json.dumps(source, ensure_ascii=False),
                                             text=True, capture_output=True, timeout=10)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stderr, '')
                        results.append([json.loads(line) for line in run.stdout.splitlines()])
                    self.assertEqual(results[0], results[1])

    def test_json_stream_error_paths(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        cases = ['[1 x]', '["a" x]', '[1 2]', '[1:2]', '{"a":1 "b":2}',
                 '[1,2,]', '[1,,2]', '{"a":1,"b" 2}', '[[1]', '[[1],',
                 '[[1]],', '{"a":true', '{"a":true,', '[[]', '[{},',
                 '[null', '[true', '[1,?]', '{"a":{"b":n}}', '{"a":1,"b":x}']
        for source in cases:
            with self.subTest(source=source):
                results = []
                for exe in (reference, target):
                    run = subprocess.run([exe, '-c', '--stream-errors', '.'], input=source,
                                         text=True, capture_output=True, timeout=10)
                    self.assertEqual((run.returncode, run.stderr), (0, ''))
                    records = [json.loads(line) for line in run.stdout.splitlines()]
                    self.assertTrue(records and isinstance(records[-1][0], str))
                    self.assertTrue(records[-1][0])
                    records[-1][0] = '<error>'
                    results.append(records)
                self.assertEqual(results[0], results[1])

    def test_function_arguments_and_lexical_scope(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        rng = random.Random(9816)
        expressions = [
            'def f(x): x|x; f(.+1)',
            'def f($x): [$x,.]; f((.,.+1))',
            'def f($x;$y): [$x,$y,.]; f((.,.+1);(.*2,.-1))',
            'def f(x): def g: x; .+1|g; f(.*2)',
        ]
        for _ in range(25):
            source = rng.randint(-50, 50)
            for expression in expressions:
                with self.subTest(expression=expression, source=source):
                    results = []
                    for exe in (reference, target):
                        run = subprocess.run([exe, '-c', expression], input=json.dumps(source),
                                             text=True, capture_output=True, timeout=10)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stderr, '')
                        results.append([json.loads(line) for line in run.stdout.splitlines()])
                    self.assertEqual(results[0], results[1])

    def test_binding_and_reduction_streams(self):
        target = os.environ.get('RECIPKG_TEST_JQ')
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not target and not reference:
            self.skipTest('set RECIPKG_TEST_JQ and RECIPKG_TEST_JQ_REFERENCE')
        if not target or not reference:
            self.fail('both target and reference must be specified')
        target, reference = shutil.which(target), shutil.which(reference)
        self.assertIsNotNone(target, 'jq target not found')
        self.assertIsNotNone(reference, 'jq reference not found')
        self.assertNotEqual(os.path.realpath(target), os.path.realpath(reference))
        rng = random.Random(9341)
        expressions = [
            '[.[] as $x | [$x,.]]',
            'reduce .[] as $x (0; .+$x)',
            'foreach .[] as $x (0; .+$x; [$x,.])',
            'foreach .[] as $x (0; (.,.+$x))',
        ]
        for _ in range(25):
            source = [rng.randint(-9, 9) for _ in range(rng.randrange(7))]
            for expression in expressions:
                with self.subTest(expression=expression, source=source):
                    results = []
                    for exe in (reference, target):
                        run = subprocess.run([exe, '-c', expression], input=json.dumps(source),
                                             text=True, capture_output=True, timeout=10)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stderr, '')
                        results.append([json.loads(line) for line in run.stdout.splitlines()])
                    self.assertEqual(results[0], results[1])

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
