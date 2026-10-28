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


if __name__ == '__main__':
    unittest.main()
