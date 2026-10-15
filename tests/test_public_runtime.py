"""Portability, state containment, and paid-call terminal behavior."""
import datetime
import importlib.resources
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import reqlox
reqlox._runtime()
from reqlox_paths import ensure_state, state_root
import run_reliability_reuse as runner
from reqlox_demo import contracts, model, repair, repair_contract
from reqlox_demo.cloud_model import LiveModel, ProviderFailure


def scope_config():
    return dict(project="unit-test-project", location="global", model="gemini-test",
                deadline=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).isoformat(),
                maximum_calls=2, maximum_output_tokens=2048,
                per_call_reserved_usd="0.01", maximum_reserved_usd="0.02")


def wire():
    return {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15}}


def answers(baseline):
    return {"support": {"choice": "SUPPORTED", "probabilities": {"SUPPORTED": .9, "NOT_SUPPORTED": .05, "INSUFFICIENT_INFORMATION": .05}},
            "anchor": {"choice": baseline["all_evidence_handles"][0]["id"]},
            "forecast": {"choice": "ALL_STAGES_MATCH", "probabilities": {"ALL_STAGES_MATCH": .8, "STAGE_MISMATCH": .1, "INSUFFICIENT_INFORMATION": .1}}}


class PortableStateTests(unittest.TestCase):
    def test_state_is_private_and_outside_package(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"REQLOX_STATE_DIR": str(Path(directory)/"state")}):
            state=ensure_state()
            self.assertEqual(state.stat().st_mode & 0o777, 0o700)
            self.assertEqual(runner.private(state/"result", new=True), state/"result")
            with self.assertRaises(ValueError): runner.private(Path(directory)/"escape")

    def test_shared_or_symlink_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); shared=root/"shared";shared.mkdir(mode=0o755)
            with patch.dict(os.environ, {"REQLOX_STATE_DIR": str(shared)}), self.assertRaises(ValueError): ensure_state()
            link=root/"link";link.symlink_to(shared)
            with patch.dict(os.environ, {"REQLOX_STATE_DIR": str(link)}), self.assertRaises(ValueError): state_root()

    def test_non_git_sources_are_inspected_without_importing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/"module.py").write_text("raise RuntimeError('must not be imported')\n")
            self.assertEqual(runner.load_snapshot(p), {"module.py": "raise RuntimeError('must not be imported')\n"})

    def test_linked_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/"source.txt").write_text("pass\n");(p/"module.py").symlink_to(p/"source.txt")
            with self.assertRaises(ValueError):runner.load_snapshot(p)

    def test_public_api_and_installed_assets(self):
        self.assertFalse(reqlox.inventory({"empty.py":"x=1\n"})["accepted"])
        assets=importlib.resources.files("reqlox_demo")
        self.assertIn("REQLOX", (assets/"static/index.html").read_text())
        self.assertFalse((assets/"data/repair-records.json").is_file())


class CloudTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.scope=scope_config();(self.base/"phase-user-scope.json").write_text(json.dumps(self.scope))
        self.transport=Mock()
        self.live=LiveModel(self.base,self.transport)
        self.report=contracts.SAMPLES[0]["report"]
        self.baseline=contracts.baseline(self.report)

    def tearDown(self):self.temp.cleanup()

    def assess(self, live=None):
        return (live or self.live).assess(self.report,"py-cachify",self.baseline,"OMIT_EXIT")

    def test_live_assessment_uses_no_private_development_modules(self):
        self.transport.generate.return_value=(answers(self.baseline),wire())
        value=self.assess()
        self.assertEqual(value["choice"],"SUPPORTED")
        self.assertEqual(value["reserved_usd"],"0.01")
        self.assertFalse(value["calibrated"])
        self.assertEqual(self.transport.generate.call_count,1)

    def test_unknown_outcome_retains_reservation_and_stops_across_instances(self):
        self.transport.generate.side_effect=ValueError("unknown")
        other=LiveModel(self.base,self.transport)
        for live in (self.live,self.live,other,LiveModel(self.base,self.transport)):
            with self.assertRaises(ValueError):self.assess(live)
        self.assertEqual(self.transport.generate.call_count,1)
        ledger=json.loads((self.base/"model-ledger.json").read_text())
        self.assertEqual(ledger["reserved_usd"],"0.01")
        self.assertEqual(ledger["attempts"][0]["status"],"OUTCOME_UNKNOWN")

    def test_missing_usage_stops_before_execution(self):
        self.transport.generate.return_value=(answers(self.baseline),{})
        with self.assertRaises(ValueError):self.assess()
        self.assertTrue((self.base/"demo-model-stopped.json").exists())
        self.assertEqual(self.transport.generate.call_count,1)

    def test_invalid_anchor_and_probabilities_stop(self):
        output=answers(self.baseline);output["anchor"]["choice"]="invented"
        self.transport.generate.return_value=(output,wire())
        with self.assertRaises(ValueError):self.assess()
        self.assertTrue(self.live.blocked)

    def test_call_reservation_bound_survives_restart(self):
        self.transport.generate.return_value=(answers(self.baseline),wire())
        self.assess();self.assess(LiveModel(self.base,self.transport))
        with self.assertRaises(ValueError):self.assess(LiveModel(self.base,self.transport))
        self.assertEqual(self.transport.generate.call_count,2)

    def test_expired_scope_never_calls_provider(self):
        self.live.scope["deadline"]="2000-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):self.assess()
        self.transport.generate.assert_not_called()

    def test_changed_scope_never_reuses_budget(self):
        self.transport.generate.return_value=(answers(self.baseline),wire());self.assess()
        scope=dict(self.scope,maximum_calls=3)
        (self.base/"phase-user-scope.json").write_text(json.dumps(scope))
        with self.assertRaises(ValueError):self.assess(LiveModel(self.base,self.transport))
        self.assertEqual(self.transport.generate.call_count,1)

    def test_running_instance_detects_changed_scope_before_provider_request(self):
        scope = dict(self.scope, maximum_reserved_usd="1")
        (self.base/"phase-user-scope.json").write_text(json.dumps(scope))
        with self.assertRaises(ValueError):self.assess()
        self.transport.generate.assert_not_called()
        self.assertTrue((self.base/"demo-model-stopped.json").exists())

    def test_failed_provider_response_is_kept_in_private_state(self):
        self.transport.generate.side_effect=ProviderFailure("response unavailable",{"http_status":400,"body":"failure"})
        with self.assertRaises(ValueError):self.assess()
        files=list(self.base.glob("judgment/*/failed-response.json"))
        self.assertEqual(len(files),1)
        self.assertEqual(files[0].stat().st_mode & 0o777,0o600)

    def test_generated_repair_and_forecast_are_separate_bound_calls(self):
        proposal={"code":repair_contract.BASELINE,"rationale":"Protect owned cleanup","p_repair":.6}
        self.transport.generate.side_effect=[(proposal,wire()),({"p_success":.7},wire())]
        value=self.live.propose_repair(self.report,"py-cachify","OMIT_EXIT")
        self.assertEqual(value["code"],repair_contract.BASELINE)
        self.assertEqual(value["forecast"]["event"],repair.EVENT)
        self.assertEqual(value["forecast"]["p_success"],.7)
        self.assertEqual(self.transport.generate.call_count,2)
        self.assertFalse(value["forecast_was_recorded"])

    def test_unsafe_generated_code_is_never_forwarded_to_forecast(self):
        self.transport.generate.return_value=({"code":"import os\n","rationale":"unsafe","p_repair":.5},wire())
        with self.assertRaises(ValueError):self.live.propose_repair(self.report,"py-cachify","OMIT_EXIT")
        self.assertEqual(self.transport.generate.call_count,1)


if __name__ == "__main__":unittest.main()
