#!/usr/bin/env python3
"""Verify a pinned cloud deployment through its authenticated local IAP tunnel."""
import argparse
import json
import re
import urllib.request


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=15) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Response exceeds the smoke-check bound")
        return raw, response.headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--release-sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch("[a-f0-9]{64}", args.release_sha256):
        parser.error("Use the immutable release hash from Terraform outputs")
    raw, _ = get("/api/deployment")
    health = json.loads(raw)
    if (health.get("status") != "READY" or health.get("project_id") != args.project or
            health.get("release_sha256") != args.release_sha256 or
            health.get("isolation_probe_passed") is not True or health.get("jev_credential_loaded") is not True or
            health.get("paid_model_calls_enabled") is not False):
        raise ValueError("Deployment identity, isolation, or credential loading could not be verified")
    for path in ("/", "/study", "/knowledge"):
        raw, headers = get(path)
        if (b"Google Cloud VM" not in raw or "frame-ancestors 'none'" not in headers.get("Content-Security-Policy", "")
                or headers.get("Cache-Control") != "no-store"):
            raise ValueError("Hosted page or response security contract differs")
    print(json.dumps({"status": "PASS", "project": args.project, "release_sha256": args.release_sha256,
                      "pages": 3, "credential_values_read": False, "provider_calls": 0, "target_experiments": 0}))


if __name__ == "__main__":
    main()
