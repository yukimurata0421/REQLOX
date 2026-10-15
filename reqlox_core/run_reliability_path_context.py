"Run and verify bounded public-context plans in private state."
import json
import os
from pathlib import Path
import signal
import subprocess

import reliability_path_context as protocol
import run_reliability_reuse as storage


def execute(plan, output, *, before_native=None):
    protocol.c.require(callable(before_native), 'PATH_CONTEXT_NATIVE_AUTHORIZATION_REQUIRED')
    protocol.c.check_seal(plan)
    protocol.c.require(plan['method']==protocol.methods(), 'PATH_CONTEXT_METHOD_DRIFT')
    protocol.c.require(plan==protocol.plan(plan['sources'],plan['recipe'],plan['documents'],
        provenance=plan['provenance'],forecast_ref=plan['forecast_ref']), 'PATH_CONTEXT_INPUT_DRIFT')
    output=storage.private(output,new=True);output.mkdir(mode=0o700)
    storage.save(output/'plan.json',plan)
    source=output/'target';source.mkdir(mode=0o700)
    for name,text in plan['sources'].items():
        dest=source/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    method=output/'method';method.mkdir(mode=0o700)
    for name,sha in plan['method'].items():
        data=(Path(protocol.__file__).parent/name).read_bytes()
        protocol.c.require(protocol.hashlib.sha256(data).hexdigest()==sha,'PATH_CONTEXT_METHOD_DRIFT')
        (method/name).write_bytes(data)
    parent={k:os.readlink('/proc/self/ns/'+k) for k in ('user','mnt','pid','net')}
    storage.save(output/'launch.json',protocol.c.seal(dict(plan_sha256=protocol.c.digest(plan),parent_namespaces=parent,
        credential_or_home_mounted=False,network_namespace_isolated=True,automatic_retry=False,
        launcher_limits='PRLIMIT_BEFORE_BWRAP',
        prlimit_sha256=protocol.hashlib.sha256(Path('/usr/bin/prlimit').read_bytes()).hexdigest())))
    cmd=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--cap-drop','ALL',
         '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
         '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--chdir','/tmp',
         '--ro-bind',str(output/'plan.json'),'/run/plan.json','--ro-bind',str(method),'/app',
         '--ro-bind',str(source),'/target','/usr/bin/python3','-I','-S','-B','-c',
         'import sys;sys.path.insert(0,"/app");from reliability_path_context_worker import run;run(sys.argv[1],sys.argv[2])',
         '/run/plan.json',protocol.c.digest(plan)]
    cmd=['/usr/bin/prlimit','--cpu=2:2','--as=134217728:134217728',
         '--fsize=131072:131072','--core=0:0','--',*cmd]
    code=None;error=None;observed=None
    child=None;reserved=False
    with (output/'observed.json').open('xb') as out,(output/'stderr.log').open('xb') as err:
        os.fchmod(out.fileno(),0o600);os.fchmod(err.fileno(),0o600)
        try:
            before_native()
            reserved=True
            child=subprocess.Popen(cmd,stdout=out,stderr=err,start_new_session=True)
            code=child.wait(timeout=plan['limits']['wall_seconds'])
        except subprocess.TimeoutExpired:error='WALL_LIMIT'
        except (Exception,KeyboardInterrupt) as exc:error=str(exc)[:160] or type(exc).__name__
        finally:
            if child is not None and child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL);child.wait()
    try:
        protocol.c.require(code==0 and error is None,'PATH_CONTEXT_CHILD_STOPPED')
        protocol.c.require((output/'observed.json').stat().st_size<=plan['limits']['output_bytes'],'PATH_CONTEXT_OUTPUT_BOUND')
        observed=json.loads((output/'observed.json').read_text());protocol.c.check_seal(observed)
        protocol.check_execution_boundary(observed.get('execution_boundary'))
        protocol.c.require(observed['plan_sha256']==protocol.c.digest(plan)
            and observed['method']==plan['method'] and observed['source_snapshot_sha256']==protocol.c.digest(plan['sources'])
            and observed['raw_source_bundle_verified'] is True
            and all(observed['namespaces'][k]!=parent[k] for k in parent),'PATH_CONTEXT_OBSERVATION_DRIFT')
        protocol.c.require(observed['external_action_attempts']==[], 'PATH_CONTEXT_EXTERNAL_ACTION_ATTEMPT')
        protocol.c.require(observed['public_module']==plan['recipe']['binding']['module']
            and observed['public_symbol']==plan['recipe']['binding']['symbol']
            and observed['original_implementation_mutated'] is False,'PATH_CONTEXT_PUBLIC_API_DRIFT')
        if observed['label'] is not None:
            protocol.c.require(observed['label_authority']=='NATIVE_FINITE_REQUIREMENT_ORACLE'
                and observed['callable_source_member'] in plan['sources']
                and observed['callable_module'] in protocol.module_names(plan['sources'])
                and observed['callable_kind'] in ('CLASS','FACTORY_FUNCTION'), 'PATH_CONTEXT_ORIGIN_DRIFT')
            rows=observed['rows'];expected=[(i,f) for i in range(2) for f in protocol.FAULTS]
            actual=[(r['other_file_case'],r['fault']) for r in rows]
            protocol.c.require(actual==expected[:len(actual)] and actual, 'PATH_CONTEXT_CASE_DRIFT')
            if observed['label']=='PASS':
                protocol.c.require(actual==expected and all(r['contract_pass'] is True and r.get('repeat_pass') is True
                    and r['entry_acquired'] is True and r['resource_witness'] is True
                    and r['remaining_owned_fds']==r['prior_owned_fds'] and r['other_file_preserved'] is True
                    and r['owned_path_resource_released'] is True
                    and (r['context_instance_module'] in protocol.module_names(plan['sources'])
                        or r['context_instance_module'].split('.')[0] in protocol.sys.stdlib_module_names)
                    and r['repeat_remaining_owned_fds']==r['prior_owned_fds']
                    and r['repeat_other_file_preserved'] is True
                    and r['repeat_owned_path_resource_released'] is True
                    and (r['fault']=='NONE' or r['body_failure_propagated'] is True) for r in rows),
                    'PATH_CONTEXT_PASS_ORACLE_DRIFT')
            else:
                protocol.c.require(observed['label']=='FAIL' and rows[-1]['contract_pass'] is False
                    and rows[-1]['entry_acquired'] is True and rows[-1]['resource_witness'] is True,
                    'PATH_CONTEXT_FAIL_ORACLE_DRIFT')
    except (ValueError,KeyError,TypeError,OSError) as exc:
        error=error or str(exc)[:160];observed=None
    receipt=protocol.c.seal(dict(status='COMPLETE' if observed is not None else 'STOPPED',returncode=code,error=error,
        plan_sha256=protocol.c.digest(plan),observed_sha256=protocol.hashlib.sha256((output/'observed.json').read_bytes()).hexdigest(),
        native_campaigns=int(reserved),automatic_retry=False,provider_calls=0,
        label=None if observed is None else observed['label'],label_authority='UNKNOWN' if observed is None else observed['label_authority']))
    storage.save(output/'receipt.json',receipt)
    return receipt,observed
