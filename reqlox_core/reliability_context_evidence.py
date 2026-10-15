"""Verify local execution records without acquiring data or calling providers."""
import hashlib
import json
from pathlib import Path
import re
import reliability_path_context as protocol
c = protocol.c

def read(path, *, maximum=25165824, sealed=True):
    path=Path(path)
    c.require(not path.is_symlink() and path.is_file() and path.stat().st_size<=maximum,
              'CONTEXT_EVIDENCE_FILE_BOUND')
    raw=path.read_bytes();value=json.loads(raw)
    if sealed:c.check_seal(value)
    return value,hashlib.sha256(raw).hexdigest()


def verify_observation(plan,observed,launch,receipt):
    """保存された有限context oracleを照合する。呼出元のeventは別途束縛する。"""
    if launch.get('launcher_limits') == 'PRLIMIT_BEFORE_BWRAP':
        protocol.check_execution_boundary(observed.get('execution_boundary'))
    if 'pinned_standard_import_capabilities' in plan:
        c.require(observed.get('pinned_standard_import_capabilities')==plan['pinned_standard_import_capabilities'],
                  'CONTEXT_EVIDENCE_STANDARD_IMPORT_DRIFT')
    c.require(observed['kind']=='FINITE_PATH_CONTEXT_OBSERVATION_V1'
        and observed['plan_sha256']==c.digest(plan) and observed['method']==plan['method']
        and observed['source_snapshot_sha256']==c.digest(plan['sources'])
        and observed['raw_source_bundle_verified'] is True
        and set(observed['namespaces'])==set(launch['parent_namespaces'])=={'user','mnt','pid','net'}
        and all(observed['namespaces'][k]!=launch['parent_namespaces'][k] for k in observed['namespaces'])
        and observed['external_action_attempts']==[] and observed['original_implementation_mutated'] is False
        and observed['public_module']==plan['recipe']['binding']['module']
        and observed['public_symbol']==plan['recipe']['binding']['symbol']
        and receipt['label']==observed['label'] and receipt['label_authority']==observed['label_authority'],
        'CONTEXT_EVIDENCE_OBSERVATION_BINDING')
    label=observed['label'];c.require(label in (None,'PASS','FAIL'),'CONTEXT_EVIDENCE_LABEL')
    if 'native_import_capability' in plan:
        proof=plan['native_import_capability'];c.check_seal(proof)
        c.require(proof==observed.get('native_import_capability')
            and proof['kind']=='PINNED_NATIVE_IMPORT_CAPABILITY_V1'
            and proof['module']=='fcntl' and proof['target_imported'] is False
            and type(proof['available']) is bool
            and (not proof['available'] or proof['implementation']=='cpython'
                 and proof['platform']=='linux' and proof['backend'] in ('BUILTIN','EXTENSION')
                 and re.fullmatch('[0-9a-f]{64}',proof['artifact_sha256']) is not None),
            'CONTEXT_EVIDENCE_NATIVE_IMPORT_CAPABILITY')
    if label is None:c.require(observed['label_authority']=='UNKNOWN','CONTEXT_EVIDENCE_UNKNOWN')
    else:
        c.require(observed['label_authority']=='NATIVE_FINITE_REQUIREMENT_ORACLE'
            and observed['callable_source_member'] in plan['sources']
            and observed['callable_module'] in protocol.module_names(plan['sources'])
            and observed['callable_kind'] in ('CLASS','FACTORY_FUNCTION'),'CONTEXT_EVIDENCE_API_ORIGIN')
        rows=observed['rows'];expected=[(i,f) for i in range(2) for f in protocol.FAULTS]
        actual=[(r['other_file_case'],r['fault']) for r in rows]
        c.require(bool(actual) and actual==expected[:len(actual)],'CONTEXT_EVIDENCE_CASES')
        def passed(row):
            return (row['entry_acquired'] is True and row['resource_witness'] is True
                and row['prior_owned_fds']==row['remaining_owned_fds']==[]
                and row['other_file_preserved'] is True and row['owned_path_resource_released'] is True
                and row['unexpected_error'] is None
                and (row['context_instance_module'] in protocol.module_names(plan['sources'])
                    or row['context_instance_module'].split('.')[0] in protocol.sys.stdlib_module_names)
                and (row['fault']=='NONE' or row['body_failure_propagated'] is True)
                and row.get('repeat_pass') is True and row.get('repeat_remaining_owned_fds')==[]
                and row.get('repeat_other_file_preserved') is True
                and row.get('repeat_owned_path_resource_released') is True)
        if label=='PASS':
            c.require(actual==expected and all(r['contract_pass'] is True and passed(r) for r in rows),
                      'CONTEXT_EVIDENCE_FALSE_PASS')
        else:
            c.require(rows[-1]['contract_pass'] is False and not passed(rows[-1])
                and rows[-1]['entry_acquired'] is True and rows[-1]['resource_witness'] is True
                and all(r['contract_pass'] is True and passed(r) for r in rows[:-1]),
                'CONTEXT_EVIDENCE_FALSE_FAIL')



