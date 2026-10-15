#!/usr/bin/env python3
"""Export only the existing browser assets; never export state or documents."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

OWNER_FILES = ("index.html", "study.html", "knowledge.html", "app.js", "study.js", "knowledge.js", "style.css", "targets.html", "targets.js", "targets.css", "records.html", "records.js", "workspace.js", "workspace.css")
PUBLIC_FILES = ('public-demo.html', 'public-demo.js', 'public-demo.css', 'public-demo.json')
FILES = OWNER_FILES + PUBLIC_FILES
PUBLIC_ROUTES = {'/demo/':'public-demo.html', '/demo/public-demo.html':'public-demo.html',
                 '/demo/public-demo.js':'public-demo.js', '/demo/public-demo.css':'public-demo.css',
                 '/demo/public-demo.json':'public-demo.json'}


def export(source, destination):
    from reqlox_demo.cloud_server import cloud_page
    from reqlox_demo.public_demo import export as export_public
    source, destination = Path(source), Path(destination)
    destination.mkdir(mode=0o700)
    files = []
    for name in OWNER_FILES:
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
    with tempfile.TemporaryDirectory(prefix='reqlox-public-export-') as temporary:
        public = Path(temporary) / 'public'
        summary = export_public(public, source=source)
        for row in summary['files']:
            (destination / row['name']).write_bytes((public / row['name']).read_bytes())
        files.extend(summary['files'])
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
