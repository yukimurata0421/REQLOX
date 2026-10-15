"""Reject incomplete, misleading, and boundary-rounded coverage evidence."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('reqlox_coverage_check',
    Path(__file__).resolve().parents[1] / 'scripts/coverage_check.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = dict(critical_files=['important.py'], minimum_line_percent=95, minimum_branch_percent=90)
        self.report = dict(meta={'branch_coverage': True}, files={'important.py': {'summary': dict(
            covered_lines=95, num_statements=100, covered_branches=9, num_branches=10)}})

    def test_exact_threshold_is_inclusive(self):
        self.assertTrue(gate.evaluate(self.report, self.policy)['passed'])

    def test_rounding_cannot_turn_a_below_threshold_result_into_a_pass(self):
        self.report['files']['important.py']['summary'].update(covered_lines=9499, num_statements=10000)
        self.assertFalse(gate.evaluate(self.report, self.policy)['passed'])

    def test_high_aggregate_coverage_cannot_hide_one_weak_critical_file(self):
        self.report['totals'] = {'percent_covered': 100}
        self.report['files']['important.py']['summary']['covered_branches'] = 8
        self.assertFalse(gate.evaluate(self.report, self.policy)['passed'])

    def test_every_selected_file_must_be_present(self):
        self.policy['critical_files'].append('missing.py')
        with self.assertRaisesRegex(ValueError, 'CRITICAL_FILE_MISSING'):
            gate.evaluate(self.report, self.policy)

    def test_line_only_measurement_cannot_pass_the_branch_gate(self):
        for value in (False, None, 1):
            self.report['meta']['branch_coverage'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'BRANCH_MEASUREMENT_REQUIRED'):
                gate.evaluate(self.report, self.policy)

    def test_boolean_negative_and_inconsistent_counts_are_rejected(self):
        for key, value in (('covered_lines', True), ('covered_lines', -1),
                ('covered_lines', 101), ('num_statements', 1.0), ('covered_branches', 11)):
            report = deepcopy(self.report)
            report['files']['important.py']['summary'][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'REPORT_COUNTS'):
                gate.evaluate(report, self.policy)

    def test_empty_critical_file_cannot_disappear_from_the_denominator(self):
        self.report['files']['important.py']['summary'].update(covered_lines=0, num_statements=0)
        with self.assertRaisesRegex(ValueError, 'CRITICAL_FILE_EMPTY'):
            gate.evaluate(self.report, self.policy)

    def test_a_file_without_branches_reports_not_applicable(self):
        self.report['files']['important.py']['summary'].update(covered_branches=0, num_branches=0)
        value = gate.evaluate(self.report, self.policy)
        self.assertTrue(value['passed'])
        self.assertIsNone(value['files'][0]['branch_percent'])

    def test_policy_rejects_invalid_thresholds_and_selections(self):
        original = json.loads((Path(__file__).resolve().parents[1] / 'coverage-policy.json').read_text())
        variants = []
        for value in (True, -1, 101, '95', float('inf')):
            variants.append(original | {'minimum_line_percent': value})
        for value in ([], ['important.py', 'important.py'], ['../escape.py'], ['/absolute.py'], [None]):
            variants.append(original | {'critical_files': value})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            for value in variants:
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    gate.load_policy(path)


if __name__ == '__main__':
    unittest.main()
