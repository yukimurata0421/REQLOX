"""Safe summary checks with synthetic records; no native execution."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from reqlox_demo import integration_ui as ui


class IntegrationViewTests(unittest.TestCase):
    def audited(self, adopted=True):
        return dict(phases=[dict(attempt=n, status='VERIFIED') for n in (13, 14, 15)],
                    terminal=dict(adoption='ADOPT_EXISTING_CANDIDATE_FOR_ISOLATED_COMPOSED_CALLER' if adopted else 'UNKNOWN_NOT_ADOPTED',
                                  cumulative_native_campaigns=15, cumulative_charged_seconds=62,
                                  new_native_campaigns=3, original_preserved=True,
                                  private_path='/private/raw/evidence', stop_reason='private detail'))

    def rows(self, failed=False):
        return dict(rows=[dict(passed=not (failed and i < 5), scratch_removed=True,
                              lock_released=not (failed and i < 5), owned_pending_removed=not (failed and i < 3))
                          for i in range(10)])

    def test_verified_counts_and_held_repair_status(self):
        with patch.object(ui.integration, 'audit', return_value=self.audited()), \
             patch.object(ui.integration, 'read', side_effect=[self.rows(True), self.rows(), self.rows()]):
            value = ui.summarize(Path('/synthetic/run'))
        self.assertEqual(value['phases'][0]['faults'], dict(passed=0, total=5))
        self.assertEqual(value['phases'][1]['faults'], dict(passed=5, total=5))
        self.assertEqual(value['cumulative_campaigns'], 15)
        self.assertEqual(value['cumulative_charged_seconds'], 62)
        self.assertEqual(value['held_atomic_bindings'], 4)
        self.assertFalse(value['temppath_repair_performed'])

    def test_allowlist_omits_paths_raw_code_and_private_reasons(self):
        with patch.object(ui.integration, 'audit', return_value=self.audited()), \
             patch.object(ui.integration, 'read', return_value=self.rows()):
            value = ui.summarize('/synthetic/run')
        text = json.dumps(value)
        self.assertNotIn('/private', text); self.assertNotIn('private detail', text)
        self.assertNotIn('/synthetic', text)
        self.assertFalse(value['independent_generalization'])
        self.assertFalse(value['additional_execution_enabled'])

    def test_unknown_is_not_adopted(self):
        audited = self.audited(False); audited['phases'][1]['status'] = 'UNKNOWN_MISSING_RECEIPT'
        with patch.object(ui.integration, 'audit', return_value=audited), \
             patch.object(ui.integration, 'read', return_value=self.rows()) as read:
            value = ui.summarize('/synthetic/run')
        self.assertEqual(read.call_count, 2)
        self.assertEqual(value['adoption'], 'NOT_ADOPTED_OR_UNKNOWN')
        self.assertEqual(value['phases'][1]['status'], 'UNKNOWN_MISSING_RECEIPT')

    def test_audit_failure_does_not_expose_a_success_summary(self):
        with patch.object(ui.integration, 'audit', side_effect=ValueError('synthetic failed audit')):
            with self.assertRaises(ValueError): ui.summarize('/synthetic/run')

    def test_config_has_only_startup_registered_readonly_results(self):
        from reqlox_demo.target_ui import TargetLab
        lab = TargetLab(integration_runs=(Path('/synthetic/registered'),))
        with patch.object(lab, 'saved_runs', return_value=[]), patch.object(ui, 'summarize', return_value={'synthetic': True}) as summarize:
            value = lab.configuration('synthetic-token')
        summarize.assert_called_once_with(Path('/synthetic/registered'))
        self.assertEqual(value['integration_results'], [{'synthetic': True}])
        self.assertFalse(value['native_enabled'])

    def test_registration_limit(self):
        from reqlox_demo.target_ui import TargetLab
        with self.assertRaisesRegex(ValueError, 'INTEGRATION_LIMIT'):
            TargetLab(integration_runs=['synthetic'] * 9)
