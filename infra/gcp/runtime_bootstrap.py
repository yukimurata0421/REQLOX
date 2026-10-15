#!/usr/bin/env python3
"""Install a hash-bound release and root-owned runtime contract on a new VM."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request

METADATA = "http://metadata.google.internal/computeMetadata/v1/"
MAXIMUM_ARCHIVE_BYTES = 128 * 1024 * 1024


def request(url, headers=None, maximum=MAXIMUM_ARCHIVE_BYTES):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Download exceeds the deployment size bound")
    return raw


def metadata(key):
    return request(METADATA + key, {"Metadata-Flavor": "Google"}, 65536)


def cloud_get(url, token, maximum=MAXIMUM_ARCHIVE_BYTES):
    return request(url, {"Authorization": "Bearer " + token}, maximum)


def run(*command):
    subprocess.run(command, check=True, timeout=600)


def write(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Managed configuration cannot be a symbolic link")
    path.write_text(text)
    path.chmod(mode)


def extract_release(archive, destination):
    """No links, traversal, unknown files, or unbounded decompression as root."""
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        total = 0
        names = set()
        if not 1 <= len(members) <= 64:
            raise ValueError("Invalid release file count")
        for member in members:
            path = PurePosixPath(member.name)
            allowed = member.name in ("release.json", "requirements.txt") or (
                len(path.parts) == 2 and path.parts[0] == "wheelhouse" and
                re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", path.parts[1]))
            total += member.size
            if (not member.isfile() or not allowed or member.name in names or
                    path.is_absolute() or ".." in path.parts or total > MAXIMUM_ARCHIVE_BYTES):
                raise ValueError("Invalid release archive member")
            names.add(member.name)
        if not {"release.json", "requirements.txt"} <= names:
            raise ValueError("Release metadata is absent")
        for member in members:
            output = destination / member.name
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, output.open("xb") as target:
                shutil.copyfileobj(source, target)
            output.chmod(0o644)
    release = json.loads((destination / "release.json").read_bytes())
    if release.get("schema") != "REQLOX_CLOUD_RELEASE_V1":
        raise ValueError("Invalid release schema")
    expected = {row["path"]: row for row in release["files"]}
    if set(expected) != names - {"release.json"}:
        raise ValueError("Release file inventory differs")
    for relative, row in expected.items():
        raw = (destination / relative).read_bytes()
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Release file hash differs")
    return release


def verify_ready(runtime, attempts=15):
    for _ in range(attempts):
        try:
            value = json.loads(request("http://127.0.0.1:8765/api/deployment", maximum=65536))
            if (value.get("status") == "READY" and value.get("release_sha256") == runtime["release_sha256"]
                    and value.get("host_id") == runtime["host_id"] and value.get("project_id") == runtime["project_id"]
                    and value.get("isolation_probe_passed") is True and value.get("jev_credential_loaded") is True
                    and value.get("paid_model_calls_enabled") is False):
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise ValueError("Runtime readiness could not be verified")


def main():
    if os.getuid() != 0:
        raise ValueError("Bootstrap requires the VM startup identity")
    # Code and root-owned configuration must be readable by the service user.
    # Private state and credentials below have explicit 0700/0600 permissions.
    os.umask(0o022)
    runtime = json.loads(metadata("instance/attributes/reqlox-runtime"))
    if (runtime["project_id"] != metadata("project/project-id").decode() or
            runtime["host_id"] != metadata("instance/name").decode() or
            str(runtime["project_number"]) != metadata("project/numeric-project-id").decode()):
        raise ValueError("Cloud host identity differs from the pinned contract")
    digest = runtime["release_sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Invalid release identity")
    # A drifted contract is never repaired implicitly.
    contract_path = Path("/etc/codex-host-context/host.json")
    contract = {"schema_version": 1, "host_id": runtime["host_id"], "project_id": runtime["project_id"],
                "role": "REQLOX bounded isolated demo", "release_sha256": digest,
                "responsibilities": ["REQLOX UI, private SQLite state, bounded namespace workers"],
                "forbidden": ["stream runtime mutation", "other host mutation", "unscoped paid provider calls"],
                "scope": "Only this dedicated VM and explicitly authorized runtime release",
                "rollback": "Stop reqlox.service; preserve the state disk and secret versions"}
    if contract_path.exists() and json.loads(contract_path.read_bytes()) != contract:
        raise ValueError("Existing host contract differs; a new reviewed release is required")
    token = json.loads(metadata("instance/service-accounts/default/token"))["access_token"]
    bucket = urllib.parse.quote(runtime["artifact_bucket"], safe="")
    obj = urllib.parse.quote(runtime["artifact_object"], safe="")
    raw = cloud_get(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{obj}?alt=media", token)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Release archive hash differs")
    root = Path("/opt/reqlox/releases") / digest
    if not root.exists():
        root.mkdir(parents=True)
        archive = root / "release.tar.gz"
        archive.write_bytes(raw)
        extract_release(archive, root)
    else:
        if hashlib.sha256((root / "release.tar.gz").read_bytes()).hexdigest() != digest:
            raise ValueError("Existing release hash differs")
    if not (root / "site").exists():
        run("/usr/bin/python3", "-m", "venv", str(root / "installer"))
        run(str(root / "installer/bin/python"), "-m", "pip", "install", "--no-index", "--require-hashes",
            "--find-links", str(root / "wheelhouse"), "--target", str(root / "site"), "-r", str(root / "requirements.txt"))
    if not Path("/opt/reqlox/site").exists():
        Path("/opt/reqlox/site").symlink_to(root / "site")
    elif Path("/opt/reqlox/site").resolve() != root / "site":
        raise ValueError("Running release pointer differs")
    try:
        account = pwd.getpwnam("reqlox")
    except KeyError:
        run("useradd", "--system", "--create-home", "--home-dir", "/var/lib/reqlox", "--shell", "/usr/sbin/nologin", "reqlox")
        account = pwd.getpwnam("reqlox")
    device = "/dev/disk/by-id/google-reqlox-state"
    if subprocess.run(["blkid", "-s", "TYPE", "-o", "value", device], capture_output=True).returncode != 0:
        run("mkfs.ext4", "-F", device)
    elif subprocess.check_output(["blkid", "-s", "TYPE", "-o", "value", device], text=True).strip() != "ext4":
        raise ValueError("State disk format differs; no reformat is authorized")
    Path("/mnt/reqlox-state").mkdir(exist_ok=True)
    if not os.path.ismount("/mnt/reqlox-state"):
        run("mount", device, "/mnt/reqlox-state")
    fstab = Path("/etc/fstab")
    line = device + " /mnt/reqlox-state ext4 defaults,nofail,nodev,nosuid 0 2\n"
    if line not in fstab.read_text():
        with fstab.open("a") as stream:
            stream.write(line)
    state = Path("/mnt/reqlox-state/private")
    state.mkdir(mode=0o700, exist_ok=True)
    os.chown(state, account.pw_uid, account.pw_gid)
    state.chmod(0o700)
    secret = runtime["jev_secret_resource"]
    if not re.fullmatch(r"projects/[a-z0-9-]+/secrets/reqlox-jev-api-key/versions/[1-9][0-9]*", secret):
        raise ValueError("An exact secret version is required")
    body = json.loads(cloud_get(f"https://secretmanager.googleapis.com/v1/{secret}:access", token, 65536))
    key = base64.b64decode(body["payload"]["data"], validate=True)
    if not 8 <= len(key) <= 8192 or b"\x00" in key:
        raise ValueError("Invalid secret payload length")
    secret_dir = Path("/run/reqlox-secrets")
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    key_path = secret_dir / "jev-api-key"
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(key)
    write("/etc/reqlox/runtime.json", json.dumps(runtime, sort_keys=True) + "\n")
    write(contract_path, json.dumps(contract, sort_keys=True) + "\n")
    write("/etc/codex-host-context/AGENTS.md", """# Dedicated REQLOX host boundary
