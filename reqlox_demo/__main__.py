"Entry points for the local finite reliability demo."

import argparse
import json
from pathlib import Path
import sys

from .engine import Demo
from reqlox import _runtime

_runtime()
from reqlox_core.reqlox_paths import ensure_state, state_root


def main():
    parser = argparse.ArgumentParser(description="REQLOX: a local incident-to-lock-cleanup experiment")
    parser.add_argument("action", choices=["serve", "run", "prepare", "benchmark", "repair-benchmark"], nargs="?", default="serve")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache", type=Path, default=state_root() / "demo")
    parser.add_argument("--sample", choices=["reported", "negative", "unknown"], default="reported")
    parser.add_argument("--target", choices=["py-cachify", "readerwriterlock"], default="py-cachify")
    parser.add_argument("--method", choices=["baseline", "recorded", "live"], default="baseline")
    parser.add_argument("--repair", choices=["rule", "recorded", "live"], default="rule")
    parser.add_argument("--send-to-model", action="store_true")
    parser.add_argument("--model-scope", type=Path)
    parser.add_argument("--json-input", type=Path)
    parser.add_argument("--target-manifest", type=Path, action="append", default=[], help="Explicit local Target manifest; repeat to register several")
    parser.add_argument("--allow-target-experiments", action="store_true", help="Enable native Target runs on an isolated experiment host")
    parser.add_argument("--integration-run", type=Path, action="append", default=[], help="Read-only audited module integration result; repeat to register several")
    args = parser.parse_args()
    if args.action == "serve" and (args.allow_target_experiments or args.model_scope or args.send_to_model):
        parser.error("UI_EXECUTION_DISABLED: browser UI supports offline records and preparation only")
    if not 0 <= args.port <= 65535:
        parser.error("The port must be between 0 and 65535.")
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or later is required.")
    from .model import LiveModel
    from .contracts import SAMPLES
    ensure_state()
    engine = Demo(args.cache, LiveModel(args.model_scope) if args.model_scope else None)
    if args.action == "serve":
        from .server import Server
        server = Server(args.port, engine, args.target_manifest, args.allow_target_experiments, args.integration_run)
        print(f"REQLOX demo: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    if args.action == "prepare":
        from .targets import PACKAGES, acquire
        for name in PACKAGES:
            acquire(args.cache, name)
        print(json.dumps({"status": "KNOWN_DEMO_TARGETS_READY", "packages": len(PACKAGES), "provider_calls": 0}))
        return 0
    if args.action == "benchmark":
        if args.repair != "rule":
            parser.error("Use repair-benchmark for locally supplied repair controls.")
        from .benchmark import run
        value = run(engine, args.method)
        print(json.dumps(value, ensure_ascii=False))
        return 0 if value["status"] == "PASS" else 1
    if args.action == "repair-benchmark":
        from .repair_benchmark import run
        value = run(engine)
        print(json.dumps(value, ensure_ascii=False))
        return 0 if value["status"] == "PASS" else 1
    sample = next(s for s in SAMPLES if s["id"] == args.sample)
    request = json.loads(args.json_input.read_text()) if args.json_input else {"report": sample["report"], "caller": sample["caller"], "target": args.target, "method": args.method, "repair": args.repair, "send_to_model": args.send_to_model}
    value = engine.run(request)
    print(json.dumps(value, ensure_ascii=False))
    return 1 if value["status"] in ["STOPPED", "CONTRACT_MISMATCH"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
