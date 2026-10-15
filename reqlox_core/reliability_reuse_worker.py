"""Finite reliability controls and verification."""
import ast
import asyncio
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import reliability_reuse as reuse
import repository_atomic_worker as atomic_worker

def compile_site(code, scope):
    node = ast.parse(code).body[0]
    ns = dict(scope, __builtins__={})
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<bound-owned-function>', 'exec'), ns)
    return ns[node.name]

async def async_case(code, fault, returns_result=None):
    lock = asyncio.Lock()
    executions = []
    token = object()

    async def work():
        executions.append(lock.locked())
        if fault == 'EXCEPTION':
            raise RuntimeError('OWNED_WORK_FAILURE')
        if fault == 'TASK_CANCEL':
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        return token
    fn = compile_site(code, {'Exception': Exception, 'BaseException': BaseException})
    if returns_result is None:
        returns_result = reuse.async_binding(ast.parse(code).body[0])['returns_result']
    error = None
    returned = None
    prior_owner_preserved = True
    waiting_observed = False
    holder = None
    resume = None
    if fault == 'ACQUIRE_CANCEL':
        entered = asyncio.Event()
        resume = asyncio.Event()

        async def owner():
            await lock.acquire()
            entered.set()
            try:
                await resume.wait()
            finally:
                if lock.locked():
                    lock.release()
        holder = asyncio.create_task(owner())
        await entered.wait()
    try:
        task = asyncio.create_task(fn(lock, work))
        if fault == 'ACQUIRE_CANCEL':
            await asyncio.sleep(0)
            waiting_observed = not task.done() and executions == []
            task.cancel()
        returned = await task
    except (RuntimeError, asyncio.CancelledError) as exc:
        error = type(exc).__name__
    finally:
        if holder is not None:
            prior_owner_preserved = lock.locked() and executions == []
            resume.set()
            await holder
    released = not lock.locked()

    async def contender():
        async with lock:
            return True
    reacquired = False
    try:
        reacquired = await asyncio.wait_for(asyncio.create_task(contender()), 0.02)
    except asyncio.TimeoutError:
        pass
    expected = {'NORMAL': None, 'EXCEPTION': 'RuntimeError', 'TASK_CANCEL': 'CancelledError', 'ACQUIRE_CANCEL': 'CancelledError'}[fault]
    work_held = executions == ([] if fault == 'ACQUIRE_CANCEL' else [True])
    result_preserved = returned is (token if returns_result else None) if fault == 'NORMAL' else returned is None
    passed = work_held and released and reacquired and (error == expected) and prior_owner_preserved and result_preserved
    if fault == 'ACQUIRE_CANCEL':
        passed = passed and waiting_observed
    return dict(fault=fault, contract_pass=passed, work_held_resource=work_held, resource_released=released, different_task_reacquired=reacquired, error_class=error, expected_error_class=expected, prior_owner_lock_preserved=prior_owner_preserved, acquisition_wait_observed=waiting_observed, work_result_preserved=result_preserved, returns_work_result=returns_result)

def clock_case(code, fault, ttl, cache_type):
    schedules = {'NORMAL': [(100, 0), (100 + ttl / 2, ttl / 2), (100 + ttl, ttl)], 'BACKWARD': [(100, 0), (99, ttl)], 'FORWARD': [(0, 0), (100, 1 if ttl > 1 else ttl / 2)], 'STATIONARY': [(10, 0), (10, ttl)], 'OFFSET': [(-100, 0), (-101, ttl + 1)], 'BOUNDARY': [(100, 0), (99, ttl - 0.25 if ttl > 0.25 else ttl / 2), (98, ttl)]}
    fn = compile_site(code, {'cachetools': SimpleNamespace(TTLCache=cache_type)})
    clocks = [0, 0]
    cache = fn(lambda: clocks[0], lambda: clocks[1])
    actual = []
    expected = []
    for i, (wall, elapsed) in enumerate(schedules[fault]):
        clocks[:] = [wall, elapsed]
        if i == 0:
            cache['record'] = 11
        else:
            actual.append(cache.get('record'))
            expected.append(11 if elapsed < ttl else None)
    return dict(fault=fault, contract_pass=actual == expected, observed=actual, expected=expected, actual_cache_type=type(cache).__module__ + '.' + type(cache).__qualname__)

