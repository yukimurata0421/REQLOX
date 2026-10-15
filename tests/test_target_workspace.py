"""Selection, isolation, immutable outcomes and shared multi-repository budgets."""
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import reqlox
reqlox._runtime()
from reqlox import targets
from reqlox.target_cli import main
import run_reliability_reuse as runner
import run_reliability_improvement_loop as loop
import run_reliability_paired as paired

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''import os
from pathlib import Path

def persist(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    with pending.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(pending, destination)
'''
CONFIG = {'contracts': {'atomic_file': {'id': 'owned.atomic-bytes.v1', 'basis': 'Owned cleanup requirement', 'scope': 'Owned test snapshots only'}}}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'corpus/knowledge/semantic-experiments/local-private-quarantine' if (ROOT / 'tools').is_dir() else None
        self.temp = tempfile.TemporaryDirectory(prefix='target-cli-test-', dir=base)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.environment = patch.dict(os.environ, {'REQLOX_STATE_DIR': str(self.state)})
        self.environment.start()
        self.manifest = self.root / 'target.json'
        targets.init(self.manifest, 'owned-system')
        for name in ('api', 'worker', 'idle'):
            directory = self.root / name
            directory.mkdir()
            (directory / 'storage.py').write_text(SOURCE)
            configuration = self.root / (name + '.json')
            configuration.write_text(json.dumps(CONFIG))
            targets.add(self.manifest, name, directory, configuration)

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def prepare(self, names=('api',), **kwargs):
        return targets.prepare(self.manifest, names, **kwargs)

    def execute(self, plan, name='run'):
        planned, prepared, roots = plan
        return targets.execute(planned, prepared, roots, self.state, name=name)

    @staticmethod
    def completed(*args, **kwargs):
        kwargs['before_native']()
        return dict(status='ADOPTED_IN_SNAPSHOT', native_campaigns=1)

    def test_init_and_registration_store_manifest_relative_paths(self):
        _, manifest, _ = targets.load(self.manifest)
        self.assertEqual(manifest['repositories']['api']['path'], 'api')
        self.assertEqual(manifest['repositories']['api']['configuration'], 'api.json')
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): targets.init(self.manifest, 'other')

    def test_existing_registration_and_overlapping_roots_are_rejected(self):
        for name, directory in [('api', self.root / 'api'), ('other', self.root / 'api')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                targets.add(self.manifest, name, directory, self.root / 'api.json')
        child = self.root / 'api/nested'
        child.mkdir()
        with self.assertRaises(ValueError): targets.add(self.manifest, 'nested', child, self.root / 'api.json')

    def test_unknown_duplicate_empty_and_conflicting_selections_are_rejected(self):
        for names, all_repos in [((), False), (('absent',), False), (('api', 'api'), False), (('api',), True)]:
            with self.subTest(names=names), self.assertRaises(ValueError):
                targets.prepare(self.manifest, names, all_repos)

    def test_all_and_repeated_selection_preserve_explicit_order(self):
        plan, _, _ = targets.prepare(self.manifest, (), True)
        self.assertEqual(plan['plan']['selected_repositories'], ['api', 'worker', 'idle'])
        self.assertEqual(self.prepare(('worker', 'api'))[0]['plan']['selected_repositories'], ['worker', 'api'])

    def test_dry_run_imports_no_target_and_writes_no_runtime_state(self):
        (self.root / 'api/storage.py').write_text('raise RuntimeError("must not be imported")\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(['run', '--target', str(self.manifest), '--repo', 'api', '--dry-run'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['native_attempts'], 0)
        self.assertFalse(self.state.exists())

    def test_invalid_second_configuration_prevents_all_execution(self):
        (self.root / 'worker.json').write_text('{"contracts":{},"shell":"echo forbidden"}')
        with patch.object(loop, 'run') as run, self.assertRaises(ValueError):
            self.prepare(('api', 'worker'))
        run.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_unselected_configuration_and_code_are_not_inspected(self):
        (self.root / 'worker.json').write_text('not JSON')
        (self.root / 'worker/storage.py').write_text('import syntax broken')
        self.assertEqual(len(self.prepare()[1]), 1)

    def test_source_and_configuration_changes_invalidate_reviewed_plan(self):
        first = self.prepare()[0]['plan_sha256']
        (self.root / 'api/storage.py').write_text(SOURCE + '# changed\n')
        self.assertNotEqual(first, self.prepare()[0]['plan_sha256'])
        planned, prepared, roots = self.prepare()
        with self.assertRaises(ValueError):
            targets.execute(planned, prepared, roots, self.state, expected=first)
        self.assertFalse(self.state.exists())

    def test_source_drift_after_preparation_stops_before_dispatch(self):
        plan = self.prepare()
        (self.root / 'api/storage.py').write_text(SOURCE + '# drift\n')
        with patch.object(loop, 'run') as run:
            result = self.execute(plan)
        run.assert_not_called()
        self.assertEqual(result['status'], 'STOPPED')
        self.assertEqual(result['native_attempts'], 0)
        self.assertFalse(result['checkout_unchanged'])

    def test_shared_budget_does_not_reset_between_repositories(self):
        plan = self.prepare(('api', 'worker', 'idle'), campaigns=1)
        with patch.object(loop, 'run', side_effect=self.completed) as run:
            result = self.execute(plan)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result['native_attempts'], 1)
        self.assertEqual([row['status'] for row in result['repositories']],
                         ['ADOPTED_IN_SNAPSHOT', 'STOPPED', 'NOT_RUN_AFTER_STOP'])
        self.assertEqual(len(list(Path(result['output']).glob('native-reservation-*.json'))), 1)
        self.assertEqual(result['status'], 'STOPPED')

    def test_failed_dispatch_keeps_attempt_and_preserves_remaining_names(self):
        def fail(*args, **kwargs):
            kwargs['before_native']()
            raise OSError('owned launch failure')
        with patch.object(loop, 'run', side_effect=fail): result = self.execute(self.prepare(('api', 'worker')))
        self.assertEqual(result['native_attempts'], 1)
        self.assertEqual(result['repositories'][1]['status'], 'NOT_RUN_AFTER_STOP')
        self.assertFalse(result['automatic_failed_trial_retry'])

    def test_selected_repository_only_is_dispatched_and_original_sources_are_unchanged(self):
        with patch.object(loop, 'run', side_effect=self.completed) as run:
            result = self.execute(self.prepare())
        self.assertEqual(run.call_count, 1)
        self.assertEqual([row['name'] for row in result['repositories']], ['api'])
        self.assertEqual((self.root / 'api/storage.py').read_text(), SOURCE)
        self.assertTrue(result['checkout_unchanged'])
        self.assertEqual(result['checkout_unchanged_scope'], 'SELECTED_PYTHON_SOURCE_SNAPSHOTS')
        for field in ('independent_generalization_certified', 'natural_source_added_value_certified', 'probability_calibration_certified'):
            self.assertFalse(result[field])

    def test_held_repository_is_partial_and_not_success(self):
        (self.root / 'api.json').write_text('{"contracts":{}}')
        result = self.execute(self.prepare(campaigns=0))
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['repositories'][0]['status'], 'HELD_NO_EXECUTION')
        self.assertEqual(result['native_attempts'], 0)

    def test_zero_campaign_limit_prevents_real_native_dispatch(self):
        with patch.object(runner, 'execute') as native:
            result = self.execute(self.prepare(campaigns=0))
        native.assert_not_called()
        self.assertEqual(result['status'], 'STOPPED')
        self.assertEqual(result['native_attempts'], 0)

    def test_actual_loop_guard_reserves_before_dispatch(self):
        with patch.object(runner, 'execute', side_effect=OSError('owned native failure')) as native:
            result = self.execute(self.prepare(campaigns=2))
        self.assertEqual(native.call_count, 1)
        self.assertEqual(result['native_attempts'], 1)
        child = Path(result['repositories'][0]['output'])
        self.assertEqual(runner.read(child / 'result.json')['status'], 'STOPPED')

    def test_actual_paired_path_forwards_shared_guard(self):
        with patch.object(runner, 'execute', side_effect=OSError('owned paired launch failure')) as native:
            result = self.execute(self.prepare(paired=True, campaigns=2))
        self.assertEqual(native.call_count, 1)
        self.assertEqual(result['native_attempts'], 1)
        self.assertEqual(result['status'], 'STOPPED')

    def test_paired_complete_with_held_arm_is_partial(self):
        def fake(*args, **kwargs):
            kwargs['before_native']()
            return dict(status='COMPLETE', native_campaigns=1, arms={'SOURCE': {'status': 'ADOPTED_IN_SNAPSHOT'},
                                                                  'NO_SOURCE': {'status': 'HELD_NO_EXECUTION'}})
        with patch.object(paired, 'run', side_effect=fake): result = self.execute(self.prepare(paired=True))
        self.assertEqual(result['status'], 'PARTIAL')

    def test_shared_budget_spans_both_comparison_arms(self):
        def fake(*args, **kwargs):
            for arm in ('SOURCE', 'NO_SOURCE'): kwargs['before_native']()
            return dict(status='COMPLETE', native_campaigns=2, arms={arm: {'status': 'NO_COUNTEREXAMPLE'} for arm in runner.ARMS})
        with patch.object(paired, 'run', side_effect=fake): result = self.execute(self.prepare(paired=True, campaigns=1))
        self.assertEqual(result['status'], 'STOPPED')
        self.assertEqual(result['native_attempts'], 1)

    def test_repository_names_cannot_collide_with_aggregate_artifacts(self):
        directory = self.root / 'extra';directory.mkdir()
        (directory / 'storage.py').write_text(SOURCE)
        targets.add(self.manifest, 'result.json', directory, self.root / 'api.json')
        with patch.object(loop, 'run', side_effect=self.completed):
            result = self.execute(self.prepare(('result.json',)))
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertTrue((Path(result['output']) / 'result.json').is_file())
        self.assertEqual(Path(result['repositories'][0]['output']).parent.name, 'repositories')

    def test_repeated_run_name_cannot_overwrite_terminal(self):
        with patch.object(loop, 'run', side_effect=self.completed): self.execute(self.prepare())
        with self.assertRaises(ValueError): self.execute(self.prepare())

    def test_state_inside_any_registered_repository_is_rejected_before_write(self):
        planned, prepared, roots = self.prepare()
        for root in (self.root / 'api/state', self.root / 'idle/state'):
            with self.assertRaises(ValueError): targets.execute(planned, prepared, roots, root)
            self.assertFalse(root.exists())

    def test_symlinked_manifest_root_configuration_and_state_are_rejected(self):
        for name, source in [('linked.json', self.manifest), ('linked-config.json', self.root / 'api.json')]:
            link = self.root / name
            link.symlink_to(source)
            with self.assertRaises(ValueError): targets.path_at(str(link), self.root)
        link = self.root / 'linked-repo'
        link.symlink_to(self.root / 'api')
        with self.assertRaises(ValueError): targets.add(self.manifest, 'linked', link, self.root / 'api.json')
        self.state.symlink_to(self.root / 'api')
        with self.assertRaises(ValueError): self.execute(self.prepare())

    def test_bad_names_and_invalid_bounds_are_rejected(self):
        for name in ('../api', '', '--all', 'a/b', '.', 'a' * 65):
            with self.subTest(name=name), self.assertRaises(ValueError): targets.checked_name(name)
        for options in [dict(seconds=0), dict(seconds=7201), dict(campaigns=-1), dict(campaigns=65), dict(rounds=1), dict(rounds=5)]:
            with self.subTest(options=options), self.assertRaises(ValueError): self.prepare(**options)

    def test_duplicate_keys_nonfinite_json_and_unknown_manifest_fields_are_rejected(self):
        for text in ['{"schema":1,"schema":2}', '{"number":NaN}']:
            (self.root / 'invalid.json').write_text(text)
            with self.assertRaises(ValueError): targets.read_json(self.root / 'invalid.json')
        value = json.loads(self.manifest.read_text());value['command'] = 'forbidden'
        with self.assertRaises(ValueError): targets.validate_manifest(value)

    def test_git_snapshot_excludes_untracked_files_and_does_not_import_sources(self):
        import subprocess
        repo = self.root / 'git-fixture';repo.mkdir()
        (repo / 'tracked.py').write_text('raise RuntimeError("do not import")\n')
        (repo / 'untracked.py').write_text('raise RuntimeError("untracked")\n')
        subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'add', 'tracked.py'], check=True, capture_output=True)
        self.assertEqual(list(runner.load_snapshot(repo)), ['tracked.py'])

    def test_deadline_guard_and_pending_reservations_do_not_refund(self):
        expired = targets.Budget(1, datetime.datetime.now(datetime.timezone.utc))
        with self.assertRaisesRegex(ValueError, 'DEADLINE'): expired.reserve()
        self.assertEqual(expired.attempts, 0)
        budget = targets.Budget(1, datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30))
        budget.reserve()
        with self.assertRaisesRegex(ValueError, 'CAMPAIGN_LIMIT'): budget.reserve()
        self.assertEqual(budget.attempts, 1)


if __name__ == '__main__': unittest.main()
