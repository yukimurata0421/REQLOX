
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

pass  # Package imports resolve from the repository root.
from reqlox_core import incident_reference as c
from reqlox_core import source_discovery_metrics as discovery
from reqlox_core import source_discovery_effort as measured
from reqlox_core import workflow_effort as effort


class EffortDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.group = dict(id='control', source_group='s', target_group='t', mechanism_group='m',
            condition_ids=['case'], normal_api_sha256='a'*64, owned_purpose_sha256='b'*64,
            target_snapshot_sha256='c'*64, source_sha256='d'*64)
        self.policy = discovery.prepare([self.group], maximum_experiments=3, method_revision='e'*64)
        self.counter = 0

    def binding(self, arm):
        g = self.group
        return dict(group_id=g['id'], arm=arm, policy_sha256=c.digest(self.policy),
            method_revision=self.policy['method_revision'], normal_api_sha256=g['normal_api_sha256'],
            owned_purpose_sha256=g['owned_purpose_sha256'], target_snapshot_sha256=g['target_snapshot_sha256'],
            source_sha256=g['source_sha256'] if arm == 'CORRECT_SOURCE' else None)

    def outcome(self, arm):
        return dict(**self.binding(arm), attempted_experiments=1, usage_known=True,
            reserved_amounts={'gcp_jpy': '0', 'jev_usd': '0'},
            conditions={'case': dict(zip(discovery.METRICS, [1, 1, 1]))}, first_repair_experiment=1)

    def summary(self, arm, *, duration=2, complete=True, dollars='0.1', sources=None):
        self.counter += 1; clock = [0]
        recorder = effort.Recorder(self.root/str(self.counter), run_id=arm,
            binding=self.binding(arm), cost_sources=sources or {'api': 'USD', 'compute': 'JPY'},
            human_tracking_complete=complete, retry_tracking_complete=True, clock=lambda: clock[0])
        clock[0] = duration*1000000000
        recorder.cost('api', reserved='1', estimated=dollars, usage_known=True)
        return recorder.finish()

    def report(self, summaries):
        return measured.report(self.policy, [self.outcome(a) for a in discovery.ARMS], summaries)

    def test_same_repair_success_can_have_different_measured_effort(self):
        a = self.summary('CORRECT_SOURCE', duration=2, dollars='0.1')
        b = self.summary('NO_SOURCE', duration=4, dollars='0.2')
        result = self.report([a, b]); pair = result['effort_rows'][0]
        self.assertEqual(result['discovery_report']['equally_weighted_paired_group_difference_bounds']['repair_reinjection_pass'], [0, 0])
        self.assertEqual(pair['source_minus_no_source_effort']['elapsed_seconds'], -2)
        self.assertEqual(pair['source_minus_no_source_costs']['USD']['estimated'], '-0.1')
        self.assertIsNone(pair['source_minus_no_source_costs']['JPY']['estimated'])
        self.assertFalse(result['automation_benefit_certified'])
        self.assertFalse(result['source_contribution_certified'])

    def test_missing_effort_arm_does_not_disappear_or_become_zero(self):
        result = self.report([self.summary('CORRECT_SOURCE')])
        self.assertEqual(result['attempted_arms'], 2)
        self.assertEqual(result['missing_effort_arms'], 1)
        pair = result['effort_rows'][0]
        self.assertIsNone(pair['arms']['NO_SOURCE'])
        self.assertIsNone(pair['source_minus_no_source_effort']['elapsed_seconds'])

    def test_incomplete_human_coverage_does_not_prove_no_intervention(self):
        result = self.report([self.summary('CORRECT_SOURCE', complete=False), self.summary('NO_SOURCE')])
        differences = result['effort_rows'][0]['source_minus_no_source_effort']
        self.assertIsNone(differences['human_active_seconds'])
        self.assertIsNone(differences['observed_interventions'])

    def test_duplicate_measurement_arm_is_rejected(self):
        a = self.summary('CORRECT_SOURCE')
        with self.assertRaisesRegex(ValueError, 'IDENTITY'): self.report([a, a])

    def test_wrong_source_target_method_or_policy_is_rejected(self):
        a = self.summary('CORRECT_SOURCE')
        for field in ('source_sha256', 'target_snapshot_sha256', 'owned_purpose_sha256', 'normal_api_sha256',
                      'method_revision', 'policy_sha256'):
            value = deepcopy(a); value['binding'][field] = 'f'*64
            with self.assertRaisesRegex(ValueError, 'BINDING'): self.report([c.seal(value)])

    def test_source_absence_must_remain_absent_in_the_measurement_binding(self):
        a = self.summary('NO_SOURCE'); a['binding']['source_sha256'] = 'd'*64
        with self.assertRaisesRegex(ValueError, 'BINDING'): self.report([c.seal(a)])

    def test_different_cost_coverage_cannot_create_a_cheaper_arm(self):
        a = self.summary('CORRECT_SOURCE'); b = self.summary('NO_SOURCE', sources={'api': 'USD'})
        with self.assertRaisesRegex(ValueError, 'MEASUREMENT_SCOPE'): self.report([a, b])

    def test_boolean_negative_and_nonfinite_measurement_time_are_rejected(self):
        a = self.summary('CORRECT_SOURCE')
        for value in (True, -1, '2'):
            wrong = deepcopy(a); wrong['elapsed_seconds'] = value
            with self.assertRaisesRegex(ValueError, 'TIME'): self.report([c.seal(wrong)])

    def test_old_discovery_results_are_preserved_when_effort_is_missing(self):
        result = self.report([])
        self.assertEqual(result['discovery_report'], discovery.report(self.policy, [self.outcome(a) for a in discovery.ARMS]))
        self.assertEqual(result['missing_effort_arms'], 2)
        self.assertFalse(result['independent_generalization_certified'])


if __name__ == '__main__': unittest.main()
