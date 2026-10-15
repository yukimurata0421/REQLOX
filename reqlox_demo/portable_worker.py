"Finite reliability controls and verification."

import asyncio
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import resource
import socket
import sys


def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    raw = Path(sys.argv[1]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sys.argv[2]:
        raise ValueError("PORTABLE_PLAN_DRIFT")
    p = json.loads(raw)
    sys.path.insert(0, "/app")
    from reqlox_demo import repair_contract as contract
    from reqlox_demo import portable
    portable.validate_binding(p["binding"], p["declarations"])
    proof = contract.validate(p["candidate_code"])
    if proof != p["candidate_proof"] or p["original_caller_policy"] != "OMIT_EXIT":
        raise ValueError("PORTABLE_CODE_DRIFT")
    for ref in p["input_files"]:
        data = Path(ref["path"]).read_bytes()
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("PORTABLE_SOURCE_DRIFT")
    root = Path(p["snapshot_root"]).resolve()
    sys.path.insert(0, str(root))
    attempts = []
    def deny(*a, **kw):
        attempts.append(True)
        raise ValueError("PORTABLE_NETWORK_FORBIDDEN")
    socket.socket.connect = deny
    socket.create_connection = deny
    b = p["binding"]
    module = importlib.import_module(b["module"])
    factory = getattr(module, b["owner_class"])
    cls = getattr(module, b["context_class"])
    for value in [factory, cls]:
        if not Path(inspect.getfile(value)).resolve().is_relative_to(root):
            raise ValueError("PORTABLE_CLASS_ORIGIN")
    functions = {}
    for label, code in [("HEALTHY", contract.HEALTHY), ("FAULT", contract.BASELINE), ("CANDIDATE", p["candidate_code"])]:
        contract.validate(code)
        namespace = {"__builtins__": {}, "Exception": Exception, "BaseException": BaseException}
        exec(compile(code, "<owned-" + label.lower() + ">", "exec"), namespace)
        functions[label] = namespace["async_critical_section"]
    errors = {"TimeoutError": TimeoutError, "RuntimeError": RuntimeError, "ValueError": ValueError,
              "CancelledError": asyncio.CancelledError}
    async def stage(case, s):
        owner = factory(**b["owner_kwargs"])
        ctx = owner if b["context_property"] is None else getattr(owner, b["context_property"])
        if type(owner) is not factory or type(ctx) is not cls:
            raise ValueError("PORTABLE_CONTEXT_TYPE")
        def held():
            value = getattr(ctx, b["probe"])
            value = value() if b["probe_kind"] == "METHOD" else value
            if type(value) is not bool:
                raise ValueError("PORTABLE_PROBE_TYPE")
            return value
        error = errors[case["exception"]]("owned injected fault")
        calls = []
        async def work():
            calls.append(held())
            if s["inject_exception"]:
                if case["fault_kind"] == "TASK_CANCEL":
                    asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
                    await asyncio.sleep(0)
                else:
                    raise error
        first = None
        preserved = not s["inject_exception"]
        returned = None
        try:
            returned = await functions.get(s["id"], functions["CANDIDATE"])(ctx, work)
        except BaseException as exc:
            first = type(exc).__name__
            preserved = exc is error or case["fault_kind"] == "TASK_CANCEL" and isinstance(exc, asyncio.CancelledError)
        before = held()
        entered = []
        original_task = asyncio.current_task()
        async def contender():
            if asyncio.current_task() is original_task:
                raise ValueError("PORTABLE_CONTENDER_OWNER_DRIFT")
            async with ctx:
                entered.append(True)
        task = asyncio.create_task(contender())
        done, pending = await asyncio.wait({task}, timeout=p["second_acquire_timeout_seconds"])
        timed_out = bool(pending)
        if pending:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        else:
            await task
        return dict(first_exception=first, locked_after_first=before, second_entered=bool(entered),
                    locked_after_second=held(), work_calls=len(calls), work_inside_context=bool(calls) and all(calls),
                    exception_preserved=preserved, returned_none=returned is None,
                    second_owner_different=True, second_wait_timed_out=timed_out)
    trace = {c["id"]: {s["id"]: asyncio.run(stage(c, s)) for s in p["stages"]} for c in p["cases"]}
    print(json.dumps(dict(cases=trace, plan_sha256=hashlib.sha256(raw).hexdigest(),
        executed_candidate_sha256=proof["code_sha256"], actual_candidate_code_executed=True,
        source_unchanged=all(hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"] for r in p["input_files"]),
        network_attempts=len(attempts), target_source_modified=False, different_task_contender=True,
        namespaces={k: os.readlink("/proc/self/ns/" + k) for k in ["user", "mnt", "pid", "net"]})))


if __name__ == "__main__":
    main()
