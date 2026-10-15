#!/usr/bin/env python3
"""Configure the new isolated Web VM; credentials never enter metadata or argv."""
import base64
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def base_module():
    spec = importlib.util.spec_from_file_location("reqlox_base_bootstrap", "/usr/local/libexec/reqlox-base-bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def secret(base, name, token):
    if not re.fullmatch(r"projects/[a-z0-9-]+/secrets/reqlox-web-(owner-login|tunnel-token)/versions/[1-9][0-9]*", name):
        raise ValueError("Web credentials require exact scoped secret versions")
    value = json.loads(base.cloud_get("https://secretmanager.googleapis.com/v1/" + name + ":access", token, 65536))
    raw = base64.b64decode(value["payload"]["data"], validate=True)
    if not 16 <= len(raw) <= 8192 or b"\x00" in raw:
        raise ValueError("Invalid Web credential payload")
    return raw


def nginx_config(domain, bucket, gateway=False):
    if (not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.[a-z]{2,}", domain)
            or not re.fullmatch(r"[a-z0-9-]+-reqlox-web-assets", bucket)):
        raise ValueError("Unexpected domain or public assets bucket")
    locations = []
    assets = {"/": "index.html", "/study": "study.html", "/knowledge": "knowledge.html",
              "/records": "records.html", "/records.js": "records.js",
              "/workspace.js": "workspace.js", "/workspace.css": "workspace.css",
              "/targets": "targets.html", "/targets.js": "targets.js", "/targets.css": "targets.css",
              "/app.js": "app.js", "/study.js": "study.js", "/knowledge.js": "knowledge.js", "/style.css": "style.css"}
    public = {'/demo/': 'public-demo.html', '/demo/public-demo.html': 'public-demo.html',
              '/demo/public-demo.js': 'public-demo.js', '/demo/public-demo.css': 'public-demo.css',
              '/demo/public-demo.json': 'public-demo.json'}
    assets.update(public)
    for route, filename in assets.items():
        locations.append(f"""    location = {route} {{
      {"auth_basic off;" if route in public else ""}
      limit_except GET {{ deny all; }}
      proxy_pass https://storage.googleapis.com/{bucket}/{filename};
      proxy_ssl_server_name on;
      proxy_ssl_name storage.googleapis.com;
      proxy_ssl_verify on;
      proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
      proxy_set_header Host storage.googleapis.com;
      proxy_set_header Authorization "";
      proxy_set_header Cookie "";
      proxy_set_header X-REQLOX-Token "";
      proxy_hide_header Cache-Control;
      proxy_hide_header X-Goog-Metageneration;
    }}""")
    locations.append("    location = /demo { return 308 /demo/; }\n    location /demo/ { return 404; }")
    return """user www-data;
worker_processes 1;
pid /run/nginx.pid;
events { worker_connections 128; }
http {
  access_log off;
  error_log /var/log/nginx/error.log warn;
  map $http_host $local_host_ok { default 0; "127.0.0.1:8765" 1; "localhost:8765" 1; }
  map $http_origin $local_origin_ok { default 0; "" 1; "http://127.0.0.1:8765" 1; "http://localhost:8765" 1; }
  map $http_host $web_host_ok { default 0; "DOMAIN" 1; }
  map $http_origin $web_origin_ok { default 0; "" 1; "https://DOMAIN" 1; }
  map $http_x_forwarded_proto $web_https { default 0; "https" 1; }
  limit_conn_zone $server_name zone=connections:1m;
  limit_req_zone $server_name zone=requests:1m rate=10r/s;
  server {
    listen 8080;
    server_name localhost;
    if ($local_host_ok = 0) { return 403; }
    if ($local_origin_ok = 0) { return 403; }
    client_max_body_size 8m;
    limit_conn connections 16;
    limit_req zone=requests burst=20 nodelay;
    limit_req_status 429;
    location / {
      proxy_pass http://127.0.0.1:8765;
      proxy_set_header Host 127.0.0.1:8765;
      proxy_set_header Authorization "";
      proxy_set_header X-Forwarded-For "";
      proxy_set_header X-Forwarded-Host "";
      proxy_read_timeout 90s;
    }
  }
  server {
    listen 127.0.0.1:8081;
    server_name DOMAIN;
    if ($web_host_ok = 0) { return 403; }
    if ($web_origin_ok = 0) { return 403; }
    if ($web_https = 0) { return 308 https://DOMAIN$request_uri; }
    auth_basic "REQLOX owner";
    auth_basic_user_file /run/reqlox-secrets/web.htpasswd;
    client_max_body_size 8m;
    client_header_timeout 10s;
    client_body_timeout 30s;
    limit_conn connections 16;
    limit_req zone=requests burst=20 nodelay;
    limit_req_status 429;
    add_header Cache-Control "no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Strict-Transport-Security "max-age=86400" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'" always;
ASSETS
    location /api/ {
      proxy_pass http://127.0.0.1:8765;
      proxy_set_header Host 127.0.0.1:8765;
      proxy_set_header Authorization "";
      proxy_set_header Cookie "";
      proxy_set_header X-Forwarded-For "";
      proxy_set_header X-Forwarded-Host "";
      proxy_read_timeout 90s;
      proxy_connect_timeout 3s;
    }
    location / { return 404; }
  }
}
""".replace("DOMAIN", domain).replace("ASSETS", "\n".join(locations)).replace(
        "listen 127.0.0.1:8081;", "listen 8081;" if gateway else "listen 127.0.0.1:8081;")


def verify_web_once(base, runtime, password):
    domain = urllib.parse.urlsplit(runtime["web"]["public_origin"]).hostname
    auth = "Basic " + base64.b64encode(b"reqlox:" + password).decode()
    try:
        base.request("http://127.0.0.1:8081/api/config", {"Host": domain, "X-Forwarded-Proto": "https"}, 65536)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise ValueError("Anonymous API requests must require authentication") from None
    else:
        raise ValueError("Anonymous API access is forbidden")
    for route in ("/", "/study", "/knowledge", "/app.js", "/study.js", "/knowledge.js", "/style.css"):
        body = base.request("http://127.0.0.1:8081" + route, {"Host": domain, "Authorization": auth, "X-Forwarded-Proto": "https"}, 1024 * 1024)
        if not body or (route in ("/", "/study", "/knowledge") and b"Inputs stay local" in body):
            raise ValueError("GCS Web assets did not verify")
    value = json.loads(base.request("http://127.0.0.1:8081/api/deployment", {"Host": domain, "Authorization": auth, "X-Forwarded-Proto": "https"}, 65536))
    if value.get("status") != "READY" or value.get("release_sha256") != runtime["release_sha256"]:
        raise ValueError("Web runtime did not verify")


def verify_web(base, runtime, password):
    # nginx reload returns before its new workers bind the new listener.
    # Only a connection failure is transient; identity/authentication errors stop.
    for attempt in range(15):
        try:
            return verify_web_once(base, runtime, password)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if attempt == 14:
                raise ValueError("Web listener did not become ready") from None
            time.sleep(1)


def main():
    base = base_module()
    base.main()
    runtime = json.loads(base.metadata("instance/attributes/reqlox-runtime"))
    if runtime["host_id"] != "reqlox-web" or runtime["access"] != "CLOUDFLARE_OWNER_LOGIN":
        raise ValueError("Only the new isolated Web VM is authorized")
    web = runtime["web"]
    token = json.loads(base.metadata("instance/service-accounts/default/token"))["access_token"]
    password = secret(base, web["owner_secret_resource"], token)
    if not re.fullmatch(rb"[A-Za-z0-9_-]{24,128}", password):
        raise ValueError("Owner password must be a generated URL-safe secret")
    gateway = web["frontend_mode"] == "CLOUD_RUN_GATEWAY"
    secret_root = Path("/run/reqlox-secrets")
    hashed = subprocess.run(["openssl", "passwd", "-6", "-stdin"], input=password + b"\n",
                            capture_output=True, check=True, timeout=10).stdout.strip()
    if not hashed.startswith(b"$6$"):
        raise ValueError("Password hashing did not verify")
    htpasswd = secret_root / "web.htpasswd"
    htpasswd.write_bytes(b"reqlox:" + hashed + b"\n")
    os.chown(htpasswd, 0, grp.getgrnam("www-data").gr_gid)
    htpasswd.chmod(0o640)
    # nginx workers may traverse this directory but cannot read the raw tokens.
    secret_root.chmod(0o711)
    domain = urllib.parse.urlsplit(web["public_origin"]).hostname
    base.write("/etc/nginx/nginx.conf", nginx_config(domain, web["assets_bucket"], gateway))
    base.run("nginx", "-t")
    base.run("systemctl", "reload", "nginx.service")
    verify_web(base, runtime, password)
    if gateway:
        base.run("systemctl", "start", "codex-host-context-refresh.service")
        print("REQLOX_WEB_READY")
        return
    connector = secret(base, web["tunnel_secret_resource"], token)
    binary = base.request(web["cloudflared_url"])
    if hashlib.sha256(binary).hexdigest() != web["cloudflared_sha256"]:
        raise ValueError("Official cloudflared binary checksum differs")
    Path("/usr/local/bin/cloudflared").write_bytes(binary)
    Path("/usr/local/bin/cloudflared").chmod(0o755)
    (secret_root / "tunnel-token").write_bytes(connector)
    (secret_root / "tunnel-token").chmod(0o600)
    base.write("/etc/systemd/system/reqlox-tunnel.service", """[Unit]
Description=REQLOX dedicated HTTPS connector
After=network-online.target nginx.service reqlox.service
Requires=nginx.service reqlox.service
StartLimitIntervalSec=600
StartLimitBurst=3
[Service]
DynamicUser=yes
LoadCredential=tunnel-token:/run/reqlox-secrets/tunnel-token
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --protocol http2 run --token-file %d/tunnel-token
Restart=on-failure
RestartSec=30
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
MemoryMax=256M
CPUQuota=20%
TasksMax=128
LimitNOFILE=1024
[Install]
WantedBy=multi-user.target
""")
    base.run("systemctl", "daemon-reload")
    verify_web(base, runtime, password)
    base.run("systemctl", "enable", "--now", "reqlox-tunnel.service")
    base.run("systemctl", "start", "codex-host-context-refresh.service")
    print("REQLOX_WEB_READY")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("REQLOX_WEB_BOOTSTRAP_STOPPED", flush=True)
        raise SystemExit(1)
