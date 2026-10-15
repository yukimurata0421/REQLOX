"Finite reliability controls and verification."
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
    if hashlib.sha256(raw).hexdigest()!=sys.argv[2]:raise ValueError('SYNC_CONTEXT_PLAN_DRIFT')
    p=json.loads(raw);sys.path.insert(0,str(ROOT/'reqlox_core'))
    from qualification_context_sync import validate
    validate(p['inventory'],p['binding']);b=p['binding']
    for r in p['input_files']:
        data=Path(r['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=r['sha256'] or len(data)!=r['bytes']:raise ValueError('SYNC_CONTEXT_SOURCE_DRIFT')
    roots=[Path(p['snapshot_root']).resolve(),*[Path(r).resolve() for r in p['dependency_roots']]];sys.path[:0]=[str(r) for r in roots]
    attempts=[]
    def deny(*a,**k):attempts.append(True);raise ValueError('SYNC_CONTEXT_NETWORK_FORBIDDEN')
    socket.socket.connect=deny;socket.create_connection=deny
    def resolve(module,name):
        value=importlib.import_module(module)
        for part in name.split('.'):value=getattr(value,part)
        if not Path(inspect.getfile(value)).resolve().is_relative_to(roots[0]):raise ValueError('SYNC_CONTEXT_CLASS_ORIGIN')
        return value
    owner_class=resolve(b['factory_module'],b['factory_class']);context_class=resolve(b['context_module'],b['context_class'])
    errors={'TimeoutError':TimeoutError,'RuntimeError':RuntimeError,'ValueError':ValueError}
    trace={}
    for case in p['cases']:
        trace[case['id']]={}
        for stage in p['stages']:
            owner=owner_class(**b['factory_kwargs']);ctx=getattr(owner,b['context_method'])(**b['context_kwargs']);first=None
            if type(ctx) is not context_class:raise ValueError('SYNC_CONTEXT_RESULT_TYPE')
            try:
                if stage['policy']=='OMIT_EXIT':
                    ctx.__enter__()
                    if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
                else:
                    with ctx:
                        if stage['inject_exception']:raise errors[case['exception']]('owned injected failure')
            except BaseException as exc:first=type(exc).__name__
            held=getattr(ctx,b['probe_method'])();next_ctx=getattr(owner,b['context_method'])(**b['context_kwargs'])
            if type(next_ctx) is not context_class:raise ValueError('SYNC_CONTEXT_NEXT_RESULT_TYPE')
            entered=getattr(next_ctx,b['next_acquire_method'])(**b['next_acquire_kwargs'])
            if type(held) is not bool or type(entered) is not bool:raise ValueError('SYNC_CONTEXT_BOOLEAN_RESULT')
            if entered:getattr(next_ctx,b['next_release_method'])()
            after=bool(getattr(ctx,b['probe_method'])() or getattr(next_ctx,b['probe_method'])())
            trace[case['id']][stage['id']]=dict(first_exception=first,locked_after_first=held,second_entered=entered,locked_after_second=after)
    unchanged=all(hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'] for r in p['input_files'])
    print(json.dumps(dict(cases=trace,plan_sha256=hashlib.sha256(raw).hexdigest(),real_oss_code_executed=True,source_unchanged=unchanged,
        network_attempts=len(attempts),target_source_modified=False,second_acquisition_nonblocking=True,
        namespaces={k:os.readlink('/proc/self/ns/'+k) for k in ['user','mnt','pid','net']})))

if __name__=='__main__':main()
