"Project supplied failure spans into finite cleanup programs."
import ast
import errno
import hashlib
from pathlib import Path
import re

from . import reliability_source_study as study

c=study.c
EVENT='FINITE_GENERATED_CLEANUP_CONDITION_V1'
ACTIONS=('NONE','DELETE_ERROR_ONCE','REMOVE_OWNED_BEFORE_CLEANUP','REMOVE_OWNED_BEFORE_DELETE',
         'REMOVE_SIBLING_AFTER_FIRST_DELETE')
METHODS=(*study.METHODS,'reliability_incident_conditions.py',
         'reliability_incident_conditions_worker.py','run_reliability_incident_conditions.py',
         'reliability_context_evidence.py')


def methods():
    return {n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in METHODS}


def program(action, error=None):
    c.require(action in ACTIONS and (action=='DELETE_ERROR_ONCE')==(error is not None),
              'INCIDENT_CONDITION_ACTION')
    if error is not None:
        c.require(type(error) is str and re.fullmatch(r'E[A-Z0-9]{1,20}',error)
            and type(getattr(errno,error,None)) is int, 'INCIDENT_CONDITION_ERRNO')
    return c.seal(dict(kind='FINITE_OWNED_CLEANUP_CONDITION_PROGRAM_V1',action=action,errno=error,
        phase='CLEANUP_AND_FRESH_REPEAT',maximum_events_per_cleanup=1,
        owned_regular_files_only=True,other_owner_preserved=True,execution_authority=False))


def project(source):
    "Project."
    c.check_seal(source)
    c.require(source['kind']=='PUBLIC_OBSERVED_FAILURE_SOURCE_V1'
        and source['source_type'] in ('ISSUE_REPORT','POSTMORTEM','OWNED_SYNTHETIC_REPORT')
        and type(source['url']) is str and source['url'].startswith('https://')
        and source['retrieval_complete'] is True and source['execution_authority'] is False
        and re.fullmatch('[a-f0-9]{64}',source['raw_sha256']) is not None,
        'INCIDENT_CONDITION_SOURCE')
    documents=source['documents']
    c.require(type(documents) is dict and 1<=len(documents)<=100
        and all(type(k) is str and type(v) is str for k,v in documents.items())
        and sum(len(v.encode()) for v in documents.values())<=65536,'INCIDENT_CONDITION_SOURCE_BOUND')
    rows=[];held=[]
    for document,text in sorted(documents.items()):
        for match in re.finditer(r'[^\r\n]+(?:\r?\n(?!\r?\n)[^\r\n]+)*',text):
            paragraph=match.group()
            if len(paragraph)>2048:continue
            operation=re.search(r'\b(?:rmtree|unlink|remove|removing)\b',paragraph,re.I)
            observed=re.search(r'\b(?:raised|raises|failure|fails|failed|triggers)\b',paragraph,re.I)
            disappeared=re.search(r'\b(?:removed|deleted|disappears?|vanishes?)\b',paragraph,re.I)
            temporal=re.search(r'\b(?:between|before|race condition)\b',paragraph,re.I)
            missing=re.search(r'\bFileNotFound(?:Error|\s+exception|\s+error)?\b|\bENOENT\b',paragraph,re.I)
            if not operation or not observed:continue
            if re.search(r'\b(?:should not|never|does not|doesn.t|not raised|no failure)\b',paragraph,re.I):
                held.append(dict(document=document,reason='NEGATED_OR_EXPECTED_CLAIM'));continue
            value=None
            if (re.search(r'\bother file\b',paragraph,re.I)
                and re.search(r'\bwhen\b[^.]{0,200}\b(?:file|files)\b[^.]{0,100}\bremoved\b',paragraph,re.I)):
                value=program('REMOVE_SIBLING_AFTER_FIRST_DELETE')
            elif disappeared and temporal and missing:
                value=program('REMOVE_OWNED_BEFORE_DELETE')
            else:
                errors=set(re.findall(r'\bE[A-Z0-9]{1,20}\b',paragraph))
                supported=sorted(q for q in errors if type(getattr(errno,q,None)) is int)
                if len(supported)==1:value=program('DELETE_ERROR_ONCE',supported[0])
                elif supported:held.append(dict(document=document,reason='AMBIGUOUS_ERROR_NAMES'))
            if value is not None and not any(r['program']==value for r in rows):
                rows.append(dict(program=value,document=document,document_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    span=dict(start=match.start(),end=match.end(),sha256=hashlib.sha256(paragraph.encode()).hexdigest()),
                    inference='DETERMINISTIC_SCHEDULE_FROM_REPORTED_ORDER_OR_ERROR',
                    occurrence_count_basis='OWNER_FINITE_POLICY_NOT_SOURCE_FREQUENCY'))
    c.require(1<=len(rows)<=4,'INCIDENT_CONDITION_NO_UNAMBIGUOUS_SUPPORTED_SPAN')
    return c.seal(dict(kind='SOURCE_GENERATED_CLEANUP_CONDITIONS_V1',source_record_sha256=c.digest(source),
        rows=rows,held=held,target_sources_read=False,source_is_requirement_authority=False,
        semantic_support_certified=False,natural_incident_reproduced=False,execution_authority=False))


