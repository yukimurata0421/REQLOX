"""Whole-module composed caller, run only inside the bounded Target sandbox."""
import asyncio
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import resource
import sys
from unittest.mock import patch

FAULTS = ('API_WRITE_ERROR', 'API_FSYNC_ERROR', 'API_REPLACE_ERROR',
          'OPERATION_EXCEPTION_BEFORE_PERSIST', 'OPERATION_TASK_CANCEL_BEFORE_PERSIST')
PAYLOADS = (b'ordinary bytes', b'', b'\x00\xff\x00', '日本語'.encode())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class InjectedError(OSError):
    pass


class FailedWrite:
    def __init__(self, stream, hit):
        self.stream, self.hit = stream, hit

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, data):
        self.hit.append('API_WRITE_ERROR')
        raise InjectedError('owned write boundary')

    def __getattr__(self, name):
        return getattr(self.stream, name)


async def composed_case(api, worker, constructor, root, fault, payload, *, preexisting=False):
    """Dependency faults affect only this invocation; no Target function extraction."""
    root.mkdir()
    destination = root / 'destination'
    destination.write_bytes(b'prior destination')
    unrelated = root / 'unrelated.tmp'
    unrelated.write_bytes(b'unrelated')
    pending = destination.with_name(destination.name + f'.tmp-{os.getpid()}')
    if preexisting:
        pending.write_bytes(b'prior pending owner')
    lock = asyncio.Lock()
    hit, scratch_paths, acquisitions = [], [], []
    injecting = True
    real_open, real_fsync, real_replace = Path.open, os.fsync, os.replace
    active_fd = []

    def open_hook(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if path == pending and args and args[0] == 'xb':
            active_fd[:] = [stream.fileno()]
            if fault == 'API_WRITE_ERROR':
                return FailedWrite(stream, hit)
        return stream

    def fsync_hook(fd):
        if fault == 'API_FSYNC_ERROR' and active_fd == [fd]:
            hit.append(fault)
            raise InjectedError('owned fsync boundary')
        return real_fsync(fd)

    def replace_hook(source, target, *args, **kwargs):
        if fault == 'API_REPLACE_ERROR' and source == pending and target == destination:
            hit.append(fault)
            raise InjectedError('owned replace boundary')
        return real_replace(source, target, *args, **kwargs)

    async def operation():
        acquisitions.append(lock.locked())
        with constructor() as scratch:
            scratch_paths.append(scratch)
            scratch.write_bytes(payload)
            data = scratch.read_bytes()
            require(data == payload, 'SCRATCH_BYTES_DRIFT')
            if injecting and fault == 'OPERATION_EXCEPTION_BEFORE_PERSIST':
                hit.append(fault)
                raise InjectedError('owned operation boundary')
            if injecting and fault == 'OPERATION_TASK_CANCEL_BEFORE_PERSIST':
                hit.append(fault)
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            api.persist(destination, data)

    error = None
    with patch.object(Path, 'open', open_hook), patch.object(os, 'fsync', fsync_hook), \
            patch.object(os, 'replace', replace_hook):
        try:
            await asyncio.create_task(worker.use_resource(lock, operation))
        except (InjectedError, FileExistsError, asyncio.CancelledError) as exc:
            error = type(exc).__name__
    expected = ('FileExistsError' if preexisting else 'CancelledError'
                if fault == 'OPERATION_TASK_CANCEL_BEFORE_PERSIST' else 'InjectedError' if fault else None)
    initial = dict(injection_reached=hit == ([fault] if fault else []),
                   acquired=acquisitions == [True], exception_preserved=error == expected,
                   exception_type=error, destination_preserved=destination.read_bytes() ==
                   (b'prior destination' if fault or preexisting else payload),
                   lock_released=not lock.locked(), scratch_removed=bool(scratch_paths)
                   and all(not path.exists() for path in scratch_paths),
                   owned_pending_removed=not pending.exists() if not preexisting else
                   pending.read_bytes() == b'prior pending owner',
                   unrelated_preserved=unrelated.read_bytes() == b'unrelated')
    # Preserve a prior owner's pending file; following call uses a distinct destination.
    if preexisting:
        destination = root / 'following-destination'
    injecting = False
    following_error = None
    try:
        await asyncio.wait_for(worker.use_resource(lock, operation), timeout=0.04)
    except (FileExistsError, asyncio.TimeoutError) as exc:
        following_error = type(exc).__name__
    initial['following_normal_error'] = following_error
    initial['following_normal_pass'] = (following_error is None and not lock.locked()
        and destination.read_bytes() == payload and all(not p.exists() for p in scratch_paths))
    keys = ('injection_reached', 'acquired', 'exception_preserved', 'destination_preserved',
            'lock_released', 'scratch_removed', 'owned_pending_removed', 'unrelated_preserved',
            'following_normal_pass')
    initial.update(case=fault or ('PREEXISTING_PENDING' if preexisting else 'NORMAL'),
                   payload_sha256=hashlib.sha256(payload).hexdigest(),
                   passed=all(initial[key] is True for key in keys))
    return initial


async def exercise(api, worker, constructor, root):
    rows = []
    for index, fault in enumerate(FAULTS):
        rows.append(await composed_case(api, worker, constructor, root / f'fault-{index}', fault, PAYLOADS[0]))
    for index, payload in enumerate(PAYLOADS):
        rows.append(await composed_case(api, worker, constructor, root / f'normal-{index}', None, payload))
    rows.append(await composed_case(api, worker, constructor, root / 'prior-owner', None,
                                    PAYLOADS[0], preexisting=True))
    return rows


def run(plan_path, expected_digest):
    plan = json.loads(Path(plan_path).read_text())
    require(digest(plan) == expected_digest, 'INTEGRATION_PLAN_DRIFT')
    for limit, value in ((resource.RLIMIT_CPU, 2), (resource.RLIMIT_AS, 134217728),
                         (resource.RLIMIT_FSIZE, 131072), (resource.RLIMIT_CORE, 0),
                         (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_NPROC, 1)):
        resource.setrlimit(limit, (value, value))
    os.nice(10)
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    boundary = dict(uid=os.getuid(), effective_capabilities=int(status['CapEff'].strip(), 16),
                    home_visible=Path('/home').exists() or Path('/root').exists(),
                    cpu=list(resource.getrlimit(resource.RLIMIT_CPU)),
                    memory=list(resource.getrlimit(resource.RLIMIT_AS)),
                    output=list(resource.getrlimit(resource.RLIMIT_FSIZE)),
                    core=list(resource.getrlimit(resource.RLIMIT_CORE)))
    require(boundary['uid'] > 0 and boundary['effective_capabilities'] == 0
            and not boundary['home_visible'] and boundary['cpu'] == [2, 2]
            and boundary['memory'] == [134217728, 134217728]
            and boundary['output'] == [131072, 131072] and boundary['core'] == [0, 0],
            'INTEGRATION_ISOLATION')
    namespaces = {k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net')}
    require(set(namespaces) == set(plan['parent_namespaces'])
            and all(namespaces[k] != plan['parent_namespaces'][k] for k in namespaces),
            'INTEGRATION_NAMESPACE_BEFORE_TARGET_IMPORT')
    for name, sha in plan['sources'].items():
        require(hashlib.sha256((Path('/target') / name).read_bytes()).hexdigest() == sha,
                'INTEGRATION_SOURCE_DRIFT')
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() ==
            plan['method']['integration_worker.py'], 'INTEGRATION_WORKER_DRIFT')
    attempts = []

    def audit(event, args):
        # asyncio's local socketpair is internal; all network activity is denied.
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto',
                     'subprocess.Popen', 'os.system', 'os.exec', 'os.fork', 'os.posix_spawn'):
            attempts.append(event)
            raise RuntimeError('INTEGRATION_EXTERNAL_ACTION_DENIED')

    sys.addaudithook(audit)
    sys.path[:0] = ['/target', '/target/temppath']
    api = importlib.import_module('api.storage')
    worker = importlib.import_module('worker.resource')
    constructor = importlib.import_module('temppath').TemporaryPathContext
    origins = dict(api=str(Path(inspect.getsourcefile(api.persist))),
                   worker=str(Path(inspect.getsourcefile(worker.use_resource))),
                   temppath=str(Path(inspect.getsourcefile(constructor))))
    require(origins == dict(api='/target/api/storage.py', worker='/target/worker/resource.py',
                            temppath='/target/temppath/temppath/temppath.py'), 'INTEGRATION_IMPORT_ORIGIN')
    root = Path('/tmp/integration'); root.mkdir()
    rows = asyncio.run(exercise(api, worker, constructor, root))
    result = dict(schema='reqlox.module-integration-observation.v1', plan_sha256=expected_digest,
                  scenario_sha256=plan['scenario_sha256'], sources=plan['sources'], method=plan['method'],
                  origins=origins, execution_boundary=boundary,
                  namespaces=namespaces,
                  rows=rows, external_action_attempts=attempts, module_imported=True,
                  held_atomic_bindings=4, temppath_repair_performed=False)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
