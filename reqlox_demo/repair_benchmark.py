"Check locally supplied repair controls without claiming independent evaluation."

import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from . import contracts, repair, repair_contract as contract, targets

CONTROLS = Path(os.environ.get("REQLOX_RECORDED_CONTROLS", Path(__file__).parent / "data" / "repair-controls.json"))


def run(engine):
    data = json.loads(CONTROLS.read_bytes())
    if data["record_sha256"] != contracts.sha({k: v for k, v in data.items() if k != "record_sha256"}):
        raise ValueError("The local repair-control integrity check failed.")
    if len(data["controls"]) != 18:
        raise ValueError("The finite repair-control count does not match.")
    report = contracts.SAMPLES[0]["report"]
    tasks = []
    for target in ["py-cachify", "readerwriterlock"]:
        tasks.append({"id": "generated_" + target, "target": target, "expected_repair_label": 1,
                      "role": "SAVED_GENERATED_REPAIR", "proposal": repair.recorded(report, target, "OMIT_EXIT")})
    for row in data["controls"]:
        if contract.validate(row["code"])["code_sha256"] != row["candidate_sha256"]:
            raise ValueError("The repair-control code hash does not match.")
        if row["expected_repair_label"] not in (0, 1):
            raise ValueError("The repair control has no known finite expectation.")
        tasks.append({"id": row["id"], "target": row["target"], "role": row["expected_role"],
                      "expected_repair_label": row["expected_repair_label"], "proposal": {
                          "code": row["code"], "rationale": "Owned historical caller control",
                          "p_repair": .5, "forecast": row["forecast"], "forecast_rubric": row["forecast_rubric"],
                          "forecast_was_recorded": True, "proposal_sha256": row["candidate_sha256"],
                          "method": "SAVED_OWNED_CONTROL", "generation_calls_this_run": 0}})
    directory = engine.cache / "repair-benchmarks" / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    frozen = contracts.sha(tasks)
    (directory / "plan.json").write_bytes(contracts.encode({"tasks": tasks, "tasks_sha256": frozen,
        "provider_calls": 0, "maximum_native_campaigns": 20, "historical_controls": True}))
    (directory / "plan.json").chmod(0o600)
    results = []
    for task in tasks:
        run_dir = directory / task["id"]
        run_dir.mkdir(mode=0o700)
        started = time.monotonic()
        result = {"run_id": task["id"], "target": {"name": task["target"], "version": targets.PACKAGES[task["target"]]["version"]},
                  "source_sha256": hashlib.sha256(report.encode()).hexdigest(),
                  "caller": contracts.caller_policy(contracts.LEAK_CALLER), "assessment": contracts.baseline(report),
                  "repair_candidate": task["proposal"], "native_attempts": 0, "native_executions": 0,
                  "native_execution_status": "NOT_ATTEMPTED", "cases": [], "stage_observations": 0,
                  "stage_matches": 0, "probability_evaluation": None, "input_code_executed": False}
        try:
            repair.execute(engine, result, run_dir, task["proposal"])
        except Exception as exc:
            result.update(status="STOPPED", error_class=type(exc).__name__)
        engine.finish(result, run_dir, started)
        label = result["probability_evaluation"]["label"] if result["probability_evaluation"] else None
        results.append({"id": task["id"], "target": task["target"], "role": task["role"],
                        "expected_repair_label": task["expected_repair_label"], "observed_repair_label": label,
                        "correct": label is not None and label == task["expected_repair_label"],
                        "status": result["status"], "native_executions": result["native_executions"],
                        "result_sha256": result["report_sha256"], "forecast": result["probability_evaluation"]})
    value = {"schema_version": "reqlox.repair-replay-benchmark.v0.1", "denominator": len(tasks),
             "correct": sum(r["correct"] for r in results), "missing_or_stopped": sum(r["observed_repair_label"] is None for r in results),
             "status": "PASS" if all(r["correct"] for r in results) else "FAILED", "rows": results,
             "task_sha256_before_execution": frozen, "provider_calls": 0, "prospective_forecast_count": 0,
             "independent_new_trials": 0, "known_controls_only": True, "generated_proposal_groups": 1,
             "probabilities_calibrated": False, "natural_accuracy_certified": False,
             "independent_generalization_certified": False, "stage_rows_are_independent_trials": False}
    value["record_sha256"] = contracts.sha(value)
    (directory / "result.json").write_bytes(contracts.encode(value))
    (directory / "result.json").chmod(0o600)
    return value
