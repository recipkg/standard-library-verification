"""Selected jq match(regex) behavior against explicit executables."""
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
    r"a*",
    r"(?=.)",
    r"(?<greek>α|β)+",
    r"(a)?(b*)",
]
TEXTS = ["ab 12", "a\nb", "XYZ9", "é🙂", "αβ", "FOO\nbar", "", "no match", "13"]
FLAGS = ["", "g", "i", "m", "n", "x", "l", "p", "s"]


class JqMatchSamples(unittest.TestCase):
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

    def test_match_objects_and_capture_shapes(self):
        cases = [
            ('match("foo")', "foo bar foo"),
            ('match("(abc)+"; "g")', "abc abc"),
            ('match("(?<a>a)?(?<b>b*)")', "bb"),
            (r'match("(?<n>\\d+)")', "🙂α42!"),
            ('match("zz")', "foo"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_global_flags_array_shorthand_and_generator_order(self):
        cases = [
            ('match(["foo", "ig"])', "foo bar FOO"),
            ('match(("a", "b"); "g")', "ab ab"),
            ('match(("a", "b"); ("", "i"))', "A b"),
            ('match("(?<x>foo)"; "ig")', "FOO foo"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_utf8_codepoint_offsets_and_zero_width_byte_advance(self):
        cases = [
            ('match("42")', "🙂α42!"),
            (r'match("(?<word>\\p{L}+)")', "π abc-123"),
            ('match("(?=.)"; "g")', "aβc"),
            ('match("(?=.)"; "g")', "a🙂b"),
            ('match("a*"; "g")', "bbb"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_type_and_regex_errors(self):
        cases = [
            ('match(2)', "abc", "number not a string or array"),
            ('match("foo"; 2)', "abc", "number (2) is not a string"),
            ('match("[")', "abc", "Regex failure:"),
            ('match("foo"; "q")', "abc", "not a valid modifier string"),
            ('match("foo")', 2, "cannot be matched, as it is not a string"),
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
        expression = (
            "[.[] | .text as $text | .pattern as $pattern | .flags as $flags | "
            "($text | match($pattern; $flags))]"
        )
        actual = self.run_filter(self.target, expression, cases)
        expected = self.run_filter(self.reference, expression, cases)
        self.assertEqual((actual.returncode, actual.stderr), (0, ""))
        self.assertEqual((expected.returncode, expected.stderr), (0, ""))
        self.assertEqual(self.output_values(actual), self.output_values(expected))


if __name__ == "__main__":
    unittest.main()
