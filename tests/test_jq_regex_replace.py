"""Selected sub/gsub behavior against explicit jq executables."""
import ctypes.util
import json
import os
import random
import shutil
import subprocess
import unittest


class JqRegexReplaceSamples(unittest.TestCase):
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

    def assert_matches(self, expression, source, expected=None):
        actual = self.run_filter(self.target, expression, source)
        reference = self.run_filter(self.reference, expression, source)
        self.assertEqual((actual.returncode, actual.stderr), (0, ""))
        self.assertEqual((reference.returncode, reference.stderr), (0, ""))
        actual_values = self.output_values(actual)
        self.assertEqual(actual_values, self.output_values(reference))
        if expected is not None:
            self.assertEqual(actual_values, expected)
        return actual_values

    def assert_error(self, expression, source, marker):
        actual = self.run_filter(self.target, expression, source)
        reference = self.run_filter(self.reference, expression, source)
        self.assertNotEqual(actual.returncode, 0)
        self.assertNotEqual(reference.returncode, 0)
        self.assertEqual(actual.stdout, "")
        self.assertEqual(reference.stdout, "")
        self.assertIn(marker, actual.stderr)
        self.assertIn(marker, reference.stderr)

    def test_sub_replaces_first_and_gsub_or_g_flag_replaces_all(self):
        cases = [
            ('sub("a"; "X")', "aba", ["Xba"]),
            ('sub("a"; "X"; "g")', "aba", ["XbX"]),
            ('gsub("a"; "X")', "aba", ["XbX"]),
            ('gsub("a"; "X"; null)', "aba", ["XbX"]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                self.assert_matches(expression, source, expected)

    def test_named_capture_interpolation_and_unicode(self):
        cases = [
            ('sub("(?<x>[a-z]+)-(?<n>[0-9]+)"; "\\(.x):\\(.n)")',
             "éfoo-12", ["éfoo:12"]),
            ('sub("(?<x>a)?b"; "[\\(.x // "∅")]" )',
             "b", ["[∅]"]),
            ('sub("(a)"; "x\\(.a // "missing")")',
             "a", ["xmissing"]),
            ('gsub("(?<x>.)"; "<\\(.x)>")', "é🙂", ["<é><🙂>"]),
            ('sub("(?<x>a)?b"; "\\(.x // "a)b")")', "b", ["a)b"]),
            ('sub("a"; "\\\\(literal)")', "a", ["\\(literal)"]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                self.assert_matches(expression, source, expected)

    def test_interpolation_values_streams_and_nested_strings(self):
        cases = [
            ('sub("a"; "n=\\(42), v=\\(null)")', "a",
             ["n=42, v=null"]),
            ('sub("(?<x>.)"; "\\(.x, "Z")")', "a", ["a", "Z"]),
            ('sub("(?<x>.)"; "x=\\("y=\\(.x)")")', "a", ["x=y=a"]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                self.assert_matches(expression, source, expected)

    def test_replacement_streams_are_aligned_by_output_index(self):
        self.assert_matches('gsub("p"; "a", "b")', "pp", ["aa", "bb"])
        self.assert_matches('sub("a"; null)', "a", [""])
        self.assert_matches(
            'sub("(?<a>.)"; "\\(.a|ascii_upcase)", "\\(.a|ascii_downcase)")',
            "aB",
            ["AB", "aB"],
        )
        self.assert_matches(
            'gsub("(?<x>.)"; if .x == "p" then ("A", "B") else "C" end)',
            "pq",
            ["AC", "B"],
        )
        self.assert_matches(
            'gsub("(?<x>.)"; if .x == "p" then empty else ("C", "D") end)',
            "pq",
            ["C", "D"],
        )
        self.assert_matches('gsub("(?<x>p)"; if .x == "p" then empty else "B" end)',
                            "pp", ["pp"])
        self.assert_matches('sub("z"; error("replacement evaluated"))',
                            "abc", ["abc"])

    def test_zero_width_flags_and_global_unicode_matches(self):
        cases = [
            ('sub(""; "X"; "g")', "a", ["XaX"]),
            ('gsub(""; "-"; "n")', "éa", ["éa"]),
            ('gsub(""; "-")', "éa", ["-é--a-"]),
            ('gsub("(?<x>.)"; "<\\(.x)>")', "aβ🙂", ["<a><β><🙂>"]),
        ]
        for expression, source, expected in cases:
            with self.subTest(expression=expression):
                self.assert_matches(expression, source, expected)

    def test_pattern_and_flags_generators_keep_order(self):
        self.assert_matches('sub(("a", "b"); "X")', "aba", ["Xba", "aXa"])
        self.assert_matches('sub("a"; "X"; ("i", "g"))', "Aaa", ["Xaa", "AXX"])
        self.assert_matches('gsub(("a", "b"); "X"; ("i", ""))', "Aab")

    def test_type_regex_and_modifier_errors(self):
        cases = [
            ('sub(2; "X")', "a", "is not a string"),
            ('sub("a"; "X"; 2)', "a", "is not a string"),
            ('gsub("a"; "X"; 2)', "a", "cannot be added"),
            ('sub("a"; 42)', "a", "cannot be added"),
            ('sub("["; "X")', "a", "Regex failure"),
            ('sub("a"; "X"; "?")', "a", "not a valid modifier string"),
            ('sub("x"; "X")', 2, "cannot be matched"),
        ]
        for expression, source, marker in cases:
            with self.subTest(expression=expression):
                self.assert_error(expression, source, marker)

    def test_seeded_differential(self):
        rng = random.Random(20261030)
        texts = ["", "abc", "Aab", "βa🙂", "bbb", "aab", "éa"]
        patterns = ["a", "b+", "(?<x>a)", "(?=.)", "a?", "(?i)b", "[ab]"]
        flags = ["", "i", "g", "n", "in", "gn", "m"]
        cases = [
            {"text": rng.choice(texts), "pattern": rng.choice(patterns),
             "flags": rng.choice(flags)}
            for _ in range(100)
        ]
        for function in ("sub", "gsub"):
            expression = (
                "[.[] | .text as $text | .pattern as $pattern | .flags as $flags | "
                f"[$text | {function}($pattern; \"Z\"; $flags)]]"
            )
            actual = self.run_filter(self.target, expression, cases)
            reference = self.run_filter(self.reference, expression, cases)
            with self.subTest(function=function):
                self.assertEqual((actual.returncode, actual.stderr), (0, ""))
                self.assertEqual((reference.returncode, reference.stderr), (0, ""))
                self.assertEqual(self.output_values(actual), self.output_values(reference))


if __name__ == "__main__":
    unittest.main()
