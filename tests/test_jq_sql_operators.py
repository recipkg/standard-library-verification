"""Selected jq INDEX and JOIN SQL-style operator samples."""
import json
import os
import random
import shutil
import subprocess
import unittest


class JqSqlOperatorSamples(unittest.TestCase):
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

    def outputs(self, executable, expression, source):
        result = self.run_filter(executable, expression, source)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_index_keys_duplicates_and_multiple_keys(self):
        source = {'records': [
            {'id': 'first', 'aliases': ['x', 'y'], 'value': 1},
            {'id': 'x', 'aliases': ['x', 'z'], 'value': 2},
            {'id': 7, 'aliases': [7], 'value': 3},
        ]}
        indexed = self.outputs(self.target, 'INDEX(.records[]; .id)', source)
        self.assertEqual(indexed, [{
            'first': source['records'][0],
            'x': source['records'][1],
            '7': source['records'][2],
        }])
        aliases = self.outputs(self.target, 'INDEX(.records[]; .aliases[])', source)
        self.assertEqual(aliases, [{
            'x': source['records'][1],
            'y': source['records'][0],
            'z': source['records'][1],
            '7': source['records'][2],
        }])

    def test_join_pairs_custom_join_and_two_argument_form(self):
        source = {
            'users': [{'id': 'u1', 'name': 'Ada'}, {'id': 'u2', 'name': 'Lin'}],
            'posts': [{'user': 'u2', 'title': 'B'},
                      {'user': 'missing', 'title': 'C'},
                      {'user': 'u1', 'title': 'A'}],
        }
        pair_expr = ('. as $root | INDEX($root.users[]; .id) as $idx | '
                     'JOIN($idx; $root.posts[]; .user)')
        pairs = self.outputs(self.target, pair_expr, source)
        self.assertEqual(pairs, [
            [source['posts'][0], source['users'][1]],
            [source['posts'][1], None],
            [source['posts'][2], source['users'][0]],
        ])
        join_expr = ('. as $root | INDEX($root.users[]; .id) as $idx | '
                     'JOIN($idx; $root.posts[]; .user; .[0] + .[1])')
        joined = self.outputs(self.target, join_expr, source)
        self.assertEqual(joined, [
            {'user': 'u2', 'title': 'B', 'id': 'u2', 'name': 'Lin'},
            {'user': 'missing', 'title': 'C'},
            {'user': 'u1', 'title': 'A', 'id': 'u1', 'name': 'Ada'},
        ])
        array_expr = ('. as $root | INDEX($root.users[]; .id) as $idx | '
                      '$root.posts | JOIN($idx; .user)')
        self.assertEqual(self.outputs(self.target, array_expr, source), [pairs])

    def test_empty_index_stream_and_null_index_keys(self):
        self.assertEqual(self.outputs(self.target, 'INDEX(.[]; .id)', []), [{}])
        self.assertEqual(self.outputs(
            self.target, 'INDEX(.[]; .id)', [{'value': 1}, {'id': None, 'value': 2}]),
            [{'null': {'id': None, 'value': 2}}])
        keyed = [{'key': key, 'value': index} for index, key in enumerate(
            [None, True, [1, 2], {'x': 1}])]
        self.assertEqual(self.outputs(self.target, 'INDEX(.[]; .key)', keyed), [{
            'null': keyed[0],
            'true': keyed[1],
            '[1,2]': keyed[2],
            '{"x":1}': keyed[3],
        }])

    def test_in_stream_membership(self):
        cases = [
            ('2 | IN(range(4))', True),
            ('4 | IN(range(4))', False),
            ('null | IN(range(4); range(2; 6))', True),
            ('null | IN(range(4); range(5; 8))', False),
            ('1 | IN(0, 1, 2)', True),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(self.outputs(self.target, expression, None), [expected])

    def test_seeded_differential(self):
        reference = os.environ.get('RECIPKG_TEST_JQ_REFERENCE')
        if not reference:
            self.skipTest('set RECIPKG_TEST_JQ_REFERENCE for differential cases')
        reference = shutil.which(reference)
        self.assertIsNotNone(reference)
        self.assertNotEqual(os.path.realpath(reference), os.path.realpath(self.target))
        rng = random.Random(315113)
        cases = []
        for _ in range(100):
            users = [{'id': f'u{rng.randrange(1, 6)}', 'rank': rng.randrange(100)}
                     for _ in range(rng.randrange(1, 8))]
            posts = [{'user': f'u{rng.randrange(1, 8)}', 'value': rng.randrange(100)}
                     for _ in range(rng.randrange(1, 8))]
            cases.append({'users': users, 'posts': posts})
        data = ''.join(json.dumps(item) + '\n' for item in cases)
        expression = ('. as $root | INDEX($root.users[]; .id) as $idx | '
                      'JOIN($idx; $root.posts[]; .user)')
        actual = subprocess.run([self.target, '-c', expression], input=data,
                                capture_output=True, text=True, timeout=10)
        expected = subprocess.run([reference, '-c', expression], input=data,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual((actual.returncode, actual.stderr), (0, ''))
        self.assertEqual((expected.returncode, expected.stderr), (0, ''))
        self.assertEqual([json.loads(line) for line in actual.stdout.splitlines()],
                         [json.loads(line) for line in expected.stdout.splitlines()])
