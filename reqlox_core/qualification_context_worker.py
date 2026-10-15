"Finite reliability controls and verification."

if __name__ == '__main__' and not __package__:
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))
    __package__ = 'reqlox_core'

import asyncio
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import resource
import socket
import sys
ROOT=Path(__file__).resolve().parents[1]


def main():
    os.nice(10);resource.setrlimit(resource.RLIMIT_CPU,(10,10));resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456));resource.setrlimit(resource.RLIMIT_FSIZE,(1048576,1048576))
    raw=Path(sys.argv[1]).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sys.argv[2]:raise ValueError('CONTEXT_NATIVE_PLAN_DRIFT')
    p=json.loads(raw);pass  # Package imports resolve from the repository root.
    from .qualification_context_protocol import validate
    validate(p['inventory'],p['binding']);b=p['binding']
    for ref in p['input_files']:
        data=Path(ref['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=ref['sha256'] or len(data)!=ref['bytes']:raise ValueError('CONTEXT_NATIVE_SOURCE_DRIFT')
    roots=[Path(p['snapshot_root']).resolve(),*[Path(r).resolve() for r in p['dependency_roots']]]
    sys.path[:0]=[str(r) for r in roots]
    attempts=[]
    def deny(*args,**kwargs):attempts.append(True);raise ValueError('CONTEXT_NETWORK_FORBIDDEN')
    socket.socket.connect=deny;socket.create_connection=deny
    factory_module=importlib.import_module(b['factory_module']);owner_module=importlib.import_module(b['owner_module']);context_module=importlib.import_module(b['context_module'])
    factory=getattr(factory_module,b['factory_name']);owner_class=getattr(owner_module,b['owner_class']);context_class=getattr(context_module,b['context_class'])
    for callable_value in [factory,owner_class,context_class]:
        if not Path(inspect.getfile(callable_value)).resolve().is_relative_to(roots[0]):raise ValueError('CONTEXT_NATIVE_CLASS_ORIGIN')
    errors={'TimeoutError':TimeoutError,'RuntimeError':RuntimeError,'ValueError':ValueError,'CancelledError':asyncio.CancelledError}
    trace={};native_entries=0
    def context(owner,key):
        result=getattr(owner,b['context_method'])(**{**b['context_kwargs'],b['key_parameter']:key})
        if type(result) is not context_class:raise ValueError('CONTEXT_NATIVE_RESULT_TYPE')
        return result
    async def async_stage(owner,key,case,stage):
        ctx=context(owner,key);first=None
        try:
            if stage['policy']=='OMIT_EXIT':
                await ctx.__aenter__()
                if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
            else:
                async with ctx:
                    if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
        except BaseException as exc:first=type(exc).__name__
        held=bool(await getattr(ctx,b['async_probe'])());second=False;next_ctx=context(owner,key)
        try:
            async with next_ctx:second=True
        except BaseException:
            if not held:raise
        return dict(first_exception=first,locked_after_first=held,second_entered=second,locked_after_second=bool(await getattr(ctx,b['async_probe'])()))
    def sync_stage(owner,key,case,stage):
        ctx=context(owner,key);first=None
        try:
            if stage['policy']=='OMIT_EXIT':
                ctx.__enter__()
                if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
            else:
                with ctx:
                    if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
        except BaseException as exc:first=type(exc).__name__
        held=bool(getattr(ctx,b['sync_probe'])());second=False;next_ctx=context(owner,key)
        try:
            with next_ctx:second=True
        except BaseException:
            if not held:raise
        return dict(first_exception=first,locked_after_first=held,second_entered=second,locked_after_second=bool(getattr(ctx,b['sync_probe'])()))
    for case in p['cases']:
        trace[case['id']]={}
        for stage in p['stages']:
            owner=factory(**b['factory_kwargs'])
            if type(owner) is not owner_class:raise ValueError('CONTEXT_OWNER_RESULT_TYPE')
            key='owned-'+case['id']+'-'+stage['id'];native_entries+=2
            trace[case['id']][stage['id']]=asyncio.run(async_stage(owner,key,case,stage)) if case['mode']=='ASYNC' else sync_stage(owner,key,case,stage)
    unchanged=all(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'] for r in p['input_files'])
    print(json.dumps(dict(cases=trace,native_context_entry_attempts=native_entries,plan_sha256=hashlib.sha256(raw).hexdigest(),
        real_oss_code_executed=True,source_unchanged=unchanged,network_attempts=len(attempts),
        repair_scope='OWNED_CALLER_BALANCED_CONTEXT_PROTOCOL',target_source_modified=False,
        namespaces={k:os.readlink('/proc/self/ns/'+k) for k in ['user','mnt','pid','net']})))

if __name__=='__main__':main()
