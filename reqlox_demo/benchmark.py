"Run owned demo controls while preserving missing observations."

import uuid

from . import contracts


def run(engine, method="baseline"):
    if method not in ["baseline", "recorded"]:
        raise ValueError("The benchmark supports baseline and locally recorded assessments without paid calls.")
    tasks = []
    for target in ["py-cachify", "readerwriterlock"]:
        for sample in contracts.SAMPLES:
            status = {"reported": "REPRODUCED_AND_REPAIRED", "negative": "NOT_SUPPORTED", "unknown": "INSUFFICIENT_INFORMATION"}[sample["id"]]
            tasks.append({"target": target, "source_group": sample["id"], "report": sample["report"], "caller": sample["caller"], "expected": status})
        tasks.append({"target": target, "source_group": "reported", "report": contracts.SAMPLES[0]["report"],
                      "caller": contracts.REPAIRED_CALLER, "expected": "NOT_REPRODUCED"})
    frozen = contracts.sha(tasks)
    directory = engine.cache / "benchmarks" / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    plan_path = directory / "plan.json"
    plan_path.write_bytes(contracts.encode({"tasks": tasks, "tasks_sha256": frozen, "method": method, "provider_calls": 0, "known_controls_only": True}))
    plan_path.chmod(0o600)
    rows = []
    for task in tasks:
        result = engine.run({"report": task["report"], "caller": task["caller"], "target": task["target"], "method": method})
        rows.append({"target": task["target"], "source_group": task["source_group"], "expected": task["expected"],
                     "observed": result["status"], "correct": result["status"] == task["expected"],
                     "native_executions": result["native_executions"], "stage_observations": result["stage_observations"],
                     "stage_matches": result["stage_matches"], "result_sha256": result["report_sha256"], "elapsed_seconds": result["elapsed_seconds"],
                     "forecast": result["probability_evaluation"]})
    forecasts = [r["forecast"] for r in rows if r["forecast"] is not None]
    value = {"schema_version": "reqlox.demo-finite-benchmark.v0.1", "status": "PASS" if all(r["correct"] for r in rows) else "FAILED",
             "tasks_sha256_before_execution": frozen, "denominator": len(tasks), "correct": sum(r["correct"] for r in rows),
             "missing_or_stopped": sum(r["observed"] == "STOPPED" for r in rows), "source_groups": 3, "target_groups": 2,
             "native_executions": sum(r["native_executions"] or 0 for r in rows), "stage_observations": sum(r["stage_observations"] for r in rows),
             "stage_matches": sum(r["stage_matches"] for r in rows), "rows": rows,
             "method": method, "provider_calls": 0, "probabilities_calibrated": False, "natural_accuracy_certified": False,
             "forecast_count": len(forecasts), "forecast_mean_brier": sum(r["brier"] for r in forecasts) / len(forecasts) if forecasts else None,
             "prospective_forecast_count": 0, "independent_new_forecast_trials": 0,
             "forecast_expected_executed_count": 4 if method == "recorded" else 0,
             "forecast_missing_executed_count": 4 - len(forecasts) if method == "recorded" else 0,
             "source_probabilities_are_not_execution_probabilities": True,
             "independent_generalization_certified": False, "known_controls_only": True, "stage_rows_independent_trials": False}
    value["record_sha256"] = contracts.sha(value)
    path = directory / "result.json"
    path.write_bytes(contracts.encode(value))
    path.chmod(0o600)
    return value
