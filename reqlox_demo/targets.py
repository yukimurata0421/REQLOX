"Finite reliability controls and verification."

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "py-cachify": {"version": "3.1.0", "license": "MIT", "bytes": 26585,
        "sha256": "8fdbe0f710154223cbe7a93797e48abb2dbbb5473a39f3deccf4d8524ee98b46",
        "url": "https://files.pythonhosted.org/packages/99/d9/122ec9d6b864be8261909797d574bd8d891dadf700be04043948cdfed39d/py_cachify-3.1.0-py3-none-any.whl"},
    "readerwriterlock": {"version": "1.0.9", "license": "MIT", "bytes": 9999,
        "sha256": "8c4b704e60d15991462081a27ef46762fea49b478aa4426644f2146754759ca7",
        "url": "https://files.pythonhosted.org/packages/c2/5a/2f2e7fc026d5e64b5408aa3fbe0296a6407b8481196cae4daacacb3a3ae0/readerwriterlock-1.0.9-py3-none-any.whl"},
    "typing-extensions": {"version": "4.15.0", "license": "PSF-2.0", "bytes": 44614,
        "sha256": "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548",
        "url": "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl"},
}


def extract(raw, destination):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set()
        total = 0
        if not 1 <= len(archive.infolist()) <= 256:
            raise ValueError("The distribution exceeds the file-count limit.")
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            total += item.file_size
            if (not path.parts or path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or item.filename in names or total > 4194304 or item.file_size > 1048576
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("The distribution layout exceeds the supported bounds.")
            names.add(item.filename)
            if item.is_dir():
                continue
            output = destination / path
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with output.open("xb") as stream:
                stream.write(archive.read(item))
            output.chmod(0o600)


def files(root):
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Links inside the target are unsupported.")
        if path.is_file() and path != root / "snapshot.json":
            raw = path.read_bytes()
            result.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return result


def acquire(cache, name):
    if name not in PACKAGES:
        raise ValueError("Only the pinned distributions can be acquired.")
    spec = PACKAGES[name]
    directory = Path(cache) / "targets" / (name + "-" + spec["version"])
    if directory.exists():
        if directory.is_symlink() or not (directory / "snapshot.json").is_file():
            raise ValueError("The target cache is incomplete. Select a new cache directory.")
        snapshot = json.loads((directory / "snapshot.json").read_text())
        if snapshot["package"] != name or snapshot["distribution_sha256"] != spec["sha256"] or snapshot["files"] != files(directory):
            raise ValueError("The cached target hash has changed.")
        return directory, snapshot
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    request = urllib.request.Request(spec["url"], headers={"User-Agent": "REQLOX-demo/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if not response.geturl().startswith("https://files.pythonhosted.org/"):
            raise ValueError("The download host has changed.")
        raw = response.read(spec["bytes"] + 1)
    if len(raw) != spec["bytes"] or hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("The distribution hash does not match.")
    temporary = Path(tempfile.mkdtemp(prefix=".download-", dir=directory.parent))
    try:
        extract(raw, temporary)
        licenses = [p for p in temporary.rglob("*") if p.is_file() and p.name.lower().startswith(("license", "licence", "copying"))]
        if not licenses:
            raise ValueError("No license notice was found in the distribution.")
        snapshot = {"package": name, "version": spec["version"], "distribution_sha256": spec["sha256"],
                    "license": spec["license"], "files": files(temporary), "build_or_install_executed": False,
                    "role": "KNOWN_DEMO_CONTROL", "unused_holdout": False}
        (temporary / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        (temporary / "snapshot.json").chmod(0o600)
        os.rename(temporary, directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return directory, snapshot