def generic_programs():
    
    return [program('DELETE_ERROR_ONCE','EINTR'),program('DELETE_ERROR_ONCE','EIO'),
            program('REMOVE_OWNED_BEFORE_CLEANUP'),program('REMOVE_OWNED_BEFORE_DELETE')]


def target_guided_programs(sources):
    "Target guided programs."
    hints=[]
    for member,text in sorted(sources.items()):
        tree=ast.parse(text)
        deletes=[v for v in ast.walk(tree) if isinstance(v,ast.Call) and isinstance(v.func,ast.Attribute)
            and v.func.attr in ('unlink','remove','rmtree')]
        repeated=any(isinstance(v,(ast.For,ast.While)) and any(q in deletes for q in ast.walk(v))
            for v in ast.walk(tree))
        if len(deletes)>1 or repeated or any(v.func.attr=='rmtree' for v in deletes):
            hints.append(dict(member=member,source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                deletion_call_lines=[v.lineno for v in deletes],repeated_deletion_syntax=repeated,
                runtime_multi_file_behavior_certified=False))
    baseline=generic_programs()
    if hints:
        ordered=[program('REMOVE_SIBLING_AFTER_FIRST_DELETE'),program('REMOVE_OWNED_BEFORE_DELETE'),
            baseline[0],baseline[1],baseline[2]]
    else:ordered=baseline+[program('REMOVE_SIBLING_AFTER_FIRST_DELETE')]
    return c.seal(dict(kind='SOURCE_BLIND_TARGET_GUIDED_CLEANUP_PROGRAMS_V1',programs=ordered,
        hints=hints,source_payload_read=False,implementation_behavior_used_as_specification=False,
        complete_condition_search_certified=False,execution_authority=False))


def freeze(base,source,*,budget=4,arm_order=('NO_SOURCE','SOURCE'),baseline_policy='FIXED_GENERIC_V1'):
    c.require(type(budget) is int and 1<=budget<=4,'INCIDENT_CONDITION_BUDGET')
    c.require(tuple(arm_order) in (('NO_SOURCE','SOURCE'),('SOURCE','NO_SOURCE')),'INCIDENT_CONDITION_ARM_ORDER')
    c.require(base==study.context.plan(base['sources'],base['recipe'],base['documents'],
        provenance=base['provenance'],forecast_ref=base['forecast_ref']),'INCIDENT_CONDITION_BASE_DRIFT')
    c.require(baseline_policy in ('FIXED_GENERIC_V1','TARGET_GUIDED_SOURCE_BLIND_V1'),
        'INCIDENT_CONDITION_BASELINE_POLICY')
    projection=project(source);generated=[r['program'] for r in projection['rows']]
    guided=target_guided_programs(base['sources']) if baseline_policy=='TARGET_GUIDED_SOURCE_BLIND_V1' else None
    baseline=guided['programs'] if guided else generic_programs()
    ordered=generated+[v for v in baseline if v not in generated]
    envelope=[program('NONE'),*baseline,*[v for v in generated if v not in baseline]]
    return c.seal(dict(kind='FROZEN_SOURCE_GENERATED_CONDITION_STUDY_V1',event=EVENT,base_plan=base,
        source=source,source_projection=projection,method=methods(),arm_order=list(arm_order),
        plans=dict(NO_SOURCE=baseline[:budget],SOURCE=ordered[:budget]),
        maximum_discovery_campaigns_per_arm=budget,common_confirmation_envelope=envelope,
        repair_policy='SAME_GENERATOR; EIO_EINTR_BOUNDED_RETRY; VERIFIED_ABSENCE_ONLY_IF_DISCOVERED',
        owner_requirement='Release owned resources, preserve body failures and other-owner contents under '
            'one transient deletion error or the declared disappearance of an owned regular file. '
            'This policy is owned separately from the public failure report.',
        source_program_generation_tested=True,supported_primitive_library_shared=True,
        **(dict(target_guidance=guided) if guided else {}),
        no_source_policy=('SOURCE_BLIND_TARGET_GUIDED_CLEANUP_PROGRAMS_V1' if guided
            else 'FIXED_GENERIC_ERROR_AND_MISSING_STATE_PROGRAMS_V1'),
        no_source_target_guided_condition_generation=guided is not None,baseline_is_exhaustive=False,
        source_conditions_already_in_full_generic_envelope=all(v in baseline for v in generated),
        generated_programs_outside_generic_envelope=[c.digest(v) for v in generated if v not in baseline],
        new_condition_family_proven=False,independent_unused_pair_verified=False,
        natural_incident_transfer_certified=False,execution_authority=False))


