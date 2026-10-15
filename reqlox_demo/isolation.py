"Isolate privately owned workers in four bounded namespaces."

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

from .contracts import encode

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["qualification_adapters_v2.py", "qualification_context_protocol.py", "qualification_context_sync.py",
         "qualification_context_worker.py", "qualification_context_sync_worker.py",
         "qualification_context_gold.py", "qualification_context_oracle_log.py"]


def run(directory, entry, payload, mounts=()):
    directory = Path(directory)
    if directory.exists() or entry not in ["gold", "py-cachify", "readerwriterlock", "candidate", "portable"] or len(mounts) > 2:
        raise ValueError("Check the isolation scope.")
    if not shutil.which("bwrap") or not Path(sys.executable).resolve().is_relative_to(Path("/usr")):
        raise ValueError("This experiment requires Linux, bubblewrap, and Python under /usr.")
    directory.mkdir(parents=True, mode=0o700)
    plan = directory / "plan.json"
    raw = encode(payload)
    plan.write_bytes(raw)
    plan.chmod(0o600)
    digest = hashlib.sha256(raw).hexdigest()
    parent = {name: os.readlink("/proc/self/ns/" + name) for name in ["user", "mnt", "pid", "net"]}
    command = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv", "--cap-drop", "ALL",
               "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
               "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev", "--chdir", "/tmp",
               "--ro-bind", str(plan), "/run/plan.json"]
    refs = []
    for name in TOOLS:
        source = ROOT / "reqlox_core" / name
        if source.is_symlink():
            raise ValueError("Worker sources cannot contain links.")
        refs.append({"path": "reqlox_core/" + name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        command += ["--ro-bind", str(source), "/app/reqlox_core/" + name]
    source = ROOT / "reqlox_demo" / "oracle_worker.py"
    refs.append({"path": "reqlox_demo/oracle_worker.py", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    command += ["--ro-bind", str(source), "/app/reqlox_demo/oracle_worker.py"]
    if entry in ["candidate", "portable"]:
        names = ["repair_contract.py", "repair_worker.py"] if entry == "candidate" else ["repair_contract.py", "portable.py", "portable_worker.py"]
        for name in names:
            source = ROOT / "reqlox_demo" / name
            if source.is_symlink():
                raise ValueError("Worker sources cannot contain links.")
            refs.append({"path": "reqlox_demo/" + name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
            command += ["--ro-bind", str(source), "/app/reqlox_demo/" + name]
    for actual, virtual in mounts:
        actual = Path(actual).resolve()
        if not actual.is_dir() or virtual not in ["/target/native", "/target/dependency"]:
            raise ValueError("The target mount exceeds the supported bounds.")
        command += ["--ro-bind", str(actual), virtual]
    worker = {"gold": "/app/reqlox_demo/oracle_worker.py", "py-cachify": "/app/reqlox_core/qualification_context_worker.py",
              "readerwriterlock": "/app/reqlox_core/qualification_context_sync_worker.py",
              "candidate": "/app/reqlox_demo/repair_worker.py",
              "portable": "/app/reqlox_demo/portable_worker.py"}[entry]
    command += [str(Path(sys.executable).resolve()), "-I", "-S", "-B", worker, "/run/plan.json", digest]
    value = None
    error = None
    code = None
    with (directory / "observed.json").open("xb") as out, (directory / "stderr.log").open("xb") as err:
        os.fchmod(out.fileno(), 0o600)
        os.fchmod(err.fileno(), 0o600)
        process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
        try:
            code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            error = "WALL_LIMIT"
        if error is None:
            try:
                if code != 0 or (directory / "observed.json").stat().st_size > 1048576:
                    raise ValueError("CHILD_FAILED")
                value = json.loads((directory / "observed.json").read_bytes())
                if value["plan_sha256"] != digest or not all(value["namespaces"][k] != v for k, v in parent.items()):
                    raise ValueError("ISOLATION_OR_PLAN_DRIFT")
                if value.get("network_attempts", 0) != 0:
                    raise ValueError("NETWORK_ATTEMPT")
            except (ValueError, KeyError):
                value = None
                error = "CHILD_OR_BINDING_FAILED"
    receipt = {"status": "COMPLETE" if value is not None else "EXECUTION_FAILED", "error": error,
               "returncode": code, "plan_sha256": digest, "worker_sources": refs,
               "runtime_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
               "network_isolated": value is not None, "namespace_isolated": value is not None,
               "credentials_or_corpus_mounted": False, "automatic_retry": False}
    (directory / "receipt.json").write_bytes(encode(receipt))
    (directory / "receipt.json").chmod(0o600)
    if value is None:
        raise ValueError("Isolation could not be verified. The run was stopped with an unknown outcome.")
    return value, receipt
