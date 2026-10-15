"Finite reliability controls and verification."

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reqlox_demo import contracts, repair, repair_contract as contract, repair_model, repair_benchmark
from reqlox_demo.engine import Demo, public_view


class RepairSafetyTests(unittest.TestCase):
    def test_safe_grammar_does_not_assert_correctness(self):
        for code in [contract.HEALTHY, contract.BASELINE, "def critical_section(ctx, do_work):\n    pass\nasync def async_critical_section(ctx, do_work):\n    pass\n",
                     contract.HEALTHY.replace("do_work()", "do_work()\n        do_work()", 1)]:
            self.assertFalse(contract.validate(code)["correctness_certified"])

    def test_process_file_network_and_introspection_are_outside_grammar(self):
        for operation in ["open('x')", "__import__('os')", "ctx.__class__", "do_work.__globals__", "ctx.lock()",
                          "critical_section(ctx, do_work)", "ctx.__enter__(do_work())", "ctx.__exit__(None, None, do_work())",
                          "while True:\n        pass", "import os", "global ctx", "ctx = do_work()"]:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                contract.validate(contract.HEALTHY.replace("do_work()", operation, 1))

    def test_decorators_defaults_annotations_and_nested_functions_rejected(self):
        for code in ["@do_work\n" + contract.HEALTHY, contract.HEALTHY.replace("ctx, do_work", "ctx, do_work=None", 1),
                     contract.HEALTHY.replace("ctx, do_work", "ctx: do_work, do_work", 1),
                     contract.HEALTHY.replace("do_work()", "def nested():\n            pass", 1),
                     contract.HEALTHY + "\ndo_work()\n"]:
            with self.assertRaises(ValueError):
                contract.validate(code)

    def test_try_finally_is_not_limited_to_the_reference_patch(self):
        code = contract.BASELINE.replace("    do_work()\n    ctx.__exit__(None, None, None)",
            "    try:\n        do_work()\n    finally:\n        ctx.__exit__(None, None, None)").replace(
            "    await do_work()\n    await ctx.__aexit__(None, None, None)",
            "    try:\n        await do_work()\n    finally:\n        await ctx.__aexit__(None, None, None)")
        self.assertTrue(contract.validate(code)["safe_grammar"])

    def test_real_task_cancellation_is_separate_from_direct_exception(self):
        rows = contract.cases("py-cachify")
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(c["fault_kind"] == "TASK_CANCEL" for c in rows), 1)
        self.assertEqual(len(contract.cases("readerwriterlock")), 4)


