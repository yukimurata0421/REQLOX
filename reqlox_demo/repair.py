"Validate repair proposals and verify bounded execution outcomes."

import copy
import hashlib
import json
import os
from pathlib import Path

from . import contracts, isolation, repair_contract as contract, targets

RECORDS = Path(os.environ.get("REQLOX_RECORDED_REPAIRS", Path(__file__).parent / "data" / "repair-records.json"))
EVENT = "ALL_REPAIR_AND_REINJECTION_OBLIGATIONS"


def record_key(report, target, caller_policy):
    return contracts.sha({"source_sha256": hashlib.sha256(report.encode()).hexdigest(),
                          "target": target, "version": targets.PACKAGES[target]["version"],
                          "caller_policy": caller_policy, "contract": contract.VERSION})


def proposal_check(value):
    if (not isinstance(value, dict) or not isinstance(value.get("rationale"), str) or
            len(value["rationale"].encode()) > 4096 or type(value.get("p_repair")) not in (int, float) or
            not 0 <= value["p_repair"] <= 1):
        raise ValueError("The repair proposal schema could not be verified.")
    return contract.validate(value.get("code"))


def recorded(report, target, caller_policy):
    if not RECORDS.exists():
        raise ValueError("No local recorded repair proposal is available.")
    data = json.loads(RECORDS.read_bytes())
    if data.get("record_sha256") != contracts.sha({k: v for k, v in data.items() if k != "record_sha256"}):
        raise ValueError("The repair proposal integrity check failed.")
    key = record_key(report, target, caller_policy)
    rows = [r for r in data["records"] if r["binding_sha256"] == key]
    if len(rows) != 1:
        raise ValueError("No local repair proposal matches this input, target, and caller.")
    value = copy.deepcopy(data["proposal"])
    proof = proposal_check(value)
    if proof["code_sha256"] != data["candidate_sha256"]:
        raise ValueError("The repair proposal code hash does not match.")
    value.update(method="RECORDED_GENERATED_REPAIR", forecast=rows[0]["forecast"],
                 proposal_sha256=data["proposal_sha256"], generation_calls_this_run=0,
                 reserved_jpy="0", reserved_usd="0", forecast_was_recorded=True)
    return value


def probability(probability, label, *, recorded=False, groups=None):
    if (type(probability) not in (int, float) or not 0 <= probability <= 1 or
            not (label is None or type(label) is int and label in (0, 1))):
        raise ValueError("The forecast or label is outside the supported range.")
    return {"event": EVENT, "probability": probability, "label": label,
            "brier": None if label is None else (probability - label) ** 2,
            "constant_half_brier": None if label is None else .25,
            "calibrated": False, "forecast_was_recorded": recorded,
            "prospective_forecast_count": 0 if recorded else 1,
            "independent_sample_size": 0 if recorded else None,
            "dependency_groups": groups, "missing_is_failure": False,
            "natural_truth_probability": False}


