#!/usr/bin/env python3
"""Read local runtime facts without network calls or action authority."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess


def collect(config, agents):
    contract = json.loads(config.read_bytes())
    if config.stat().st_uid != 0 or config.stat().st_mode & 0o022:
        raise ValueError("Host contract is not protected")
    if "BEGIN MANAGED: codex-host-contract-v1" not in agents.read_text():
        raise ValueError("Managed host boundary is absent")
    facts = {"generated_jst": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
             "host_id": contract["host_id"], "project_id": contract["project_id"],
             "release_sha256": contract["release_sha256"],
             "contract_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
             "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
             "current_uid": os.getuid(), "state_disk_mounted": os.path.ismount("/mnt/reqlox-state"),
             "units": {}}
    for unit in ("reqlox.service", "nginx.service", "codex-host-context-refresh.timer"):
        result = subprocess.run(["systemctl", "show", unit, "--property=ActiveState,SubState,MainPID"],
                                capture_output=True, text=True, timeout=5)
        facts["units"][unit] = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return "# REQLOX host context\n\nRead-only facts; this is not mutation authorization.\n\n```json\n" + json.dumps(facts, indent=2) + "\n```\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--agents", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    text = collect(args.config, args.agents)
    args.context.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.context.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.chmod(0o644)
    os.replace(temporary, args.context)


if __name__ == "__main__":
    main()
