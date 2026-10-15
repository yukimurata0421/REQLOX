
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
pass  # Package imports resolve from the repository root.
from reqlox_core import incident_reference as c
from reqlox_core import source_discovery_metrics as discovery


def group(i='0', conditions=2):
    return dict(id=i, source_group='s'+i, target_group='t'+i, mechanism_group='m'+i,
                condition_ids=[str(k) for k in range(conditions)], normal_api_sha256='a'*64,
                owned_purpose_sha256='e'*64,
                target_snapshot_sha256='b'*64, source_sha256='c'*64)


def outcome(policy, g, arm, labels=(1, 1, 1)):
    return dict(group_id=g['id'], arm=arm, policy_sha256=c.digest(policy),
        method_revision=policy['method_revision'], normal_api_sha256=g['normal_api_sha256'],
        owned_purpose_sha256=g['owned_purpose_sha256'],
        target_snapshot_sha256=g['target_snapshot_sha256'],
        source_sha256=g['source_sha256'] if arm == 'CORRECT_SOURCE' else None,
        attempted_experiments=3, usage_known=True,
        reserved_amounts={'gcp_jpy':'0', 'jev_usd':'0'},
        conditions={key: dict(zip(discovery.METRICS, labels)) for key in g['condition_ids']},
        first_repair_experiment=3 if labels[-1] == 1 else None)


