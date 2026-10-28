"""Black-box samples for observed upstream recipe contracts.

These tests are partial and must not be interpreted as complete compatibility.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave


def executable(variable, default, *, required=False):
    name = os.environ.get(variable, default)
    path = shutil.which(name)
    if path is None:
        if variable in os.environ or required:
            raise RuntimeError(f"required executable not found: {name!r} ({variable})")
        raise unittest.SkipTest(f"missing executable: {name} ({variable})")
    return path


def command(args, *, cwd=None, input=None, env=None):
    return subprocess.run(args, cwd=cwd, input=input, text=True, capture_output=True,
                          env=env, timeout=30)


class JqSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jq = executable('RECIPKG_TEST_JQ', 'jq')
        print('jq target:', command([cls.jq, '--version']).stdout.strip())

    def invoke(self, args, input=None):
        return command([self.jq, *args], input=input)

    def test_filter_raw_slurp_and_variables(self):
        result = self.invoke(['-c', '.items[] | select(.n > 1) | .name'],
                             '{"items":[{"n":1,"name":"a"},{"n":2,"name":"b"}]}')
        self.assertEqual((result.returncode, result.stdout), (0, '"b"\n'))
        result = self.invoke(['-r', '.x'], '{"x":"hello"}')
        self.assertEqual((result.returncode, result.stdout), (0, 'hello\n'))
        result = self.invoke(['-s', 'length'], '1\n2\n3\n')
        self.assertEqual((result.returncode, result.stdout), (0, '3\n'))
        result = self.invoke(['-n', '--arg', 'n', '123', '--argjson', 'x', '123', '[$n,$x]'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['123', 123])

    def test_exit_status_and_invalid_json(self):
        for expression, expected in [('true', 0), ('false', 1), ('null', 1), ('empty', 4)]:
            with self.subTest(expression=expression):
                result = self.invoke(['-ne', expression])
                self.assertEqual(result.returncode, expected, result.stderr)
        result = self.invoke(['-c', '.'], '{invalid}')
        self.assertEqual(result.returncode, 5)
        self.assertTrue(result.stderr)
        self.assertEqual(result.stdout, '')

    def test_assignment_streams_paths_and_precedence(self):
        cases = [
            ('.a = .b', {'a': {'b': 10}, 'b': 20}, [{'a': 20, 'b': 20}]),
            ('.a |= .b', {'a': {'b': 10}, 'b': 20}, [{'a': 10, 'b': 20}]),
            ('.a = (1,2)', {'a': 0}, [{'a': 1}, {'a': 2}]),
            ('.a |= (1,2)', {'a': 0}, [{'a': 1}]),
            ('.a |= empty', {'a': 1, 'b': 2}, [{'b': 2}]),
            ('.a = empty', {'a': 1, 'b': 2}, []),
            ('.items[] |= .+1', {'items': [1, 2, 3]}, [{'items': [2, 3, 4]}]),
            ('(.a,.b)=0', {'a': 1, 'b': 2}, [{'a': 0, 'b': 0}]),
            ('.a,.b=0', {'a': 1, 'b': 2}, [1, {'a': 1, 'b': 0}]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.invoke(['-c', expression], json.dumps(source))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([json.loads(line) for line in result.stdout.splitlines()], expected)
                self.assertEqual(result.stderr, '')

    def test_optional_and_catch(self):
        cases = [('[.[]|.a?]', [{}, True, {'a': 1}], [None, 1]),
                 ('[.[]|try tonumber catch "bad"]', ['1', 'invalid', '3', 4], [1, 'bad', 3, 4])]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.invoke(['-c', expression], json.dumps(source))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)
                self.assertEqual(result.stderr, '')

    def test_conditions_alternatives_and_comparisons(self):
        cases = [
            ('[.[] | if . then "yes" else "no" end]',
             [False, None, 0, '', [], {}], [['no', 'no', 'yes', 'yes', 'yes', 'yes']]),
            ('if (true,false) then "T" else "F" end', 'original', ['T', 'F']),
            ('if empty then 1 else 2 end', None, []),
            ('if false then 1 end', {'x': 1}, [{'x': 1}]),
            ('if (1,2) then . else 0 end', {'x': 1}, [{'x': 1}, {'x': 1}]),
            ('[(false,null,0,"",[],{}) // "default"]', None, [[0, '', [], {}]]),
            ('[(false,null,empty) // (1,2)]', None, [[1, 2]]),
            ('[false, true // "default"]', None, [[False, True]]),
            ('[(false,true) // "default"]', None, [[True]]),
            ('[(false,null,true) | . // "default"]', None, [['default', 'default', True]]),
            ('[(true,false) and (true,false)]', None, [[True, False, False]]),
            ('[(false,true) or (true,false)]', None, [[True, False, True]]),
            ('false and error("bad")', None, [False]),
            ('true or error("bad")', None, [True]),
            ('[(null,false,0,"",[],{}) | not]', None, [[True, True, False, False, False, False]]),
            ('[1 == "1",1==1.0,{"a":1,"b":2} == {"b":2,"a":1}]', None,
             [[False, True, True]]),
            ('[{},true,[],0,false,"a",null] | sort', None, [[None, False, True, 0, 'a', [], {}]]),
            ('[[1,2] < [1,3], {"a":1} < {"b":0}, 1 < "0"]', None, [[True, True, True]]),
            ('[(1,2) < (2,3)]', None, [[True, False, True, True]]),
            ('[1==1.0, [true]==[1], {"a":true}=={"a":1}]', None, [[True, False, False]]),
            ('if false then 1 elif true then 2 end', None, [2]),
            ('[false and (1,2), true or empty]', None, [[False, True]]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                result = self.invoke(['-c', expression], json.dumps(source))
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(json.dumps(actual, sort_keys=True), json.dumps(expected, sort_keys=True))
                self.assertEqual(result.stderr, '')
        result = self.invoke(['-c', 'true and error("bad")'], 'null')
        self.assertEqual((result.returncode, result.stdout), (5, ''))
        self.assertIn('bad', result.stderr)

    def test_bindings_functions_and_reductions(self):
        cases = [
            ('.[] as $x | [$x, .]', [1, 2], [[1, [1, 2]], [2, [1, 2]]]),
            ('.foo as $x | .bar | [$x,.]', {'foo': 1, 'bar': 2}, [[1, 2]]),
            ('(.+1) as $x | (.*2) as $x | [$x,.]', 5, [[10, 5]]),
            ('.[] as [$a,$b] | [$a,$b,.]', [[1], [1, 2], [3, 4, 5]],
             [[1, None, [[1], [1, 2], [3, 4, 5]]],
              [1, 2, [[1], [1, 2], [3, 4, 5]]], [3, 4, [[1], [1, 2], [3, 4, 5]]]]),
            ('.[] as {$a,$b} | [$a,$b,.]', [{'a': 1}, {'b': 2}],
             [[1, None, [{'a': 1}, {'b': 2}]], [None, 2, [{'a': 1}, {'b': 2}]]]),
            ('def foo(f): f|f; 5|foo(.*2)', None, [20]),
            ('def f(x): [x,x]; f((1,2))', None, [[1, 2, 1, 2]]),
            ('def f($x): [$x,$x]; f((1,2))', None, [[1, 1], [2, 2]]),
            ('def f: 1; def f: 2; f', None, [2]),
            ('def f: 1; def f(x): x+1; [f, f(2)]', None, [[1, 3]]),
            ('def f: .+1; def g: f; def f: .+10; [g,f]', 0, [[1, 10]]),
            ('def fact: if .==0 then 1 else . * ((.-1)|fact) end; fact', 5, [120]),
            ('reduce .[] as $x (0; .+$x)', [1, 2, 3], [6]),
            ('reduce .[] as $x (0; .+$x)', [], [0]),
            ('reduce .[] as [$a,$b] (0; .+$a*$b)', [[1, 2], [3, 4]], [14]),
            ('reduce .[] as $x (0; (.+$x, .+100))', [1, 2], [200]),
            ('reduce .[] as $x (0; empty)', [1, 2], [None]),
            ('foreach .[] as $x (0; .+$x)', [1, 2, 3], [1, 3, 6]),
            ('foreach .[] as $x (0; .+$x; [$x,.])', [1, 2, 3], [[1, 1], [2, 3], [3, 6]]),
            ('foreach .[] as $x (0; .+$x)', [], []),
            ('foreach .[] as $x (0; (.+$x, .+100))', [1, 2], [1, 100, 102, 200]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.invoke(['-c', expression], json.dumps(source))
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(json.dumps(actual, sort_keys=True), json.dumps(expected, sort_keys=True))
                self.assertEqual(result.stderr, '')
        result = self.invoke(['-c', '(. as $x | .+1) | $x'], '5')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertTrue(result.stderr)

    def test_binding_and_reduction_boundaries(self):
        cases = [
            ('[.[] as [$a,$b] | [$a,$b]]', [[1], [], [3, 4, 5]], [[[1, None], [None, None], [3, 4]]]),
            ('[.[] as [$a,$b] | [$a,$b]]', [None], [[[None, None]]]),
            ('[(1,2) as $x | ($x,.),$x]', 10, [[1, 10, 1, 2, 10, 2]]),
            ('reduce .[] as $x (0; (.,.+$x))', [1, 2, 3], [6]),
            ('foreach .[] as $x (0; (.,.+$x))', [1, 2, 3], [0, 1, 1, 3, 3, 6]),
            ('foreach .[] as $x (0; empty)', [1, 2, 3], []),
            ('reduce (1,2) as $x ((0,10); .+$x)', None, [3, 13]),
            ('reduce (.[]? // 9) as $x ((0,10); .+$x)', [1, 2], [3, 19]),
            ('foreach .[] as $x ((0,10); .+$x)', [1, 2], [1, 3, 11, 13]),
            ('foreach .[] as $x (0; .+$x; (., .+10))', [1, 2], [1, 11, 3, 13]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                result = self.invoke(['-c', expression], json.dumps(source))
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(json.dumps(actual, sort_keys=True), json.dumps(expected, sort_keys=True))
                self.assertEqual(result.stderr, '')
        invalid = self.invoke(['-c', '[.[] as [$a,$b] | [$a,$b]]'], '[5]')
        self.assertEqual((invalid.returncode, invalid.stdout), (5, ''))
        self.assertTrue(invalid.stderr)
        for expression in ('$missing', '(. as $x | .+1) | $x'):
            with self.subTest(expression=expression):
                result = self.invoke(['-c', expression], '')
                self.assertEqual((result.returncode, result.stdout), (3, ''))
                self.assertTrue(result.stderr)
        result = self.invoke(['-c', 'reduce .[] as $x ((0,10); .+$x)'], '[1,2]')
        self.assertEqual((result.returncode, result.stdout), (5, '3\n'))
        self.assertTrue(result.stderr)

    def test_stream_records_and_parse_failure(self):
        result = self.invoke(['-c', '--stream', '.'], '["a",["b"]]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()],
                         [[[0], 'a'], [[1, 0], 'b'], [[1, 0]], [[1]]])
        malformed = '["a",n]'
        result = self.invoke(['-c', '--stream', '.'], malformed)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(json.loads(result.stdout), [[0], 'a'])
        self.assertTrue(result.stderr)
        result = self.invoke(['-c', '--stream-errors', '.'], malformed)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(records[0], [[0], 'a'])
        self.assertEqual(records[1][1], [1])
        self.assertIsInstance(records[1][0], str)
        self.assertTrue(records[1][0])
        self.assertEqual(result.stderr, '')

    def test_raw_inputs_and_nul_output(self):
        for args, expected in [(['-Rc', '.'], '"hello"\n""\n"world"\n'),
                               (['-Rsc', '.'], '"hello\\n\\nworld"\n')]:
            result = self.invoke(args, 'hello\n\nworld')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        result = self.invoke(['-n', '--raw-output0', '"a\\nb",42'])
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'a\nb\0' + '42\0', ''))
        result = self.invoke(['-n', '--raw-output0', '"bad\\u0000text"'])
        self.assertEqual((result.returncode, result.stdout), (5, ''))
        self.assertTrue(result.stderr)

    def test_input_consumption_and_multiple_files(self):
        result = self.invoke(['-cn', '[inputs]'], '1 2 3')
        self.assertEqual((result.returncode, result.stdout), (0, '[1,2,3]\n'))
        result = self.invoke(['-c', '[inputs]'], '1 2 3')
        self.assertEqual((result.returncode, result.stdout), (0, '[2,3]\n'))
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-files-') as tmp:
            root = Path(tmp)
            (root / 'a.json').write_text('1\n2\n', encoding='utf-8')
            (root / 'b.json').write_text('4\n', encoding='utf-8')
            result = command([self.jq, '-c', '.', 'a.json', '-', 'b.json'], cwd=root, input='3\n')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '1\n2\n3\n4\n', ''))
            result = command([self.jq, '-c', '.', 'missing.json', 'b.json'], cwd=root, input='')
            self.assertEqual((result.returncode, result.stdout), (2, '4\n'))
            self.assertTrue(result.stderr)
        for data, expected in [('true\nfalse\n', 1), ('false\ntrue\n', 0)]:
            result = self.invoke(['-ce', '.'], data)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (expected, data, ''))

    def test_input_and_slurp_interactions(self):
        for args, source, expected in [
            (['-cn', '[input,input]'], '1 2 3', '[1,2]\n'),
            (['-c', '[.,input]'], '1 2 3 4', '[1,2]\n[3,4]\n'),
            (['-cn', '[input?]'], '', '[]\n'),
            (['-csn', '[inputs]'], '1 2 3', '[[1,2,3]]\n'),
            (['-Rcn', '[inputs]'], 'abc\n\nx\n', '["abc","","x"]\n'),
            (['-Rscn', '[inputs]'], 'abc\n\nx\n', '["abc\\n\\nx\\n"]\n'),
        ]:
            with self.subTest(args=args):
                result = self.invoke(args, source)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-slurp-') as tmp:
            root = Path(tmp)
            (root / 'a').write_text('1\n2\n', encoding='utf-8')
            (root / 'b').write_text('3\n', encoding='utf-8')
            for args, expected in [(['-sc', '.', 'a', 'b'], '[1,2,3]\n'),
                                   (['-Rsc', '.', 'a', 'b'], '"1\\n2\\n3\\n"\n'),
                                   (['-nc', '[inputs]', 'a', 'b'], '[1,2,3]\n'),
                                   (['-nc', '1', 'missing'], '1\n')]:
                with self.subTest(args=args):
                    result = command([self.jq, *args], cwd=root, input='')
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
            result = command([self.jq, '-ce', '.', 'missing', 'b'], cwd=root, input='')
            self.assertEqual((result.returncode, result.stdout), (2, '3\n'))
            self.assertTrue(result.stderr)
            for first, second, args, expected in [
                ('[', '1]', ['-c', '.'], '[1]\n'),
                ('1', '2', ['-c', '.'], '12\n'),
                ('abc', 'def\nxyz', ['-Rc', '.'], '"abcdef"\n"xyz"\n'),
            ]:
                (root / 'a').write_text(first, encoding='utf-8')
                (root / 'b').write_text(second, encoding='utf-8')
                result = command([self.jq, *args, 'a', 'b'], cwd=root, input='')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        result = self.invoke(['-n', '--raw-output0', '"one","bad\\u0000text","after"'])
        self.assertEqual((result.returncode, result.stdout), (5, 'one\0'))
        self.assertTrue(result.stderr)

    def test_json_parsing_boundaries(self):
        cases = [
            (b'{"a":1,"a":2}', b'{"a":2}\n'),
            (b'1 2 {}[]', b'1\n2\n{}\n[]\n'),
            (b'01', b'1\n'),
            (b'-.2', b'-0.2\n'),
            (b'+1', b'1\n'),
            (b'"\\uD83D\\uDE00"', '"😀"\n'.encode()),
            (b'"\\uDC00"', '"�"\n'.encode()),
            (b'"a\\u0000b"', b'"a\\u0000b"\n'),
            (b'"\xff"', '"�"\n'.encode()),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                result = subprocess.run([self.jq, '-c', '.'], input=source,
                                        capture_output=True, timeout=30)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, b''))
        failures = [(b'1e', b''), (b'"\\uD800"', b''), (b'"line\nline"', b''),
                    (b'"\\q"', b''), (b'"a\0b"', b''), (b'{"x":1,}', b''),
                    (b'[1,]', b''), (b'[] {"x":', b'[]\n'), (b'1 garbage 2', b'1\n')]
        for source, expected in failures:
            with self.subTest(source=source):
                result = subprocess.run([self.jq, '-c', '.'], input=source,
                                        capture_output=True, timeout=30)
                self.assertEqual((result.returncode, result.stdout), (5, expected))
                self.assertTrue(result.stderr)

    def test_decnum_literal_and_arithmetic(self):
        capability = self.invoke(['-n', 'have_decnum'])
        self.assertEqual(capability.returncode, 0, capability.stderr)
        self.assertIn(capability.stdout.strip(), ('true', 'false'))
        if capability.stdout.strip() == 'false':
            self.skipTest('samples require a target built with decnum')
        source = '9007199254740993 123456789012345678901234567890'
        result = self.invoke(['-c', '.'], source)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, '9007199254740993\n123456789012345678901234567890\n', ''))
        result = self.invoke(['-cn', '[9007199254740993 == 9007199254740992, (9007199254740993|.+0)]'])
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '[false,9007199254740992]\n', ''))

    def test_json_sequence_error_recovery(self):
        source = b'\x1e1\n\x1e{bad}\n\x1e{"ok":2}\n'
        result = subprocess.run([self.jq, '--seq', '-c', '.'], input=source,
                                capture_output=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout), (0, b'\x1e1\n\x1e{"ok":2}\n'))
        self.assertTrue(result.stderr)


class RipgrepSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rg = executable('RECIPKG_TEST_RG', 'rg')
        cls.git = executable('RECIPKG_TEST_GIT', 'git', required='RECIPKG_TEST_RG' in os.environ)
        print('ripgrep target:', command([cls.rg, '--version']).stdout.splitlines()[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='recipkg-rg-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                     'GIT_CONFIG_COUNT', 'GIT_CEILING_DIRECTORIES'):
            self.env.pop(name, None)
        self.env.update(RIPGREP_CONFIG_PATH=os.devnull, GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_SYSTEM=os.devnull, LC_ALL='C', HOME=str(self.root),
                        XDG_CONFIG_HOME=str(self.root / '.config'))
        result = command([self.git, 'init', '-q'], cwd=self.root, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
        (self.root / 'normal.txt').write_text('alpha\nNeedle one\nneedle two\n', encoding='utf-8')
        (self.root / 'ignored.txt').write_text('needle ignored\n', encoding='utf-8')
        (self.root / '.hidden.txt').write_text('needle hidden\n', encoding='utf-8')
        (self.root / 'binary.dat').write_bytes(b'needle\x00binary\n')

    def invoke(self, *args):
        return command([self.rg, '--color=never', *args], cwd=self.root, env=self.env)

    def test_scope_and_case(self):
        cases = [([], {'./normal.txt:3:needle two'}),
                 (['-u'], {'./normal.txt:3:needle two', './ignored.txt:1:needle ignored'}),
                 (['--hidden'], {'./normal.txt:3:needle two', './.hidden.txt:1:needle hidden'})]
        for flags, expected in cases:
            with self.subTest(flags=flags):
                result = self.invoke('-n', *flags, 'needle', '.')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(result.stdout.splitlines()), expected)
        result = self.invoke('-n', '-i', 'needle', 'normal.txt')
        self.assertEqual(result.stdout.splitlines(), ['2:Needle one', '3:needle two'])

    def test_json_and_errors(self):
        result = self.invoke('--json', 'needle', 'normal.txt')
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event['type'] for event in events], ['begin', 'match', 'end', 'summary'])
        match = events[1]['data']
        self.assertEqual(match['path']['text'], 'normal.txt')
        self.assertEqual(match['line_number'], 3)
        self.assertEqual(match['lines']['text'], 'needle two\n')
        self.assertEqual((match['submatches'][0]['start'], match['submatches'][0]['end']), (0, 6))
        self.assertEqual(self.invoke('missing', 'normal.txt').returncode, 1)
        invalid = self.invoke('(', 'normal.txt')
        self.assertEqual(invalid.returncode, 2)
        self.assertTrue(invalid.stderr)

    def test_stdin_literal_and_json_byte_offsets(self):
        data = 'prefix\ncafé cafe\n'.encode('utf-8')
        result = subprocess.run([self.rg, '--color=never', '--json', 'é|e'],
                                cwd=self.root, env=self.env, input=data, capture_output=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event['type'] for event in events],
                         ['begin', 'match', 'match', 'end', 'summary'])
        match = events[2]['data']
        self.assertEqual(match['path'], {'text': '<stdin>'})
        self.assertEqual((match['line_number'], match['absolute_offset']), (2, 7))
        self.assertEqual(match['lines'], {'text': 'café cafe\n'})
        self.assertEqual([(x['match'], x['start'], x['end']) for x in match['submatches']],
                         [({'text': 'é'}, 3, 5), ({'text': 'e'}, 9, 10)])
        for flags, expected in [(['-F'], '1:a.b\n'), ([], '1:a.b\n2:axb\n')]:
            result = command([self.rg, '--color=never', '-n', *flags, 'a.b'],
                             cwd=self.root, env=self.env, input='a.b\naxb\n')
            self.assertEqual((result.returncode, result.stdout), (0, expected), result.stderr)

    def test_json_non_utf8_data(self):
        result = subprocess.run([self.rg, '--color=never', '--json', 'hit'],
                                cwd=self.root, env=self.env, input=b'\xff hit\n',
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        match = next(event['data'] for event in events if event['type'] == 'match')
        self.assertEqual(base64.b64decode(match['lines']['bytes']), b'\xff hit\n')
        self.assertEqual(match['submatches'][0], {'match': {'text': 'hit'}, 'start': 2, 'end': 5})

    @unittest.skipUnless(os.name == 'posix', 'non-UTF-8 filenames require POSIX bytes paths')
    def test_json_non_utf8_filename(self):
        filename = b'bad-\xff.txt'
        fd = os.open(os.fsencode(self.root) + b'/' + filename, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(b'hit\n')
        result = self.invoke('--json', 'hit', os.fsdecode(filename))
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        match = next(event['data'] for event in events if event['type'] == 'match')
        self.assertEqual(base64.b64decode(match['path']['bytes']), filename)
        self.assertEqual(match['lines'], {'text': 'hit\n'})

    def test_partial_file_error_and_quiet(self):
        result = self.invoke('-n', 'needle', 'normal.txt', 'missing.txt')
        self.assertEqual(result.returncode, 2)
        self.assertIn('normal.txt:3:needle two', result.stdout)
        self.assertIn('missing.txt', result.stderr)
        quiet = self.invoke('-q', 'needle', 'normal.txt', 'missing.txt')
        self.assertEqual(quiet.returncode, 0)
        self.assertEqual(quiet.stdout, '')

    def make_scope(self):
        scope = self.root / 'scope'
        scope.mkdir()
        paths = ['plain.txt', 'x.log', 'keep.log', 'ignored-by-ignore.txt', 'rg-only.txt',
                 '.hidden.txt', 'nested/parent-ignored.txt', 'nested/other.log']
        for name in paths:
            path = scope / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('needle\n', encoding='utf-8')
        (scope / '.gitignore').write_text('*.log\nparent-ignored.txt\n', encoding='utf-8')
        (scope / '.ignore').write_text('!keep.log\nignored-by-ignore.txt\n', encoding='utf-8')
        (scope / '.rgignore').write_text('!ignored-by-ignore.txt\nrg-only.txt\n', encoding='utf-8')
        (scope / 'nested/.ignore').write_text('!parent-ignored.txt\n', encoding='utf-8')
        (scope / 'binary.dat').write_bytes(b'needle\x00binary\n')

    def scope_result(self, *flags):
        result = self.invoke('-l', *flags, 'needle', 'scope')
        self.assertEqual(result.returncode, 0, result.stderr)
        return set(result.stdout.splitlines())

    def test_ignore_precedence_and_unrestricted_levels(self):
        self.make_scope()
        visible = {'scope/ignored-by-ignore.txt', 'scope/keep.log',
                   'scope/nested/parent-ignored.txt', 'scope/plain.txt'}
        self.assertEqual(self.scope_result(), visible)
        ignored = {'scope/nested/other.log', 'scope/rg-only.txt', 'scope/x.log'}
        self.assertEqual(self.scope_result('-u'), visible | ignored)
        self.assertEqual(self.scope_result('-uu'), visible | ignored | {'scope/.hidden.txt'})
        self.assertEqual(self.scope_result('-uuu'), visible | ignored | {'scope/.hidden.txt', 'scope/binary.dat'})
        self.assertEqual(self.scope_result('--no-ignore-dot'),
                         {'scope/ignored-by-ignore.txt', 'scope/plain.txt', 'scope/rg-only.txt'})
        self.assertEqual(self.scope_result('--no-ignore-vcs'),
                         visible | {'scope/nested/other.log', 'scope/x.log'})

    def test_glob_override_order_and_explicit_paths(self):
        self.make_scope()
        self.assertEqual(self.scope_result('-g', '*.log'),
                         {'scope/keep.log', 'scope/nested/other.log', 'scope/x.log'})
        selected = {'scope/.hidden.txt', 'scope/ignored-by-ignore.txt',
                    'scope/nested/parent-ignored.txt', 'scope/rg-only.txt'}
        self.assertEqual(self.scope_result('-g', '*.txt', '-g', '!plain.txt'), selected)
        self.assertEqual(self.scope_result('-g', '!plain.txt', '-g', '*.txt'), selected | {'scope/plain.txt'})
        for path in ('scope/x.log', 'scope/rg-only.txt', 'scope/.hidden.txt'):
            result = self.invoke('needle', path)
            self.assertEqual((result.returncode, result.stdout), (0, 'needle\n'))
        binary = self.invoke('-n', 'needle', 'scope/binary.dat')
        self.assertEqual(binary.returncode, 0)
        self.assertIn('binary file matches', binary.stdout)
        text = self.invoke('-n', '--text', 'needle', 'scope/binary.dat')
        self.assertEqual((text.returncode, text.stdout), (0, '1:needle\x00binary\n'))

    def test_gitignore_requires_repository_by_default(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-rg-nogit-') as temp:
            directory = Path(temp)
            (directory / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
            (directory / 'ignored.txt').write_text('needle\n', encoding='utf-8')
            (directory / 'plain.txt').write_text('needle\n', encoding='utf-8')
            for flags, expected in [([], {'./ignored.txt', './plain.txt'}),
                                    (['--no-require-git'], {'./plain.txt'})]:
                with self.subTest(flags=flags):
                    result = command([self.rg, '--color=never', '-l', *flags, 'needle', '.'],
                                     cwd=directory, env=self.env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(set(result.stdout.splitlines()), expected)


class FFmpegSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = [name in os.environ for name in ('RECIPKG_TEST_FFMPEG', 'RECIPKG_TEST_FFPROBE')]
        if any(selected) and not all(selected):
            raise RuntimeError('set both RECIPKG_TEST_FFMPEG and RECIPKG_TEST_FFPROBE for candidate testing')
        cls.ffmpeg = executable('RECIPKG_TEST_FFMPEG', 'ffmpeg')
        cls.ffprobe = executable('RECIPKG_TEST_FFPROBE', 'ffprobe', required=any(selected))
        print('ffmpeg target:', command([cls.ffmpeg, '-version']).stdout.splitlines()[0])
        print('ffprobe target:', command([cls.ffprobe, '-version']).stdout.splitlines()[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='recipkg-ffmpeg-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def ff(self, *args, check=True):
        result = command([self.ffmpeg, '-hide_banner', '-loglevel', 'error', *args], cwd=self.root)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def probe(self, name):
        result = command([self.ffprobe, '-v', 'error', '-select_streams', 'a',
                          '-show_entries', 'stream=codec_name,sample_rate,channels:stream_disposition=default',
                          '-of', 'json', name], cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['streams']

    def stream_hash(self, name, index=0):
        return self.ff('-i', name, '-map', f'0:a:{index}', '-c:a', 'copy',
                       '-f', 'hash', '-hash', 'sha256', '-').stdout.strip()

    def make_input(self, name, first_default):
        self.ff('-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.25',
                '-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.25',
                '-map', '0:a', '-map', '1:a', '-c:a', 'pcm_s16le',
                '-ac:a:0', '1', '-ac:a:1', '2',
                '-disposition:a:0', 'default' if first_default else '0',
                '-disposition:a:1', '0' if first_default else 'default', name)

    def test_audio_default_and_copy(self):
        for first_default in (True, False):
            with self.subTest(first_default=first_default):
                name = f'in-{first_default}.mkv'
                out = f'auto-{first_default}.mkv'
                self.make_input(name, first_default)
                self.ff('-i', name, '-c:a', 'copy', out)
                expected_index = 0 if first_default else 1
                self.assertEqual(self.probe(out)[0]['channels'], expected_index + 1)
                self.assertEqual(self.stream_hash(out), self.stream_hash(name, expected_index))

    def test_multiple_inputs_negative_optional_and_missing(self):
        self.make_input('a.mkv', True)
        self.ff('-f', 'lavfi', '-i', 'sine=frequency=660:duration=0.25',
                '-c:a', 'pcm_s16le', '-ac', '2', 'b.mkv')
        self.ff('-i', 'a.mkv', '-i', 'b.mkv', '-c:a', 'copy', 'auto.mkv')
        self.assertEqual(self.stream_hash('auto.mkv'), self.stream_hash('b.mkv'))
        self.ff('-i', 'a.mkv', '-map', '0:a', '-map', '-0:a:0', '-c:a', 'copy', 'negative.mkv')
        self.ff('-i', 'a.mkv', '-map', '0:v?', '-map', '0:a:1', '-c:a', 'copy', 'optional.mkv')
        expected = self.stream_hash('a.mkv', 1)
        self.assertEqual(self.stream_hash('negative.mkv'), expected)
        self.assertEqual(self.stream_hash('optional.mkv'), expected)
        missing = self.ff('-i', 'a.mkv', '-map', '0:v', '-c:a', 'copy', 'missing.mkv', check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertTrue(missing.stderr)
        self.assertFalse((self.root / 'missing.mkv').exists())
        missing_input = self.ff('-i', 'a.mkv', '-map', '1:a?', '-c:a', 'copy', 'missing-input.mkv', check=False)
        self.assertNotEqual(missing_input.returncode, 0)
        self.assertFalse((self.root / 'missing-input.mkv').exists())

    def wav_samples(self, name):
        with wave.open(str(self.root / name), 'rb') as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 8000))
            data = audio.readframes(audio.getnframes())
            return struct.unpack('<' + 'h' * (len(data) // 2), data)

    def test_complex_audio_mix_and_split(self):
        for name, frequency, duration in [('a.wav', 440, '0.25'), ('b.wav', 880, '0.125')]:
            self.ff('-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=8000:duration={duration}',
                    '-c:a', 'pcm_s16le', name)
        a, b = self.wav_samples('a.wav'), self.wav_samples('b.wav')
        self.assertEqual((len(a), len(b)), (2000, 1000))
        self.ff('-i', 'a.wav', '-i', 'b.wav', '-filter_complex',
                '[0:a]volume=0.5[a0];[1:a]volume=0.5[a1];'
                '[a0][a1]amix=inputs=2:duration=shortest:normalize=0[mix]',
                '-map', '[mix]', '-c:a', 'pcm_s16le', 'mix.wav')
        mix = self.wav_samples('mix.wav')
        self.assertEqual(len(mix), len(b))
        self.assertTrue(any(mix), 'mixed signal must not be silent')
        self.assertLessEqual(max(abs(got - (left + right) / 2)
                                 for got, left, right in zip(mix, a, b)), 1.0)

        self.ff('-i', 'a.wav', '-filter_complex',
                '[0:a]asplit=2[a][b];[a]volume=0[sil];[b]volume=1[orig]',
                '-map', '[sil]', '-c:a', 'pcm_s16le', 'silent.wav',
                '-map', '[orig]', '-c:a', 'pcm_s16le', 'original.wav')
        self.assertEqual(self.wav_samples('silent.wav'), (0,) * len(a))
        self.assertEqual(self.wav_samples('original.wav'), a)

    def test_complex_filter_mapping_failures(self):
        self.ff('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000:duration=0.1',
                '-c:a', 'pcm_s16le', 'source.wav')
        for name, graph, mapping, codec in [
            ('missing.wav', '[0:a]volume=1[out]', '[missing]', 'pcm_s16le'),
            ('unconnected.wav', '[0:a]asplit=2[out][unused]', '[out]', 'pcm_s16le'),
            ('copy.wav', '[0:a]volume=0.5[out]', '[out]', 'copy'),
        ]:
            with self.subTest(name=name):
                result = self.ff('-i', 'source.wav', '-filter_complex', graph,
                                 '-map', mapping, '-c:a', codec, name, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
        duplicate = self.ff('-i', 'source.wav', '-filter_complex', '[0:a]volume=1[out]',
                            '-map', '[out]', 'first.wav', '-map', '[out]', 'second.wav', check=False)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertTrue(duplicate.stderr)

    def test_unlabeled_filter_output_and_explicit_mapping(self):
        self.ff('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000:duration=0.125',
                '-c:a', 'pcm_s16le', 'source.wav')
        self.ff('-i', 'source.wav', '-filter_complex', '[0:a]volume=0',
                '-c:a', 'pcm_s16le', 'auto.mkv')
        self.assertEqual(len(self.probe('auto.mkv')), 1)
        self.ff('-i', 'source.wav', '-filter_complex', '[0:a]volume=0',
                '-map', '0:a', '-c:a', 'pcm_s16le', 'mapped.mkv')
        self.assertEqual(len(self.probe('mapped.mkv')), 2)
        for index in (0, 1):
            self.ff('-i', 'mapped.mkv', '-map', f'0:a:{index}', '-c:a', 'pcm_s16le', f'track{index}.wav')
        self.assertEqual(self.wav_samples('track0.wav'), (0,) * 1000)
        self.assertEqual(self.wav_samples('track1.wav'), self.wav_samples('source.wav'))

    def make_rgb_frames(self):
        frames = [bytes(value for y in range(4) for x in range(4)
                        for value in (frame * 40, x * 50, y * 50))
                  for frame in range(4)]
        (self.root / 'source.rgb').write_bytes(b''.join(frames))
        return frames

    def raw_video_input(self):
        return ('-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '4x4',
                '-framerate', '4', '-i', 'source.rgb')

    def test_video_crop_and_nearest_scale_pixels(self):
        self.make_rgb_frames()
        self.ff(*self.raw_video_input(), '-vf', 'crop=2:2:1:1,scale=4:4:flags=neighbor',
                '-fps_mode', 'passthrough', '-c:v', 'rawvideo', '-pix_fmt', 'rgb24',
                '-f', 'rawvideo', 'cropped.rgb')
        expected = bytes(value for frame in range(4) for y in range(4) for x in range(4)
                         for value in (frame * 40, (1 + x // 2) * 50, (1 + y // 2) * 50))
        self.assertEqual((self.root / 'cropped.rgb').read_bytes(), expected)
        for index, crop in enumerate(('crop=5:5:0:0', 'crop=0:2:0:0')):
            with self.subTest(crop=crop):
                result = self.ff(*self.raw_video_input(), '-vf', crop, '-c:v', 'rawvideo',
                                 '-pix_fmt', 'rgb24', '-f', 'rawvideo', f'invalid-{index}.rgb', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)

    def test_video_fps_frame_selection(self):
        frames = self.make_rgb_frames()
        for rate, indices in [(8, [0, 0, 1, 1, 2, 2, 3, 3]), (2, [0, 2])]:
            with self.subTest(rate=rate):
                name = f'fps-{rate}.rgb'
                self.ff(*self.raw_video_input(), '-vf', f'fps={rate}', '-fps_mode', 'passthrough',
                        '-c:v', 'rawvideo', '-pix_fmt', 'rgb24', '-f', 'rawvideo', name)
                self.assertEqual((self.root / name).read_bytes(), b''.join(frames[i] for i in indices))

    def test_video_transcode_frame_data_and_timestamps(self):
        frames = self.make_rgb_frames()
        self.ff(*self.raw_video_input(), '-vf', 'fps=2', '-fps_mode', 'passthrough',
                '-c:v', 'ffv1', 'out.mkv')
        probe = command([self.ffprobe, '-v', 'error', '-select_streams', 'v:0',
                         '-show_entries', 'stream=codec_name,width,height:frame=best_effort_timestamp_time',
                         '-show_frames', '-of', 'json', 'out.mkv'], cwd=self.root)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        data = json.loads(probe.stdout)
        self.assertEqual([(s['codec_name'], s['width'], s['height']) for s in data['streams']],
                         [('ffv1', 4, 4)])
        self.assertEqual([float(f['best_effort_timestamp_time']) for f in data['frames']], [0.0, 0.5])
        self.ff('-i', 'out.mkv', '-fps_mode', 'passthrough', '-c:v', 'rawvideo',
                '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'decoded.rgb')
        self.assertEqual((self.root / 'decoded.rgb').read_bytes(), frames[0] + frames[2])


if __name__ == '__main__':
    unittest.main()