<!-- BEGIN MANAGED: codex-host-contract-v1 -->
Default: read-only. Verify root-owned host.json, fresh context, instance identity,
release hash and current explicit authorization before any mutation.
Only this REQLOX VM is in scope. No other hosts, production streaming components,
credential publication, unbounded workers, or unscoped paid provider calls.
On identity, release or contract mismatch stop before mutation.
<!-- END MANAGED: codex-host-contract-v1 -->
""")
    write("/etc/systemd/system/codex-host-context-refresh.service", """[Unit]
Description=Read-only REQLOX host context
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/libexec/reqlox-host-context --config /etc/codex-host-context/host.json --agents /etc/codex-host-context/AGENTS.md --context /var/lib/reqlox-host-context/HOST_CONTEXT.generated.md
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/reqlox-host-context
""")
    Path("/var/lib/reqlox-host-context").mkdir(exist_ok=True)
    write("/etc/systemd/system/codex-host-context-refresh.timer", """[Unit]
Description=Refresh read-only REQLOX host facts
[Timer]
OnBootSec=30s
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
""")
    write("/etc/systemd/system/reqlox.service", """[Unit]
Description=REQLOX bounded experiment UI
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/mnt/reqlox-state
[Service]
User=reqlox
Group=reqlox
UMask=0077
WorkingDirectory=/opt/reqlox
Environment=PYTHONPATH=/opt/reqlox/site
Environment=REQLOX_STATE_DIR=/mnt/reqlox-state/private
Environment=PYTHONDONTWRITEBYTECODE=1
LoadCredential=jev-api-key:/run/reqlox-secrets/jev-api-key
ExecStart=/usr/bin/python3 -m reqlox_demo.cloud_server
Restart=no
TimeoutStopSec=30
KillMode=control-group
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/mnt/reqlox-state/private
MemoryMax=2G
CPUQuota=100%
TasksMax=128
LimitNOFILE=1024
[Install]
WantedBy=multi-user.target
""")
    # nginx accepts only the documented local tunnel origin. It never widens the
    # original loopback server's Host/Origin contract or rewrites browser Origin.
    write("/etc/nginx/nginx.conf", """user www-data;
