"""Black-box samples for observed upstream recipe contracts.

These tests are partial and must not be interpreted as complete compatibility.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def executable(variable, default):
    name = os.environ.get(variable, default)
    path = shutil.which(name)
    if path is None:
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


class RipgrepSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rg = executable('RECIPKG_TEST_RG', 'rg')
        cls.git = executable('RECIPKG_TEST_GIT', 'git')
        print('ripgrep target:', command([cls.rg, '--version']).stdout.splitlines()[0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='recipkg-rg-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.env.update(RIPGREP_CONFIG_PATH=os.devnull, GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_SYSTEM=os.devnull, LC_ALL='C')
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


class FFmpegSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = executable('RECIPKG_TEST_FFMPEG', 'ffmpeg')
        cls.ffprobe = executable('RECIPKG_TEST_FFPROBE', 'ffprobe')
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


if __name__ == '__main__':
    unittest.main()
