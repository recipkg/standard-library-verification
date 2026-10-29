"""Finite black-box samples for jq module loading; not full compatibility."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class JqModuleSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = os.environ.get('RECIPKG_TEST_JQ', 'jq')
        cls.jq = shutil.which(name)
        if cls.jq is None:
            if 'RECIPKG_TEST_JQ' in os.environ:
                raise RuntimeError(f'required executable not found: {name!r}')
            raise unittest.SkipTest(f'missing executable: {name} (RECIPKG_TEST_JQ)')
        version = subprocess.run([cls.jq, '--version'], capture_output=True, text=True,
                                  timeout=10)
        print('jq module target:', version.stdout.strip())

    def invoke(self, args, *, cwd, input='null\n'):
        return subprocess.run([self.jq, *args], input=input, text=True, capture_output=True,
                              cwd=cwd, timeout=10)

    def test_flat_layout_recursive_include_and_comments(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            library = root / 'lib'
            (library / 'math').mkdir(parents=True)
            (library / 'core.jq').write_text('# shared constant\ndef core: 41;\n', encoding='utf-8')
            (library / 'math' / 'step.jq').write_text(
                'include "core";\ndef step: core + 1;\n', encoding='utf-8')
            result = self.invoke(['-n', '-L', str(library),
                                  'include "math/step"; step'], cwd=root)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '42\n', ''))

    def test_nested_layout_fallback(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            module = root / 'lib' / 'math' / 'format'
            module.mkdir(parents=True)
            (module / 'format.jq').write_text('def module_kind: "nested";\n', encoding='utf-8')
            result = self.invoke(['-n', '-L', str(root / 'lib'),
                                  'include "math/format"; module_kind'], cwd=root)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, '"nested"\n', ''))

    def test_flat_candidate_precedes_nested_candidate(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            library = root / 'lib'
            (library / 'math' / 'format').mkdir(parents=True)
            (library / 'math' / 'format.jq').write_text(
                'def module_kind: "flat";\n', encoding='utf-8')
            (library / 'math' / 'format' / 'format.jq').write_text(
                'def module_kind: "nested";\n', encoding='utf-8')
            result = self.invoke(['-n', '-L', str(library),
                                  'include "math/format"; module_kind'], cwd=root)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, '"flat"\n', ''))

    def test_first_library_path_wins(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            first, second = root / 'first', root / 'second'
            first.mkdir()
            second.mkdir()
            (first / 'pick.jq').write_text('def picked: "first";\n', encoding='utf-8')
            (second / 'pick.jq').write_text('def picked: "second";\n', encoding='utf-8')
            for paths, expected in [((first, second), '"first"\n'),
                                    ((second, first), '"second"\n')]:
                args = ['-n']
                for path in paths:
                    args.extend(['-L', str(path)])
                args.append('include "pick"; picked')
                with self.subTest(paths=paths):
                    result = self.invoke(args, cwd=root)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, expected, ''))

    def test_dot_relative_module_uses_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            (root / 'local.jq').write_text('def local_value: 7;\n', encoding='utf-8')
            result = self.invoke(['-n', 'include "./local"; local_value'], cwd=root)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '7\n', ''))

    def test_missing_module_is_compile_error(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            library = root / 'lib'
            library.mkdir()
            result = self.invoke(['-n', '-L', str(library),
                                  'include "missing"; .'], cwd=root)
            self.assertEqual((result.returncode, result.stdout), (3, ''))
            self.assertIn('module not found', result.stderr)

    def test_import_is_explicitly_out_of_scope(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            result = self.invoke(['-n', 'import "anything" as anything; .'], cwd=root)
            self.assertEqual((result.returncode, result.stdout), (3, ''))
            self.assertIn('import', result.stderr)
            self.assertIn('not supported', result.stderr)

    def test_unimplemented_module_features_are_explicit(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            cases = [
                (['-n', 'include "settings.json"; .'], 3, 'JSON modules are not supported'),
                (['-n', 'module { "name": "sample" }; .'], 3, 'module metadata is not supported'),
                (['-n', 'module "sample"; .'], 3, 'module metadata is not supported'),
                (['-n', 'modulemeta'], 3, 'modulemeta is not supported'),
                (['-n', 'include "local"; .'], 3, 'default module search paths are not supported'),
            ]
            for args, code, message in cases:
                with self.subTest(args=args):
                    result = self.invoke(args, cwd=root)
                    self.assertEqual((result.returncode, result.stdout), (code, ''))
                    self.assertIn(message, result.stderr)

    def test_include_cycle_reports_compile_error(self):
        with tempfile.TemporaryDirectory(prefix='recipkg-jq-modules-') as temporary:
            root = Path(temporary)
            library = root / 'lib'
            library.mkdir()
            (library / 'first.jq').write_text('include "second"; def first: 1;\n', encoding='utf-8')
            (library / 'second.jq').write_text('include "first"; def second: 2;\n', encoding='utf-8')
            result = self.invoke(['-n', '-L', str(library), 'include "first"; first'], cwd=root)
            self.assertEqual((result.returncode, result.stdout), (3, ''))
            self.assertIn('recursive module include', result.stderr)


if __name__ == '__main__':
    unittest.main()
