"Bind quoted evidence and exact finite caller structures."

import ast
import hashlib
import json
import re

LEAK_CALLER = """def critical_section(ctx):
    ctx.__enter__()
    do_work()
    ctx.__exit__(None, None, None)
"""
REPAIRED_CALLER = """def critical_section(ctx):
    with ctx:
        do_work()
"""
SAMPLES = [
    {"id": "reported", "title": "Processing stops after an exception", "kind": "OWNED_SYNTHETIC_REPORT",
     "report": "The payment worker acquired an exclusive lock before calling an external service.\nAfter the service returned TimeoutError, the lock was not released and the next worker could not acquire it.\nThe context exit was not called on the exception path.",
     "caller": LEAK_CALLER},
    {"id": "negative", "title": "The lock is released after the same exception", "kind": "OWNED_SYNTHETIC_REPORT",
     "report": "The external service returned TimeoutError.\nAfter the exception, the lock was released and the next worker could acquire it.\nThere was no lock leak in this observation.",
     "caller": REPAIRED_CALLER},
    {"id": "unknown", "title": "Insufficient lock observations", "kind": "OWNED_SYNTHETIC_REPORT",
     "report": "The service returned TimeoutError and delayed some requests.\nThe lock state and cleanup after the exception were not observed, so the cause is unknown.",
     "caller": LEAK_CALLER},
]


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(encode(value)).hexdigest()


def caller_policy(source):
    if not isinstance(source, str) or not 1 <= len(source) <= 3000:
        raise ValueError("Caller code must contain at most 3,000 characters.")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        raise ValueError("Check the caller code syntax.") from None
    
    shape = ast.dump(tree, include_attributes=False)
    for text, policy in [(LEAK_CALLER, "OMIT_EXIT"), (REPAIRED_CALLER, "BALANCED_CONTEXT")]:
        if shape == ast.dump(ast.parse(text), include_attributes=False):
            return {"policy": policy, "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "input_code_executed": False, "translation": "EXACT_FINITE_CALLER_AST"}
    raise ValueError("This demo supports the two displayed critical_section structures. Input code is not executed.")


def evidence(report):
    if not isinstance(report, str) or not 1 <= len(report.strip()) <= 12000:
        raise ValueError("The incident report must contain 1 to 12,000 characters.")
    result = []
    for match in re.finditer(r"[^。.!?\n]+[。.!?]?", report):
        text = match.group().strip()
        if not text:
            continue
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        for offset in range(0, len(text), 300):
            quote = text[offset:offset + 300]
            result.append({"id": f"e{len(result)}", "start_char": start + offset,
                           "end_char": start + offset + len(quote), "text": quote,
                           "sha256": hashlib.sha256(quote.encode()).hexdigest()})
    if len(result) > 64:
        raise ValueError("Too many quotation candidates. Limit the input to one episode.")
    for row in result:
        assert report[row["start_char"]:row["end_char"]] == row["text"]
    return result


def baseline(report):
    quotes = evidence(report)
    relevant = [r for r in quotes if re.search(r"lock|\u30ed\u30c3\u30af|\u6392\u4ed6|cleanup|\u89e3\u653e|exit", r["text"], re.I)]
    positive = [r for r in relevant if re.search(r"\u89e3\u653e\u3055\u308c\u305a|\u89e3\u653e\u3055\u308c\u306a\u304b\u3063\u305f|\u89e3\u653e\u6f0f\u308c\u304c(?:\u767a\u751f|\u3042\u3063\u305f)|exit\u51e6\u7406\u304c\u547c\u3070\u308c\u3066\u3044\u306a\u304b\u3063\u305f|lock (?:remained|was left) held|lock was not released", r["text"], re.I)]
    negative = [r for r in relevant if re.search(r"\u89e3\u653e\u6f0f\u308c\u306f\u306a\u304b\u3063\u305f|\u6b63\u5e38\u306b\u89e3\u653e|lock was released|no lock leak", r["text"], re.I)]
    
    qualifier = r"\u672a\u78ba\u5b9a|\u4e0d\u660e|\u8a18\u9332\u304c\u306a\u304f|\u304b\u3082\u3057\u308c|\u5426\u5b9a|\u4eee\u8aac|\u8a13\u7df4|\u4e88\u5b9a|\u3082\u3057|\u60f3\u5b9a|\u7591\u3044|\u53ef\u80fd\u6027|not confirmed|unknown|not observed|hypothetic|training|future|might|suspect|would|\bif\b"
    positive = [r for r in positive if not re.search(qualifier, r["text"], re.I)]
    negative = [r for r in negative if not re.search(qualifier, r["text"], re.I)]
    choice = "SUPPORTED" if positive and not negative else "NOT_SUPPORTED" if negative and not positive else "INSUFFICIENT_INFORMATION"
    selected = positive if choice == "SUPPORTED" else negative if choice == "NOT_SUPPORTED" else relevant[:4]
    return {"method": "MECHANICAL_BASELINE", "choice": choice, "probabilities": None,
            "calibrated": False, "evidence": selected[:4], "all_evidence_handles": quotes,
            "hypothesis": "The context cleanup is skipped on an exception path, leaving a lock held and blocking the next acquisition.",
            "hypothesis_origin": "EXPERIMENT_HYPOTHESIS", "natural_truth_certified": False,
            "execution_authority": False,
            "note": "This baseline uses finite text rules. It does not establish unrestricted semantic support or natural incident truth."}


def stages(policy):
    return [{"id": "HEALTHY", "policy": "BALANCED_CONTEXT", "inject_exception": False},
            {"id": "FAULT", "policy": policy, "inject_exception": True},
            {"id": "REPAIR", "policy": "BALANCED_CONTEXT", "inject_exception": False},
            {"id": "REINJECTION", "policy": "BALANCED_CONTEXT", "inject_exception": True}]


def cases(target):
    if target not in ("py-cachify", "readerwriterlock"):
        raise ValueError("Select a supported target.")
    rows = [{"id": "sync-timeout", "mode": "SYNC", "exception": "TimeoutError"},
            {"id": "sync-runtime", "mode": "SYNC", "exception": "RuntimeError"},
            {"id": "sync-value", "mode": "SYNC", "exception": "ValueError"}]
    if target == "py-cachify":
        rows += [{"id": "async-timeout", "mode": "ASYNC", "exception": "TimeoutError"},
                 {"id": "async-runtime", "mode": "ASYNC", "exception": "RuntimeError"}]
    return rows
