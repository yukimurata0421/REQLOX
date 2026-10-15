"Compute finite reference observations separately from target and predictor."

import hashlib
import json
import os
from pathlib import Path
import resource
import sys


def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    raw = Path(sys.argv[1]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sys.argv[2]:
        raise ValueError("GOLD_PLAN_DRIFT")
    plan = json.loads(raw)
    sys.path.insert(0, "/app/reqlox_core")
    import qualification_context_gold as state
    import qualification_context_oracle_log as log
    first = {case["id"]: {stage["id"]: state.expected(case, stage) for stage in plan["stages"]} for case in plan["cases"]}
    second = {case["id"]: {stage["id"]: log.expected(case, stage) for stage in plan["stages"]} for case in plan["cases"]}
    if first != second:
        raise ValueError("GOLD_DISAGREEMENT")
    print(json.dumps({"expected": first, "both_oracles_agree": True, "target_executions": 0,
                      "plan_sha256": hashlib.sha256(raw).hexdigest(), "network_attempts": 0,
                      "namespaces": {k: os.readlink("/proc/self/ns/" + k) for k in ["user", "mnt", "pid", "net"]}}))


if __name__ == "__main__":
    main()
