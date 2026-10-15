"Validate candidate syntax separately from repair success."

import ast
import hashlib

VERSION = "generated-cleanup-v1"
FUNCTIONS = {"critical_section": ast.FunctionDef, "async_critical_section": ast.AsyncFunctionDef}
BASELINE = """def critical_section(ctx, do_work):
    ctx.__enter__()
    do_work()
    ctx.__exit__(None, None, None)

async def async_critical_section(ctx, do_work):
    await ctx.__aenter__()
    await do_work()
    await ctx.__aexit__(None, None, None)
"""
HEALTHY = """def critical_section(ctx, do_work):
    with ctx:
        do_work()

async def async_critical_section(ctx, do_work):
    async with ctx:
        await do_work()
"""


def validate(code):
    if not isinstance(code, str) or not 1 <= len(code.encode()) <= 4096 or len(code.splitlines()) > 60:
        raise ValueError("The repair code exceeds the safety grammar size limit.")
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        raise ValueError("The repair code syntax could not be verified.") from None
    if len(tree.body) != 2 or {getattr(n, "name", None) for n in tree.body} != set(FUNCTIONS):
        raise ValueError("The repair must contain exactly the specified synchronous and asynchronous functions.")
    allowed = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.arguments, ast.arg,
               ast.Expr, ast.Call, ast.Attribute, ast.Name, ast.Load, ast.Constant,
               ast.With, ast.AsyncWith, ast.withitem, ast.Await, ast.Try,
               ast.ExceptHandler, ast.Raise, ast.Pass, ast.Return)
    nodes = list(ast.walk(tree))
    if len(nodes) > 200:
        raise ValueError("The repair AST exceeds the node limit.")
    for fn in tree.body:
        args = fn.args
        if (type(fn) is not FUNCTIONS[fn.name] or fn.decorator_list or fn.returns or
                args.posonlyargs or args.kwonlyargs or args.defaults or args.kw_defaults or
                args.vararg or args.kwarg or [a.arg for a in args.args] != ["ctx", "do_work"] or
                any(a.annotation for a in args.args) or getattr(fn, "type_params", [])):
            raise ValueError("The repair function declaration is outside the contract.")
    for n in nodes:
        if not isinstance(n, allowed):
            raise ValueError("The repair contains an unsupported operation.")
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n not in tree.body:
            raise ValueError("Nested functions are unsupported.")
        if isinstance(n, ast.Name) and n.id not in {"ctx", "do_work", "Exception", "BaseException"}:
            raise ValueError("The repair references a name outside the contract.")
        if isinstance(n, ast.Constant) and n.value is not None:
            raise ValueError("Only the None literal is permitted in repairs.")
        if isinstance(n, ast.Attribute) and (not isinstance(n.value, ast.Name) or n.value.id != "ctx" or
                n.attr not in {"__enter__", "__exit__", "__aenter__", "__aexit__"}):
            raise ValueError("The repair references an attribute outside the contract.")
        if isinstance(n, ast.Call):
            work = isinstance(n.func, ast.Name) and n.func.id == "do_work" and not n.args
            protocol = isinstance(n.func, ast.Attribute) and (not n.args if n.func.attr in {"__enter__", "__aenter__"}
                        else len(n.args) == 3 and all(isinstance(a, ast.Constant) and a.value is None for a in n.args))
            if n.keywords or not (work or protocol):
                raise ValueError("The repair call is outside the contract.")
        if isinstance(n, ast.withitem) and (not isinstance(n.context_expr, ast.Name) or
                n.context_expr.id != "ctx" or n.optional_vars is not None):
            raise ValueError("The context must be the ctx argument.")
        if isinstance(n, ast.ExceptHandler) and (n.name is not None or
                n.type is not None and (not isinstance(n.type, ast.Name) or n.type.id not in {"Exception", "BaseException"})):
            raise ValueError("The exception handler is outside the safety grammar.")
        if isinstance(n, ast.Raise) and (n.exc is not None or n.cause is not None):
            raise ValueError("Exception operations may only re-raise the original exception.")
    
    return {"code_sha256": hashlib.sha256(code.encode()).hexdigest(), "grammar_version": VERSION,
            "safe_grammar": True, "correctness_certified": False, "ast_nodes": len(nodes)}


def cases(target):
    rows = [{"id": "sync-" + x.lower(), "mode": "SYNC", "exception": x, "fault_kind": "DIRECT"}
            for x in ["TimeoutError", "RuntimeError", "ValueError", "CancelledError"]]
    if target == "py-cachify":
        rows += [{"id": "async-" + x.lower(), "mode": "ASYNC", "exception": x, "fault_kind": "DIRECT"}
                 for x in ["TimeoutError", "RuntimeError", "CancelledError"]]
        rows += [{"id": "async-task-cancel", "mode": "ASYNC", "exception": "CancelledError", "fault_kind": "TASK_CANCEL"}]
    elif target != "readerwriterlock":
        raise ValueError("Select a supported target.")
    return rows


def expected(case, stage, lock_gold):
    return {**lock_gold, "work_calls": 1, "work_inside_context": True,
            "exception_preserved": True, "returned_none": True}
