"""Owned synthetic protocol control. No real Target sources or real JEV answers."""
import json
from pathlib import Path
import tempfile
from reqlox_knowledge import reference, storage
from reqlox_system import core, projection


def build_package(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    created='2026-10-13T00:00:00Z';sid='tsm_'+'1'*20;revision='rev_20261013T000000Z_'+'1'*12
    node=dict(id='owned_worker',label='Owned synthetic worker',kind='PROCESS',layer='owned_layer',host='owned_host',
        authority='NONE',failure_domain='PROCESS',source_refs=['src/owned.py'],implementation_refs=['owned::Worker.run'],
        unit_templates=[],identity_fields=['pid'],freshness_fields=['sequence'],current_value_policy='SOURCE_ONLY')
    graph=dict(schema='cra.evidence_lineage.v1',status='CURRENT_STATE_SPEC',purpose='Owned synthetic protocol control',
        boundaries=dict(canonical_scope='Fictitious example only',excluded_current_values=['live state'],mutation_authority='NONE'),
        owner_verification=dict(catalog='OWNED_SYNTHETIC_CONTROL',component_id='owned_worker',duplication_policy='REFERENCE_CANONICAL_CATALOG'),
        live_overlay_contract={'fixture':True},
        hosts=[dict(id='owned_host',expected_host_id='synthetic-host',role='EXAMPLE',authority='NONE')],
        layers=[dict(id='owned_layer',label='Example layer',order=1)],nodes=[node],
        edges=[dict(id='owned_dependency',**{'from':'owned_worker','to':'owned_worker'},relationship='Example self-reference',
            mode='SOURCE_ONLY',evidence='Synthetic declaration',required_bindings=['sequence'],assertion='Example only',
            failure_policy={k:'NOT_OBSERVED' for k in ('evidence_loss_domain','current_sut_state','soak_impact','breach_domain')},
            contract_refs=['src/owned.py'])],
        restart_domains=[dict(id='owned_restart',label='Example process',scope_nodes=['owned_worker'],event='EXAMPLE_EXIT',
            identity_changes=['pid'],must_preserve=['source hash'],observed_by_edges=['owned_dependency'],observation_sources=['src/owned.py'],
            normal_meaning='Example only',soak_rule='NOT_QUALIFIED',new_epoch_when=['EXAMPLE_EXIT'])],
        failure_modes=[dict(id='owned_surface',label='Synthetic exception',trigger='EXAMPLE',affected_nodes=['owned_worker'],
            evidence_edges=['owned_dependency'],restart_domains=['owned_restart'],source_refs=['src/owned.py'],
            detector_refs=['owned::Worker.run'],oracle_refs=[],sequence_test_refs=[],evidence_absence_domain='EXAMPLE',
            formal_rule='NOT_QUALIFIED',required_qualification=['Separate real evidence'])])
    # This fixture schema validates only owned controls; it is never substituted
    # for a real package's captured source schema.
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object',
            'required':list(graph),'properties':{k:{'const':v} for k,v in graph.items()}}
    policy={'owned_synthetic_control':True}
    payloads={projection.GRAPH_PATH:reference.canonical(graph),projection.POLICY_PATH:reference.canonical(policy),
        'harness/contracts/evidence_lineage.v1.schema.json':reference.canonical(schema),
        'src/owned.py':b'raise RuntimeError("TARGET_CODE_MUST_NOT_EXECUTE")\nclass Worker:\n    def run(self):\n        return "owned example"\n'}
    digest=lambda value:core.hashlib.sha256(value).hexdigest()
    counts={k:len(graph[k]) for k in ('hosts','layers','nodes','edges','restart_domains','failure_modes')}
    manifest=dict(id=sid,contract_type='TargetSourceManifest',contract_version='0.1.0',revision_id=revision,created_at=created,
        target_id=projection.TARGET_ID,source_repository=dict(logical_name='OWNED_SYNTHETIC_CONTROL',git_commit_sha1='1'*40,
            git_tree_sha1='2'*40,branch_observed='example',worktree_clean_at_capture=True),
        source_files=[dict(path=p,snapshot_path='source/stream_recovery_control/'+p,sha256=digest(v),role='SOURCE_IMPLEMENTATION')
                      for p,v in sorted(payloads.items())],
        source_tree_coverage=dict(tracked_file_count=len(payloads),captured_file_count=len(payloads),omitted_paths=[],
            tracked_paths_sha256=digest(reference.canonical(sorted(payloads)))),
        native_validation=dict(status='PASS',validator='OWNED_SYNTHETIC_RECEIPT_NOT_EXECUTED',
            mapping_sha256=digest(reference.canonical(graph)),counts=counts),
        processing_boundary=dict(visibility='LOCAL_PRIVATE',external_model_disclosure_allowed=False,publication_allowed=False),
        limitations=['OWNED_SYNTHETIC_CONTROL_NOT_RUNTIME_EVIDENCE'])
    evidence=[]
    def add(path,kind,value,content):
        evidence.append(dict(id=projection.stable_id('tev_',sid,path,value),contract_type='TargetEvidence',contract_version='0.1.0',
            created_at=created,source_manifest_id=sid,source_file=dict(path=path,sha256=digest(payloads[path])),
            locator=dict(kind=kind,value=value),content_sha256=digest(content),origin='SOURCE_OBSERVED',
            extraction=dict(method='RAW_FILE_SNAPSHOT' if kind=='WHOLE_FILE' else 'DETERMINISTIC_JSON_POINTER',
                tool='OWNED_SYNTHETIC_CONTROL',input_sha256=digest(payloads[path])),
            verification=dict(status='AUTO_VERIFIED',method='HASH_MATCH' if kind=='WHOLE_FILE' else 'HASH_AND_POINTER_MATCH')))
    for path,raw in sorted(payloads.items()):add(path,'WHOLE_FILE','WHOLE_FILE',raw)
    for key in counts:add(projection.GRAPH_PATH,'JSON_POINTER','/'+key,reference.canonical(graph[key]))
    system=projection.project(graph,policy,manifest,evidence)
    for path,raw in payloads.items():
        target=directory/'source/stream_recovery_control'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    metadata={'source-manifest.v0.1.json':reference.canonical(manifest),'system-ir.v0.1.json':reference.canonical(system),
        'evidence.v0.1.jsonl':b''.join(reference.canonical(e)+b'\n' for e in evidence),
        'system-contract.v0.1.json':b'{"owned_synthetic_control":true}'}
    package=dict(id='tpm_'+'1'*20,contract_type='TargetPackageManifest',contract_version='0.1.0',revision_id=revision,created_at=created,
        target_id=projection.TARGET_ID,artifacts=[dict(path=k,sha256=digest(v),record_count=len(evidence) if k.endswith('jsonl') else 1,
            contract_type={'source-manifest.v0.1.json':'TargetSourceManifest','system-ir.v0.1.json':'SystemIR',
                'evidence.v0.1.jsonl':'TargetEvidence','system-contract.v0.1.json':'SystemContract'}[k]) for k,v in metadata.items()],
        refs=dict(source_manifest_id=sid,system_ir_id=system['id'],system_ir_revision=revision,
            **system['target_specific_context']['derived_ir_refs'],system_contract_id=projection.stable_id('scontract_',projection.TARGET_ID)),
        gates={k:k in ('source_identity_verified','source_graph_complete','system_ir_candidate_ready') for k in
            ('source_identity_verified','source_graph_complete','system_ir_candidate_ready','canonical_system_ir','human_contract_approved',
             'jev_required','applicability_authorized','experiment_generation_authorized','fault_injection_authorized')},
        next_action='HUMAN_REVIEW_SYSTEM_IR_AND_ANNOTATE_RELEVANT_FAILURE_SLICE')
    metadata['package-manifest.v0.1.json']=reference.canonical(package)
    for name,raw in metadata.items():(directory/name).write_bytes(raw)
    return directory


