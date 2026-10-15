#!/usr/bin/env python3
"""Emit fixed read-only host facts to private boot diagnostics; never credentials."""
import base64
import datetime
import json
from pathlib import Path
import urllib.request


def protected_read(name):
    path = Path(name)
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("Host evidence ownership differs")
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Host evidence exceeds its bound")
    return raw.decode()


def main():
    # The collector unit is read first; only its fixed reviewed paths follow.
    unit = protected_read("/etc/systemd/system/codex-host-context-refresh.service")
    paths = {"contract": "/etc/codex-host-context/host.json",
             "instructions": "/etc/codex-host-context/AGENTS.md",
             "context": "/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md"}
    if not all(name in unit for name in paths.values()):
        raise ValueError("Collector paths differ")
    facts = {"collector_unit": unit, **{k: protected_read(v) for k, v in paths.items()}}
    request = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/id",
                                     headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=3) as response:
        facts["physical_instance_id"] = response.read(128).decode().strip()
    facts["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    facts["observed_jst"] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
    print("REQLOX_BOOT_EVIDENCE_BASE64=" + base64.b64encode(json.dumps(facts).encode()).decode(), flush=True)


if __name__ == "__main__":
    main()