def verify_execution(directory):
    """hash、元の公開参照、namespace、有限oracleの保存内容を照合する。"""
    directory=Path(directory)
    plan,plan_sha=read(directory/'plan.json');receipt,receipt_sha=read(directory/'receipt.json')
    launch,_=read(directory/'launch.json')
    c.require(plan['kind']=='FINITE_PATH_CONTEXT_EXECUTION_PLAN_V1'
        and plan['event']==protocol.EVENT and plan['faults']==list(protocol.FAULTS)
        and plan['initial_other_file_contents']==['','prior-owned-by-another-invocation']
        and plan['limits']==dict(cpu_seconds=2,wall_seconds=5,memory_bytes=134217728,
            output_bytes=131072,file_bytes=1048576,open_files=64,processes=16)
        and plan['original_implementation_mutated'] is False
        and receipt['plan_sha256']==launch['plan_sha256']==c.digest(plan)
        and receipt['native_campaigns']==1 and receipt['automatic_retry'] is False
        and launch['credential_or_home_mounted'] is False and launch['network_namespace_isolated'] is True,
        'CONTEXT_EVIDENCE_EXECUTION_BINDING')
    c.require(set(plan['method']) in (set(protocol.LEGACY_METHODS),set(protocol.METHODS)),
              'CONTEXT_EVIDENCE_METHOD_SET')
    for name,sha in plan['method'].items():
        path=directory/'method'/name
        c.require(not path.is_symlink() and path.stat().st_size<=262144
            and hashlib.sha256(path.read_bytes()).hexdigest()==sha,'CONTEXT_EVIDENCE_METHOD_DRIFT')
    verify_specification(plan)
    files={str(p.relative_to(directory/'target')) for p in (directory/'target').rglob('*') if p.is_file()}
    c.require(files==set(plan['sources']),'CONTEXT_EVIDENCE_SOURCE_INVENTORY')
    for name,text in plan['sources'].items():
        path=directory/'target'/name
        c.require(not path.is_symlink() and path.read_text()==text,'CONTEXT_EVIDENCE_SOURCE_DRIFT')
    raw=(directory/'observed.json').read_bytes()
    c.require(len(raw)<=plan['limits']['output_bytes'] and hashlib.sha256(raw).hexdigest()==receipt['observed_sha256'],
              'CONTEXT_EVIDENCE_OBSERVATION_BYTES')
    if receipt['status']=='STOPPED':
        c.require(receipt['label'] is None and receipt['label_authority']=='UNKNOWN',
                  'CONTEXT_EVIDENCE_STOPPED_GOLD')
        observed=None
    else:
        c.require(receipt['status']=='COMPLETE' and receipt['returncode']==0 and receipt['error'] is None,
                  'CONTEXT_EVIDENCE_RECEIPT')
        observed=json.loads(raw);c.check_seal(observed)
        verify_observation(plan,observed,launch,receipt)
    return c.seal(dict(kind='ARCHIVED_CONTEXT_EXECUTION_CHECK_V1',plan_sha256=plan_sha,
        receipt_sha256=receipt_sha,label=receipt['label'],label_authority=receipt['label_authority'],
        archived_method_hashes_verified=True,original_source_bytes_verified=True,
        namespace_and_finite_observation_verified=observed is not None,
        native_campaigns=0,provider_calls=0,trusted_time_attested=False,
        adversarial_target_semantics_certified=False,execution_authority=False))



def verify_specification(plan):
    """保存した公開例、元span、公開bindingの有限一致を照合する。"""
    found=protocol.recipes(plan['sources'],plan['documents']);recipe=plan['recipe']
    if recipe.get('recipe_origin')=='AUTHOR_DOCUMENTATION_AND_PUBLIC_SIGNATURE':
        c.require(recipe in found['rows'] and set(plan['method'])==set(protocol.METHODS),
                  'CONTEXT_EVIDENCE_SIGNATURE_RECIPE_DRIFT')
        text=plan['sources'][recipe['source_member']]
        c.require(hashlib.sha256(text.encode()).hexdigest()==recipe['source_member_sha256']
            ==recipe['document_sha256'] and recipe['implementation_behavior_used_as_specification'] is False
            and recipe['generated_python_example_presented_as_author_documentation'] is False,
            'CONTEXT_EVIDENCE_SIGNATURE_SOURCE_DRIFT')
        for span in recipe['documentation_spans']:
            c.require(type(span['start']) is int and type(span['end']) is int
                and 0<=span['start']<span['end']<=len(text)
                and hashlib.sha256(text[span['start']:span['end']].encode()).hexdigest()==span['sha256'],
                'CONTEXT_EVIDENCE_SIGNATURE_DOCUMENTATION_DRIFT')
        return
    text=plan['documents'][recipe['document']];span=recipe['span']
    c.require(recipe['binding'] in [r['binding'] for r in found['rows']]
        and hashlib.sha256(text.encode()).hexdigest()==recipe['document_sha256']
        and type(span['start']) is int and type(span['end']) is int and 0<=span['start']<span['end']<=len(text)
        and hashlib.sha256(text[span['start']:span['end']].encode()).hexdigest()==span['sha256']
        and any(start==span['start'] and end==span['end']
            and hashlib.sha256(code.encode()).hexdigest()==recipe['example_sha256']
            for start,end,code in protocol.example_blocks(text)), 'CONTEXT_EVIDENCE_SPECIFICATION_DRIFT')

