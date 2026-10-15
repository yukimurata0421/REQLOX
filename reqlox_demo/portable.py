"Finite reliability controls and verification."

import ast
import hashlib
import json
from pathlib import Path
import re


def declarations(root, module):
    root = Path(root)
    path = root / (module.replace(".", "/") + ".py")
    if not path.is_file():
        path = root / module.replace(".", "/") / "__init__.py"
    tree = ast.parse(path.read_text())
    rows = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = {n.name: {"async": isinstance(n, ast.AsyncFunctionDef),
                    "property": any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list)}
                    for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for n in node.body:
                if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                        and isinstance(n.value, ast.Name) and n.value.id in methods):
                    methods[n.targets[0].id] = dict(methods[n.value.id])
            rows[node.name] = {"bases": [b.id for b in node.bases if isinstance(b, ast.Name)], "methods": methods}
    return {"module": module, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "classes": rows}


def validate_binding(binding, index):
    if set(binding) != {"module", "owner_class", "owner_kwargs", "context_class", "context_property", "probe", "probe_kind"}:
        raise ValueError("PORTABLE_BINDING_SCHEMA")
    if (binding["module"] != index["module"] or binding["owner_kwargs"] != {} or
            binding["probe_kind"] not in {"METHOD", "PROPERTY"} or any(
            not isinstance(binding[k], str) or not re.fullmatch(r"[A-Za-z_]\w*", binding[k])
            for k in ["owner_class", "context_class", "probe"])):
        raise ValueError("PORTABLE_BINDING_SCOPE")
    classes = index["classes"]
    if binding["owner_class"] not in classes or binding["context_class"] not in classes:
        raise ValueError("PORTABLE_DECLARATION_MISSING")
    def method(cls, name, seen=()):
        if cls not in classes or cls in seen:
            raise ValueError("PORTABLE_INHERITANCE_SCOPE")
        row = classes[cls]
        if name in row["methods"]:
            return row["methods"][name]
        for base in row["bases"]:
            if base in classes:
                try:
                    return method(base, name, (*seen, cls))
                except ValueError:
                    continue
        raise ValueError("PORTABLE_METHOD_MISSING")
    for name in ["__aenter__", "__aexit__"]:
        if not method(binding["context_class"], name)["async"]:
            raise ValueError("PORTABLE_ASYNC_PROTOCOL_REQUIRED")
    probe = method(binding["context_class"], binding["probe"])
    if probe["async"] or probe["property"] != (binding["probe_kind"] == "PROPERTY"):
        raise ValueError("PORTABLE_PROBE_SHAPE")
    prop = binding["context_property"]
    if prop is None:
        if binding["owner_class"] != binding["context_class"]:
            raise ValueError("PORTABLE_SELF_CONTEXT_TYPE")
    elif not isinstance(prop, str) or not re.fullmatch(r"[A-Za-z_]\w*", prop) or not method(binding["owner_class"], prop)["property"]:
        raise ValueError("PORTABLE_CONTEXT_PROPERTY")
    return {"static_declarations_only": True, "runtime_types_required": True, "source_sha256": index["source_sha256"]}


def cases():
    return [{"id": "async-" + x.lower(), "mode": "ASYNC", "exception": x, "fault_kind": "DIRECT"}
            for x in ["TimeoutError", "RuntimeError", "ValueError", "CancelledError"]] + [
            {"id": "async-task-cancel", "mode": "ASYNC", "exception": "CancelledError", "fault_kind": "TASK_CANCEL"}]


def execute(directory, root, snapshot, binding, proposal):
    from . import contracts, isolation, repair, repair_contract as contract
    directory, root = Path(directory), Path(root)
    directory.mkdir(parents=True, mode=0o700)
    proof = repair.proposal_check(proposal)
    index = declarations(root, binding["module"])
    validate_binding(binding, index)
    row_cases = cases()
    stages = contracts.stages("OMIT_EXIT")
    plan = {"cases": row_cases, "stages": stages, "candidate_code": proposal["code"], "candidate_proof": proof,
            "binding": binding, "declarations": index, "snapshot_root": "/target/native",
            "original_caller_policy": "OMIT_EXIT", "second_acquire_timeout_seconds": .1,
            "input_files": [{**r, "path": "/target/native/" + r["path"]} for r in snapshot["files"]]}
    (directory / "sealed-plan.json").write_bytes(contracts.encode(plan))
    (directory / "sealed-plan.json").chmod(0o600)
    gold, gold_receipt = isolation.run(directory / "gold", "gold", {"cases": row_cases, "stages": stages})
    expected = {c["id"]: {s["id"]: {**contract.expected(c, s, gold["expected"][c["id"]][s["id"]]),
        "second_owner_different": True, "second_wait_timed_out": s["policy"] == "OMIT_EXIT"} for s in stages} for c in row_cases}
    (directory / "gold.json").write_bytes(contracts.encode(expected))
    (directory / "gold.json").chmod(0o600)
    try:
        observed, receipt = isolation.run(directory / "native", "portable", plan, [(root, "/target/native")])
    except Exception:
        value = {"status": "STOPPED", "native_attempts": 1, "native_executions": None,
                 "label": None, "candidate_sha256": proof["code_sha256"], "automatic_retry": False}
        (directory / "result.json").write_bytes(contracts.encode(value))
        (directory / "result.json").chmod(0o600)
        raise
    if observed.get("executed_candidate_sha256") != proof["code_sha256"] or not observed["source_unchanged"]:
        raise ValueError("PORTABLE_EXECUTION_DRIFT")
    matches = [observed["cases"].get(c["id"], {}).get(s["id"]) == expected[c["id"]][s["id"]]
               for c in row_cases for s in stages]
    repair_rows = [(c, s) for c in row_cases for s in stages[2:]]
    missing = any(observed["cases"].get(c["id"], {}).get(s["id"]) is None for c, s in repair_rows)
    repair_pass = not missing and all(observed["cases"][c["id"]][s["id"]] == expected[c["id"]][s["id"]] for c, s in repair_rows)
    value = {"status": "REPRODUCED_AND_REPAIRED" if all(matches) else "CONTRACT_MISMATCH",
             "label": None if missing else int(repair_pass), "native_attempts": 1, "native_executions": 1,
             "candidate_sha256": proof["code_sha256"], "candidate_code_executed": True,
             "condition_pairs": len(row_cases), "stage_observations": 20, "stage_matches": sum(matches),
             "cases": observed["cases"], "source_unchanged": True, "network_attempts": observed["network_attempts"],
             "different_task_contender": observed["different_task_contender"], "namespace_isolated": receipt["namespace_isolated"],
             "observation_sha256": contracts.sha(observed), "receipt_sha256": contracts.sha(receipt),
             "gold_receipt_sha256": contracts.sha(gold_receipt), "automatic_retry": False}
    (directory / "result.json").write_bytes(contracts.encode(value))
    (directory / "result.json").chmod(0o600)
    return value
