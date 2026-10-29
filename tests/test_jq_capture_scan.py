"""Selected jq capture/scan behavior against explicit executables."""
import ctypes.util
import json
import os
import random
import shutil
import subprocess
import unittest


CAPTURE_PATTERNS = [
    r"(?<word>[A-Z]+)(?<digits>\d+)?",
    r"(?<greek>α|β)+",
    r"(?<a>a)?(?<b>b*)",
    r"(foo)",
]
SCAN_PATTERNS = [
    r"\d+",
    r"(?<word>[A-Z]+)(?<digits>\d+)?",
    r"(a)?(b*)",
    r"(?=.)",
]
TEXTS = ["ab 12", "a\nb", "XYZ9", "é🙂", "αβ", "FOO\nbar", "", "no match", "13"]
FLAGS = ["", "g", "i", "m", "n", "x", "l", "p", "s"]


class JqCaptureScanSamples(unittest.TestCase):
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

    def test_capture_names_missing_groups_and_first_result(self):
        cases = [
            ('capture("(?<a>[a-z]+)-(?<n>[0-9]+)")', "xyzzy-14"),
            ('capture("(?<a>a)?(?<b>b*)")', "bb"),
            ('capture("missing")', "abc"),
            ('capture("(foo)")', "foo"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_capture_array_shorthand_global_and_generator_order(self):
        cases = [
            ('capture(["(?<x>foo)", "ig"])', "foo FOO"),
            ('capture(("(?<a>a)", "(?<b>b)"); ("", "i"))', "ab"),
            ('capture("(?<word>[A-Z]+)(?<digits>[0-9]+)?"; "g")', "ABC 42 XYZ"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_scan_strings_capture_arrays_and_flags(self):
        cases = [
            ('scan("c")', "abcdefabc"),
            ('scan("(a+)(b+)")', "abaabbaaabbb"),
            ('scan("(a)?(b*)"; "g")', "bb"),
            ('scan("(a)?(b*)"; "gn")', "bb"),
            ('scan("(?<x>foo)"; "ig")', "foo FOO"),
            ('scan("(?=.)"; "g")', "aβc"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_argument_errors_and_scan_array_is_not_shorthand(self):
        cases = [
            ('capture(2)', "abc", "not a string or array"),
            ('capture("foo"; 2)', "abc", "number (2) is not a string"),
            ('scan(2)', "abc", "number (2) is not a string"),
            ('scan("foo"; 2)', "abc", 'string ("g") and number (2) cannot be added'),
            ('scan(["foo", "i"])', "FOO", 'array (["foo","i"]) is not a string'),
            ('scan("foo")', 2, "cannot be matched, as it is not a string"),
        ]
        for expression, source, marker in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_error(expression, source, marker)

    def test_seeded_differential(self):
        rng = random.Random(20261030)
        capture_cases = [
            {
                "text": rng.choice(TEXTS),
                "pattern": rng.choice(CAPTURE_PATTERNS),
                "flags": rng.choice(FLAGS),
            }
            for _ in range(50)
        ]
        scan_cases = [
            {
                "text": rng.choice(TEXTS),
                "pattern": rng.choice(SCAN_PATTERNS),
                "flags": rng.choice(FLAGS),
            }
            for _ in range(50)
        ]
        for function, cases in (("capture", capture_cases), ("scan", scan_cases)):
            expression = (
                "[.[] | .text as $text | .pattern as $pattern | .flags as $flags | "
                f"($text | {function}($pattern; $flags))]"
            )
            actual = self.run_filter(self.target, expression, cases)
            expected = self.run_filter(self.reference, expression, cases)
            with self.subTest(function=function):
                self.assertEqual((actual.returncode, actual.stderr), (0, ""))
                self.assertEqual((expected.returncode, expected.stderr), (0, ""))
                self.assertEqual(self.output_values(actual), self.output_values(expected))


if __name__ == "__main__":
    unittest.main()
