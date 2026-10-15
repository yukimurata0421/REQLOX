"Finite reliability controls and verification."

import copy
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

from . import contracts, isolation, targets

ROOT = Path(__file__).resolve().parents[1]
pass  # Package imports resolve from the repository root.
from reqlox_core import qualification_adapters_v2 as api
from reqlox_core import qualification_context_protocol as context
from reqlox_core import qualification_context_sync as sync


def binding(target):
    if target == "py-cachify":
        return {"factory_module": "py_cachify._backend._lib", "factory_name": "init_cachify",
                "owner_module": "py_cachify._backend._lib", "owner_class": "Cachify", "context_method": "lock",
                "context_module": "py_cachify._backend._lock", "context_class": "lock",
                "factory_kwargs": {"is_global": False, "default_lock_expiration": None},
                "context_kwargs": {"nowait": True, "exp": None}, "key_parameter": "key",
                "sync_probe": "is_locked", "async_probe": "is_alocked"}
    if target == "readerwriterlock":
        return {"factory_module": "readerwriterlock.rwlock", "factory_class": "RWLockFair", "factory_kwargs": {},
                "context_method": "gen_wlock", "context_module": "readerwriterlock.rwlock", "context_class": "RWLockFair._aWriter",
                "context_kwargs": {}, "probe_method": "locked", "next_acquire_method": "acquire",
                "next_acquire_kwargs": {"blocking": False}, "next_release_method": "release"}
    raise ValueError("Select a supported target.")


