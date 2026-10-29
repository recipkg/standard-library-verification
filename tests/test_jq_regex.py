"""Selected jq test(regex) behavior against explicit executables."""
import ctypes.util
import json
import os
import random
import shutil
import subprocess
import unittest


PATTERNS = [
    r"\d+",
    r"\w+",
    r"foo|bar",
    r"(?<letters>[A-Z]{1,3})-\d+",
    r"a.*b",
    r"[éΩ]+",
    r"^([a-z]{2,4})$",
    r"(?i:ab)c",
    r"a*",
]
TEXTS = ["ab 12", "a\nb", "XYZ9", "é🙂", "αβ", "FOO\nbar", "", "no match", "13"]
FLAGS = ["", "g", "i", "m", "n", "x", "l", "p", "s"]


class JqRegexTestSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ctypes.util.find_library("onig"):
            raise unittest.SkipTest("system libonig is unavailable")
        target = os.environ.get("RECIPKG_TEST_JQ")
        if not target:
            raise unittest.SkipTest("set RECIPKG_TEST_JQ to the candidate executable")
        cls.target = shutil.which(target)
        if not cls.target:
            raise RuntimeError(f"jq target not found: {target}")
        reference = os.environ.get("RECIPKG_TEST_JQ_REFERENCE")
        if not reference:
            raise unittest.SkipTest("set RECIPKG_TEST_JQ_REFERENCE for differential cases")
        cls.reference = shutil.which(reference)
        if not cls.reference:
            raise RuntimeError(f"jq reference not found: {reference}")
        if os.path.realpath(cls.reference) == os.path.realpath(cls.target):
            raise RuntimeError("candidate and reference must be different executables")

    def run_filter(self, executable, expression, source):
        return subprocess.run(
            [executable, "-c", expression],
            input=json.dumps(source, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )

    def output_values(self, result):
        return [json.loads(line) for line in result.stdout.splitlines()]

    def assert_matches(self, expression, source):
        actual = self.run_filter(self.target, expression, source)
        expected = self.run_filter(self.reference, expression, source)
        self.assertEqual((actual.returncode, actual.stderr), (0, ""))
        self.assertEqual((expected.returncode, expected.stderr), (0, ""))
        self.assertEqual(self.output_values(actual), self.output_values(expected))
        return self.output_values(actual)

    def assert_error(self, expression, source, marker):
        actual = self.run_filter(self.target, expression, source)
        expected = self.run_filter(self.reference, expression, source)
        self.assertNotEqual(actual.returncode, 0)
        self.assertNotEqual(expected.returncode, 0)
        self.assertEqual(actual.stdout, "")
        self.assertEqual(expected.stdout, "")
        self.assertIn(marker, actual.stderr)
        self.assertIn(marker, expected.stderr)

    def test_basic_strings_unicode_and_named_group_syntax(self):
        cases = [
            ('test("foo")', "foo bar", [True]),
            ('test("foo")', "bar", [False]),
            (r'test("\\p{Greek}+")', "αβ", [True]),
            (r'test("(?<part>foo)")', "foo", [True]),
            (r'test("(?=u)")', "qux", [True]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                self.assertEqual(self.assert_matches(expression, source), expected)

    def test_jq_regex_flags(self):
        cases = [
            ('test("foo"; "i")', "FOO", [True]),
            ('test("a.b"; "m")', "a\nb", [True]),
            ('test("a.b"; "p")', "a\nb", [True]),
            ('test("a.b"; "s")', "a\nb", [False]),
            ('test("a*")', "bbb", [True]),
            ('test("a*"; "n")', "bbb", [False]),
            ('test("a b # ignored"; "x")', "ab", [True]),
            ('test("foo"; "g")', "foo foo", [True]),
            ('test("foo"; "l")', "foo", [True]),
            ('test("foo"; "s")', "foo", [True]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                self.assertEqual(self.assert_matches(expression, source), expected)

    def test_single_array_argument_and_generator_order(self):
        cases = [
            ('test(["foo", "i"])', "FOO", [True]),
            ('test(["foo"])', "foo", [True]),
            ('test(["foo", "i", "ignored"])', "FOO", [True]),
            ('test(["foo", null])', "foo", [True]),
            ('test(("a", "b"))', "b", [False, True]),
            ('test(("a", "b"); ("", "i"))', "A",
             [False, False, True, False]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression, source=source):
                self.assertEqual(self.assert_matches(expression, source), expected)

    def test_type_invalid_pattern_and_modifier_errors(self):
        cases = [
            ('test("x")', 12, "cannot be matched"),
            ('test(1)', "x", "not a string or array"),
            ('test(1; null)', "x", "is not a string"),
            ('test("x"; 1)', "x", "is not a string"),
            ('test([])', "x", "not a string or array"),
            ('test("("; null)', "x", "Regex failure"),
            ('test("x"; "q")', "x", "not a valid modifier string"),
        ]
        for expression, source, marker in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_error(expression, source, marker)

    def test_seeded_differential(self):
        rng = random.Random(20261030)
        cases = [
            {
                "text": rng.choice(TEXTS),
                "pattern": rng.choice(PATTERNS),
                "flags": rng.choice(FLAGS),
            }
            for _ in range(100)
        ]
        source = json.dumps(cases, ensure_ascii=False)
        expression = ("[.[] | .text as $text | .pattern as $pattern | "
                      ".flags as $flags | ($text | test($pattern; $flags))]")
        actual = self.run_filter(self.target, expression, cases)
        expected = self.run_filter(self.reference, expression, cases)
        self.assertEqual((actual.returncode, actual.stderr), (0, ""))
        self.assertEqual((expected.returncode, expected.stderr), (0, ""))
        self.assertEqual(self.output_values(actual), self.output_values(expected))


if __name__ == "__main__":
    unittest.main()
