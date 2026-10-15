"Apply finite cleanup conditions without receiving Source text."
import errno
import io
import json
import os
from pathlib import Path
import sys

import reliability_incident_conditions as protocol
import reliability_path_context_worker as caller


def run(path,digest):
    plan=json.loads(Path(path).read_bytes());protocol.c.check_seal(plan)
    protocol.c.require(protocol.c.digest(plan)==digest and plan==protocol.child_plan(plan['base_plan'],plan['program']),
                       'INCIDENT_CONDITION_CHILD_PLAN_DRIFT')
    condition=plan['program'];originals={n:getattr(os,n) for n in ('unlink','remove')}
    state=dict(phase='IDLE',case=None);hits=[];attempts={};spent=set();root=Path('/tmp/path-context')
    def owned(p):
        return (p.is_absolute() and p.is_relative_to(root) and len(p.relative_to(root).parts)>=2
            and p.name!='other-owner' and not p.is_symlink() and p.is_file()
            and p.relative_to(root).parts[0]==state['case'])
    def event_key():return state['case']+':'+state['phase']
    def record(p,key,action,trigger=None):
        protocol.c.require(len(hits)<128,'INCIDENT_CONDITION_EVENT_BOUND')
        hit=dict(action=action,path=str(p),case=state['case'],phase=state['phase'],
            errno=condition['errno'],original_file_existed=True,after_file_exists=p.exists(),key=key)
        if trigger is not None:hit['trigger_path']=str(trigger)
        hits.append(hit)
    def phase(name,case):
        state.update(phase=name,case=case)
        if name in ('CLEANUP','CLEANUP_REPEAT') and condition['action']=='REMOVE_OWNED_BEFORE_CLEANUP':
            key=event_key();files=sorted(p for p in (root/case).rglob('*') if owned(p))
            protocol.c.require(len(files)<=8,'INCIDENT_CONDITION_OWNED_FILE_BOUND')
            if files and key not in spent:
                
                p=files[0];originals['unlink'](p);spent.add(key);record(p,key,condition['action'])
    def wrapper(name):
        def delete(path,*args,**kwargs):
            raw=os.fspath(path);p=Path(os.fsdecode(raw))
            if not p.is_absolute() and kwargs.get('dir_fd') is not None:
                p=Path(os.readlink('/proc/self/fd/'+str(kwargs['dir_fd'])))/p
            
            p=p.parent.resolve(strict=False)/p.name
            if state['phase'] in ('CLEANUP','CLEANUP_REPEAT') and owned(p) and condition['action'] in (
                    'DELETE_ERROR_ONCE','REMOVE_OWNED_BEFORE_DELETE','REMOVE_SIBLING_AFTER_FIRST_DELETE'):
                key=event_key();attempts[key]=attempts.get(key,0)+1
                protocol.c.require(sum(attempts.values())<=128,'INCIDENT_CONDITION_ATTEMPT_BOUND')
                if key not in spent:
                    spent.add(key)
                    if condition['action']=='REMOVE_SIBLING_AFTER_FIRST_DELETE':
                        result=originals[name](raw,*args,**kwargs)
                        files=sorted(q for q in (root/state['case']).rglob('*') if q!=p and owned(q))
                        protocol.c.require(len(files)<=8,'INCIDENT_CONDITION_OWNED_FILE_BOUND')
                        if files:
                            sibling=files[0];originals['unlink'](sibling);record(sibling,key,condition['action'],p)
                        return result
                    if condition['action']=='REMOVE_OWNED_BEFORE_DELETE':
                        originals[name](raw,*args,**kwargs);record(p,key,condition['action'])
                        
                    else:
                        record(p,key,condition['action'])
                        raise OSError(getattr(errno,condition['errno']),'FINITE_SOURCE_DERIVED_DELETE_CONDITION')
            return originals[name](raw,*args,**kwargs)
        return delete
    for n in originals:setattr(os,n,wrapper(n))
    capture=io.StringIO();old=sys.stdout
    try:
        sys.stdout=capture
        caller.run('/run/base-plan.json',protocol.c.digest(plan['base_plan']),lifecycle_observer=phase)
    finally:
        sys.stdout=old
        for n,v in originals.items():setattr(os,n,v)
    observed=json.loads(capture.getvalue());protocol.c.check_seal(observed)
    label=protocol.outcome(condition,observed,hits)
    print(json.dumps(protocol.c.seal(dict(kind='FINITE_GENERATED_CLEANUP_OBSERVATION_V1',
        plan_sha256=digest,event=protocol.EVENT,program_sha256=protocol.c.digest(condition),
        context_observation=observed,hits=hits,cleanup_attempts=attempts,label=label,
        label_authority='UNKNOWN' if label is None else 'NATIVE_FINITE_REQUIREMENT_ORACLE',
        source_payload_disclosed=False,execution_authority=False)),sort_keys=True),flush=True)


if __name__=='__main__':run(sys.argv[1],sys.argv[2])
