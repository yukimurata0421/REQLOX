#!/usr/bin/env python3
"""Export only the existing browser assets; never export state or documents."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

FILES = ("index.html", "study.html", "knowledge.html", "app.js", "study.js", "knowledge.js", "style.css", "targets.html", "targets.js", "targets.css", "records.html", "records.js", "workspace.js", "workspace.css")


def export(source, destination):
    from reqlox_demo.cloud_server import cloud_page
    source, destination = Path(source), Path(destination)
    destination.mkdir(mode=0o700)
    files = []
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Static asset must be a regular file")
        raw = path.read_bytes()
        if name.endswith(".html"):
            raw = cloud_page(raw)
        if len(raw) > 1024 * 1024:
            raise ValueError("Static asset exceeds the size bound")
        (destination / name).write_bytes(raw)
        files.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return {"schema": "REQLOX_WEB_ASSETS_V1", "files": files, "private_state_exported": False,
            "documents_exported": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    print(json.dumps(export(Path(__file__).resolve().parents[1] / "reqlox_demo/static", args.output_dir)))


if __name__ == "__main__":
    main()
