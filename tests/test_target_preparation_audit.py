"""Preparation provenance, aggregate integrity and read-only audit boundaries."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import reqlox
reqlox._runtime()
from reqlox import targets, target_prepare, target_audit
import reliability_reuse as reuse
import run_reliability_reuse as runner
import run_reliability_improvement_loop as loop
import test_target_workspace as fixtures


class TargetPreparationAuditTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.state.mkdir(mode=0o700)
    tearDown = fixtures.WorkspaceTests.tearDown
    prepare = fixtures.WorkspaceTests.prepare
    execute = fixtures.WorkspaceTests.execute

    def bundle(self, **options):
        return target_prepare.save_bundle(self.manifest, ['api', 'worker'], self.state / 'prepared', **options)

    def rewrite(self, path, mutate):
        value = json.loads(path.read_text()); mutate(value)
        path.write_bytes(reuse.c.canonical(reuse.c.seal(value)))

    def zero_run(self, **options):
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            return self.execute(self.prepare(('api', 'worker'), campaigns=0, **options))

    def test_source_preparation_reuses_existing_projection_and_preserves_originals(self):
        before = self.manifest.read_bytes()
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            result = self.bundle(natural_source={'source_texts': {'incident': 'fsync returned an error.'}})
        self.assertEqual(result['status'], 'PREPARED')
        self.assertEqual(self.manifest.read_bytes(), before)
        generated = targets.prepare(Path(result['target']), ['api', 'worker'])[0]
        self.assertEqual(generated['plan']['selected_repositories'], ['api', 'worker'])
        config = targets.read_json(self.state / 'prepared/api.configuration.json')
        self.assertTrue(config['hypotheses'])
        record = runner.read(self.state / 'prepared/api.preparation.json')
        self.assertFalse(record['execution_authority'])
        self.assertEqual(record['configuration_sha256'], targets.digest(config))
        self.assertEqual((self.state / 'prepared').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state / 'prepared/target.json').stat().st_mode & 0o777, 0o600)

    def test_source_preparation_preserves_the_registered_probe_limit(self):
        config = runner.read(self.root / 'api.json'); config['maximum_probes'] = 1
        (self.root / 'api.json').write_text(json.dumps(config))
        self.bundle(natural_source={'source_texts': {'incident': 'fsync returned an error.'}})
        prepared = targets.read_json(self.state / 'prepared/api.configuration.json')
        self.assertEqual(prepared['maximum_probes'], 1)

    def test_empty_source_preserves_owned_contracts_without_inventing_evidence(self):
        self.bundle()
        config = targets.read_json(self.state / 'prepared/api.configuration.json')
        self.assertEqual(config['source_texts'], {})
        self.assertEqual(config['hypotheses'], [])
        self.assertEqual(config['contracts'], runner.read(self.root / 'api.json')['contracts'])

    def test_condition_records_are_prepared_without_silently_adding_modes(self):
        result = self.bundle(condition_input={'records': [], 'source_texts': {'incident': 'fsync returned an error.'}})
        self.assertTrue(all(r['mode'] == 'PROVIDED_CONDITION_RECORDS' for r in result['repositories']))
        self.assertEqual(targets.read_json(self.state / 'prepared/api.configuration.json')['hypotheses'], [])

    def test_unknown_input_fields_and_conflicting_source_modes_write_nothing(self):
        for options in ({'natural_source': {'source_texts': {}, 'command': 'forbidden'}},
                        {'natural_source': {'source_texts': {}}, 'condition_input': {'records': [], 'source_texts': {}}},
                        {'packets': {}}, {'source_index': self.root / 'missing'}):
            with self.subTest(options=options), self.assertRaises(ValueError): self.bundle(**options)
            self.assertFalse((self.state / 'prepared').exists())

    def test_bad_second_contract_prevents_all_preparation_outputs(self):
        (self.root / 'worker.json').write_text('{"contracts":{"unknown":{}}}')
        with self.assertRaises(ValueError): self.bundle()
        self.assertFalse((self.state / 'prepared').exists())

    def test_reusing_preparation_output_does_not_replace_evidence(self):
        self.bundle(); before = (self.state / 'prepared/target.json').read_bytes()
        with self.assertRaises(ValueError): self.bundle()
        self.assertEqual((self.state / 'prepared/target.json').read_bytes(), before)

    def test_preparation_output_inside_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            target_prepare.save_bundle(self.manifest, ['api'], self.root / 'api/prepared')

    def test_specification_selection_must_match_selected_repositories(self):
        with self.assertRaises(ValueError): self.bundle(specification_input={'repositories': {'api': {}}})
        self.assertFalse((self.state / 'prepared').exists())

    def test_source_cannot_be_reclassified_as_target_specification(self):
        text = 'Preserve the existing destination. Propagate exceptions. Remove only temporary files owned by this call.'
        specs = {'repositories': {name: {'specification_texts': {'spec': text},
            'owner_policies': {'atomic_file': {'basis': 'Owner requirements', 'scope': 'Owned test snapshot'}}}
            for name in ('api', 'worker')}}
        with self.assertRaisesRegex(ValueError, 'ROLE_COLLISION'):
            self.bundle(natural_source={'source_texts': {'incident': text}}, specification_input=specs)

    def test_stopped_run_audit_preserves_unknowns_and_executes_no_archived_code(self):
        result = self.zero_run(); output = Path(result['output'])
        before = target_audit.files(output)
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            audited = target_audit.audit(output)
        self.assertEqual(audited['historical_status'], 'STOPPED')
        self.assertTrue(audited['aggregate_consistency_verified'])
        self.assertFalse(audited['child_semantics_verified'])
        self.assertFalse(audited['archived_code_executed'])
        self.assertEqual(target_audit.files(output), before)

    def test_failed_dispatch_reservation_is_bound_to_repository_and_plan(self):
        with patch.object(runner, 'execute', side_effect=OSError('Owned mocked launch failure')):
            result = self.execute(self.prepare(('api', 'worker'), campaigns=2))
        output = Path(result['output'])
        self.assertEqual(target_audit.audit(output)['native_attempts'], 1)
        path = output / 'native-reservation-001.json'
        before = path.read_bytes()
        for field, value in (('repository', 'worker'), ('plan_sha256', '0'*64), ('maximum', 3)):
            record = json.loads(before); record[field] = value; path.write_text(json.dumps(record))
            with self.assertRaises(ValueError): target_audit.audit(output)
            path.write_bytes(before)

    def test_paired_stop_is_audited_without_promoting_either_arm(self):
        audited = target_audit.audit(self.zero_run(paired=True)['output'])
        self.assertEqual(audited['historical_status'], 'STOPPED')
        self.assertFalse(audited['child_semantics_verified'])

    def test_real_partial_without_eligible_sites_uses_current_semantic_verifier(self):
        for name in ('api', 'worker'): (self.root / (name+'.json')).write_text('{"contracts":{}}')
        result = self.zero_run()
        audited = target_audit.audit(result['output'])
        self.assertEqual(audited['historical_status'], 'PARTIAL')
        self.assertTrue(audited['child_semantics_verified'])
        self.assertEqual(audited['verified_repositories'], ['api', 'worker'])

    def test_aggregate_budget_selection_and_false_success_tampering_are_rejected(self):
        result = self.zero_run(); path = Path(result['output']) / 'result.json'; before = path.read_bytes()
        for mutate in (lambda v: v.update(native_attempts=1), lambda v: v.update(status='COMPLETE', reason=None),
                       lambda v: v['repositories'].reverse(), lambda v: v.update(independent_generalization_certified=True)):
            self.rewrite(path, mutate)
            with self.assertRaises(ValueError): target_audit.audit(path.parent)
            path.write_bytes(before)

    def test_preparation_contract_and_snapshot_tampering_are_rejected(self):
        result = self.zero_run(); output = Path(result['output']); path = output/'preparations/api.json'; before=path.read_bytes()
        for mutate in (lambda v: v['sources'].update({'storage.py': 'changed=1\n'}),
                       lambda v: v['configuration']['contracts'].clear()):
            self.rewrite(path, mutate)
            with self.assertRaises(ValueError): target_audit.audit(output)
            path.write_bytes(before)

    def test_child_file_edits_and_symlinks_are_rejected(self):
        output=Path(self.zero_run()['output']); child=output/'repositories/api'
        path=child/'result.json'; before=path.read_bytes(); path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'FILE_DRIFT'): target_audit.audit(output)
        path.write_bytes(before); (child/'extra').symlink_to(self.root/'api.json')
        with self.assertRaisesRegex(ValueError, 'SYMLINK'): target_audit.audit(output)

    def test_method_change_stops_before_any_archived_python_is_loaded(self):
        output=Path(self.zero_run()['output'])
        self.rewrite(output/'input.json', lambda v: (v['plan']['method']['core'].update({'unknown.py':'0'*64}),
            v.update(plan_sha256=targets.digest(v['plan']))))
        with self.assertRaisesRegex(ValueError, 'METHOD_UNSUPPORTED'): target_audit.audit(output)

    def test_missing_terminal_is_incomplete_and_does_not_write_recovery_state(self):
        output=Path(self.zero_run()['output']); (output/'result.json').unlink(); before=target_audit.files(output)
        result=target_audit.audit(output)
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertEqual(result['historical_status'], 'UNKNOWN_TERMINAL')
        self.assertEqual(target_audit.files(output), before)

    def test_new_claims_and_provider_counts_cannot_be_inferred_from_audit(self):
        result=target_audit.audit(self.zero_run()['output'])
        for key in ('independent_generalization_certified','natural_source_added_value_certified','probability_calibration_certified'):
            self.assertFalse(result[key])
        self.assertEqual(result['new_native_campaigns'], 0)
        self.assertEqual(result['new_provider_calls'], 0)


if __name__ == '__main__': unittest.main()
