#!/usr/bin/env python3
"""Build an allowlisted, offline-installable Debian 12 runtime release."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile


def build_manifest(wheelhouse):
    requirements = []
    for wheel in sorted(wheelhouse.glob("*.whl")):
        with zipfile.ZipFile(wheel) as bundle:
            names = bundle.namelist()
            if wheel.name.startswith("reqlox-"):
                for name in names:
                    first = name.split("/", 1)[0]
                    if first not in ("reqlox", "reqlox_core", "reqlox_demo", "reqlox_knowledge", "reqlox_system") and not first.endswith(".dist-info"):
                        raise ValueError("The application wheel contains files outside the public runtime")
                    if ".." in name.split("/") or "\\" in name:
                        raise ValueError("Invalid application wheel path")
            metadata = [n for n in names if n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Wheel metadata is ambiguous")
            text = bundle.read(metadata[0]).decode()
            name = re.search(r"^Name: ([A-Za-z0-9_.-]+)$", text, re.M)
            version = re.search(r"^Version: ([A-Za-z0-9_.+!-]+)$", text, re.M)
            if not name or not version:
                raise ValueError("Wheel identity is unsupported")
        requirements.append(f"{name[1]}=={version[1]} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
    if not requirements or len(requirements) > 60:
        raise ValueError("Dependency set exceeds the release bound")
    return "\n".join(requirements) + "\n"


def archive_release(directory, output, *, rollout_method_sha256=None):
    if rollout_method_sha256 is not None and (type(rollout_method_sha256) is not str
            or not re.fullmatch('[a-f0-9]{64}', rollout_method_sha256)):
        raise ValueError('The reviewed rollout method requires an exact SHA-256')
    entries = sorted([directory / "requirements.txt", *directory.glob("wheelhouse/*.whl")])
    files = [{"path": str(p.relative_to(directory)), "bytes": p.stat().st_size,
              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in entries]
    if sum(f["bytes"] for f in files) > 128 * 1024 * 1024:
        raise ValueError("Release exceeds 128 MiB")
    manifest = {"schema": "REQLOX_CLOUD_RELEASE_V1", "target_python": "3.11", "target_os": "DEBIAN_12",
                "architecture": "x86_64", "files": files, "documentation_included": False,
                "private_evidence_included": False, "provider_calls": 0}
    if rollout_method_sha256 is not None:
        manifest['rollout_method_sha256'] = rollout_method_sha256
    meta = directory / "release.json"
    meta.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    entries.append(meta)
    with output.open("xb") as target, gzip.GzipFile(fileobj=target, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for path in sorted(entries):
                raw = path.read_bytes()
                info = tarfile.TarInfo(str(path.relative_to(directory)))
                info.size, info.mode, info.mtime = len(raw), 0o644, 0
                info.uid = info.gid = 0
                bundle.addfile(info, io.BytesIO(raw))
    output.chmod(0o600)
    return {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size, "files": len(entries), "docs_uploaded": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rollout-method-sha256")
    args = parser.parse_args()
    output = args.output_dir.absolute()
    output.mkdir(mode=0o700)
    wheelhouse = output / "wheelhouse"
    wheelhouse.mkdir(mode=0o700)
    # Resolve target-platform wheels without installing or executing their code.
    command = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--dest", str(wheelhouse),
               "--python-version", "311", "--implementation", "cp", "--abi", "cp311"]
    for platform in ("manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_27_x86_64", "manylinux_2_28_x86_64"):
        command += ["--platform", platform]
    command += [str(args.wheel.absolute()) + "[knowledge,cloud]"]
    subprocess.run(command, check=True, timeout=300)
    (output / "requirements.txt").write_text(build_manifest(wheelhouse))
    print(json.dumps(archive_release(output, output / "cloud-release.tar.gz",
        rollout_method_sha256=args.rollout_method_sha256)))


if __name__ == "__main__":
    main()