def context_case(source, symbol, fault, binding=None, default_mode=False, condition=None, payload_case='BASE', sources=None):
    if binding is not None and 'module_graph' in binding:
        with reuse.module_graph.loaded(sources, binding) as (namespace, namespaces):
            row = _context_case(source, symbol, fault, binding, default_mode, condition, payload_case, namespace, namespaces)
            graph = binding['module_graph']
            row.update(public_entry_member=graph['entry_member'], repair_member=graph['repair_member'], executed_source_sha256=reuse.c.digest(sources), executed_module_members=sorted(sources))
            if 'public_entry_resolution' in graph:
                public_function = namespace[binding['entry_symbol']]
                row.update(public_function_module=public_function.__module__, public_function_symbol=public_function.__name__)
            return row
    return _context_case(source, symbol, fault, binding, default_mode, condition, payload_case)

def _context_case(source, symbol, fault, binding=None, default_mode=False, condition=None, payload_case='BASE', namespace=None, namespaces=None):
    """Context case."""
    ns = namespace
    if ns is None:
        ns = {'__name__': 'isolated_frozen_target', '__file__': '/tmp/frozen_target.py'}
        exec(compile(source, '/tmp/frozen_target.py', 'exec'), ns)
    namespaces = [ns] if namespaces is None else namespaces
    delegated = binding is not None and binding.get('kind') == reuse.delegated.KIND
    descriptor_generator = binding is not None and binding.get('kind') == 'FD_GENERATOR_CONTEXT'
    serialized = binding is not None and binding.get('kind') == reuse.serialized.KIND
    fn = ns[binding['entry_symbol'] if delegated or serialized else symbol]
    payload, expected_content = reuse.serialized.sample(binding['caller_profile'], payload_case) if serialized else (None, b'new')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        dest = root / 'record'
        dest.write_bytes(b'prior')
        unrelated = root / 'other.pending'
        unrelated.write_bytes(b'other')
        error = None
        injected = []
        old_fsync = os.fsync
        old_rename = os.rename
        old_replace = os.replace
        old_temporary = tempfile.NamedTemporaryFile
        old_open = io.open
        injector = None if condition is None else reuse.conditions.Injector(condition)

        class ConditionStream:

            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args) if injector is None else injector.call('STREAM_CLOSE', lambda: self.stream.__exit__(*args))

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def flush(self):
                return self.stream.flush() if injector is None else injector.call('STREAM_FLUSH', self.stream.flush)

            def write(self, value):
                if serialized and fault == 'WRITE':
                    injected.append('WRITE')
                    raise OSError('OWNED_WRITE_FAILURE')
                return self.stream.write(value)

        def temporary(*args, **kwargs):
            stream = old_temporary(*args, **kwargs)
            return stream if injector is None and (not (serialized and fault == 'WRITE')) else ConditionStream(stream)

        def opened(*args, **kwargs):
            stream = old_open(*args, **kwargs)
            wrapped = delegated or descriptor_generator or (serialized and binding['io_kind'] == 'FD_GENERATOR_CONTEXT')
            return stream if not wrapped or (injector is None and (not (serialized and fault == 'WRITE'))) else ConditionStream(stream)

        def fsync(fd):
            if fault == 'FSYNC':
                injected.append('FSYNC')
                raise OSError(errno.EIO, 'OWNED_FSYNC_FAILURE')
            return old_fsync(fd)

        def rename(a, b):
            if fault == 'REPLACE':
                injected.append('REPLACE')
                raise OSError('OWNED_REPLACE_FAILURE')
            return old_rename(a, b)

        def replace(a, b):
            if fault == 'REPLACE':
                injected.append('REPLACE')
                raise OSError('OWNED_REPLACE_FAILURE')
            return old_replace(a, b)
        with patch.object(os, 'fsync', fsync), patch.object(os, 'rename', rename), patch.object(os, 'replace', replace), patch.object(tempfile, 'NamedTemporaryFile', temporary), patch.object(io, 'open', opened):
            for scope in namespaces:
                for k, v in list(scope.items()):
                    for original, proxy in ((old_fsync, fsync), (old_rename, rename), (old_replace, replace), (old_temporary, temporary), (old_open, opened)):
                        if v is original:
                            scope[k] = proxy
            generator = binding is not None and binding.get('kind') in reuse.contexts.GENERATOR_KINDS
            options = {binding['mode_parameter']: 'wb'} if generator and binding['mode_parameter'] and (not default_mode) else {}
            if not generator:
                options = dict(overwrite=True, mode='wb')
            text_mode = generator and binding['default_mode'] == 'w' and (default_mode or not binding['mode_parameter'])
            if delegated:
                options = dict(overwrite=True) if default_mode else dict(overwrite=True, mode='wb')
                text_mode = default_mode and binding['default_mode'] == 'w'
            if serialized:
                options = {}
                text_mode = True
            returned = None
            try:
                if serialized:
                    returned = fn(str(dest), payload)
                else:
                    with fn(str(dest), **options) as stream:
                        if fault == 'WRITE':
                            injected.append('WRITE')
                            raise OSError('OWNED_WRITE_FAILURE')
                        stream.write('new' if text_mode else b'new')
            except OSError as exc:
                error = type(exc).__name__
        if injector is not None:
            injected.extend(injector.hits)
        expected_error = None if fault == 'NORMAL' else 'OSError'
        residue = [p for p in root.iterdir() if p not in (dest, unrelated)]
        required_content = expected_content if fault == 'NORMAL' else b'prior'
        passed = error == expected_error and dest.read_bytes() == required_content and (unrelated.read_bytes() == b'other') and (not residue) and (returned is None)
        reached = fault == 'NORMAL' or bool(injected)
        row = dict(fault=fault, contract_pass=passed if reached else None, error_class=error, fault_injected=bool(injected), fault_injection_count=len(injected), applicability='OBSERVED' if reached else 'FAULT_NOT_REACHED', default_mode_used=default_mode, invocation_kwargs=options, write_input_kind='TEXT' if text_mode else 'BYTES', expected_error_class=expected_error, residual_temporary_files=len(residue), destination_preserved=dest.read_bytes() == required_content, unrelated_file_preserved=unrelated.read_bytes() == b'other')
        if injector is not None:
            row.update(condition_id=condition['condition_id'], condition_hits=injector.hits, condition_seen=injector.seen)
        if delegated:
            row.update(public_entry_symbol=binding['entry_symbol'], repair_symbol=binding['repair_symbol'])
        if serialized:
            row.update(public_entry_symbol=binding['entry_symbol'], repair_symbol=binding['repair_symbol'], input_profile=binding['caller_profile'], input_case=payload_case, input_payload_sha256=reuse.c.digest(payload), expected_content_sha256=reuse.sha(required_content), destination_sha256=reuse.sha(dest.read_bytes()), returned_none=returned is None, input_domain_qualified=False)
        return row