def execute(engine, result, directory, proposal):
    from .engine import api, binding, context, sync
    target = result["target"]["name"]
    result["repair_candidate"] = {**proposal, "scope": "OWNED_CALLER", "upstream_modified": False}
    result["generation_calls_this_run"] = proposal.get("generation_calls_this_run", 0)
    proof = proposal_check(proposal)
    result["repair_candidate"].update(proof)
    rows = contract.cases(target)
    policy = result["caller"]["policy"]
    stage_rows = contracts.stages(policy)
    result["repair_event"] = EVENT
    result["repair_attempts"] = 1
    result["repair_outcome"] = "NOT_EXECUTED"
    result["candidate_code_executed"] = False
    native_root, snapshot = targets.acquire(engine.cache, target)
    dep_root, dep_snapshot = targets.acquire(engine.cache, "typing-extensions")
    index = sync.inventory(native_root) if target == "readerwriterlock" else api.inventory(native_root)
    b = binding(target)
    static = sync.validate(index, b) if target == "readerwriterlock" else context.validate(index, b)
    plan = {"target": target, "cases": rows, "stages": stage_rows, "binding": b,
            "inventory": index, "static_proof": static, "candidate_code": proposal["code"],
            "candidate_proof": proof, "snapshot_root": "/target/native", "dependency_roots": ["/target/dependency"],
            "input_files": [{**r, "path": "/target/native/" + r["path"]} for r in snapshot["files"]]
                         + [{**r, "path": "/target/dependency/" + r["path"]} for r in dep_snapshot["files"]],
            "role": "KNOWN_DEMO_CONTROL", "unused_holdout": False,
            "source_sha256": result["source_sha256"], "caller_sha256": result["caller"]["input_sha256"]}
    
    plan["original_caller_policy"] = policy
    (directory / "sealed-plan.json").write_bytes(contracts.encode(plan))
    (directory / "sealed-plan.json").chmod(0o600)
    gold, gold_receipt = isolation.run(directory / "gold", "gold", {"cases": rows, "stages": stage_rows})
    expected = {c["id"]: {s["id"]: contract.expected(c, s, gold["expected"][c["id"]][s["id"]])
                          for s in stage_rows} for c in rows}
    (directory / "gold.json").write_bytes(contracts.encode({"lock_gold": gold, "obligations": expected}))
    (directory / "gold.json").chmod(0o600)
    result.update(native_attempts=1, native_executions=None, native_execution_status="ATTEMPTED_OUTCOME_UNKNOWN",
                  repair_outcome="UNKNOWN")
    try:
        native, receipt = isolation.run(directory / "native", "candidate", plan,
                                       [(native_root, "/target/native"), (dep_root, "/target/dependency")])
    except Exception:
        result["probability_evaluation"] = probability(proposal["forecast"]["probabilities"]["PASS"], None,
            recorded=proposal.get("forecast_was_recorded", False))
        raise
    if (native.get("executed_candidate_sha256") != proof["code_sha256"] or
            native.get("actual_candidate_code_executed") is not True or not native["source_unchanged"]):
        raise ValueError("The executed repair code or source identity could not be verified.")
    result.update(native_executions=1, native_execution_status="OBSERVED", candidate_code_executed=True)
    observations = []
    for c in rows:
        stages = []
        for s in stage_rows:
            observed = native["cases"].get(c["id"], {}).get(s["id"])
            exp = expected[c["id"]][s["id"]]
            stages.append({"stage": s["id"], "observed": observed, "expected": exp,
                           "matches_gold": observed == exp, "missing": observed is None})
        observations.append({**c, "stages": stages})
    result["cases"] = observations
    result["stage_observations"] = sum(not s["missing"] for c in observations for s in c["stages"])
    result["stage_matches"] = sum(s["matches_gold"] for c in observations for s in c["stages"])
    repair_rows = [s for c in observations for s in c["stages"] if s["stage"] in ["REPAIR", "REINJECTION"]]
    missing = any(s["missing"] for s in repair_rows)
    repair_pass = not missing and all(s["matches_gold"] for s in repair_rows)
    finite_pass = all(s["matches_gold"] for c in observations for s in c["stages"])
    reproduced = finite_pass and policy == "OMIT_EXIT"
    result.update(status="REPRODUCED_AND_REPAIRED" if reproduced else "NOT_REPRODUCED" if finite_pass else "CONTRACT_MISMATCH",
        message="The proposed code was executed. Reinjection confirmed work, release, and exception propagation." if reproduced else
                "The repaired input did not reproduce the fault and the candidate met the finite contract." if finite_pass else
                "The candidate observations differed from the frozen obligations.",
        repair_outcome="UNKNOWN" if missing else "COMPLETE" if repair_pass else "FAILED",
        repair_case_pairs=len(rows), repair_case_pairs_passed=sum(all(s["matches_gold"] for s in c["stages"][2:]) for c in observations),
        repair_success=repair_pass, finite_contract_pass=finite_pass, gold_oracles_agree=gold["both_oracles_agree"],
        gold_target_executions=0, gold_frozen_before_native_execution=True,
        additional_work_obligations="PREDECLARED_FINITE_SPECIFICATION", source_unchanged=True, network_attempts=0,
        namespace_isolated=True, independent_target_trial=False, caller_repair_only=True,
        receipt_sha256=contracts.sha(receipt), gold_receipt_sha256=contracts.sha(gold_receipt),
        plan_sha256=contracts.sha(plan), observation_sha256=contracts.sha(native))
    result["probability_evaluation"] = probability(proposal["forecast"]["probabilities"]["PASS"],
        None if missing else int(repair_pass), recorded=proposal.get("forecast_was_recorded", False),
        groups={"source_sha256": result["source_sha256"], "candidate_sha256": proof["code_sha256"],
                "target": target, "generation_group": proposal.get("proposal_sha256")})
    result["probability_evaluation"]["forecast_rubric"] = proposal.get("forecast_rubric", "binary-repair-v2")
    return result


def run_demo(engine, result, directory, report, caller_policy, mode):
    if mode == "recorded":
        proposal = recorded(report, result["target"]["name"], caller_policy)
    else:
        if engine.model is None:
            raise ValueError("A new repair proposal requires a configured shared budget scope.")
        from .repair_model import live
        proposal = live(engine.model, report, result["target"]["name"], caller_policy)
    execute(engine, result, directory, proposal)
