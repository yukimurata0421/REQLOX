"""Portable entry points for inspection, bounded experiments, and the UI."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__, _runtime


def check():
    available = sys.platform == "linux" and shutil.which("bwrap") is not None
    python_ok = Path(sys.executable).resolve().is_relative_to(Path("/usr"))
    isolated = False
    if available and python_ok:
        command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
                   "--clearenv", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr",
                   "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                   "--proc", "/proc", "--dev", "/dev", "/usr/bin/true"]
        try:
            isolated = subprocess.run(command, capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    value = dict(version=__version__, python_supported=sys.version_info >= (3, 11),
                 linux=sys.platform == "linux", bubblewrap=available,
                 system_python=python_ok, isolation_probe_passed=isolated,
                 experiments_available=available and python_ok and isolated,
                 target_experiments=0, provider_calls=0)
    print(json.dumps(value))
    return 0 if value["experiments_available"] else 1


def main(argv=None):
    _runtime()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("target", "run"):
        from .target_cli import main as delegated
        return delegated(argv)
    if argv and argv[0] == "knowledge":
        from .knowledge_cli import main as delegated
        return delegated(argv[1:])
    if argv and argv[0] == "study":
        from .study_cli import main as delegated
        return delegated(argv[1:])
    if argv and argv[0] == "integration":
        from .integration_cli import main as delegated
        return delegated(argv[1:])
    if argv and argv[0] == "scope":
        from .scope_cli import main as delegated
        return delegated(argv[1:])
    if argv and argv[0] in ("demo", "prepare"):
        if argv[0] == "demo":
            from reqlox_demo.__main__ import main as delegated
        else:
            from reqlox_core.prepare_reliability_reuse import main as delegated
        saved = sys.argv
        try:
            sys.argv = ["reqlox " + argv[0], *argv[1:]]
            return delegated()
        finally:
            sys.argv = saved
    parser = argparse.ArgumentParser(description="Finite reliability inspection and isolated repair")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Probe isolation with /usr/bin/true; no target experiments")
    commands.add_parser("target", help="Register named repositories; run 'reqlox target --help'")
    commands.add_parser("run", help="Run selected Target repositories; run 'reqlox run --help'")
    commands.add_parser("integration", help="Copied module caller; reqlox integration --help")
    commands.add_parser("scope", help="Inspect inherited evaluation bounds; reqlox scope --help")
    inspect = commands.add_parser("inventory", help="Statically inspect a source directory")
    inspect.add_argument("--root", type=Path, required=True)
    qualify = commands.add_parser("qualify", help="Run a bounded repair loop on an owned snapshot")
    qualify.add_argument("--root", type=Path, required=True)
    qualify.add_argument("--configuration", type=Path, required=True)
    qualify.add_argument("--state-dir", type=Path)
    qualify.add_argument("--name", default=None)
    qualify.add_argument("--seconds", type=int, default=120)
    qualify.add_argument("--maximum-native-campaigns", type=int, default=12)
    qualify.add_argument("--maximum-rounds", type=int, default=3)
    qualify.add_argument("--dependency", type=Path)
    qualify.add_argument("--paired", action="store_true", help="Use separate Source and No Source snapshots")
    audit = commands.add_parser("audit", help="Verify a saved result without executing targets")
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--kind", choices=("run", "loop", "paired"), default="loop")
    audit.add_argument("--state-dir", type=Path)
    commands.add_parser("demo", help="Browser UI; run 'reqlox demo --help' for options")
    commands.add_parser("prepare", help="Prepare quoted conditions; run 'reqlox prepare --help'")
    commands.add_parser("study", help="Local preparation, Source comparison, and calibration; run 'reqlox study --help'")
    commands.add_parser("knowledge", help="Local document search and source-bound IR review; run 'reqlox knowledge --help'")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check()
        if args.command == "inventory":
            from reqlox_core import run_reliability_reuse as runner
            sources = runner.load_snapshot(args.root.resolve())
            print(json.dumps(runner.inventory_for(sources), ensure_ascii=False))
            return 0
        if args.state_dir is not None:
            os.environ["REQLOX_STATE_DIR"] = str(args.state_dir.absolute())
        from reqlox_core.reqlox_paths import ensure_state
        state = ensure_state()
        if args.command == "audit":
            from reqlox_core import audit_reliability_reuse
            saved = sys.argv
            try:
                sys.argv = ["reqlox audit", "--kind", args.kind, "--output", str(args.output.absolute())]
                audit_reliability_reuse.main()
            finally:
                sys.argv = saved
            return 0
        from reqlox_core import run_reliability_reuse as runner
        if not 1 <= args.seconds <= 7200 or not 0 <= args.maximum_native_campaigns <= 64:
            parser.error("seconds must be 1..7200 and campaign limit must be 0..64")
        name = args.name or datetime.datetime.now(datetime.timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
        if not name or Path(name).name != name or name in (".", "..") or "\\" in name:
            parser.error("name must be one directory component")
        runs = state / "runs"
        runs.mkdir(mode=0o700, exist_ok=True)
        output = runs / name
        sources = runner.load_snapshot(args.root.resolve())
        config = runner.read(args.configuration)
        deadline = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=args.seconds)).isoformat()
        common = dict(deadline=deadline, maximum_rounds=args.maximum_rounds,
                      maximum_probes=config.get("maximum_probes", 3))
        if args.paired:
            from reqlox_core import reliability_requirement_experiment as requirements
            from reqlox_core import run_reliability_paired as paired
            policies = {family: {key: row[key] for key in ("basis", "scope")} for family, row in config["contracts"].items()}
            experiment = requirements.prepare(sources, config.get("specification_texts", {}), policies)
            result = paired.run(sources, experiment, config.get("source_texts", {}), output,
                                maximum_native_campaigns_per_arm=args.maximum_native_campaigns, **common)
        else:
            from reqlox_core import reliability_reuse as reuse
            from reqlox_core import run_reliability_improvement_loop as loop
            hypotheses = [reuse.hypothesis(h, config.get("source_texts", {})) for h in config.get("hypotheses", [])]
            result = loop.run(sources, config["contracts"], hypotheses, output,
                              source_texts=config.get("source_texts", {}),
                              dependency=None if args.dependency is None else args.dependency.resolve(),
                              maximum_native_campaigns=args.maximum_native_campaigns, **common)
        if runner.load_snapshot(args.root.resolve()) != sources:
            raise ValueError("Source changed during execution")
        print(json.dumps(dict(status=result["status"], output=str(output),
                              checkout_mutated=False, natural_source_added_value_certified=False,
                              independent_generalization_certified=False), ensure_ascii=False))
        return 0 if result["status"] == "ADOPTED_IN_SNAPSHOT" or result["status"] == "COMPLETE" else 1
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps(dict(status="STOPPED", reason=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2