def observe(plan, cache_type=None, loop=None):
    c = reuse.c
    site = plan['site']
    family = site['family']
    c.require(plan['contract']['family'] == family and plan['contract']['code_sha256'] == site['code_sha256'], 'REUSE_NATIVE_CONTRACT')
    c.require(reuse.sha(site['code']) == site['code_sha256'], 'REUSE_NATIVE_CODE')
    code = site['code']
    patched = plan['candidate_code']
    if patched is not None:
        reuse.apply_candidate(plan['sources'], site, patched)

    def case(value, fault, payload=b'new', *, preexisting=False):
        if family == 'atomic_file':
            bound = site['binding'].get('instance')
            factory = None if bound is None else lambda scope: reuse.instances.callable_factory(bound, value, scope)
            row = atomic_worker.case(value, fault, payload, preexisting=preexisting, callable_factory=factory)
            row['fault'] = fault
            return row
        if family == 'async_resource':
            c.require(loop is not None, 'REUSE_ASYNC_LOOP_REQUIRED')
            return loop.run_until_complete(async_case(value, fault, site['binding']['returns_result']))
        if family == 'elapsed_ttl':
            c.require(cache_type is not None, 'REUSE_REAL_TTL_DEPENDENCY_REQUIRED')
            return clock_case(value, fault, site['binding']['ttl'], cache_type)
        sources = plan['sources'] if value == code else reuse.apply_candidate(plan['sources'], site, value)
        program = plan['proposal'].get('condition_programs', {}).get(fault)
        return context_case(sources[site['member']], site['symbol'], fault, site['binding'], condition=program, sources=sources)
    healthy = case(code, 'NORMAL')
    probes = [case(code, f) for f in plan['proposal']['faults']]
    found = healthy['contract_pass'] and any((r['contract_pass'] is False for r in probes))
    if found and patched is None:
        patched = reuse.candidate(site)
        if patched is not None:
            reuse.apply_candidate(plan['sources'], site, patched)
    reinjection = []
    regression = []
    if found and patched is not None:
        reinjection = [case(patched, f) for f in reuse.qualification_faults(site, plan['proposal'])]
        regression = [case(patched, 'NORMAL')]
        if family == 'atomic_file':
            regression.append(case(patched, 'NORMAL', preexisting=True))
            regression.extend((case(patched, 'NORMAL', p) for p in (b'', b'\x00', '\u8a18\u9332'.encode())))
        elif family == 'elapsed_ttl':
            regression.extend((case(patched, f) for f in ('OFFSET', 'BOUNDARY')))
        elif family == 'atomic_context':
            revised = reuse.apply_candidate(plan['sources'], site, patched)
            if site['binding'].get('kind') == reuse.serialized.KIND:
                regression.extend((context_case(revised[site['member']], site['symbol'], 'NORMAL', site['binding'], payload_case=k, sources=revised) for k in ('EMPTY', 'UNICODE')))
            else:
                regression.append(context_case(revised[site['member']], site['symbol'], 'NORMAL', site['binding'], default_mode=True))
        revised = reuse.apply_candidate(plan['sources'], site, patched)
        rebound = next((x for x in reuse.inventory(revised)['accepted'] if x['id'] == site['id']))
        c.require(rebound['code'] == patched, 'REUSE_PATCH_REBIND_DRIFT')
    executed = bool(reinjection)
    return dict(family=family, healthy=healthy, probes=probes, fault_discovered=found, candidate_code=patched if executed else None, candidate_sha256=reuse.sha(patched) if executed else None, actual_candidate_code_executed=executed, reinjection=reinjection, regression=regression, repair_pass=None if not executed else all((r['contract_pass'] is True for r in reinjection + regression)), status='BASELINE_INVALID' if not healthy['contract_pass'] else 'FAULT_NOT_REACHED' if any((r['contract_pass'] is None for r in probes)) else 'REPAIRED' if executed and all((r['contract_pass'] is True for r in reinjection + regression)) else 'REPAIR_FAILED' if executed else 'REPAIR_UNSUPPORTED' if found else 'NO_COUNTEREXAMPLE', generator='VALIDATED_FAMILY_REWRITE_OR_SUPPLIED_CANDIDATE', model_calls=0, forecasts=None)

