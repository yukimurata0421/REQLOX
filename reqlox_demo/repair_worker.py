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
        raise ValueError("REPAIR_PLAN_DRIFT")
    p = json.loads(raw)
    if p.get("original_caller_policy") not in {"OMIT_EXIT", "BALANCED_CONTEXT"}:
        raise ValueError("REPAIR_CALLER_POLICY")
    sys.path[:0] = ["/app/reqlox_demo", "/app/reqlox_core"]
    import repair_contract as contract
    proof = contract.validate(p["candidate_code"])
    if proof != p["candidate_proof"]:
        raise ValueError("REPAIR_CANDIDATE_DRIFT")
    b = p["binding"]
    if p["target"] == "py-cachify":
        from qualification_context_protocol import validate
    else:
        from qualification_context_sync import validate
    validate(p["inventory"], b)
    for ref in p["input_files"]:
        data = Path(ref["path"]).read_bytes()
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("REPAIR_SOURCE_DRIFT")
    roots = [Path(p["snapshot_root"]).resolve(), *[Path(x).resolve() for x in p["dependency_roots"]]]
    sys.path[:0] = [str(r) for r in roots]
    attempts = []
    def deny(*a, **kw):
        attempts.append(True)
        raise ValueError("REPAIR_NETWORK_FORBIDDEN")
    socket.socket.connect = deny
    socket.create_connection = deny
    def resolve(module, name):
        value = importlib.import_module(module)
        for part in name.split("."):
            value = getattr(value, part)
        if not Path(inspect.getfile(value)).resolve().is_relative_to(roots[0]):
            raise ValueError("REPAIR_CLASS_ORIGIN")
        return value
    if p["target"] == "py-cachify":
        factory = resolve(b["factory_module"], b["factory_name"])
        owner_class = resolve(b["owner_module"], b["owner_class"])
    else:
        factory = owner_class = resolve(b["factory_module"], b["factory_class"])
    context_class = resolve(b["context_module"], b["context_class"])
    functions = {}
    for label, code in [("HEALTHY", contract.HEALTHY),
                        ("FAULT", contract.BASELINE if p["original_caller_policy"] == "OMIT_EXIT" else contract.HEALTHY),
                        ("CANDIDATE", p["candidate_code"])]:
        contract.validate(code)
        namespace = {"__builtins__": {}, "Exception": Exception, "BaseException": BaseException}
        exec(compile(code, "<owned-" + label.lower() + ">", "exec"), namespace)
        functions[label] = namespace
    errors = {"TimeoutError": TimeoutError, "RuntimeError": RuntimeError, "ValueError": ValueError,
              "CancelledError": asyncio.CancelledError}
    def new_context(owner, key):
        kwargs = dict(b["context_kwargs"])
        if p["target"] == "py-cachify":
            kwargs[b["key_parameter"]] = key
        ctx = getattr(owner, b["context_method"])(**kwargs)
        if type(ctx) is not context_class:
            raise ValueError("REPAIR_CONTEXT_TYPE")
        return ctx
    def sync_case(owner, key, case, stage):
        ctx = new_context(owner, key)
        probe = lambda: bool(getattr(ctx, b["sync_probe"] if p["target"] == "py-cachify" else b["probe_method"])())
        error = errors[case["exception"]]("owned injected fault")
        calls = []
        def work():
            calls.append(probe())
            if stage["inject_exception"]:
                raise error
        first = None
        preserved = not stage["inject_exception"]
        returned = None
        fn = functions.get(stage["id"], functions["CANDIDATE"])["critical_section"]
        try:
            returned = fn(ctx, work)
        except BaseException as exc:
            first = type(exc).__name__
            preserved = exc is error
        held = probe()
        next_ctx = new_context(owner, key)
        entered = False
        if p["target"] == "py-cachify":
            try:
                with next_ctx:
                    entered = True
            except BaseException:
                if not held:
                    raise
            after = probe()
        else:
            entered = getattr(next_ctx, b["next_acquire_method"])(**b["next_acquire_kwargs"])
            if entered:
                getattr(next_ctx, b["next_release_method"])()
            after = bool(probe() or getattr(next_ctx, b["probe_method"])())
        return dict(first_exception=first, locked_after_first=held, second_entered=entered,
                    locked_after_second=after, work_calls=len(calls), work_inside_context=bool(calls) and all(calls),
                    exception_preserved=preserved, returned_none=returned is None)
    async def async_case(owner, key, case, stage):
        ctx = new_context(owner, key)
        async def probe():
            return bool(await getattr(ctx, b["async_probe"])())
        error = errors[case["exception"]]("owned injected fault")
        calls = []
        async def work():
            calls.append(await probe())
            if stage["inject_exception"]:
                if case["fault_kind"] == "TASK_CANCEL":
                    task = asyncio.current_task()
                    asyncio.get_running_loop().call_soon(task.cancel)
                    await asyncio.sleep(0)
                else:
                    raise error
        first = None
        preserved = not stage["inject_exception"]
        returned = None
        fn = functions.get(stage["id"], functions["CANDIDATE"])["async_critical_section"]
        try:
            returned = await fn(ctx, work)
        except BaseException as exc:
            first = type(exc).__name__
            preserved = (case["fault_kind"] == "TASK_CANCEL" and isinstance(exc, asyncio.CancelledError)) or exc is error
        held = await probe()
        entered = False
        try:
            async with new_context(owner, key):
                entered = True
        except BaseException:
            if not held:
                raise
        return dict(first_exception=first, locked_after_first=held, second_entered=entered,
                    locked_after_second=await probe(), work_calls=len(calls),
                    work_inside_context=bool(calls) and all(calls), exception_preserved=preserved,
                    returned_none=returned is None)
    trace = {}
    for case in p["cases"]:
        trace[case["id"]] = {}
        for stage in p["stages"]:
            owner = factory(**b["factory_kwargs"])
            if type(owner) is not owner_class:
                raise ValueError("REPAIR_OWNER_TYPE")
            key = "owned-" + case["id"] + "-" + stage["id"]
            trace[case["id"]][stage["id"]] = asyncio.run(async_case(owner, key, case, stage)) if case["mode"] == "ASYNC" else sync_case(owner, key, case, stage)
    unchanged = all(hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"] for r in p["input_files"])
    print(json.dumps(dict(cases=trace, plan_sha256=hashlib.sha256(raw).hexdigest(),
        executed_candidate_sha256=proof["code_sha256"], actual_candidate_code_executed=True,
        real_oss_code_executed=True, source_unchanged=unchanged, network_attempts=len(attempts),
        target_source_modified=False, namespaces={k: os.readlink("/proc/self/ns/" + k) for k in ["user", "mnt", "pid", "net"]})))


if __name__ == "__main__":
    main()
