"""Check both known workers using HEALTHY only: no injected faults or cancellation."""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reqlox
reqlox._runtime()
from reqlox_demo import contracts, isolation, targets, repair, repair_contract
from reqlox_demo.engine import binding, api, context, sync


def main():
    with tempfile.TemporaryDirectory(prefix="reqlox-healthy-") as directory:
        root = Path(directory)
        cache = root / "cache"
        stages = [s for s in contracts.stages("OMIT_EXIT") if s["id"] == "HEALTHY"]
        assert len(stages) == 1 and stages[0]["inject_exception"] is False
        rows = []
        for target in ("py-cachify", "readerwriterlock"):
            native, snapshot = targets.acquire(cache, target)
            dependency, dependency_snapshot = targets.acquire(cache, "typing-extensions")
            index = sync.inventory(native) if target == "readerwriterlock" else api.inventory(native)
            bound = binding(target)
            proof = sync.validate(index, bound) if target == "readerwriterlock" else context.validate(index, bound)
            cases = [c for c in contracts.cases(target) if c["mode"] == "SYNC"][:1]
            plan = dict(target=target, cases=cases, stages=stages, binding=bound, static_proof=proof,
                        inventory=index, snapshot_root="/target/native", dependency_roots=["/target/dependency"],
                        input_files=[{**r, "path": "/target/native/"+r["path"]} for r in snapshot["files"]]
                                   +[{**r, "path": "/target/dependency/"+r["path"]} for r in dependency_snapshot["files"]])
            gold, gold_receipt = isolation.run(root / (target+"-gold"), "gold", {"cases": cases, "stages": stages})
            observed, receipt = isolation.run(root / (target+"-baseline"), target, plan,
                                             [(native,"/target/native"),(dependency,"/target/dependency")])
            for case in cases:
                assert observed["cases"][case["id"]]["HEALTHY"] == gold["expected"][case["id"]]["HEALTHY"]
            plan.update(original_caller_policy="OMIT_EXIT", candidate_code=repair_contract.BASELINE,
                        candidate_proof=repair_contract.validate(repair_contract.BASELINE))
            generated, candidate_receipt = isolation.run(root/(target+"-candidate"), "candidate", plan,
                                                       [(native,"/target/native"),(dependency,"/target/dependency")])
            for case in cases:
                expected = repair_contract.expected(case, stages[0], gold["expected"][case["id"]]["HEALTHY"])
                assert generated["cases"][case["id"]]["HEALTHY"] == expected
            assert all(r["namespace_isolated"] for r in (gold_receipt,receipt,candidate_receipt))
            rows.append(dict(target=target, baseline_matches=True, candidate_matches=True, namespaces_isolated=True))
        print(json.dumps(dict(status="HEALTHY_SMOKE_PASS", targets=rows, injected_faults=0,
                              provider_calls=0, repair_qualification=False)))


if __name__ == "__main__":main()
