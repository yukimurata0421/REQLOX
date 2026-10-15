#!/usr/bin/env python3
"""Apply a narrowly scoped Tunnel/DNS declaration; retain redacted state locally."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def credentials(ssh_host, path):
    # Reading an existing user-owned credential does not change the source host.
    code = ("from pathlib import Path;import os,stat,sys;"
            "p=Path(" + repr(path) + ");s=p.stat();"
            "assert not p.is_symlink() and s.st_uid==os.getuid() and not stat.S_IMODE(s.st_mode)&0o077;"
            "sys.stdout.buffer.write(p.read_bytes())")
    value = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_host,
                            "python3 -c " + shlex.quote(code)], capture_output=True, check=True, timeout=20).stdout.decode()
    result = {}
    for line in value.splitlines():
        match = re.fullmatch(r"\s*(?:export\s+)?(CLOUDFLARE_[A-Z_]+)\s*=\s*(.*?)\s*", line)
        if match:
            result[match[1]] = match[2].strip("\"'")
    for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ZONE_ID", "CLOUDFLARE_API_TOKEN"):
        if not result.get(key):
            raise ValueError("Required credential fields are absent")
    return result


class Edge:
    def __init__(self, values, state):
        self.values, self.state = values, Path(state)

    def request(self, method, path, payload=None):
        raw = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request("https://api.cloudflare.com/client/v4" + path, data=raw,
            headers={"Authorization": "Bearer " + self.values["CLOUDFLARE_API_TOKEN"], "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                value = json.loads(response.read(1024 * 1024))
        except urllib.error.HTTPError as exc:
            self.audit(method, path, raw, "HTTP_" + str(exc.code))
            raise ValueError("Cloudflare request failed: HTTP " + str(exc.code)) from None
        if value.get("success") is not True:
            self.audit(method, path, raw, "API_REJECTED")
            raise ValueError("Cloudflare rejected the scoped request")
        self.audit(method, path, raw, "SUCCESS")
        return value["result"]

    def audit(self, method, path, raw, status):
        row = {"jst": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
               "method": method, "path": path, "payload_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
               "status": status, "credentials_recorded": False}
        with (self.state / "edge-audit.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")


def validate(config):
    if (config.get("name") != "reqlox-web" or config.get("project") != "reqlox"
            or not re.fullmatch(r"[a-z0-9-]+\." + re.escape(config.get("root_domain", "")), config.get("domain", ""))
            or config.get("tunnel_secret") != "reqlox-web-tunnel-token"):
        raise ValueError("Edge declaration differs from the dedicated Web scope")
    return config


def ingress(domain):
    return {"config": {"ingress": [{"hostname": domain, "service": "http://127.0.0.1:8081",
        "originRequest": {"httpHostHeader": domain, "connectTimeout": 10}}, {"service": "http_status:404"}]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--credential-ssh-host", required=True)
    parser.add_argument("--credential-path", required=True)
    parser.add_argument("--phase", choices=("prepare", "activate", "inspect"), required=True)
    args = parser.parse_args()
    os.umask(0o077)
    config = validate(json.loads(args.config.read_bytes()))
    args.state_dir.mkdir(mode=0o700, exist_ok=True)
    values = credentials(args.credential_ssh_host, args.credential_path)
    edge = Edge(values, args.state_dir)
    account, zone = values["CLOUDFLARE_ACCOUNT_ID"], values["CLOUDFLARE_ZONE_ID"]
    z = edge.request("GET", "/zones/" + zone)
    if z["name"] != config["root_domain"] or z["status"] != "active" or z["account"]["id"] != account:
        raise ValueError("Cloudflare zone/account identity differs")
    target = "/zones/" + zone + "/dns_records"
    records = edge.request("GET", target + "?" + urllib.parse.urlencode({"name": config["domain"]}))
    state_path = args.state_dir / "edge-state.json"
    if args.phase == "prepare":
        if state_path.exists() or records:
            raise ValueError("Preserve any previous attempt or existing target DNS; do not retry")
        tunnels = edge.request("GET", "/accounts/" + account + "/cfd_tunnel?is_deleted=false")
        if any(t["name"] == config["name"] for t in tunnels):
            raise ValueError("A pre-existing tunnel cannot be adopted implicitly")
        result = edge.request("POST", "/accounts/" + account + "/cfd_tunnel", {"name": config["name"], "config_src": "cloudflare"})
        state = {"schema": "REQLOX_EDGE_STATE_V1", "name": config["name"], "domain": config["domain"],
                 "tunnel_id": result["id"], "dns_id": None, "secret_version": None}
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        token = result.get("token") or edge.request("GET", "/accounts/" + account + "/cfd_tunnel/" + result["id"] + "/token")
        version = subprocess.run(["gcloud", "secrets", "versions", "add", config["tunnel_secret"],
            "--project=" + config["project"], "--data-file=-", "--format=value(name)", "--quiet"],
            input=token.encode(), capture_output=True, check=True, timeout=30).stdout.decode().strip()
        if not version.endswith("/versions/1"):
            raise ValueError("A fresh tunnel token version is required")
        state["secret_version"] = "1"
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        edge.request("PUT", "/accounts/" + account + "/cfd_tunnel/" + result["id"] + "/configurations", ingress(config["domain"]))
    else:
        state = json.loads(state_path.read_bytes())
        if state["domain"] != config["domain"] or state["name"] != config["name"]:
            raise ValueError("Saved edge identity differs")
        tunnel = edge.request("GET", "/accounts/" + account + "/cfd_tunnel/" + state["tunnel_id"])
        if args.phase == "activate":
            if state.get("dns_id") is not None or records or tunnel.get("status") != "healthy":
                raise ValueError("Only a healthy new tunnel with absent DNS may be activated")
            result = edge.request("POST", target, {"type": "CNAME", "proxied": True, "ttl": 1,
                "name": config["domain"], "content": state["tunnel_id"] + ".cfargotunnel.com", "comment": "REQLOX isolated Web deployment"})
            state["dns_id"] = result["id"]
            state_path.write_text(json.dumps(state, indent=2) + "\n")
        else:
            print(json.dumps({"tunnel_status": tunnel.get("status"), "domain": state["domain"],
                "dns_matches": len(records) == 1 and records[0]["id"] == state.get("dns_id") and records[0]["content"] == state["tunnel_id"] + ".cfargotunnel.com"}))
            return
    print(json.dumps(state))


if __name__ == "__main__":
    main()
