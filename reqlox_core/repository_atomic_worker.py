"Finite reliability controls and verification."

if __name__ == '__main__' and not __package__:
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))
    __package__ = 'reqlox_core'

import ast
import errno
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from . import repository_atomic_write as contract


class WriteHandle:
    def __init__(self, handle, fail):
        self.handle = handle
        self.fail = fail

    def __enter__(self):
        self.handle.__enter__()
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)

    @property
    def name(self):
        return self.handle.name

    def write(self, data):
        if self.fail:
            raise OSError('OWNED_WRITE_FAILURE')
        return self.handle.write(data)

    def flush(self):
        return self.handle.flush()

    def fileno(self):
        return self.handle.fileno()


def temporary_path(code, destination):
    bound = contract.binding(code)
    rows = ast.parse(code).body[0].body
    assignment = next(n for n in rows if isinstance(n, ast.Assign)
                      and isinstance(n.targets[0], ast.Name) and n.targets[0].id == bound['temporary'])
    expression = ast.Expression(body=assignment.value)
    scope = {'__builtins__': {}, bound['parameters'][0]: destination,
             'os': SimpleNamespace(getpid=lambda: 17)}
    for row in rows[:rows.index(assignment)]:
        if isinstance(row,ast.Assign) and len(row.targets) == 1 and isinstance(row.targets[0],ast.Name) and isinstance(row.value,ast.Constant):
            scope[row.targets[0].id] = row.value.value
    return eval(compile(expression, '<owned-temp-path>', 'eval'),scope)


def case(code, phase, payload=b'new', *, preexisting=False, callable_factory=None):
    bound = contract.binding(code)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        destination = root/'record'
        destination.write_bytes(b'prior')
        unrelated = root/'other.pending'
        unrelated.write_bytes(b'owned elsewhere')
        occupied = None
        if preexisting and bound['kind'] == 'EXCLUSIVE_PATH':
            occupied = temporary_path(code, destination)
            occupied.write_bytes(b'owned elsewhere')
        failing = [phase]
        real_open = Path.open

        def open_file(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            return WriteHandle(handle, failing[0] == 'WRITE') if args and args[0] == 'xb' else handle

        def named_temp(**kwargs):
            return WriteHandle(tempfile.NamedTemporaryFile(**kwargs), failing[0] == 'WRITE')

        def fsync(fd):
            if failing[0] == 'FSYNC':
                raise OSError(errno.EIO, 'OWNED_FSYNC_FAILURE')
            os.fsync(fd)

        def replace(source, target):
            if failing[0] == 'REPLACE':
                raise OSError('OWNED_REPLACE_FAILURE')
            os.replace(source, target)

        scope = {'Path': Path,
            'os': SimpleNamespace(getpid=lambda: 17, fsync=fsync, replace=replace),
            'tempfile': SimpleNamespace(NamedTemporaryFile=named_temp)}
        function = contract.compile_function(code, scope) if callable_factory is None else callable_factory(scope)
        error = None
        with patch.object(Path, 'open', open_file):
            try:
                function(destination, payload)
            except OSError as exc:
                error = type(exc).__name__
        before_retry = destination.read_bytes()
        residue = [p for p in root.iterdir() if p not in (destination, unrelated, occupied)]
        preserved_occupied = occupied is None or occupied.read_bytes() == b'owned elsewhere'
        if occupied is not None:
            expected_error = 'FileExistsError'
        elif phase == 'NORMAL' or preexisting:
            expected_error = None
        else:
            expected_error = 'OSError'
        expected_data = b'prior' if expected_error else payload
        passed = (error == expected_error and before_retry == expected_data and not residue
                  and preserved_occupied and unrelated.read_bytes() == b'owned elsewhere')
        retry_error = None
        retry_pass = None
        if phase != 'NORMAL' and not preexisting:
            failing[0] = 'NORMAL'
            with patch.object(Path, 'open', open_file):
                try:
                    function(destination, payload)
                except OSError as exc:
                    retry_error = type(exc).__name__
            retry_pass = retry_error is None and destination.read_bytes() == payload
            passed = passed and retry_pass
        return dict(phase=phase, preexisting=preexisting, error_class=error,
                    expected_error_class=expected_error, destination_preserved=before_retry == expected_data,
                    residual_temporary_files=len(residue), preexisting_file_preserved=preserved_occupied,
                    unrelated_file_preserved=unrelated.read_bytes() == b'owned elsewhere',
                    retry_pass=retry_pass, retry_error_class=retry_error, contract_pass=passed,
                    actual_instance_invocation=callable_factory is not None)


def observe(plan):
    original = plan['original_code']
    candidate = plan['candidate_code']
    if contract.sha(original) != plan['original_sha256'] or contract.sha(candidate) != plan['candidate_sha256']:
        raise ValueError('ATOMIC_CODE_DRIFT')
    healthy = case(original, 'NORMAL')
    probes = [case(original, phase) for phase in plan['probe_order'][:plan['maximum_probes']]]
    found = any(not row['contract_pass'] for row in probes)
    repaired = []
    regression = []
    if found:
        repaired = [case(candidate, phase) for phase in contract.FAULTS]
        repaired.append(case(candidate, 'NORMAL', preexisting=True))
        regression = [case(candidate, 'NORMAL', payload) for payload in (b'', b'a', b'\0', '\u8a18\u9332'.encode())]
    return dict(healthy=healthy, probes=probes, fault_discovered=found,
                repair_reinjection=repaired, regression=regression,
                repair_reinjection_pass=bool(repaired) and all(r['contract_pass'] for r in repaired + regression),
                actual_candidate_code_executed=found, original_sha256=contract.sha(original),
                candidate_sha256=contract.sha(candidate), generator='DETERMINISTIC_AST_LIFECYCLE_REWRITE',
                forecasts=None, model_calls=0, upstream_modules_imported=False)


def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (134217728, 134217728))
    resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    raw = Path('/run/plan.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != sys.argv[1]:
        raise ValueError('ATOMIC_PLAN_DRIFT')
    attempts = []

    def audit(event, args):
        if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.fork'):
            attempts.append(event)
            raise ValueError('ATOMIC_EXTERNAL_ACTION')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = os.fsdecode(args[0])
            if not path.startswith('/tmp/'):
                attempts.append('OUTSIDE_TMP_OPEN')
                raise ValueError('ATOMIC_EXTERNAL_FILE')

    namespaces = {k: os.readlink('/proc/self/ns/'+k) for k in ('user', 'mnt', 'pid', 'net')}
    sys.addaudithook(audit)
    result = observe(json.loads(raw))
    result.update(plan_sha256=hashlib.sha256(raw).hexdigest(), namespaces=namespaces,
                  external_action_attempts=len(attempts),
                  maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
