
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

pass  # Package imports resolve from the repository root.
from reqlox_core import incident_reference as c
from reqlox_core import workflow_effort as effort


class Clock:
    def __init__(self): self.value = 0
    def __call__(self): return self.value
    def step(self, seconds=1): self.value += seconds*1000000000


class EffortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.clock = Clock(); self.counter = 0

    def recorder(self, *, complete=True, sources=None):
        self.counter += 1
        return effort.Recorder(self.root/str(self.counter), run_id='control', binding={'target': 'a'*64},
            cost_sources=sources or {'api': 'USD', 'compute': 'JPY'}, human_tracking_complete=complete,
            retry_tracking_complete=True, clock=self.clock, cpu_clock=self.clock)

    def test_wait_and_overlapping_human_activity_are_distinct(self):
        r = self.recorder(); self.clock.step(10)
        r.intervention('CHECK', active_intervals_ns=[[2000000000, 5000000000]],
                       wait_interval_ns=[0, 2000000000], basis='INSTRUMENTED')
        r.intervention('REVIEW', active_intervals_ns=[[4000000000, 6000000000]],
                       wait_interval_ns=[0, 1000000000], basis='SELF_REPORTED')
        result = r.finish()
        self.assertEqual(result['human_active_seconds'], 4)
        self.assertEqual(result['human_wait_seconds'], 2)
        self.assertEqual(result['observed_interventions'], 2)
        self.assertEqual(effort.read(r.directory), result)

    def test_no_observed_intervention_is_unknown_with_partial_coverage(self):
        r = self.recorder(complete=False); result = r.finish()
        self.assertEqual(result['observed_interventions'], 0)
        self.assertIsNone(result['human_active_seconds'])
        self.assertIsNone(result['human_wait_seconds'])

    def test_zero_activity_is_scoped_to_the_runner_not_all_human_work(self):
        result = self.recorder().finish()
        self.assertEqual(result['human_active_seconds'], 0)
        self.assertEqual(result['human_scope'], effort.HUMAN_SCOPE)
        self.assertTrue(result['human_time_outside_runner_unknown'])

    def test_missing_activity_for_one_intervention_is_not_invented(self):
        r = self.recorder(); self.clock.step(3)
        r.intervention('CHECK')
        result = r.finish()
        self.assertEqual(result['observed_interventions'], 1)
        self.assertIsNone(result['human_active_seconds'])

    def test_api_zero_does_not_make_unpriced_compute_or_invoice_zero(self):
        r = self.recorder(); r.cost('api', reserved='0', estimated='0', usage_known=True)
        r.cost('compute')
        result = r.finish(); costs = result['cost_vectors']
        self.assertEqual(costs['USD']['estimated_total'], '0')
        self.assertIsNone(costs['USD']['invoiced_total'])
        self.assertIsNone(costs['JPY']['estimated_total'])

    def test_missing_cost_source_and_partial_total_remain_unknown(self):
        r = self.recorder(sources={'api': 'USD', 'compute': 'USD'})
        r.cost('api', reserved='0.20', estimated='0.10', usage_known=True)
        value = r.finish()['cost_vectors']['USD']
        self.assertEqual(value['estimated_known_subtotal'], '0.10')
        self.assertIsNone(value['estimated_total'])
        self.assertIsNone(value['reserved_total'])

    def test_decimal_totals_and_reconciled_invoices_are_separate(self):
        r = self.recorder(sources={'a': 'USD', 'b': 'USD'})
        for name, amount in [('a', '0.1'), ('b', '0.2')]:
            r.cost(name, reserved='1', estimated=amount, invoiced=amount,
                   usage_known=True, invoice_reconciled=True)
        value = r.finish()['cost_vectors']['USD']
        self.assertEqual(value['reserved_total'], '2')
        self.assertEqual(value['estimated_total'], '0.3')
        self.assertEqual(value['invoiced_total'], '0.3')

    def test_reservation_is_not_a_charge_or_a_known_usage_estimate(self):
        r = self.recorder(); r.cost('api', reserved='10')
        value = r.finish()['cost_vectors']['USD']
        self.assertEqual(value['reserved_total'], '10')
        self.assertIsNone(value['estimated_total']); self.assertIsNone(value['invoiced_total'])

    def test_bad_cost_is_rejected_before_persisting_an_invalid_event(self):
        for value in (True, -1, '-1', 'NaN', 'Infinity', '1e3', '1000000001'):
            with self.subTest(value=value):
                r = self.recorder()
                with self.assertRaises(ValueError): r.cost('api', reserved=value)
                self.assertEqual(r.events, [])
                self.assertEqual(r.finish()['event_count'], 1)

    def test_unknown_usage_estimate_missing_invoice_and_duplicate_cost_are_rejected(self):
        r = self.recorder()
        with self.assertRaises(ValueError): r.cost('api', estimated='1', usage_known=False)
        with self.assertRaises(ValueError): r.cost('api', invoice_reconciled=True)
        r.cost('api', reserved='1')
        with self.assertRaises(ValueError): r.cost('api', reserved='2')
        self.assertEqual(len(r.events), 1)
        r.finish()

    def test_invalid_or_future_activity_cannot_inflate_human_time(self):
        r = self.recorder(); self.clock.step()
        for interval in ([0, 2000000000], [True, 1], [-1, 1], [4, 3]):
            with self.assertRaises(ValueError):
                r.intervention('CHECK', active_intervals_ns=[interval], basis='INSTRUMENTED')
        self.assertEqual(r.events, [])
        r.finish()

    def test_failed_stage_is_saved_and_replayable_after_stop(self):
        r = self.recorder()
        with self.assertRaisesRegex(RuntimeError, 'expected'):
            with r.stage('native'):
                self.clock.step(2); raise RuntimeError('expected')
        result = r.finish('STOPPED', 'RuntimeError')
        self.assertEqual(result['elapsed_seconds'], 2)
        self.assertEqual(result['failed_stages'], 1)
        self.assertEqual(result['stages'][0]['status'], 'FAILED')
        self.assertEqual(effort.read(r.directory), result)

    def test_retry_is_counted_without_erasing_the_failed_stage(self):
        r = self.recorder()
        try:
            with r.stage('probe'): raise RuntimeError()
        except RuntimeError: pass
        r.retry('LOCAL_RECOVERY', 's0000', automatic=True)
        with r.stage('probe_successor'): self.clock.step()
        result = r.finish()
        self.assertEqual(result['retry_count'], 1)
        self.assertEqual(result['observed_automatic_retries'], 1)
        self.assertEqual(result['failed_stages'], 1)
        self.assertFalse(result['measurement_grants_execution_authority'])

    def test_retry_without_a_recorded_failure_is_rejected(self):
        r = self.recorder()
        with self.assertRaises(ValueError): r.retry('RETRY', 's0000', automatic=True)
        r.finish()

    def test_missing_retry_coverage_is_not_a_zero_total(self):
        r = effort.Recorder(self.root/'retry-unknown', run_id='unknown', binding={}, cost_sources={'api': 'USD'})
        self.assertIsNone(r.finish()['retry_count'])

    def test_incomplete_stage_cannot_be_complete_but_can_be_saved_as_stopped(self):
        r = self.recorder(); r.emit('STAGE_START', {'id': 's0', 'name': 'native'})
        with self.assertRaises(ValueError): r.finish()
        self.assertFalse(r.closed)
        self.assertEqual(r.finish('STOPPED')['incomplete_stages'], ['native'])

    def test_terminal_slot_is_reserved_at_the_event_limit(self):
        with patch.object(effort, 'MAX_EVENTS', 4):
            r = self.recorder()
            with r.stage('probe'): pass
            r.intervention('CHECK')
            with self.assertRaises(ValueError): r.cost('api', reserved='0')
            self.assertEqual(r.finish('STOPPED')['event_count'], 4)

    def test_clock_regression_is_rejected_without_altering_the_trace(self):
        r = self.recorder(); self.clock.step(); r.cost('api', reserved='0')
        self.clock.value = 0
        with self.assertRaises(ValueError): r.finish()
        self.clock.step(2)
        self.assertEqual(r.finish('STOPPED')['event_count'], 2)

    def test_existing_trace_cannot_be_overwritten_and_finish_is_terminal(self):
        r = self.recorder(); r.finish()
        with self.assertRaises(FileExistsError):
            effort.Recorder(r.directory, run_id='control', binding={}, cost_sources={'api': 'USD'})
        with self.assertRaises(ValueError): r.finish()

    def test_symlinks_cannot_redirect_writes_or_reading_events(self):
        (self.root/'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            effort.Recorder(self.root/'link'/'run', run_id='control', binding={}, cost_sources={'api': 'USD'})
        r = self.recorder(); r.finish()
        (r.directory/'events').rename(r.directory/'old-events')
        (r.directory/'events').symlink_to(r.directory/'old-events', target_is_directory=True)
        with self.assertRaises(ValueError): effort.read(r.directory)

    def test_changed_or_reordered_events_and_summary_are_rejected(self):
        r = self.recorder(); self.clock.step(); r.cost('api', reserved='0'); r.finish()
        path = r.directory/'events'/'0000.json'; original = path.read_bytes()
        event = json.loads(original); event['offset_ns'] = 0
        path.write_bytes(c.canonical(c.seal(event)))
        with self.assertRaises(ValueError): effort.read(r.directory)
        path.write_bytes(original)
        summary = r.directory/'summary.json'; value = json.loads(summary.read_bytes())
        value['human_active_seconds'] = 999; summary.write_bytes(c.canonical(c.seal(value)))
        with self.assertRaises(ValueError): effort.read(r.directory)


if __name__ == '__main__': unittest.main()
