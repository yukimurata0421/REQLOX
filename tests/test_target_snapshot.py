"""Local Target copy, lineage, source drift and private output boundaries."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import test_target_workspace as fixtures
from reqlox import targets, target_audit, target_prepare, target_snapshot as snapshot
from reqlox.target_cli import main
import reliability_reuse as reuse
import run_reliability_reuse as runner


class TargetSnapshotTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.state.mkdir(mode=0o700)
        self.output = self.state / 'copied-target'
    tearDown = fixtures.WorkspaceTests.tearDown

    def copy(self, **options):
        return snapshot.save_bundle(self.manifest, ['api', 'worker'], self.output, **options)

    def receipt(self, mutate):
        path = self.output / 'snapshot.json'
        value = runner.read(path); mutate(value)
        path.write_bytes(reuse.c.canonical(reuse.c.seal(value)))

    def test_copy_selected_code_contracts_and_private_permissions_without_execution(self):
        (self.root / 'api' / '.env').write_text('LOCAL_TEST_FIXTURE_ONLY')
        (self.root / 'api' / 'trace.log').write_text('LOCAL_TEST_FIXTURE_ONLY')
        originals = {name: runner.load_snapshot(self.root / name) for name in ('api', 'worker')}
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            result = self.copy(); audited = snapshot.verify(self.output)
        self.assertEqual(result['status'], 'SNAPSHOTTED')
        self.assertEqual(audited['selected_repositories'], ['api', 'worker'])
        self.assertFalse(audited['repair_verified'])
        self.assertFalse(audited['archived_code_executed'])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        _, manifest, roots = targets.load(result['target'])
        self.assertNotIn('idle', manifest['repositories'])
        for name, root in roots.items():
            self.assertEqual(runner.load_snapshot(root), originals[name])
            self.assertEqual(runner.load_snapshot(self.root / name), originals[name])
            self.assertFalse((root / '.env').exists())
            self.assertFalse((root / 'trace.log').exists())
            self.assertTrue(root.is_relative_to(self.output))
        for path in self.output.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_raw_line_endings_and_source_hash_are_preserved(self):
        original = self.root / 'api/storage.py'
        original.write_bytes(original.read_bytes().replace(b'\n', b'\r\n'))
        before = original.read_bytes(); self.copy()
        self.assertEqual((self.output / 'repositories/api/storage.py').read_bytes(), before)
        self.assertEqual(original.read_bytes(), before)

    def test_selection_order_survives_manifest_serialization(self):
        result = snapshot.save_bundle(self.manifest, ['worker','api','idle'], self.output)
        self.assertEqual(snapshot.verify(self.output)['selected_repositories'], ['worker','api','idle'])
        planned = targets.prepare(result['target'], [], True)[0]
        self.assertEqual(planned['plan']['selected_repositories'], ['worker','api','idle'])
        prepared = target_prepare.save_bundle(result['target'], [], self.state/'prepared-copy', True)
        self.assertEqual(targets.prepare(prepared['target'], [], True)[0]['plan']['selected_repositories'], ['worker','api','idle'])

    def test_copied_roots_cannot_overlap_run_output_or_contain_state(self):
        result = self.copy()
        planned, prepared, roots = targets.prepare(result['target'], ['api'], campaigns=0)
        # The broader private state root may contain separate copy/run subtrees.
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            stopped = targets.execute(planned, prepared, roots, self.state, name='zero-budget-copy')
        self.assertEqual(stopped['status'], 'STOPPED')
        self.assertEqual(stopped['native_attempts'], 0)
        with self.assertRaises(ValueError):
            targets.execute(planned, prepared, roots, self.output/'repositories/api/state')
        with self.assertRaises(ValueError):
            targets.execute(planned, prepared, {'api':self.state/'target-runs'}, self.state)

    def test_copied_target_remains_available_after_original_changes(self):
        result = self.copy()
        (self.root / 'api/storage.py').write_text('raise AssertionError("Must not be imported")\n')
        audited = snapshot.verify(self.output)
        self.assertFalse(audited['original_repository_rechecked'])
        copied = targets.prepare(result['target'], ['api', 'worker'])[0]
        self.assertEqual(copied['plan']['selected_repositories'], ['api', 'worker'])
        self.assertTrue(all(row['executable_sites'] == 1 for row in copied['plan']['repositories']))

    def test_git_roots_copy_only_tracked_python_and_no_metadata(self):
        root = self.root / 'api'
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        subprocess.run(['git', 'add', '--', 'storage.py'], cwd=root, check=True, capture_output=True)
        (root / 'untracked.py').write_text('raise AssertionError("Must not be imported")\n')
        self.copy()
        copied = self.output / 'repositories/api'
        self.assertEqual({p.name for p in copied.iterdir()}, {'storage.py'})
        self.assertFalse((copied / '.git').exists())

    def test_dependency_is_copied_without_installation_and_is_hash_checked(self):
        wheel = self.root / 'owned-0.1-py3-none-any.whl'; wheel.write_bytes(b'OWNED_WHEEL_TRANSPORT_FIXTURE')
        value = runner.read(self.manifest); value['repositories']['api']['dependency'] = wheel.name
        self.manifest.write_text(json.dumps(value))
        self.copy(); self.assertTrue(snapshot.verify(self.output)['snapshot_inputs_verified'])
        copied = self.output / 'dependencies/api' / wheel.name
        self.assertEqual(copied.read_bytes(), wheel.read_bytes())
        copied.write_bytes(b'CHANGED_FIXTURE')
        with self.assertRaisesRegex(ValueError, 'FILE_DRIFT'): snapshot.verify(self.output)

    def test_invalid_selection_configuration_and_copy_bound_write_no_output(self):
        for selected in ([], ['api', 'api'], ['missing']):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                snapshot.save_bundle(self.manifest, selected, self.output)
            self.assertFalse(self.output.exists())
        with patch.object(snapshot, 'MAX_BYTES', 1), self.assertRaisesRegex(ValueError, 'COPY_BOUND'):
            self.copy()
        self.assertFalse(self.output.exists())
        (self.root / 'worker.json').write_text('{"contracts":{"unknown":{}}}')
        with self.assertRaises(ValueError): self.copy()
        self.assertFalse(self.output.exists())

    def test_output_overlap_public_parent_and_existing_destination_are_rejected(self):
        with self.assertRaises(ValueError):
            snapshot.save_bundle(self.manifest, ['api'], self.root / 'api/copied')
        self.state.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'PRIVATE_PARENT'): self.copy()
        self.state.chmod(0o700); self.copy(); before = (self.output / 'snapshot.json').read_bytes()
        with self.assertRaises(ValueError): self.copy()
        self.assertEqual((self.output / 'snapshot.json').read_bytes(), before)

    def test_parent_segments_cannot_hide_an_output_inside_original_repository(self):
        output = self.state / '..' / 'api' / 'copied-target'
        with self.assertRaises(ValueError):
            snapshot.save_bundle(self.manifest, ['api'], output)
        self.assertFalse((self.root/'api/copied-target').exists())
        with self.assertRaises(ValueError):
            target_prepare.save_bundle(self.manifest, ['api'], self.state/'..'/'api'/'prepared-target')
        self.assertFalse((self.root/'api/prepared-target').exists())

    def test_source_drift_before_copy_leaves_no_output(self):
        original = snapshot.unchanged
        def changed(*args):
            (self.root / 'api/storage.py').write_text('changed = True\n')
            return original(*args)
        with patch.object(snapshot, 'unchanged', side_effect=changed), self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
            self.copy()
        self.assertFalse(self.output.exists())

    def test_drift_after_copy_retains_unfinished_directory_without_success_receipt(self):
        original = snapshot.unchanged; count = 0
        def changed(*args):
            nonlocal count
            count += 1
            if count == 2: (self.root / 'worker.json').write_text('{"contracts":{}}')
            return original(*args)
        with patch.object(snapshot, 'unchanged', side_effect=changed), self.assertRaisesRegex(ValueError, 'CONFIGURATION_CHANGED'):
            self.copy()
        self.assertTrue(self.output.exists())
        self.assertFalse((self.output / 'snapshot.json').exists())
        with self.assertRaises(ValueError): snapshot.verify(self.output)
        with self.assertRaises(ValueError): self.copy()

    def test_modified_copy_extra_files_and_symlinks_fail_read_only_audit(self):
        self.copy(); member = self.output / 'repositories/api/storage.py'; before = member.read_bytes()
        member.write_text('changed = True\n')
        with self.assertRaisesRegex(ValueError, 'FILE_DRIFT'): snapshot.verify(self.output)
        member.write_bytes(before); extra = self.output / 'unexpected.log'; extra.write_text('OWNED_FIXTURE')
        with self.assertRaisesRegex(ValueError, 'FILE_DRIFT'): snapshot.verify(self.output)
        extra.unlink(); extra.symlink_to(member)
        with self.assertRaisesRegex(ValueError, 'SYMLINK'): snapshot.verify(self.output)

    def test_resealed_claims_and_external_roots_cannot_promote_snapshot_to_qualification(self):
        self.copy(); before = (self.output / 'snapshot.json').read_bytes()
        for field, value in (('independent_generalization_certified', True), ('native_attempts', 1),
                             ('provider_calls', True), ('original_selected_inputs_unchanged', False)):
            self.receipt(lambda r: r.update({field:value}))
            with self.assertRaisesRegex(ValueError, 'CLAIM_DRIFT'): snapshot.verify(self.output)
            (self.output / 'snapshot.json').write_bytes(before)
        manifest = runner.read(self.output / 'target.json')
        manifest['repositories']['api']['path'] = str(self.root / 'api')
        (self.output / 'target.json').write_text(json.dumps(manifest))
        self.receipt(lambda r: r.update(files={k:v for k,v in target_audit.files(self.output).items()
            if k != 'snapshot.json'}, target_manifest_sha256=targets.digest(manifest)))
        with self.assertRaisesRegex(ValueError, 'PATH_DRIFT'): snapshot.verify(self.output)

    def test_cli_copies_audits_plans_and_rejects_tampered_snapshot_before_native(self):
        def command(args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output): code = main(args)
            return code, json.loads(output.getvalue())
        code, value = command(['target','snapshot','--target',str(self.manifest),'--repo','api','--repo','worker','--output',str(self.output)])
        self.assertEqual(code, 0); self.assertEqual(value['status'], 'SNAPSHOTTED')
        self.assertEqual(command(['target','snapshot-audit','--output',str(self.output)])[0], 0)
        planned = command(['run','--target',str(self.output/'target.json'),'--all','--dry-run'])
        self.assertEqual(planned[0], 0)
        (self.output/'repositories/api/storage.py').write_text('changed = True\n')
        with patch.object(runner,'execute',side_effect=AssertionError('Native execution forbidden')):
            stopped = command(['run','--target',str(self.output/'target.json'),'--all'])
        self.assertEqual(stopped[0], 2)
        self.assertIn('FILE_DRIFT', stopped[1]['reason'])
        self.assertFalse((self.state/'target-runs').exists())

    def test_missing_receipt_stops_direct_and_prepared_targets_before_output(self):
        result = self.copy()
        prepared = target_prepare.save_bundle(result['target'], [], self.state/'prepared-copy', True)
        (self.output/'snapshot.json').unlink()
        for manifest in (result['target'], prepared['target']):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                targets.prepare(manifest, [], True)
            with self.assertRaises(ValueError):
                target_prepare.save_bundle(manifest, [], self.state/'incomplete-preparation', True)
        self.assertFalse((self.state/'target-runs').exists())
        self.assertFalse((self.state/'incomplete-preparation').exists())

    def test_prepared_manifest_cannot_redirect_to_original_or_extend_frozen_copy(self):
        result = self.copy()
        with self.assertRaisesRegex(ValueError, 'membership is frozen'):
            targets.add(result['target'], 'idle', self.root/'idle', self.root/'idle.json')
        prepared = target_prepare.save_bundle(result['target'], [], self.state/'prepared-copy', True)
        manifest = Path(prepared['target']); value = runner.read(manifest)
        value['repositories']['api']['path'] = str(self.root/'api')
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'ROOT_REDIRECT'):
            targets.prepare(manifest, [], True)


if __name__ == '__main__': unittest.main()
