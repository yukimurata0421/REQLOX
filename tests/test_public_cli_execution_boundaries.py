"""Mocked CLI execution covers stop states without provider or Target calls."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()
from runtime_imports import patched_runtime_modules

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import reqlox
from reqlox import cli


class IsolationProbeTests(unittest.TestCase):
    def probe(self, *, platform='linux', executable='/usr/bin/python3', found='bwrap', result=0, error=None):
        output = io.StringIO()
        with patch.object(cli.sys, 'platform', platform), patch.object(cli.sys, 'executable', executable), \
                patch.object(cli.shutil, 'which', return_value=found), \
                patch.object(cli.subprocess, 'run', return_value=SimpleNamespace(returncode=result), side_effect=error) as run, \
                contextlib.redirect_stdout(output):
            status = cli.check()
        return status, json.loads(output.getvalue()), run

    def test_success_probes_only_true_and_reports_zero_experiments(self):
        status, value, run = self.probe()
        self.assertEqual(status, 0)
        self.assertTrue(value['experiments_available'])
        self.assertEqual((value['provider_calls'], value['target_experiments']), (0, 0))
        args, options = run.call_args
        self.assertEqual(args[0][-1], '/usr/bin/true')
        self.assertIn('--unshare-all', args[0])
        self.assertEqual(options, {'capture_output': True, 'timeout': 5})

    def test_unsupported_platform_missing_isolator_or_non_system_python_never_launch(self):
        for options in ({'platform': 'darwin'}, {'found': None}, {'executable': '/owned/python'}):
            with self.subTest(options=options):
                status, value, run = self.probe(**options)
                self.assertEqual(status, 1)
                self.assertFalse(value['experiments_available'])
                run.assert_not_called()

    def test_probe_failure_timeout_and_launch_error_are_unavailable(self):
        for options in ({'result': 1}, {'error': OSError('owned failure')},
                        {'error': subprocess.TimeoutExpired(['owned-probe'], 5)}):
            with self.subTest(options=options):
                status, value, run = self.probe(**options)
                self.assertEqual(status, 1)
                self.assertFalse(value['isolation_probe_passed'])
                run.assert_called_once()


class PublicCliExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = {'owned.py': 'value = 1\n'}
        self.config = {'contracts': {'family': {'basis': 'OWNED', 'scope': 'CALLER'}},
                       'source_texts': {'incident': 'owned evidence'}, 'hypotheses': ['owned hypothesis']}
        self.runner = ModuleType('reqlox_core.run_reliability_reuse')
        self.runner.load_snapshot = Mock(return_value=self.sources)
        self.runner.read = Mock(return_value=self.config)
        self.paths = ModuleType('reqlox_core.reqlox_paths')
        self.paths.ensure_state = Mock(return_value=self.root)
        self.reuse = ModuleType('reqlox_core.reliability_reuse')
        self.reuse.hypothesis = Mock(return_value='prepared hypothesis')
        self.loop = ModuleType('reqlox_core.run_reliability_improvement_loop')
        self.loop.run = Mock(return_value={'status': 'ADOPTED_IN_SNAPSHOT'})
        self.requirements = ModuleType('reqlox_core.reliability_requirement_experiment')
        self.requirements.prepare = Mock(return_value='owned experiment')
        self.paired = ModuleType('reqlox_core.run_reliability_paired')
        self.paired.run = Mock(return_value={'status': 'COMPLETE'})
        self.audit = ModuleType('reqlox_core.audit_reliability_reuse')
        self.audit.main = Mock()
        for replacement in (patch.object(cli, '_runtime'), patch.dict(os.environ),
                            patched_runtime_modules( {m.__name__: m for m in
                                (self.runner, self.paths, self.reuse, self.loop, self.requirements, self.paired, self.audit)})):
            self.enterContext(replacement)

    def qualify(self, *extra):
        output, error = io.StringIO(), io.StringIO()
        args = ['qualify', '--root', str(self.root), '--configuration', str(self.root / 'config.json'), *extra]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = cli.main(args)
        return status, json.loads(output.getvalue() or error.getvalue())

    def test_qualification_forwards_bounds_and_preserves_conservative_claims(self):
        status, value = self.qualify('--name', 'owned', '--maximum-native-campaigns', '0',
                                    '--maximum-rounds', '1', '--seconds', '1', '--dependency', str(self.root / 'dep'),
                                    '--state-dir', str(self.root / 'requested-state'))
        self.assertEqual(status, 0)
        self.assertEqual(value['output'], str(self.root / 'runs' / 'owned'))
        for name in ('checkout_mutated', 'natural_source_added_value_certified', 'independent_generalization_certified'):
            self.assertIs(value[name], False)
        self.assertEqual(os.environ['REQLOX_STATE_DIR'], str(self.root / 'requested-state'))
        args, options = self.loop.run.call_args
        self.assertEqual(args, (self.sources, self.config['contracts'], ['prepared hypothesis'], self.root / 'runs' / 'owned'))
        self.assertEqual(options['maximum_native_campaigns'], 0)
        self.assertEqual(options['maximum_rounds'], 1)
        self.assertEqual(options['maximum_probes'], 3)
        self.assertEqual(options['dependency'], self.root / 'dep')
        self.reuse.hypothesis.assert_called_once_with('owned hypothesis', self.config['source_texts'])
        self.assertEqual(self.runner.load_snapshot.call_count, 2)

    def test_generated_name_and_absent_optional_inputs(self):
        self.config = {'contracts': {}}
        self.runner.read.return_value = self.config
        status, value = self.qualify()
        self.assertEqual(status, 0)
        self.assertRegex(Path(value['output']).name, r'^run-\d{8}T\d{12}Z$')
        self.assertIsNone(self.loop.run.call_args.kwargs['dependency'])
        self.assertEqual(self.loop.run.call_args.args[2], [])

    def test_paired_qualification_uses_separate_runner_and_per_arm_limit(self):
        self.config['maximum_probes'] = 2
        self.config['specification_texts'] = {'owned.py': 'owned specification'}
        status, value = self.qualify('--paired', '--name', 'pair', '--maximum-native-campaigns', '2')
        self.assertEqual((status, value['status']), (0, 'COMPLETE'))
        self.loop.run.assert_not_called()
        self.requirements.prepare.assert_called_once_with(self.sources, self.config['specification_texts'],
                                                         {'family': {'basis': 'OWNED', 'scope': 'CALLER'}})
        self.assertEqual(self.paired.run.call_args.args, (self.sources, 'owned experiment',
                                                        self.config['source_texts'], self.root / 'runs' / 'pair'))
        self.assertEqual(self.paired.run.call_args.kwargs['maximum_native_campaigns_per_arm'], 2)
        self.assertEqual(self.paired.run.call_args.kwargs['maximum_probes'], 2)

    def test_terminal_stop_result_has_nonzero_status(self):
        self.loop.run.return_value = {'status': 'STOPPED'}
        status, value = self.qualify('--name', 'stopped')
        self.assertEqual((status, value['status']), (1, 'STOPPED'))

    def test_source_drift_stops_instead_of_certifying_a_result(self):
        self.runner.load_snapshot.side_effect = [self.sources, {'owned.py': 'value = 2\n'}]
        status, value = self.qualify('--name', 'drift')
        self.assertEqual(status, 2)
        self.assertEqual(value, {'status': 'STOPPED', 'reason': 'Source changed during execution'})

    def test_missing_contracts_and_io_errors_return_machine_readable_stop(self):
        for error in (KeyError('contracts'), OSError('owned denied'),
                      json.JSONDecodeError('owned invalid', '{}', 0)):
            with self.subTest(error=type(error).__name__):
                self.runner.read.side_effect = error
                status, value = self.qualify('--name', 'failure')
                self.assertEqual((status, value['status']), (2, 'STOPPED'))
                self.assertIn('reason', value)
        self.loop.run.assert_not_called()

    def test_invalid_limits_and_names_fail_before_loading_source_or_running(self):
        invalid = [('--seconds', '0'), ('--seconds', '7201'), ('--maximum-native-campaigns', '-1'),
                   ('--maximum-native-campaigns', '65'), ('--name', '../escape'), ('--name', '.'),
                   ('--name', '..'), ('--name', 'a\\b')]
        for option, value in invalid:
            with self.subTest(option=option, value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    cli.main(['qualify', '--root', str(self.root), '--configuration', 'owned.json', option, value])
                self.assertEqual(stopped.exception.code, 2)
        self.runner.load_snapshot.assert_not_called()
        self.loop.run.assert_not_called()
        self.assertFalse((self.root / 'runs').exists())

    def test_audit_passes_absolute_output_and_restores_argv_even_on_failure(self):
        saved, seen = sys.argv, []
        for error in (None, ValueError('owned audit rejection')):
            self.audit.main.side_effect = lambda error=error: seen.append(sys.argv.copy()) or (self.raise_error(error) if error else None)
            with contextlib.redirect_stderr(io.StringIO()):
                status = cli.main(['audit', '--kind', 'paired', '--output', 'owned-output'])
            self.assertEqual(status, 0 if error is None else 2)
            self.assertIs(sys.argv, saved)
        self.assertEqual(seen, [['reqlox audit', '--kind', 'paired', '--output', str(Path('owned-output').absolute())]] * 2)

    @staticmethod
    def raise_error(error):
        raise error

    def test_check_command_returns_probe_status(self):
        with patch.object(cli, 'check', return_value=1) as check:
            self.assertEqual(cli.main(['check']), 1)
        check.assert_called_once_with()

    def test_knowledge_and_study_receive_only_their_arguments(self):
        for command in ('knowledge', 'study'):
            delegate = ModuleType('reqlox.' + command + '_cli')
            delegate.main = Mock(return_value=4)
            arguments = [command, '--help']
            with self.subTest(command=command), patched_runtime_modules( {delegate.__name__: delegate}):
                self.assertEqual(cli.main(arguments), 4)
                delegate.main.assert_called_once_with(['--help'])
                self.assertEqual(arguments, [command, '--help'])

    def test_prepare_delegate_receives_arguments_and_restores_argv_on_exception(self):
        delegate = ModuleType('reqlox_core.prepare_reliability_reuse')
        saved, seen = sys.argv, []
        delegate.main = Mock(side_effect=lambda: seen.append(sys.argv.copy()) or self.raise_error(RuntimeError('owned')))
        with patched_runtime_modules( {delegate.__name__: delegate}), self.assertRaisesRegex(RuntimeError, 'owned'):
            cli.main(['prepare', '--help'])
        self.assertIs(sys.argv, saved)
        self.assertEqual(seen, [['reqlox prepare', '--help']])


class PublicRuntimeBoundaryTests(unittest.TestCase):
    def test_inventory_api_keeps_target_top_level_code_static(self):
        sources = {'owned.py': "raise RuntimeError('must remain static')\n"}
        result = reqlox.inventory(sources)
        self.assertEqual(result['accepted'], [])
        self.assertEqual(sources, {'owned.py': "raise RuntimeError('must remain static')\n"})

    def test_source_conditions_api_preserves_source_identity_without_execution_authority(self):
        result = reqlox.source_conditions('owned-source', 'Timeout interrupted cleanup after acquisition.')
        self.assertEqual(result['source_id'], 'owned-source')
        self.assertIs(result['execution_authority'], False)

    def test_loaded_module_without_origin_is_rejected_without_import_path_mutation(self):
        before = sys.path.copy()
        with patched_runtime_modules( {'reqlox_core': ModuleType('reqlox_core')}):
            with self.assertRaisesRegex(ImportError, 'Conflicting runtime package'):
                reqlox._runtime()
        self.assertEqual(sys.path, before)