worker_processes 1;
pid /run/nginx.pid;
events { worker_connections 128; }
http {
  access_log off;
  error_log /var/log/nginx/error.log warn;
  map $http_host $host_ok { default 0; "127.0.0.1:8765" 1; "localhost:8765" 1; }
  map $http_origin $origin_ok { default 0; "" 1; "http://127.0.0.1:8765" 1; "http://localhost:8765" 1; }
  limit_conn_zone $server_name zone=connections:1m;
  limit_req_zone $server_name zone=requests:1m rate=10r/s;
  server {
    listen 8080;
    server_name localhost;
    if ($host_ok = 0) { return 403; }
    if ($origin_ok = 0) { return 403; }
    client_max_body_size 8m;
    client_header_timeout 10s;
    client_body_timeout 30s;
    limit_conn connections 8;
    limit_req zone=requests burst=20 nodelay;
    limit_req_status 429;
    location / {
      proxy_pass http://127.0.0.1:8765;
      proxy_set_header Host 127.0.0.1:8765;
      proxy_set_header X-Forwarded-For "";
      proxy_set_header X-Forwarded-Host "";
      proxy_read_timeout 90s;
      proxy_connect_timeout 3s;
    }
  }
}
""")
    run("nginx", "-t")
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "reqlox.service", "nginx.service", "codex-host-context-refresh.timer")
    run("systemctl", "start", "reqlox.service")
    run("systemctl", "restart", "nginx.service")
    verify_ready(runtime)
    run("systemctl", "start", "codex-host-context-refresh.service", "codex-host-context-refresh.timer")
    run("systemctl", "is-active", "reqlox.service", "nginx.service")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Secret responses, metadata tokens, and private state never enter logs.
        print("REQLOX_BOOTSTRAP_STOPPED", flush=True)
        raise SystemExit(1)