def main():
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (134217728, 134217728))
    resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    boundary = dict(uid=os.getuid(), effective_capabilities=int(status['CapEff'].strip(), 16),
                    home_visible=Path('/home').exists() or Path('/root').exists(),
                    cpu_seconds=list(resource.getrlimit(resource.RLIMIT_CPU)),
                    memory_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),
                    file_bytes=list(resource.getrlimit(resource.RLIMIT_FSIZE)),
                    core_bytes=list(resource.getrlimit(resource.RLIMIT_CORE)))
    reuse.c.require(boundary['uid'] != 0 and boundary['effective_capabilities'] == 0
                    and not boundary['home_visible'], 'REUSE_EXECUTION_BOUNDARY')
    raw = Path('/run/plan.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != sys.argv[1]: raise ValueError('REUSE_PLAN_DRIFT')
    plan = json.loads(raw); cache_type = None; loop = None
    if plan['site']['family'] == 'elapsed_ttl':
        wheel = Path('/run/dependency.whl')
        if reuse.sha(wheel.read_bytes()) != plan['dependency_sha256']: raise ValueError('REUSE_DEPENDENCY_DRIFT')
        sys.path.insert(0, str(wheel)); import cachetools
        if not cachetools.__file__.startswith('/run/dependency.whl/'): raise ValueError('REUSE_DEPENDENCY_ORIGIN')
        cache_type = cachetools.TTLCache
    if plan['site']['family'] == 'async_resource': loop = asyncio.new_event_loop()
    attempts = []
    def audit(event, args):
        if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.fork'):
            attempts.append(event); raise ValueError('REUSE_EXTERNAL_ACTION')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            p = os.fsdecode(args[0])
            if not (p.startswith('/tmp/') or p.startswith('/usr/') or p.startswith('/run/modules/')):
                attempts.append('OUTSIDE_SCOPE_OPEN'); raise ValueError('REUSE_EXTERNAL_FILE')
    namespaces = {k: os.readlink('/proc/self/ns/'+k) for k in ('user', 'mnt', 'pid', 'net')}
    sys.addaudithook(audit)
    try: value = observe(plan, cache_type, loop)
    finally:
        if loop is not None: loop.close()
    value.update(plan_sha256=reuse.c.digest(plan), namespaces=namespaces,
                 execution_boundary=boundary,
                 external_action_attempts=len(attempts), maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
if __name__ == '__main__':
    main()