def child_plan(base,value):
    c.require(value==program(value['action'],value['errno']),'INCIDENT_CONDITION_PROGRAM_DRIFT')
    return c.seal(dict(kind='FINITE_GENERATED_CLEANUP_EXECUTION_PLAN_V1',event=EVENT,
        base_plan=base,program=value,method=methods(),source_payload_disclosed=False,execution_authority=False))


def repair(sources,failed_programs):
    c.require(bool(failed_programs) and all(v==program(v['action'],v['errno']) for v in failed_programs),
              'INCIDENT_CONDITION_REPAIR_INPUT')
    absent=any(v['action'].startswith(('REMOVE_OWNED_','REMOVE_SIBLING_')) for v in failed_programs)
    return study.candidate(sources,retry_errnos=('EIO','EINTR'),ignore_absent=absent)


def outcome(value,raw,hits):
    "Outcome."
    if value['action']=='NONE':return raw['label']
    if not hits:return None
    if raw['label']=='PASS':
        required={f"case-{r['other_file_case']}-{r['fault']}:{phase}" for r in raw['rows']
                  for phase in ('CLEANUP','CLEANUP_REPEAT')}
        if {h['key'] for h in hits}!=required:return None
    return raw['label']


def comparison(frozen,results,confirmations,baseline=None):
    c.check_seal(frozen);c.require(set(results)=={'NO_SOURCE','SOURCE'},'INCIDENT_CONDITION_ARMS')
    faults={};unknown={};adopted={};first={};pairs={}
    for arm,values in frozen['plans'].items():
        rows=results[arm]
        c.require([r['program_sha256'] for r in rows]==[c.digest(v) for v in values]
            and all(r['label'] in (None,'PASS','FAIL') for r in rows),'INCIDENT_CONDITION_RESULT_BINDING')
        faults[arm]=[r['program_sha256'] for r in rows if r['label']=='FAIL']
        unknown[arm]=[r['program_sha256'] for r in rows if r['label'] is None]
        first[arm]=next((i+1 for i,r in enumerate(rows) if r['label']=='FAIL'),None)
        pairs[arm]={r['program_sha256']:r['label'] for r in rows}
        checks=confirmations.get(arm,[])
        c.require(not checks or [r['program_sha256'] for r in checks]==[
            c.digest(v) for v in frozen['common_confirmation_envelope']],'INCIDENT_CONDITION_CONFIRMATION_ENVELOPE')
        c.require(all(r['label'] in (None,'PASS','FAIL') for r in checks),'INCIDENT_CONDITION_CONFIRMATION_LABEL')
        adopted[arm]=bool(faults[arm]) and bool(checks) and all(r['label']=='PASS' for r in checks)
    shared=set(pairs['SOURCE'])&set(pairs['NO_SOURCE'])
    disagreement=sorted(q for q in shared if pairs['SOURCE'][q]!=pairs['NO_SOURCE'][q])
    unique=set(faults['SOURCE'])-set(faults['NO_SOURCE'])
    uncertain=sorted(unique&set(pairs['NO_SOURCE']))
    added=sorted(unique-set(pairs['NO_SOURCE']))
    if baseline is not None:
        c.require(baseline['program_sha256']==c.digest(program('NONE')) and baseline['label']=='PASS',
                  'INCIDENT_CONDITION_ORIGINAL_BASELINE')
    return c.seal(dict(kind='SOURCE_GENERATED_CONDITION_COMPARISON_V1',freeze_sha256=c.digest(frozen),
        discovery_faults=faults,unknown_conditions=unknown,first_fault_campaign=first,
        source_only_discovered_programs=added,source_comparison_unknown=uncertain,
        paired_program_disagreements=disagreement,private_candidate_adopted=adopted,
        source_added_adoptions=int(adopted['SOURCE'])-int(adopted['NO_SOURCE']),
        comparison_complete=not any(unknown.values()) and not disagreement,
        source_program_generation_tested=True,new_condition_family_proven=False,
        source_conditions_already_in_full_generic_envelope=frozen['source_conditions_already_in_full_generic_envelope'],
        native_campaigns=sum(map(len,results.values()))+sum(map(len,confirmations.values()))+int(baseline is not None),
        original_normal_context_verified=baseline is not None,
        original_baseline_receipt_sha256=c.digest(baseline) if baseline is not None else None,
        provider_calls=0,unique_original_targets=1,original_implementation_mutated=False,
        independent_generalization_certified=False,natural_source_added_value_certified=False,
        probability_calibration_certified=False,production_adoption=False,execution_authority=False))
