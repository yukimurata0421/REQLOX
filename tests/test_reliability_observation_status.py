"""Pure result classification; no Target function or fault injector is run."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import itertools
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
pass  # Package imports resolve from the repository root.
from reqlox_core import reliability_reuse_worker as worker


class ObservationStatusTests(unittest.TestCase):
    def test_all_verdicts_and_precedence(self):
        cases = [
            (False, [None], True, True, True, 'BASELINE_INVALID'),
            (None, [True], False, False, None, 'BASELINE_INVALID'),
            (True, [None, False], True, True, True, 'FAULT_NOT_REACHED'),
            (True, [False], True, True, True, 'REPAIRED'),
            (True, [False], True, True, False, 'REPAIR_FAILED'),
            (True, [False], True, False, None, 'REPAIR_UNSUPPORTED'),
            (True, [True], False, False, None, 'NO_COUNTEREXAMPLE'),
        ]
        for baseline, outcomes, found, executed, repair_pass, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(worker.observation_status(
                    {'contract_pass': baseline}, [{'contract_pass': x} for x in outcomes],
                    found, executed, repair_pass), expected)

    def test_finite_truth_table_preserves_previous_classification(self):
        for baseline, probe, found, executed, repair in itertools.product(
                [True, False, None], [True, False, None], [True, False], [True, False], [True, False, None]):
            if not baseline: expected = 'BASELINE_INVALID'
            elif probe is None: expected = 'FAULT_NOT_REACHED'
            elif executed and repair: expected = 'REPAIRED'
            elif executed: expected = 'REPAIR_FAILED'
            elif found: expected = 'REPAIR_UNSUPPORTED'
            else: expected = 'NO_COUNTEREXAMPLE'
            self.assertEqual(worker.observation_status(
                {'contract_pass': baseline}, [{'contract_pass': probe}], found, executed, repair), expected)
