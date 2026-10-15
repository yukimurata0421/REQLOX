"""Verify execution orchestration with owned receipts, without native workers."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reqlox_demo import contracts, isolation, portable, repair_contract


SOURCE = '''class Context:
    async def __aenter__(self): pass
    async def __aexit__(self, *args): pass
    @property
    def locked(self): return False
class Owner:
    @property
    def writer(self): return Context()
'''
CONDITIONS = {
    'async-timeouterror': 'TimeoutError', 'async-runtimeerror': 'RuntimeError',
    'async-valueerror': 'ValueError', 'async-cancellederror': 'CancelledError',
    'async-task-cancel': 'CancelledError',
}
STAGES = ('HEALTHY', 'FAULT', 'REPAIR', 'REINJECTION')


class PortableExecutionProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / 'repository'
        self.repository.mkdir()
        raw = SOURCE.encode()
        (self.repository / 'owned.py').write_bytes(raw)
        self.snapshot = {'files': [{'path': 'owned.py', 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}]}
        self.binding = dict(module='owned', owner_class='Owner', owner_kwargs={},
            context_class='Context', context_property='writer', probe='locked', probe_kind='PROPERTY')
        self.proposal = dict(code=repair_contract.HEALTHY, rationale='Owned protocol control', p_repair=.9)
        self.code_hash = hashlib.sha256(self.proposal['code'].encode()).hexdigest()
        self.output = self.root / 'result'
        # Fixed observations describe the finite lifecycle contract independently
        # of portable.execute and repair_contract.expected.
        self.gold = {'expected': {}}
        rows = {}
        for case, exception in CONDITIONS.items():
            self.gold['expected'][case] = {}
            rows[case] = {}
            for stage in STAGES:
                held = stage == 'FAULT'
                base = dict(first_exception=exception if stage in ('FAULT', 'REINJECTION') else None,
                    locked_after_first=held, second_entered=not held, locked_after_second=held)
                self.gold['expected'][case][stage] = base
                rows[case][stage] = dict(base, work_calls=1, work_inside_context=True,
                    exception_preserved=True, returned_none=True, second_owner_different=True,
                    second_wait_timed_out=held)
        self.observed = dict(executed_candidate_sha256=self.code_hash, source_unchanged=True,
            cases=rows, network_attempts=0, different_task_contender=True)
        self.gold_receipt = {'namespace_isolated': True, 'role': 'owned-gold-fixture'}
        self.receipt = {'namespace_isolated': True, 'role': 'owned-native-fixture'}

    def run_protocol(self, observed=None):
        responses = [(deepcopy(self.gold), deepcopy(self.gold_receipt)),
            (deepcopy(self.observed if observed is None else observed), deepcopy(self.receipt))]
        with patch.object(isolation, 'run', side_effect=responses) as worker:
            result = portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        return result, worker

    def test_matching_protocol_persists_candidate_input_and_receipt_bindings(self):
        result, worker = self.run_protocol()
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(result['status'], 'REPRODUCED_AND_REPAIRED')
        self.assertIs(type(result['label']), int)
        self.assertEqual(result['label'], 1)
        self.assertEqual(result['stage_matches'], 20)
        self.assertEqual(result['stage_observations'], 20)
        self.assertEqual(result['condition_pairs'], 5)
        self.assertFalse(result['automatic_retry'])
        self.assertEqual(result['candidate_sha256'], self.code_hash)
        self.assertEqual(result['observation_sha256'], contracts.sha(self.observed))
        self.assertEqual(result['receipt_sha256'], contracts.sha(self.receipt))
        self.assertEqual(result['gold_receipt_sha256'], contracts.sha(self.gold_receipt))
        plan = json.loads((self.output / 'sealed-plan.json').read_text())
        self.assertEqual(plan['candidate_code'], self.proposal['code'])
        self.assertEqual(plan['binding'], self.binding)
        self.assertEqual(plan['input_files'], [{**self.snapshot['files'][0], 'path': '/target/native/owned.py'}])
        self.assertEqual({row['id'] for row in plan['cases']}, set(CONDITIONS))
        self.assertEqual([stage['id'] for stage in plan['stages']], list(STAGES))
        self.assertEqual(worker.call_args_list[1].args[3], [(self.repository, '/target/native')])
        for name in ('sealed-plan.json', 'gold.json', 'result.json'):
            self.assertEqual((self.output / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.output / 'result.json').read_text()), result)
        self.assertEqual((self.repository / 'owned.py').read_text(), SOURCE)

    def test_native_failure_retains_unknown_terminal_and_is_never_retried(self):
        with patch.object(isolation, 'run', side_effect=[(self.gold, self.gold_receipt), OSError('owned failure')]) as worker:
            with self.assertRaisesRegex(OSError, 'owned failure'):
                portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        self.assertEqual(worker.call_count, 2)
        terminal = json.loads((self.output / 'result.json').read_text())
        self.assertEqual(terminal['status'], 'STOPPED')
        self.assertEqual(terminal['native_attempts'], 1)
        self.assertIsNone(terminal['native_executions'])
        self.assertIsNone(terminal['label'])
        self.assertFalse(terminal['automatic_retry'])
        self.assertEqual(terminal['candidate_sha256'], self.code_hash)
        self.assertEqual((self.output / 'result.json').stat().st_mode & 0o777, 0o600)

    def test_gold_failure_prevents_native_dispatch(self):
        with patch.object(isolation, 'run', side_effect=ValueError('owned gold failure')) as worker:
            with self.assertRaisesRegex(ValueError, 'owned gold failure'):
                portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(worker.call_args.args[1], 'gold')
        self.assertFalse((self.output / 'result.json').exists())

    def test_invalid_candidate_stops_before_any_worker(self):
        self.proposal['code'] = 'import os'
        with patch.object(isolation, 'run') as worker, self.assertRaises(ValueError):
            portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        worker.assert_not_called()
        self.assertFalse((self.output / 'sealed-plan.json').exists())

    def test_invalid_binding_stops_before_any_worker(self):
        self.binding['probe'] = 'missing'
        with patch.object(isolation, 'run') as worker, self.assertRaises(ValueError):
            portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        worker.assert_not_called()
        self.assertFalse((self.output / 'sealed-plan.json').exists())

    def test_candidate_hash_drift_is_rejected(self):
        self.observed['executed_candidate_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'PORTABLE_EXECUTION_DRIFT'):
            self.run_protocol()
        self.assertFalse((self.output / 'result.json').exists())

    def test_source_mutation_is_rejected(self):
        self.observed['source_unchanged'] = False
        with self.assertRaisesRegex(ValueError, 'PORTABLE_EXECUTION_DRIFT'):
            self.run_protocol()
        self.assertFalse((self.output / 'result.json').exists())

    def test_missing_repair_observation_is_unknown_instead_of_failure(self):
        del self.observed['cases']['async-runtimeerror']['REPAIR']
        result, _ = self.run_protocol()
        self.assertEqual(result['status'], 'CONTRACT_MISMATCH')
        self.assertIsNone(result['label'])
        self.assertEqual(result['stage_matches'], 19)

    def test_missing_reinjection_observation_is_unknown(self):
        del self.observed['cases']['async-task-cancel']['REINJECTION']
        result, _ = self.run_protocol()
        self.assertIsNone(result['label'])
        self.assertEqual(result['stage_matches'], 19)

    def test_failed_reinjection_is_an_observed_failure(self):
        self.observed['cases']['async-task-cancel']['REINJECTION']['exception_preserved'] = False
        result, _ = self.run_protocol()
        self.assertEqual(result['status'], 'CONTRACT_MISMATCH')
        self.assertEqual(result['label'], 0)
        self.assertEqual(result['stage_matches'], 19)

    def test_healthy_mismatch_does_not_reclassify_matching_repair_as_failure(self):
        self.observed['cases']['async-timeouterror']['HEALTHY']['work_calls'] = 2
        result, _ = self.run_protocol()
        self.assertEqual(result['status'], 'CONTRACT_MISMATCH')
        self.assertEqual(result['label'], 1)
        self.assertEqual(result['stage_matches'], 19)

    def test_same_owner_contender_cannot_count_as_a_matching_repair(self):
        self.observed['cases']['async-valueerror']['REPAIR']['second_owner_different'] = False
        result, _ = self.run_protocol()
        self.assertEqual(result['label'], 0)
        self.assertEqual(result['stage_matches'], 19)

    def test_existing_terminal_directory_is_preserved(self):
        self.output.mkdir()
        prior = self.output / 'result.json'
        prior.write_text('{"status":"STOPPED"}\n')
        with patch.object(isolation, 'run') as worker, self.assertRaises(FileExistsError):
            portable.execute(self.output, self.repository, self.snapshot, self.binding, self.proposal)
        worker.assert_not_called()
        self.assertEqual(prior.read_text(), '{"status":"STOPPED"}\n')


if __name__ == '__main__':
    unittest.main()
