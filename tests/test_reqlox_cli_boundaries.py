"""CLI delegation preserves arguments and avoids importing Target code."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()
from runtime_imports import patched_runtime_modules

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import reqlox
from reqlox import cli


class CliBoundaryTests(unittest.TestCase):
    def setUp(self):
        runtime = patch.object(cli, '_runtime')
        self.runtime = runtime.start()
        self.addCleanup(runtime.stop)

    def test_review_and_preparation_commands_delegate_without_execution(self):
        for command, module in [('knowledge', 'reqlox.knowledge_cli'),
                                ('study', 'reqlox.study_cli'),
                                ('scope', 'reqlox.scope_cli'),
                                ('integration', 'reqlox.integration_cli')]:
            delegate = ModuleType(module)
            delegate.main = Mock(return_value=7)
            with self.subTest(command=command), patched_runtime_modules( {module: delegate}):
                self.assertEqual(cli.main([command, 'inspect', '--input', 'fixture']), 7)
            delegate.main.assert_called_once_with(['inspect', '--input', 'fixture'])

    def test_version_exits_successfully_and_prints_package_version(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_code:
            cli.main(['--version'])
        self.assertEqual(exit_code.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), reqlox.__version__)
        self.runtime.assert_called_once_with()

    def test_help_exposes_supported_commands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_code:
            cli.main(['--help'])
        self.assertEqual(exit_code.exception.code, 0)
        for command in ('target', 'run', 'demo', 'inventory'):
            self.assertIn(command, output.getvalue())

    def test_missing_or_unknown_command_is_a_parser_error(self):
        for arguments in ([], ['unknown'], ['--unknown']):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_code:
                    cli.main(arguments)
                self.assertEqual(exit_code.exception.code, 2)

    def test_target_and_run_preserve_selection_order_and_return_status(self):
        delegated = ModuleType('reqlox.target_cli')
        delegated.main = Mock(return_value=7)
        for command in ('target', 'run'):
            arguments = [command, '--repo', 'worker', '--repo', 'api']
            before = arguments.copy()
            with self.subTest(command=command), patched_runtime_modules( {delegated.__name__: delegated}):
                self.assertEqual(cli.main(arguments), 7)
                delegated.main.assert_called_with(before)
                self.assertEqual(arguments, before)

    def test_demo_receives_only_its_arguments_and_restores_argv(self):
        delegated = ModuleType('reqlox_demo.__main__')
        seen = []
        delegated.main = Mock(side_effect=lambda: seen.append(sys.argv.copy()) or 3)
        original = sys.argv
        arguments = ['demo', 'run', '--sample', 'unknown']
        with patched_runtime_modules( {delegated.__name__: delegated}):
            self.assertEqual(cli.main(arguments), 3)
        self.assertEqual(seen, [['reqlox demo', 'run', '--sample', 'unknown']])
        self.assertIs(sys.argv, original)
        self.assertEqual(arguments, ['demo', 'run', '--sample', 'unknown'])

    def test_demo_restores_argv_after_delegate_exception(self):
        delegated = ModuleType('reqlox_demo.__main__')
        delegated.main = Mock(side_effect=RuntimeError('owned failure'))
        original = sys.argv
        with patched_runtime_modules( {delegated.__name__: delegated}):
            with self.assertRaisesRegex(RuntimeError, 'owned failure'):
                cli.main(['demo', 'run'])
        self.assertIs(sys.argv, original)

    def test_demo_restores_argv_after_parser_exit(self):
        delegated = ModuleType('reqlox_demo.__main__')
        delegated.main = Mock(side_effect=SystemExit(2))
        original = sys.argv
        with patched_runtime_modules( {delegated.__name__: delegated}), self.assertRaises(SystemExit):
            cli.main(['demo', '--unknown'])
        self.assertIs(sys.argv, original)

    def test_default_arguments_use_sys_argv_without_modifying_it(self):
        arguments = ['owned-cli', '--version']
        with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_code:
                cli.main()
            self.assertEqual(exit_code.exception.code, 0)
            self.assertEqual(sys.argv, ['owned-cli', '--version'])

    def test_inventory_requires_root_before_loading_a_snapshot(self):
        runner = ModuleType('reqlox_core.run_reliability_reuse')
        runner.load_snapshot = Mock()
        runner.inventory_for = Mock()
        with patched_runtime_modules( {runner.__name__: runner}), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_code:
                cli.main(['inventory'])
        self.assertEqual(exit_code.exception.code, 2)
        runner.load_snapshot.assert_not_called()
        runner.inventory_for.assert_not_called()

    def test_inventory_emits_one_json_document_and_resolves_relative_root(self):
        runner = ModuleType('reqlox_core.run_reliability_reuse')
        sources = {'owned.py': 'value = 1\n'}
        runner.load_snapshot = Mock(return_value=sources)
        runner.inventory_for = Mock(return_value={'accepted': [], 'reason': '対象外'})
        output = io.StringIO()
        with patched_runtime_modules( {runner.__name__: runner}), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['inventory', '--root', 'owned']), 0)
        runner.load_snapshot.assert_called_once_with(Path('owned').absolute())
        runner.inventory_for.assert_called_once_with(sources)
        self.assertEqual(json.loads(output.getvalue()), {'accepted': [], 'reason': '対象外'})
        self.assertIn('対象外', output.getvalue())

    def test_real_inventory_does_not_execute_repository_top_level_code(self):
        reqlox._runtime()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'executed'
            source = "from pathlib import Path\nPath(__file__).with_name('executed').touch()\nraise RuntimeError('must not import')\n"
            (root / 'owned.py').write_text(source)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['inventory', '--root', str(root)]), 0)
            self.assertEqual(json.loads(output.getvalue())['accepted'], [])
            self.assertFalse(marker.exists())
            self.assertEqual((root / 'owned.py').read_text(), source)


class RuntimeImportBoundaryTests(unittest.TestCase):
    def test_unqualified_module_cannot_shadow_packaged_runtime(self):
        before = list(sys.path)
        with patch.dict(sys.modules, {'workflow_effort': ModuleType('workflow_effort')}):
            self.assertEqual(reqlox._runtime().__name__, 'reqlox_core')
        self.assertEqual(sys.path, before)

    def test_runtime_import_does_not_change_global_search_path(self):
        before = list(sys.path)
        self.assertIs(reqlox._runtime(), reqlox._runtime())
        self.assertEqual(sys.path, before)

    def test_foreign_or_missing_package_origin_is_rejected(self):
        for origin in (None, '/unrelated/runtime/__init__.py'):
            package = ModuleType('reqlox_core')
            if origin is not None:
                package.__file__ = origin
            with patch.dict(sys.modules, {'reqlox_core': package}):
                with self.assertRaisesRegex(ImportError, 'Conflicting runtime package'):
                    reqlox._runtime()


if __name__ == '__main__':
    unittest.main()
