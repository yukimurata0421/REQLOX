"""Authenticated-tunnel deployment of the existing loopback UI."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import re
import socket
import urllib.request

from .engine import Demo
from .server import Handler, Server


def isolation_probe():
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
               "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
               "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "/usr/bin/true"]
    try:
        return subprocess.run(command, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def load_runtime(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError("Deployment configuration must be root-owned and read-only")
    value = json.loads(path.read_bytes())
    if (value.get("access") not in ("IAP_TCP_ONLY", "CLOUDFLARE_OWNER_LOGIN") or value.get("paid_model_calls_enabled") is not False
            or value.get("application_port") != 8765 or len(value.get("release_sha256", "")) != 64):
        raise ValueError("Deployment contract does not match the bounded loopback server")
    if value["access"] == "CLOUDFLARE_OWNER_LOGIN":
        web = value.get("web", {})
        if (not re.fullmatch(r"https://[a-z0-9-]+\.[a-z0-9.-]+", web.get("public_origin", ""))
                or web.get("authentication") != "OWNER_BASIC_AUTH"
                or not re.fullmatch(r"projects/[a-z0-9-]+/secrets/reqlox-web-owner-login/versions/[1-9][0-9]*", web.get("owner_secret_resource", ""))):
            raise ValueError("The HTTPS owner access contract is absent or invalid")
    return value


def cloud_page(raw):
    raw = raw.replace(b"Inputs stay local", b"Inputs stay on this VM")
    if b'href="/targets"' not in raw:
        raw = raw.replace(b"</nav>", b'<a href="/targets">Targets</a></nav>', 1)
    return raw.replace(b"<body>", b'<body><p class="cloud-location">This interface runs on your Google Cloud VM. Uploaded inputs and private artifacts are stored on that VM.</p>', 1)


def host_evidence():
    """Expose only fixed read-only host facts through the authenticated UI."""
    unit = Path("/etc/systemd/system/codex-host-context-refresh.service").read_text()
    paths = {"contract": "/etc/codex-host-context/host.json",
             "instructions": "/etc/codex-host-context/AGENTS.md",
             "context": "/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md"}
    evidence = {"collector_unit": unit}
    for key, name in paths.items():
        path = Path(name)
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError("Host evidence must retain root ownership")
        evidence[key] = path.read_text()
    request = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/id",
                                     headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=3) as response:
        evidence["physical_instance_id"] = response.read(128).decode().strip()
    evidence["hostname"] = socket.gethostname()
    evidence["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    evidence["observed_jst"] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
    return evidence


class CloudHandler(Handler):
    def send(self, value, status=200, kind="application/json; charset=utf-8"):
        if kind.startswith("text/html") and isinstance(value, bytes):
            value = cloud_page(value)
        return super().send(value, status, kind)

    def do_GET(self):
        if self.path == "/api/host-context":
            if not self.valid_host() or self.headers.get("X-REQLOX-Token") != self.server.token:
                return self.send({"error": "Use the authenticated owner session."}, 403)
            try:
                return self.send(host_evidence())
            except (OSError, ValueError):
                return self.send({"error": "Host evidence is unavailable."}, 503)
        if self.path == "/api/deployment":
            if not self.valid_host():
                return self.send({"error": "Use the configured authenticated tunnel."}, 403)
            return self.send(self.server.deployment)
        return super().do_GET()


def main():
    runtime = load_runtime("/etc/reqlox/runtime.json")
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent")) / "jev-api-key"
    if not credentials.is_file() or credentials.stat().st_size == 0:
        raise ValueError("The pinned Jev credential was not loaded")
    isolated = isolation_probe()
    if not isolated:
        raise ValueError("The namespace isolation probe failed; the UI cannot start")
    from reqlox import _runtime
    _runtime()
    from reqlox_core.reqlox_paths import ensure_state
    state = ensure_state()
    server = Server(8765, Demo(state / "demo"))
    # Only the reviewed aggregate ships; no copied Target or raw receipt is loaded.
    from .integration_ui import summarize_public
    summary = Path(__file__).parent / 'data/copied-module-integration-summary.json'
    server.target_lab.public_integration_results = (summarize_public(json.loads(summary.read_bytes())),)
    if runtime["access"] == "CLOUDFLARE_OWNER_LOGIN":
        server.allowed_origins = ["http://127.0.0.1:8765", "http://localhost:8765",
                                  runtime["web"]["public_origin"]]
    server.RequestHandlerClass = CloudHandler
    server.deployment = {
        "status": "READY", "release_sha256": runtime["release_sha256"],
        "host_id": runtime["host_id"], "project_id": runtime["project_id"],
        "process_started_jst": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
        "isolation_probe_passed": isolated, "jev_credential_loaded": True,
        "jev_secret_version": runtime["jev_secret_resource"].rsplit("/", 1)[-1],
        "paid_model_calls_enabled": False, "database_backend": "SQLITE",
        "runtime_config_sha256": hashlib.sha256(Path("/etc/reqlox/runtime.json").read_bytes()).hexdigest(),
    }
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
