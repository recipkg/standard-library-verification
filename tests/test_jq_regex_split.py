"""Selected regex split/splits behavior against explicit jq executables."""
import ctypes.util
import json
import os
import random
import shutil
import subprocess
import unittest


PATTERNS = [r"[,;:]+", r"\s+", r"(?=.)", r"(?<sep>[0-9]+)", r"a?"]
TEXTS = ["a,b;c", "β,🧪::x", "", "no separator", "a  b\nc", "111aa22", ",,,", "aba"]
FLAGS = ["", "n", "i", "m", "s", "x"]


class JqRegexSplitSamples(unittest.TestCase):
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

    def test_split_regex_two_argument_and_literal_compatibility(self):
        cases = [
            ('split(", *"; null)', "ab,cd, ef"),
            ('split(",? *"; "n")', "ab,cd ef, gh"),
            ('split(", ")', "a, b,c,d, e, "),
            ('split("(?<sep>[,:]+)"; "g")', "a,b::c"),
            ('split("absent"; null)', "abc"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_splits_stream_boundaries_unicode_and_zero_width(self):
        cases = [
            ('splits(",? *")', "ab,cd, ef, gh"),
            ('splits(",? *"; "n")', "ab,cd ef, gh"),
            ('splits("(?<sep>,)")', "a,b::c"),
            ('splits("(?=.)")', "aβc"),
            ('splits("a?")', "aba"),
            ('splits("z")', "abc"),
            ('splits(",")', ",a,,b,"),
            ('splits(",")', ""),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_pattern_and_flags_generator_order(self):
        cases = [
            ('splits((",", ";"); ("", "i"))', "a,b;c"),
            ('split((",", ";"); ("", "i"))', "a,b;c"),
            ('splits("[,]"; null)', "a,b"),
        ]
        for expression, source in cases:
            with self.subTest(expression=expression, source=source):
                self.assert_matches(expression, source)

    def test_invalid_types_patterns_and_modifiers_fail(self):
        cases = [
            ('split("x"; 2)', "a", "cannot be added"),
            ('splits("x"; 2)', "a", "cannot be added"),
            ('splits(2)', "a", "not a string"),
            ('splits(["x", "i"])', "a", "not a string"),
            ('splits("[")', "a", "Regex failure"),
            ('splits("x"; "?")', "a", "not a valid modifier string"),
            ('splits("x")', 2, "not a string"),
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
            for _ in range(50)
        ]
        for function in ("split", "splits"):
            expression = (
                "[.[] | .text as $text | .pattern as $pattern | .flags as $flags | "
                + (f"($text | {function}($pattern; $flags))" if function == "split"
                   else f"[$text | {function}($pattern; $flags)]")
                + "]"
            )
            actual = self.run_filter(self.target, expression, cases)
            expected = self.run_filter(self.reference, expression, cases)
            with self.subTest(function=function):
                self.assertEqual((actual.returncode, actual.stderr), (0, ""))
                self.assertEqual((expected.returncode, expected.stderr), (0, ""))
                self.assertEqual(self.output_values(actual), self.output_values(expected))


if __name__ == "__main__":
    unittest.main()