class DiscoveryMetricsTests(unittest.TestCase):
    def policy(self, groups=None):
        return discovery.prepare(groups or [group()], maximum_experiments=5, method_revision='d'*64)

    def test_source_can_help_discovery_even_when_final_repair_success_is_equal(self):
        p = self.policy(); g = p['groups'][0]
        r = discovery.report(p, [outcome(p, g, 'CORRECT_SOURCE'),
                                  outcome(p, g, 'NO_SOURCE', (0, 0, 1))])
        differences = r['equally_weighted_paired_group_difference_bounds']
        self.assertEqual(differences['fault_discovered'], [1., 1.])
        self.assertEqual(differences['discriminating_experiment'], [1., 1.])
        self.assertEqual(differences['repair_reinjection_pass'], [0., 0.])
        self.assertFalse(r['independent_generalization_certified'])

    def test_absent_arm_remains_unknown_in_the_full_denominator(self):
        p = self.policy(); g = p['groups'][0]
        r = discovery.report(p, [outcome(p, g, 'CORRECT_SOURCE')])
        self.assertEqual(r['attempted_arms'], 2); self.assertEqual(r['missing_arms'], 1)
        self.assertEqual(r['per_arm_condition_metrics']['NO_SOURCE']['fault_discovered']['unknown'], 2)
        self.assertEqual(r['equally_weighted_paired_group_difference_bounds']['fault_discovered'], [0., 1.])

    def test_unknown_oracle_outcome_is_not_invented_as_no_failure(self):
        p = self.policy(); g = p['groups'][0]
        r = discovery.report(p, [outcome(p, g, 'CORRECT_SOURCE', (None, None, None)),
                                  outcome(p, g, 'NO_SOURCE', (0, 0, 0))])
        self.assertEqual(r['equally_weighted_paired_group_difference_bounds']['fault_discovered'], [0., 1.])
        self.assertTrue(r['bounds_are_unknown_label_ranges_not_confidence_intervals'])

    def test_group_average_does_not_weight_one_large_case_catalog_as_more_trials(self):
        p = self.policy([group('0', 2), group('1', 20)]); outcomes = []
        for g in p['groups']:
            outcomes.extend([outcome(p, g, 'CORRECT_SOURCE', (1, 1, 1) if g['id'] == '0' else (0, 0, 0)),
                             outcome(p, g, 'NO_SOURCE', (0, 0, 0))])
        r = discovery.report(p, outcomes)
        self.assertEqual(r['equally_weighted_paired_group_difference_bounds']['fault_discovered'], [.5, .5])
        self.assertAlmostEqual(r['per_arm_condition_metrics']['CORRECT_SOURCE']['fault_discovered']['finite_fraction_bounds'][0], 2/22)

    def test_usage_unknown_preserves_stage_results_but_not_complete_budget_comparison(self):
        p = self.policy(); g = p['groups'][0]; a = outcome(p, g, 'CORRECT_SOURCE'); a['usage_known'] = False
        r = discovery.report(p, [a, outcome(p, g, 'NO_SOURCE')])
        self.assertFalse(r['all_usage_known']); self.assertEqual(r['missing_arms'], 0)

    def test_source_contract_and_target_drift_are_rejected(self):
        p = self.policy(); g = p['groups'][0]
        for field, value in [('policy_sha256', 'f'*64), ('method_revision', 'f'*64),
                             ('normal_api_sha256', 'f'*64), ('target_snapshot_sha256', 'f'*64),
                             ('owned_purpose_sha256', 'f'*64),
                             ('source_sha256', None), ('arm', 'OTHER')]:
            r = outcome(p, g, 'CORRECT_SOURCE'); r[field] = value
            with self.assertRaises(ValueError): discovery.report(p, [r])

    def test_missing_conditions_duplicate_arms_and_boolean_labels_are_rejected(self):
        p = self.policy(); g = p['groups'][0]; r = outcome(p, g, 'CORRECT_SOURCE')
        for mode in ('missing', 'bool', 'identified'):
            bad = deepcopy(r)
            if mode == 'missing': bad['conditions'].pop('0')
            elif mode == 'bool': bad['conditions']['0']['fault_discovered'] = True
            else: bad['conditions']['0']['fault_discovered'] = 0
            with self.assertRaises(ValueError): discovery.report(p, [bad])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_ARM'): discovery.report(p, [r, r])

    def test_experiment_budget_and_first_repair_indices_are_enforced(self):
        p = self.policy(); g = p['groups'][0]
        for field, value in [('attempted_experiments', 6), ('attempted_experiments', 0),
                             ('first_repair_experiment', 4), ('first_repair_experiment', True)]:
            r = outcome(p, g, 'CORRECT_SOURCE'); r[field] = value
            with self.assertRaises(ValueError): discovery.report(p, [r])

    def test_shared_groups_are_reported_without_independence_or_authority_claim(self):
        groups = [group('0'), group('1')]; groups[1]['mechanism_group'] = groups[0]['mechanism_group']
        p = self.policy(groups); r = discovery.report(p, [])
        self.assertFalse(r['source_target_mechanism_ids_disjoint'])
        self.assertFalse(r['execution_authority']); self.assertFalse(p['external_calls_authorized'])

    def test_resealed_policy_cannot_reveal_fault_catalog_or_change_authority(self):
        for field in ('fault_condition_catalog_and_gold_hidden_from_generator', 'execution_authority'):
            p = self.policy(); p[field] = not p[field]; p = c.seal(p)
            with self.assertRaisesRegex(ValueError, 'POLICY_DRIFT'): discovery.report(p, [])

    def test_equal_provider_caps_do_not_require_equal_observed_cost_or_hide_unknown_usage(self):
        p = discovery.prepare([group()], maximum_experiments=5, method_revision='d'*64,
                              provider_reservation_caps={'gcp_jpy':'100', 'jev_usd':'0.01'})
        a = outcome(p, p['groups'][0], 'CORRECT_SOURCE'); b = outcome(p, p['groups'][0], 'NO_SOURCE')
        a['reserved_amounts']['gcp_jpy'] = '50'; b['reserved_amounts']['gcp_jpy'] = '100'
        a['usage_known'] = False
        r = discovery.report(p, [a, b])
        self.assertTrue(r['equal_per_arm_reservation_caps']); self.assertFalse(r['all_usage_known'])
        self.assertEqual(r['known_reserved_totals_per_arm']['CORRECT_SOURCE']['gcp_jpy'], '50')
        self.assertTrue(r['reservations_are_not_invoice_charges'])
        b['reserved_amounts']['gcp_jpy'] = '101'
        with self.assertRaisesRegex(ValueError, 'RESERVATION_LIMIT'): discovery.report(p, [a, b])

    def test_reservation_amounts_cannot_use_boolean_negative_nan_or_wrong_currency(self):
        for value in (True, '-1', 'NaN', '1e100', '1000000001'):
            with self.assertRaises(ValueError):
                discovery.prepare([group()], maximum_experiments=5, method_revision='d'*64,
                                  provider_reservation_caps={'gcp_jpy':value, 'jev_usd':'0'})
        with self.assertRaises(ValueError):
            discovery.prepare([group()], maximum_experiments=5, method_revision='d'*64,
                              provider_reservation_caps={'gcp_jpy':'1', 'usd':'1'})


if __name__ == '__main__': unittest.main()
