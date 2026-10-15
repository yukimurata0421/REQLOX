"""Reject private material and unsupported claims in the hosted aggregate."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import copy
import json
from pathlib import Path
import unittest

from reqlox_demo.integration_ui import summarize_public


class PublicAggregateTests(unittest.TestCase):
    def record(self):
        return json.loads((Path(__file__).parents[1] / 'reqlox_demo/data/copied-module-integration-summary.json').read_text())

    def test_archived_label_and_no_execution_authority(self):
        value = summarize_public(self.record())
        self.assertEqual(value['audit'], 'ARCHIVED_LOCAL_HASH_AUDIT')
        self.assertEqual(value['cumulative_campaigns'], 15)
        self.assertFalse(value['additional_execution_enabled'])
        self.assertNotIn('/home/', json.dumps(value))

    def test_unknown_root_and_nested_fields_rejected(self):
        for location in ('root', 'summary', 'phase', 'count'):
            value = self.record()
            target = value if location == 'root' else value['summary'] if location == 'summary' else value['summary']['phases'][0] if location == 'phase' else value['summary']['phases'][0]['faults']
            target['raw_path'] = '/private/raw'
            with self.assertRaises(ValueError): summarize_public(value)

    def test_execution_and_unproven_claims_cannot_be_enabled(self):
        for key in ('additional_execution_enabled', 'independent_generalization', 'probability_calibration', 'source_added_value', 'temppath_repair_performed'):
            value = self.record(); value['summary'][key] = True
            with self.assertRaises(ValueError): summarize_public(value)

    def test_invalid_counts_and_boolean_numbers_rejected(self):
        for passed in (-1, 6, True, '5'):
            value = self.record(); value['summary']['phases'][0]['faults']['passed'] = passed
            with self.assertRaises(ValueError): summarize_public(value)

    def test_missing_or_wrong_phase_is_not_confirmed(self):
        value = self.record(); value['summary']['phases'].pop()
        with self.assertRaises(ValueError): summarize_public(value)
        value = self.record(); value['summary']['phases'][2]['attempt'] = 16
        with self.assertRaises(ValueError): summarize_public(value)

    def test_result_does_not_mutate_packaged_record(self):
        value = self.record(); original = copy.deepcopy(value)
        output = summarize_public(value); output['phases'][0]['faults']['passed'] = 1
        self.assertEqual(value, original)
