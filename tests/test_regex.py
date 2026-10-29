"""Small black-box samples for a regex adapter; not full engine acceptance."""

import json
import os
import shutil
import subprocess
import unittest


class RegexSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get('RECIPKG_TEST_REGEX_ADAPTER')
        if selected is None:
            raise unittest.SkipTest('set RECIPKG_TEST_REGEX_ADAPTER to a candidate adapter')
        cls.adapter = shutil.which(selected)
        if cls.adapter is None:
            raise RuntimeError('RECIPKG_TEST_REGEX_ADAPTER executable not found')
        version = subprocess.run([cls.adapter, '--version'], capture_output=True, text=True, timeout=20)
        if version.returncode != 0 or not version.stdout.strip():
            raise RuntimeError('regex adapter did not report its version')
        print('regex adapter:', version.stdout.strip())

    def invoke(self, pattern, text):
        p = subprocess.run([self.adapter, pattern, text], capture_output=True, text=True, timeout=20)
        return p.returncode, json.loads(p.stdout)

    def invoke_bytes(self, pattern, data):
        p = subprocess.run([self.adapter, '--bytes', pattern, data.hex()],
                           capture_output=True, text=True, timeout=20)
        return p.returncode, json.loads(p.stdout)

    def invoke_captures(self, pattern, text):
        p = subprocess.run([self.adapter, '--captures', pattern, text],
                           capture_output=True, text=True, timeout=20)
        return p.returncode, json.loads(p.stdout)

    def invoke_replace(self, mode, pattern, text, replacement):
        p = subprocess.run([self.adapter, mode, pattern, text, replacement],
                           capture_output=True, text=True, timeout=20)
        return p.returncode, json.loads(p.stdout)

    def test_alternation_and_greed(self):
        cases = [('sam|samwise', 'samwise', [[0, 3]]),
                 ('samwise|sam', 'samwise', [[0, 7]]),
                 ('a+', 'baaa', [[1, 4]]),
                 ('a+?', 'baaa', [[1, 2], [2, 3], [3, 4]]),
                 ('a|aa', 'aa', [[0, 1], [1, 2]])]
        for pattern, text, ranges in cases:
            with self.subTest(pattern=pattern, text=text):
                self.assertEqual(self.invoke(pattern, text), (0, {'matches': ranges}))

    def test_utf8_empty_and_unicode(self):
        cases = [('', 'éx', [[0, 0], [2, 2], [3, 3]]),
                 ('a*', 'baa', [[0, 0], [1, 3]]),
                 (r'\w+', 'abcé', [[0, 5]]),
                 (r'(?-u:\w+)', 'abcé', [[0, 3]]),
                 ('(?i)é', 'Éé', [[0, 2], [2, 4]]),
                 (r'\b', 'é x', [[0, 0], [2, 2], [3, 3], [4, 4]])]
        for pattern, text, ranges in cases:
            with self.subTest(pattern=pattern, text=text):
                self.assertEqual(self.invoke(pattern, text), (0, {'matches': ranges}))

    def test_anchors_and_no_match(self):
        self.assertEqual(self.invoke('^a$', 'a\na'), (0, {'matches': []}))
        self.assertEqual(self.invoke('(?m)^a$', 'a\na'), (0, {'matches': [[0, 1], [2, 3]]}))
        self.assertEqual(self.invoke('xyz', 'abc'), (0, {'matches': []}))

    def test_unsupported_or_invalid_patterns(self):
        for pattern in ('(?=a)', r'(a)\1', '['):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.invoke(pattern, 'aa'), (2, {'error': 'compile'}))

    def test_byte_mode_empty_matches_can_split_utf8(self):
        self.assertEqual(self.invoke('', 'éx'), (0, {'matches': [[0, 0], [2, 2], [3, 3]]}))
        self.assertEqual(self.invoke_bytes('', 'éx'.encode()),
                         (0, {'matches': [[0, 0], [1, 1], [2, 2], [3, 3]]}))
        self.assertEqual(self.invoke_bytes('', b'\xff'), (0, {'matches': [[0, 0], [1, 1]]}))

    def test_byte_mode_unicode_and_raw_bytes(self):
        data = b'\xffa\xc3\xa9'
        self.assertEqual(self.invoke_bytes('.', data), (0, {'matches': [[1, 2], [2, 4]]}))
        self.assertEqual(self.invoke_bytes(r'(?-u:.)', data),
                         (0, {'matches': [[0, 1], [1, 2], [2, 3], [3, 4]]}))
        self.assertEqual(self.invoke_bytes(r'(?-u:\xFF)', b'a\xffb\xff'),
                         (0, {'matches': [[1, 2], [3, 4]]}))
        self.assertEqual(self.invoke_bytes(r'\xFF', b'\xff\xc3\xbf'),
                         (0, {'matches': [[1, 3]]}))

    def test_byte_mode_unicode_word_and_invalid_pattern(self):
        data = b'\xffabc\xc3\xa9'
        self.assertEqual(self.invoke_bytes(r'\w+', data), (0, {'matches': [[1, 6]]}))
        self.assertEqual(self.invoke_bytes(r'(?-u:\w+)', data), (0, {'matches': [[1, 4]]}))
        self.assertEqual(self.invoke_bytes('(?=a)', data), (2, {'error': 'compile'}))

    def test_capture_names_numbering_and_nonoverlapping_matches(self):
        self.assertEqual(
            self.invoke_captures(r'(?<first>[A-Z][a-z]+) (?<last>[A-Z][a-z]+)',
                                 'Ada Lovelace; Alan Turing'),
            (0, {'names': [None, 'first', 'last'],
                 'captures': [[[0, 12], [0, 3], [4, 12]],
                              [[14, 25], [14, 18], [19, 25]]]}))

    def test_unmatched_optional_capture_is_null(self):
        self.assertEqual(
            self.invoke_captures(r'(?<letter>a)(?<optional>b)?', 'ab a'),
            (0, {'names': [None, 'letter', 'optional'],
                 'captures': [[[0, 2], [0, 1], [1, 2]],
                              [[3, 4], [3, 4], None]]}))

    def test_capture_ranges_use_utf8_byte_offsets(self):
        self.assertEqual(self.invoke_captures(r'(?<word>\w+)', 'éx'),
                         (0, {'names': [None, 'word'],
                              'captures': [[[0, 3], [0, 3]]]}))

    def test_first_and_all_replacement_expansion(self):
        self.assertEqual(self.invoke_replace('--replace-first', r'\d+', 'a1 b22', '<$0>'),
                         (0, {'text': 'a<1> b22'}))
        self.assertEqual(self.invoke_replace('--replace-all', r'\d+', 'a1 b22', '<$0>'),
                         (0, {'text': 'a<1> b<22>'}))
        self.assertEqual(self.invoke_replace('--replace-all', r'([a-z])(\d+)',
                                             'a12 b34', '$2:$1'),
                         (0, {'text': '12:a 34:b'}))
        self.assertEqual(
            self.invoke_replace('--replace-all', r'(?<first>deep) (?<second>fried)',
                                'deep fried', '${first}_$second|$missing|$$'),
            (0, {'text': 'deep_fried||$'}))
        self.assertEqual(self.invoke_replace('--replace-all', 'xyz', 'unchanged', 'x'),
                         (0, {'text': 'unchanged'}))


if __name__ == '__main__':
    unittest.main()
