"Serve a local browser interface for finite experiments."

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from . import contracts, targets, model as assessments, repair
from .engine import Demo, public_view
from .target_ui import TargetLab, OPERATIONS as TARGET_OPERATIONS
from .study_ui import StudyLab, MAXIMUM_REQUEST_BYTES, OPERATIONS, public_error
from .knowledge_ui import KnowledgeLab, OPERATIONS as KNOWLEDGE_OPERATIONS

from .workspace import Workspace, OPERATIONS as WORKSPACE_OPERATIONS, policy, check_execution

ASSETS = Path(__file__).parent / "static"


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, engine, target_manifests=(), allow_target_native=False, integration_runs=(), *, allow_study_native=False):
        self.engine = engine
        self.token = secrets.token_urlsafe(24)
        self.run_lock = threading.Lock()
        self.target_lab = TargetLab(target_manifests, False, integration_runs)
        self.study = StudyLab(engine.cache, self.run_lock, allow_native=False)
        self.knowledge = KnowledgeLab(engine.cache)
        self.workspace = Workspace(engine.cache)
        if not integration_runs:
            from .integration_ui import summarize_public
            self.target_lab.public_integration_results = (summarize_public(json.loads((Path(__file__).resolve().parent / "data/copied-module-integration-summary.json").read_bytes())),)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "REQLOX-demo"
    sys_version = ""

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(90)

    def valid_host(self):
        return self.headers.get("Host") in [f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"]

    def valid_origin(self):
        allowed = getattr(self.server, "allowed_origins", [
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}"])
        origin = self.headers.get("Origin")
        return origin is None or origin in allowed

    def send(self, value, status=200, kind="application/json; charset=utf-8"):
        raw = value if isinstance(value, bytes) else contracts.encode(value)
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self.valid_host():
            return self.send({"error": "Only the local origin is supported."}, 403)
        path = urlsplit(self.path).path
        from .public_demo import asset
        if path == "/demo":
            self.send_response(308)
            self.send_header("Location", "/demo/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        public_asset = asset(path)
        if public_asset is not None:
            raw, kind = public_asset
            return self.send(raw, kind=kind)
        if path == "/api/workspace/config":
            return self.send(self.server.workspace.configuration(self.server.token))
        static = {"/records": ("records.html", "text/html; charset=utf-8"), "/records.js": ("records.js", "text/javascript; charset=utf-8"), "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"), "/": ("index.html", "text/html; charset=utf-8"), "/targets.js": ("targets.js", "text/javascript; charset=utf-8"), "/targets.css": ("targets.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/study": ("study.html", "text/html; charset=utf-8"), "/study.js": ("study.js", "text/javascript; charset=utf-8"),
                  "/workspace.css": ("workspace.css", "text/css; charset=utf-8"),
                  "/knowledge": ("knowledge.html", "text/html; charset=utf-8"), "/knowledge.js": ("knowledge.js", "text/javascript; charset=utf-8")}
        if path in static:
            filename, kind = static[path]
            return self.send((ASSETS / filename).read_bytes(), kind=kind)
        if path == "/api/targets/config":
            return self.send({**self.server.target_lab.configuration(self.server.token), "execution_policy": policy(), "native_enabled": False, })
        if path == "/targets":
            return self.send((ASSETS / "targets.html").read_bytes(), kind="text/html; charset=utf-8")
        if path == "/api/config":
            return self.send({"token": self.server.token, "samples": contracts.SAMPLES,
                              "targets": [{"name": k, "version": v["version"], "role": "KNOWN_DEMO_CONTROL"} for k, v in targets.PACKAGES.items() if k != "typing-extensions"],
                              "execution_policy": policy(), "native_execution_enabled": False,
                              "live_model_available": False,
                              "live_repair_available": False,
                              "recorded_model_available": assessments.RECORDS.is_file(),
                              "recorded_repair_available": repair.RECORDS.is_file(),
                              "repaired_caller": contracts.REPAIRED_CALLER})
        if path == "/api/study/config":
            return self.send({**self.server.study.configuration(self.server.token), "execution_policy": policy(), "native_execution_enabled": False, })
        if path == "/api/knowledge/config":
            return self.send({**self.server.knowledge.configuration(self.server.token), "execution_policy": policy(), })
        if path.startswith('/api/study/job/'):
            if self.headers.get('X-REQLOX-Token') != self.server.token:
                return self.send({'error': 'Use the same local page.'}, 403)
            try:
                return self.send(self.server.study.job(path.removeprefix('/api/study/job/')))
            except ValueError:
                return self.send({'error': 'This job is unavailable.'}, 404)
        return self.send({"error": "Not found."}, 404)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-REQLOX-Token") != self.server.token or not self.valid_origin():
            return self.send({"error": "Run this request from the same local page."}, 403)
        path = urlsplit(self.path).path
        operation = path.removeprefix('/api/study/') if path.startswith('/api/study/') else None
        target_operation = path.removeprefix("/api/targets/") if path.startswith("/api/targets/") else None
        knowledge_operation = path.removeprefix('/api/knowledge/') if path.startswith('/api/knowledge/') else None
        workspace_operation = path.removeprefix('/api/workspace/') if path.startswith('/api/workspace/') else None
        if path != "/api/run" and operation not in OPERATIONS and knowledge_operation not in KNOWLEDGE_OPERATIONS and target_operation not in TARGET_OPERATIONS and workspace_operation not in WORKSPACE_OPERATIONS:
            return self.send({"error": "Not found."}, 404)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.send({"error": "Check the JSON input."}, 400)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            bound = MAXIMUM_REQUEST_BYTES if operation == 'capsule' else 1024 * 1024 if operation or knowledge_operation or target_operation or workspace_operation else 65536
            if not 1 <= length <= bound:
                # Drain only a small overrun so the client can receive the JSON
                # rejection while still writing its request. Large bodies close
                # immediately without allocating or reading unbounded input.
                if bound < length <= bound + 16384:
                    self.rfile.read(length)
                raise ValueError("The input exceeds the size limit.")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete input.')
            request = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON.')))
        except (ValueError, UnicodeError):
            return self.send({"error": "Check the JSON input and size."}, 400)
        try:
            check_execution(path)
        except ValueError:
            return self.send({'error': 'UI_EXECUTION_DISABLED', 'execution_policy': policy()}, 403)
        if not self.server.run_lock.acquire(blocking=False):
            return self.send({"error": "Another run is active. Wait for completion."}, 409)
        status = 200
        try:
            if workspace_operation:
                response = self.server.workspace.dispatch(workspace_operation, request)
            elif target_operation:
                response = self.server.target_lab.dispatch(target_operation, request)
            elif knowledge_operation:
                response = self.server.knowledge.dispatch(knowledge_operation, request)
            elif operation:
                response = self.server.study.dispatch(operation, request)
            else:
                result = self.server.engine.run(request)
                response = {"result": result, "download": public_view(result)}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            response, status = {"error": public_error(exc) if operation or knowledge_operation or workspace_operation else str(exc)}, 400
        except Exception:
            response, status = {"error": "The operation could not be verified and was stopped."}, 500
        finally:
            self.server.run_lock.release()
        # Finish the operation before exposing its response to a following request.
        return self.send(response, status)