class RepairEvidenceTests(unittest.TestCase):
    def proposal(self):
        return {"code": contract.HEALTHY, "rationale": "owned test", "p_repair": .9,
                "forecast": {"probabilities": {"PASS": .8, "FAIL": .2, "INSUFFICIENT_INFORMATION": 0}},
                "method": "RECORDED_GENERATED_REPAIR", "forecast_was_recorded": True}

    def test_missing_prediction_label_is_not_failure_and_replay_is_not_prospective(self):
        value = repair.probability(.8, None, recorded=True)
        self.assertIsNone(value["brier"])
        self.assertIsNone(value["label"])
        self.assertEqual(value["prospective_forecast_count"], 0)
        self.assertEqual(repair.probability(.8, 0)["brier"], .8**2)
        self.assertAlmostEqual(repair.probability(.8, 1)["brier"], .04)

    def test_binary_outcome_requires_integer_or_unknown_without_numeric_coercion(self):
        from decimal import Decimal
        class IntegerSubclass(int):
            pass
        for label in [True, False, 0.0, 1.0, Decimal(1), IntegerSubclass(1), "1", -1, 2]:
            with self.subTest(label=repr(label)), self.assertRaises(ValueError):
                repair.probability(.8, label)
        for label in [0, 1, None]:
            value = repair.probability(.8, label)
            self.assertIs(type(value["label"]), type(label))
            self.assertEqual(value["label"], label)

    def test_probability_rejects_boolean_nonfinite_and_out_of_range_forecasts(self):
        for forecast in [True, False, float("nan"), float("inf"), -float("inf"), -.01, 1.01]:
            with self.subTest(forecast=forecast), self.assertRaises(ValueError):
                repair.probability(forecast, 1)
        self.assertEqual(repair.probability(0, 0)["brier"], 0)
        self.assertEqual(repair.probability(1, 1)["brier"], 0)

    def test_forecast_has_code_binding_but_no_results_or_gold(self):
        payload = repair_model.forecast_payload({"candidate": {"code": contract.BASELINE, "target": "py-cachify"}})
        self.assertEqual(payload["state"]["subjects"]["candidate"]["code"], contract.BASELINE)
        self.assertFalse(payload["state"]["execution_authority"])
        self.assertTrue(payload["state"]["cases_and_gold_and_runtime_hidden"])
        self.assertNotIn("expected", payload["state"])
        self.assertEqual(set(payload["questions"]["candidate"]["criteria"]), {"PASS", "FAIL"})

    def test_new_generation_payload_binds_selected_target(self):
        p = repair_model.generation_payload(contracts.SAMPLES[0]["report"], "OMIT_EXIT", "readerwriterlock")
        self.assertEqual(json.loads(p["prompt"])["target"]["name"], "readerwriterlock")

    def test_live_predecessor_stop_marker_blocks_all_provider_calls(self):
        from reqlox_demo.model import LiveModel
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "phase-user-scope.json").write_text("{}")
            model = LiveModel(base)
            (base / "demo-model-stopped.json").write_text("{}")
            with patch("reqlox_demo.cloud_model.VertexTransport.generate") as generate, patch("reqlox_demo.cloud_model.VertexTransport.generate") as judge:
                with self.assertRaises(ValueError):
                    repair_model.live(model, contracts.SAMPLES[0]["report"], "py-cachify", "OMIT_EXIT")
                generate.assert_not_called()
                judge.assert_not_called()

    def test_replay_benchmark_preserves_missing_and_never_calls_provider(self):
        def stopped(engine, value, directory, proposal):
            value.update(native_attempts=1, native_executions=None)
            raise ValueError("missing native receipt")
        with tempfile.TemporaryDirectory() as d, patch.object(repair, "execute", side_effect=stopped), \
             patch("reqlox_demo.cloud_model.VertexTransport.generate") as generate, patch("reqlox_demo.cloud_model.VertexTransport.generate") as judge:
            controls = {'controls': [{'id': 'owned-control-' + str(i), 'target': 'py-cachify',
                'code': contract.HEALTHY, 'candidate_sha256': contract.validate(contract.HEALTHY)['code_sha256'],
                'expected_repair_label': 1, 'expected_role': 'OWNED_TEST_CONTROL',
                'forecast': self.proposal()['forecast'], 'forecast_rubric': 'binary-repair-v2'} for i in range(18)]}
            controls['record_sha256'] = contracts.sha(controls)
            control_path = Path(d)/'owned-controls.json'
            control_path.write_text(json.dumps(controls))
            with patch.object(repair_benchmark, 'CONTROLS', control_path), \
                 patch.object(repair, 'recorded', return_value=self.proposal()):
                value = repair_benchmark.run(Demo(Path(d)/'cache'))
            self.assertEqual(value["denominator"], 20)
            self.assertEqual(value["missing_or_stopped"], 20)
            self.assertEqual(value["correct"], 0)
            self.assertEqual(value["status"], "FAILED")
            self.assertEqual(value["prospective_forecast_count"], 0)
            generate.assert_not_called()
            judge.assert_not_called()

    def test_record_binds_source_target_policy_and_code(self):
        report = contracts.SAMPLES[0]["report"]
        data = {"proposal": self.proposal(), "candidate_sha256": contract.validate(contract.HEALTHY)["code_sha256"],
                "proposal_sha256": "owned", "records": [{"binding_sha256": repair.record_key(report, "py-cachify", "OMIT_EXIT"),
                                                         "forecast": self.proposal()["forecast"]}]}
        data["record_sha256"] = contracts.sha(data)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "record.json"
            p.write_bytes(contracts.encode(data))
            with patch.object(repair, "RECORDS", p):
                self.assertEqual(repair.recorded(report, "py-cachify", "OMIT_EXIT")["generation_calls_this_run"], 0)
                for text, target, policy in [(report+"\u7de8\u96c6", "py-cachify", "OMIT_EXIT"), (report, "readerwriterlock", "OMIT_EXIT"),
                                              (report, "py-cachify", "BALANCED_CONTEXT")]:
                    with self.assertRaises(ValueError):
                        repair.recorded(text, target, policy)
                data["proposal"]["code"] = contract.BASELINE
                p.write_bytes(contracts.encode(data))
                with self.assertRaises(ValueError):
                    repair.recorded(report, "py-cachify", "OMIT_EXIT")

    def test_unsupported_source_never_proposes_or_executes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(repair, "run_demo") as run:
            value = Demo(d).run({"report": contracts.SAMPLES[1]["report"], "repair": "recorded"})
            self.assertEqual(value["status"], "NOT_SUPPORTED")
            run.assert_not_called()

    def test_fresh_proposal_requires_explicit_text_send(self):
        with tempfile.TemporaryDirectory() as d, patch.object(repair, "run_demo") as run:
            value = Demo(d).run({"report": contracts.SAMPLES[0]["report"], "repair": "live"})
            self.assertEqual(value["status"], "STOPPED")
            run.assert_not_called()

    def test_unknown_native_outcome_retains_attempt_and_excludes_brier(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "run"
            directory.mkdir()
            result = {"target": {"name": "py-cachify"}, "caller": {"policy": "OMIT_EXIT", "input_sha256": "owned"}, "source_sha256": "owned"}
            gold = {"expected": {c["id"]: {s["id"]: {"lock": True} for s in contracts.stages("OMIT_EXIT")} for c in contract.cases("py-cachify")}}
            with patch("reqlox_demo.targets.acquire", return_value=(Path(d), {"files": []})), \
                 patch("reqlox_demo.engine.api.inventory", return_value={}), patch("reqlox_demo.engine.context.validate", return_value={}), \
                 patch("reqlox_demo.isolation.run", side_effect=[(gold, {}), ValueError("missing native receipt")]):
                with self.assertRaises(ValueError):
                    repair.execute(Demo(d), result, directory, self.proposal())
            self.assertEqual(result["native_attempts"], 1)
            self.assertIsNone(result["native_executions"])
            self.assertEqual(result["repair_outcome"], "UNKNOWN")
            self.assertIsNone(result["probability_evaluation"]["label"])
            self.assertIsNone(result["probability_evaluation"]["brier"])

    def test_export_removes_candidate_code(self):
        value = public_view({"assessment": {"all_evidence_handles": [], "evidence": []}, "repair_candidate": self.proposal()})
        self.assertNotIn("code", value["repair_candidate"])
        self.assertNotIn("rationale", value["repair_candidate"])


if __name__ == "__main__":
    unittest.main()