def synthetic_bundle(plan):
    exchanges=[]
    for batch in plan['batches']:
        answer=dict(type='choice',choice='SUPPORTED',confidence=.95,probabilities={k:float(k=='SUPPORTED') for k in core.CRITERIA})
        response=dict(model=core.judge_client.PINNED_MODEL,answers={'q001':answer},usage=dict(input_tokens=100,output_tokens=20),
                      request_id='OWNED_SYNTHETIC_CONTROL')
        exchanges.append(dict(batch_id=batch['id'],exchange=dict(request=core.wire(core.outbound(batch)),
            response=core.wire(reference.canonical(response)),http_status=200)))
    return reference.seal(dict(schema_version=core.BUNDLE_SCHEMA,response_provenance='OWNED_SYNTHETIC_CONTROL',plan=plan,exchanges=exchanges))


def build_fixture():
    with tempfile.TemporaryDirectory() as directory:
        return synthetic_bundle(core.freeze(core.capture_package(build_package(directory))))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--package-output',type=Path)
    args=parser.parse_args()
    if args.package_output:build_package(args.package_output)
    value=build_fixture();storage.save(args.output,value)
    print(json.dumps(dict(status='OWNED_SYNTHETIC_CONTROL_CREATED',bundle_sha256=value['record_sha256'],provider_calls=0,target_executions=0)))


if __name__=='__main__':main()
