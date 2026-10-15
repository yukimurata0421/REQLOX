"""Compare bounded condition searches on separate private snapshots."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import reliability_incident_conditions as protocol
import reliability_context_evidence as evidence
import run_reliability_reuse as storage
c = protocol.c

def verify_source_raw(source):
    c.check_seal(source)
    c.require(source['raw_sha256'] == c.digest(source['documents']), 'PUBLIC_SOURCE_DOCUMENT_DRIFT')
    return c.seal(dict(kind='LOCAL_SUPPLIED_SOURCE_BINDING_V1', source_sha256=c.digest(source),
        supplied_document_bytes_bound=True, external_retrieval_verified=False,
        semantic_support_certified=False, natural_incident_reproduced=False, execution_authority=False))

def verify_observation(plan,observed,launch):
    c.check_seal(observed);raw=observed['context_observation'];c.check_seal(raw)
    c.require(observed['kind']=='FINITE_GENERATED_CLEANUP_OBSERVATION_V1'
        and observed['plan_sha256']==c.digest(plan) and observed['event']==protocol.EVENT
        and observed['program_sha256']==c.digest(plan['program'])
        and observed['source_payload_disclosed'] is observed['execution_authority'] is False,
        'INCIDENT_CONDITION_OBSERVATION_BINDING')
    evidence.verify_observation(plan['base_plan'],raw,launch,
        dict(label=raw['label'],label_authority=raw['label_authority']))
    hits=observed['hits'];attempts=observed['cleanup_attempts'];value=plan['program']
    c.require(type(hits) is list and type(attempts) is dict and len(hits)<=128
        and all(type(v) is int and 0<v<=128 for v in attempts.values())
        and sum(attempts.values())<=128,'INCIDENT_CONDITION_ATTEMPT_BOUND')
    cases={f"case-{r['other_file_case']}-{r['fault']}" for r in raw['rows']}
    keys=set()
    for hit in hits:
        p=Path(hit['path']);root=Path('/tmp/path-context');key=hit['key']
        sibling=value['action']=='REMOVE_SIBLING_AFTER_FIRST_DELETE'
        c.require(set(hit)=={'action','path','case','phase','errno','original_file_existed','after_file_exists','key'}
            | ({'trigger_path'} if sibling else set())
            and hit['action']==value['action'] and hit['errno']==value['errno']
            and hit['phase'] in ('CLEANUP','CLEANUP_REPEAT') and hit['case'] in cases
            and key==hit['case']+':'+hit['phase'] and key not in keys
            and p.is_absolute() and '..' not in p.parts and p.is_relative_to(root)
            and len(p.relative_to(root).parts)>=2 and p.name!='other-owner'
            and p.relative_to(root).parts[0]==hit['case'] and hit['original_file_existed'] is True
            and hit['after_file_exists'] is (value['action']=='DELETE_ERROR_ONCE'),
            'INCIDENT_CONDITION_INJECTION_BINDING')
        if sibling:
            trigger=Path(hit['trigger_path'])
            c.require(trigger!=p and trigger.is_absolute() and '..' not in trigger.parts
                and trigger.is_relative_to(root) and len(trigger.relative_to(root).parts)>=2
                and trigger.relative_to(root).parts[0]==hit['case'] and trigger.name!='other-owner',
                'INCIDENT_CONDITION_SIBLING_TRIGGER_BINDING')
        keys.add(key)
        if value['action']!='REMOVE_OWNED_BEFORE_CLEANUP':
            c.require(attempts.get(key,0)>=1,'INCIDENT_CONDITION_INJECTION_ATTEMPT')
    c.require(all(k.rsplit(':',1)[0] in cases for k in attempts),'INCIDENT_CONDITION_UNOBSERVED_CASE')
    if value['action']=='NONE':c.require(not hits and not attempts,'INCIDENT_CONDITION_NORMAL_INJECTION')
    expected=protocol.outcome(value,raw,hits)
    c.require(observed['label']==expected and observed['label_authority']==('UNKNOWN' if expected is None
        else 'NATIVE_FINITE_REQUIREMENT_ORACLE'),'INCIDENT_CONDITION_LABEL_DRIFT')


def audit(directory):
    directory=Path(directory);plan,_=evidence.read(directory/'condition-plan.json')
    base,_=evidence.read(directory/'plan.json');receipt,sha=evidence.read(directory/'receipt.json')
    launch,_=evidence.read(directory/'launch.json')
    c.require(plan['kind']=='FINITE_GENERATED_CLEANUP_EXECUTION_PLAN_V1' and plan['base_plan']==base
        and plan['program']==protocol.program(plan['program']['action'],plan['program']['errno'])
        and plan['event']==protocol.EVENT and plan['source_payload_disclosed'] is plan['execution_authority'] is False,
        'INCIDENT_CONDITION_ARCHIVED_PLAN')
    c.require(launch['condition_plan_sha256']==c.digest(plan) and launch['plan_sha256']==c.digest(base)
        and launch['credential_or_home_mounted'] is False and launch['network_namespace_isolated'] is True,
        'INCIDENT_CONDITION_ARCHIVED_LAUNCH')
    for name,hash_value in plan['method'].items():
        c.require(name in protocol.METHODS and Path(name).name==name,'INCIDENT_CONDITION_ARCHIVED_METHOD_NAME')
        p=directory/'method'/name
        c.require(not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==hash_value,
                  'INCIDENT_CONDITION_ARCHIVED_METHOD_DRIFT')
    required=protocol.study.context.archived_method_names(base,protocol.METHODS)
    c.require(set(plan['method'])==required and all(plan['method'][n]==sha for n,sha in base['method'].items()),
              'INCIDENT_CONDITION_ARCHIVED_METHOD_SET')
    for name,text in base['sources'].items():
        p=directory/'target'/name
        c.require(not p.is_symlink() and p.read_text()==text,'INCIDENT_CONDITION_ARCHIVED_SOURCE_DRIFT')
    data=(directory/'observed.json').read_bytes()
    c.require(receipt['plan_sha256']==c.digest(plan) and receipt['program_sha256']==c.digest(plan['program'])
        and receipt['observed_sha256']==hashlib.sha256(data).hexdigest()
        and receipt['native_campaigns']==1 and receipt['provider_calls']==0
        and receipt['automatic_retry'] is receipt['execution_authority'] is False,
        'INCIDENT_CONDITION_RECEIPT_BINDING')
    if receipt['status']=='COMPLETE':
        observed=json.loads(data);verify_observation(plan,observed,launch)
        c.require(receipt['returncode']==0 and receipt['error'] is None
            and receipt['label']==observed['label'] and receipt['label_authority']==observed['label_authority'],
            'INCIDENT_CONDITION_RECEIPT_DRIFT')
    else:
        c.require(receipt['status']=='STOPPED' and receipt['label'] is None and receipt['label_authority']=='UNKNOWN',
                  'INCIDENT_CONDITION_STOPPED_GOLD')
    return c.seal(dict(kind='ARCHIVED_GENERATED_CONDITION_EXECUTION_CHECK_V1',receipt_sha256=sha,
        label=receipt['label'],program_sha256=receipt['program_sha256'],original_source_bytes_verified=True,
        namespace_and_finite_oracle_verified=receipt['status']=='COMPLETE',provider_calls=0,
        native_campaigns=0,natural_incident_transfer_certified=False,execution_authority=False))


def execute(plan,output,guard):
    c.require(plan==protocol.child_plan(plan['base_plan'],plan['program']),'INCIDENT_CONDITION_PLAN_DRIFT')
    guard();getattr(guard,'before_native',guard)();output=storage.private(output,new=True);output.mkdir(mode=0o700)
    base=plan['base_plan'];storage.save(output/'condition-plan.json',plan);storage.save(output/'plan.json',base)
    method=output/'method';method.mkdir(mode=0o700)
    for name,sha in plan['method'].items():
        data=(Path(protocol.__file__).parent/name).read_bytes()
        c.require(hashlib.sha256(data).hexdigest()==sha,'INCIDENT_CONDITION_METHOD_DRIFT');(method/name).write_bytes(data)
    target=output/'target';target.mkdir(mode=0o700)
    for name,text in base['sources'].items():
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    parent={k:os.readlink('/proc/self/ns/'+k) for k in ('user','mnt','pid','net')}
    launch=c.seal(dict(condition_plan_sha256=c.digest(plan),plan_sha256=c.digest(base),parent_namespaces=parent,
        credential_or_home_mounted=False,network_namespace_isolated=True,automatic_retry=False))
    storage.save(output/'launch.json',launch)
    cmd=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--cap-drop','ALL',
        '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
        '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--chdir','/tmp',
        '--ro-bind',str(output/'condition-plan.json'),'/run/condition-plan.json',
        '--ro-bind',str(output/'plan.json'),'/run/base-plan.json','--ro-bind',str(method),'/app',
        '--ro-bind',str(target),'/target','/usr/bin/python3','-I','-S','-B','-c',
        'import sys;sys.path.insert(0,"/app");from reliability_incident_conditions_worker import run;run(sys.argv[1],sys.argv[2])',
        '/run/condition-plan.json',c.digest(plan)]
    code=None;error=None;observed=None
    with (output/'observed.json').open('xb') as out,(output/'stderr.log').open('xb') as err:
        child=subprocess.Popen(cmd,stdout=out,stderr=err,start_new_session=True)
        try:code=child.wait(timeout=base['limits']['wall_seconds'])
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait();error='WALL_LIMIT'
    try:
        c.require(code==0 and error is None,'INCIDENT_CONDITION_CHILD_STOPPED')
        observed,_=evidence.read(output/'observed.json',maximum=base['limits']['output_bytes'])
        verify_observation(plan,observed,launch)
    except (ValueError,KeyError,OSError) as exc:error=error or str(exc)[:160];observed=None
    receipt=c.seal(dict(kind='GENERATED_CONDITION_EXECUTION_RECEIPT_V1',status='COMPLETE' if observed else 'STOPPED',
        plan_sha256=c.digest(plan),program_sha256=c.digest(plan['program']),returncode=code,error=error,
        observed_sha256=hashlib.sha256((output/'observed.json').read_bytes()).hexdigest(),
        label=observed['label'] if observed else None,label_authority=observed['label_authority'] if observed else 'UNKNOWN',
        native_campaigns=1,provider_calls=0,automatic_retry=False,execution_authority=False))
    storage.save(output/'receipt.json',receipt);storage.save(output/'binding-check.json',audit(output));guard();return receipt


def run(frozen,output,*,guard):
    c.require(frozen==protocol.freeze(frozen['base_plan'],frozen['source'],
        budget=frozen['maximum_discovery_campaigns_per_arm'],arm_order=frozen['arm_order'],
        baseline_policy=('TARGET_GUIDED_SOURCE_BLIND_V1' if frozen['no_source_target_guided_condition_generation']
            else 'FIXED_GENERIC_V1')),
        'INCIDENT_CONDITION_FREEZE_DRIFT')
    lineage=verify_source_raw(frozen['source'])
    guard();output=storage.private(output,new=True);output.mkdir(mode=0o700);storage.save(output/'freeze.json',frozen)
    storage.save(output/'source-lineage-check.json',lineage)
    results={};confirmations={};base=frozen['base_plan']
    def bound():guard();c.require(protocol.methods()==frozen['method'],'INCIDENT_CONDITION_RUN_METHOD_DRIFT')
    try:
        bound();baseline=execute(protocol.child_plan(base,protocol.program('NONE')),output/'original-normal',guard)
        if baseline['label']!='PASS':
            result=c.seal(dict(kind='SOURCE_GENERATED_CONDITION_STUDY_HELD_V1',status='HELD',
                reason='ORIGINAL_BASELINE_NOT_SUPPORTED_PASS',original_baseline_label=baseline['label'],
                native_campaigns=1,provider_calls=0,source_added_adoptions=None,
                natural_source_added_value_certified=False,automatic_retry=False,execution_authority=False))
            storage.save(output/'result.json',result);return result
        for arm in frozen['arm_order']:
            rows=[]
            for index,value in enumerate(frozen['plans'][arm]):
                bound();rows.append(execute(protocol.child_plan(base,value),output/f'{arm.lower()}-{index:02d}',guard))
            results[arm]=rows
        for arm in frozen['arm_order']:
            failed=[v for v,r in zip(frozen['plans'][arm],results[arm],strict=True) if r['label']=='FAIL']
            if not failed:continue
            bound();repair=protocol.repair(base['sources'],failed);storage.save(output/f'{arm.lower()}-candidate.json',repair)
            if not repair['changed_members']:continue
            recipe = protocol.study.context.candidate_recipe(base['recipe'], repair['sources'], base['documents'])
            storage.save(output/f'{arm.lower()}-candidate-binding.json', c.seal(dict(
                original_recipe=base['recipe'], candidate_recipe=recipe,
                original_author_evidence_and_signature_preserved=True, execution_authority=False)))
            fresh=protocol.study.context.plan(repair['sources'],recipe,base['documents'],
                provenance=dict(role='KNOWN_DEVELOPMENT',private_candidate_of=c.digest(base['sources'])))
            checks=[]
            for index,value in enumerate(frozen['common_confirmation_envelope']):
                bound();checks.append(execute(protocol.child_plan(fresh,value),output/f'{arm.lower()}-confirm-{index:02d}',guard))
            confirmations[arm]=checks
        bound();result=protocol.comparison(frozen,results,confirmations,baseline);storage.save(output/'result.json',result);return result
    except BaseException as exc:
        storage.save(output/'terminal.json',c.seal(dict(status='STOPPED',reason=type(exc).__name__+':'+str(exc)[:160],
            automatic_retry=False,execution_authority=False)));raise