class Demo:
    def __init__(self, cache, model=None):
        candidate = Path(cache).absolute()
        if any(p.is_symlink() for p in [candidate, *candidate.parents]):
            raise ValueError("Cache directories cannot contain links.")
        self.cache = candidate.resolve()
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.cache.is_symlink() or self.cache.stat().st_uid != __import__("os").getuid():
            raise ValueError("Select a privately owned cache directory.")
        self.model = model

    def run(self, request):
        started = time.monotonic()
        if not isinstance(request, dict) or set(request) - {"report", "caller", "target", "method", "send_to_model", "repair"}:
            raise ValueError("Check the input fields.")
        report = request.get("report", "")
        caller = request.get("caller", contracts.LEAK_CALLER)
        target = request.get("target", "py-cachify")
        method = request.get("method", "baseline")
        repair_mode = request.get("repair", "rule")
        if repair_mode not in ["rule", "recorded", "live"]:
            raise ValueError("Select a repair method.")
        if method not in ["baseline", "recorded", "live"]:
            raise ValueError("Select an assessment method.")
        structure = contracts.caller_policy(caller)
        case_rows = contracts.cases(target)
        stage_rows = contracts.stages(structure["policy"])
        assessment = contracts.baseline(report)
        run_id = uuid.uuid4().hex
        directory = self.cache / "runs" / run_id
        directory.mkdir(parents=True, mode=0o700)
        result = {"schema_version": "reqlox.hackathon-demo-result.v0.1", "run_id": run_id,
                  "created_at_jst": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds"),
                  "execution_mode": "NEW_BOUNDED_EXECUTION", "target": {"name": target, "version": targets.PACKAGES[target]["version"]},
                  "source_sha256": hashlib.sha256(report.encode()).hexdigest(), "caller": structure,
                  "repair_candidate": {"method": "FINITE_CONTEXT_REPAIR_RULE", "code": contracts.REPAIRED_CALLER,
                                       "scope": "OWNED_CALLER", "upstream_modified": False},
                  "source_kind": "USER_TEXT_NOT_NATURAL_GOLD", "assessment": assessment,
                  "native_attempts": 0, "native_executions": 0, "native_execution_status": "NOT_ATTEMPTED",
                  "cases": [], "stage_observations": 0, "stage_matches": 0,
                  "probability_evaluation": None, "natural_accuracy_certified": False,
                  "independent_generalization_certified": False, "input_code_executed": False,
                  "model_grants_execution_authority": False}
        try:
            if method == "recorded":
                from .model import recorded
                assessment = recorded(report, target, assessment, structure["policy"])
            elif method == "live":
                if self.model is None or request.get("send_to_model") is not True:
                    raise ValueError("Configure a model scope and consent to text submission before a new assessment.")
                assessment = self.model.assess(report, target, assessment, structure["policy"])
            result["assessment"] = assessment
            if assessment["choice"] != "SUPPORTED":
                result.update(status="NOT_SUPPORTED" if assessment["choice"] == "NOT_SUPPORTED" else "INSUFFICIENT_INFORMATION",
                              message="This report does not support the selected failure hypothesis." if assessment["choice"] == "NOT_SUPPORTED" else "The report provides insufficient evidence for this hypothesis. No experiment was executed.")
                return self.finish(result, directory, started)
            if not assessment["evidence"]:
                raise ValueError("No supporting quotation was available. The experiment was stopped.")
            if repair_mode != "rule":
                if repair_mode == "live" and request.get("send_to_model") is not True:
                    raise ValueError("A new repair proposal requires consent to text submission.")
                result["repair_requested"] = repair_mode
                result["generation_calls_this_run"] = None if repair_mode == "live" else 0
                from .repair import run_demo
                run_demo(self, result, directory, report, structure["policy"], repair_mode)
                return self.finish(result, directory, started)
            native_root, native_snapshot = targets.acquire(self.cache, target)
            dep_root, dep_snapshot = targets.acquire(self.cache, "typing-extensions")
            index = sync.inventory(native_root) if target == "readerwriterlock" else api.inventory(native_root)
            b = binding(target)
            proof = sync.validate(index, b) if target == "readerwriterlock" else context.validate(index, b)
            plan = {"cases": case_rows, "stages": stage_rows, "binding": b, "static_proof": proof,
                    "inventory": index, "snapshot_root": "/target/native", "dependency_roots": ["/target/dependency"],
                    "input_files": [{**r, "path": "/target/native/" + r["path"]} for r in native_snapshot["files"]]
                                 + [{**r, "path": "/target/dependency/" + r["path"]} for r in dep_snapshot["files"]],
                    "source_sha256": result["source_sha256"], "caller_sha256": structure["input_sha256"],
                    "role": "KNOWN_DEMO_CONTROL", "unused_holdout": False}
            (directory / "sealed-plan.json").write_bytes(contracts.encode(plan))
            gold, gold_receipt = isolation.run(directory / "gold", "gold", {"cases": case_rows, "stages": stage_rows})
            
            (directory / "gold.json").write_bytes(contracts.encode(gold))
            result.update(native_attempts=1, native_executions=None, native_execution_status="ATTEMPTED_OUTCOME_UNKNOWN")
            native, receipt = isolation.run(directory / "native", target, plan,
                                           [(native_root, "/target/native"), (dep_root, "/target/dependency")])
            result["native_executions"] = 1
            result["native_execution_status"] = "OBSERVED"
            if not native["source_unchanged"] or native["network_attempts"] != 0:
                raise ValueError("Target identity or network isolation could not be verified.")
            rows = []
            for case in case_rows:
                stages = []
                for stage in stage_rows:
                    observed = native["cases"].get(case["id"], {}).get(stage["id"])
                    expected = gold["expected"][case["id"]][stage["id"]]
                    stages.append({"stage": stage["id"], "observed": observed, "expected": expected,
                                   "matches_gold": observed == expected, "missing": observed is None})
                rows.append({"id": case["id"], "mode": case["mode"], "exception": case["exception"], "stages": stages})
            result["cases"] = rows
            result["stage_observations"] = sum(not s["missing"] for r in rows for s in r["stages"])
            result["stage_matches"] = sum(s["matches_gold"] for r in rows for s in r["stages"])
            finite_pass = all(s["matches_gold"] for r in rows for s in r["stages"])
            reproduced = finite_pass and all(r["stages"][1]["observed"]["locked_after_first"] and not r["stages"][1]["observed"]["second_entered"] for r in rows)
            result.update(status="REPRODUCED_AND_REPAIRED" if reproduced else "NOT_REPRODUCED" if finite_pass else "CONTRACT_MISMATCH",
                          message="The exception-path lock leak was reproduced. After repair, the same exception allowed the next acquisition." if reproduced else "The selected caller and exception conditions did not reproduce a lock leak." if finite_pass else "Observations differed from the frozen finite contract.",
                          gold_oracles_agree=gold["both_oracles_agree"], gold_target_executions=0,
                          gold_frozen_before_native_execution=True, source_unchanged=True, network_attempts=0,
                          namespace_isolated=True, finite_contract_pass=finite_pass,
                          independent_target_trial=False, caller_repair_only=True,
                          receipt_sha256=contracts.sha(receipt), gold_receipt_sha256=contracts.sha(gold_receipt),
                          plan_sha256=contracts.sha(plan), observation_sha256=contracts.sha(native))
            forecast = assessment.get("forecast")
            if forecast is not None:
                probability = forecast["probabilities"]["ALL_STAGES_MATCH"]
                label = int(finite_pass)
                result["probability_evaluation"] = {"event": "ALL_FINITE_STAGES_MATCH_GOLD", "probability": probability,
                    "label": label, "brier": (probability - label) ** 2, "calibrated": False,
                    "forecast_method": assessment["method"], "forecast_was_recorded": method == "recorded",
                    "prospective_forecast_count": 0 if method == "recorded" else 1,
                    "independent_sample_size": 0 if method == "recorded" else None,
                    "dependency_groups": {"source_sha256": result["source_sha256"], "target": target},
                    "natural_truth_probability": False}
            return self.finish(result, directory, started)
        except Exception as exc:
            result.update(status="STOPPED", message=str(exc) if isinstance(exc, ValueError) else "The run did not complete and was stopped.", error_class=type(exc).__name__)
            return self.finish(result, directory, started)

    def finish(self, result, directory, started):
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        from decimal import Decimal
        result["reserved_judgment_usd"] = str(Decimal(result["assessment"].get("reserved_usd", "0")) +
            Decimal(result["repair_candidate"].get("reserved_usd", "0")))
        result["reserved_generation_jpy"] = result["repair_candidate"].get("reserved_jpy", "0")
        if result.get("repair_requested") == "live" and result.get("generation_calls_this_run") is None:
            result["reserved_generation_jpy"] = None
        result["report_sha256"] = contracts.sha(result)
        path = directory / "result.json"
        path.write_bytes(contracts.encode(result))
        path.chmod(0o600)
        return result


def public_view(result):
    "Public view."
    value = copy.deepcopy(result)
    value["assessment"].pop("all_evidence_handles", None)
    value["assessment"].pop("evidence", None)
    value["repair_candidate"].pop("code", None)
    value["repair_candidate"].pop("rationale", None)
    value.pop("report_sha256", None)
    value["raw_user_text_or_code_included"] = False
    value["export_sha256"] = contracts.sha(value)
    return value
