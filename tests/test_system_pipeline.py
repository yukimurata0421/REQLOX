"""Source snapshot and source-fidelity replay boundaries; owned controls only."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reqlox_knowledge import reference, storage
from reqlox_system import core

path=Path(__file__).resolve().parents[1]/'examples/knowledge/create_system_replay_fixture.py'
spec=importlib.util.spec_from_file_location('owned_system_control',path)
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class SystemPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.bundle=fixture.build_fixture()

    def changed(self,mutate):
        value=deepcopy(self.bundle);mutate(value);return reference.seal(value)

    def metadata(self,snapshot,name,value):
        snapshot['metadata'][name]=core._blob(reference.canonical(value))
        if name!='package-manifest.v0.1.json':
            package=core._json(core._decode(snapshot['metadata']['package-manifest.v0.1.json']))
            next(r for r in package['artifacts'] if r['path']==name)['sha256']=snapshot['metadata'][name]['sha256']
            snapshot['metadata']['package-manifest.v0.1.json']=core._blob(reference.canonical(package))
        return reference.seal(snapshot)

    def test_same_frozen_inputs_same_ir_questions_and_routes_without_target_execution(self):
        with patch.object(core.judge_client,'api_key',side_effect=AssertionError('credential read')), \
             patch.object(core.judge_client,'urllib_transport',side_effect=AssertionError('network')):
            a,_=core.evaluate(self.bundle);b,_=core.evaluate(deepcopy(self.bundle))
        self.assertEqual(a,b);self.assertEqual(a['elements'],6)
        self.assertEqual(a['status'],'REPLAY_COMPLETE')
        self.assertFalse(a['source_code_executed']);self.assertFalse(a['canonical_system_ir'])
        self.assertFalse(a['cross_ir_applicability_judged']);self.assertEqual(a['provider_calls'],0)

    def test_file_hash_and_missing_file_are_rejected(self):
        snapshot=deepcopy(self.bundle['plan']['snapshot'])
        snapshot['files']['src/owned.py']=core._blob(b'print("different")')
        with self.assertRaisesRegex(ValueError,'SYSTEM_SOURCE_HASH'):core.freeze(reference.seal(snapshot))
        snapshot=deepcopy(self.bundle['plan']['snapshot']);snapshot['files'].pop('src/owned.py')
        with self.assertRaisesRegex(ValueError,'SYSTEM_SOURCE_COVERAGE'):core.freeze(reference.seal(snapshot))

    def test_rehashed_tree_coverage_claim_cannot_hide_missing_files(self):
        snapshot=deepcopy(self.bundle['plan']['snapshot'])
        manifest=core._json(core._decode(snapshot['metadata']['source-manifest.v0.1.json']))
        manifest['source_tree_coverage']['tracked_file_count']+=1
        with self.assertRaisesRegex(ValueError,'SYSTEM_TREE_COVERAGE'):
            core.freeze(self.metadata(snapshot,'source-manifest.v0.1.json',manifest))

    def test_rehashed_graph_receipt_or_identity_drift_is_rejected(self):
        for field in ('mapping_sha256','counts'):
            snapshot=deepcopy(self.bundle['plan']['snapshot'])
            manifest=core._json(core._decode(snapshot['metadata']['source-manifest.v0.1.json']))
            if field=='counts':manifest['native_validation'][field]['nodes']+=1
            else:manifest['native_validation'][field]='0'*64
            with self.assertRaisesRegex(ValueError,'SYSTEM_GRAPH_RECEIPT_DRIFT'):
                core.freeze(self.metadata(snapshot,'source-manifest.v0.1.json',manifest))
        snapshot=deepcopy(self.bundle['plan']['snapshot'])
        package=core._json(core._decode(snapshot['metadata']['package-manifest.v0.1.json']))
        package['refs']['system_ir_revision']='rev_20261013T000000Z_'+'2'*12
        with self.assertRaisesRegex(ValueError,'SYSTEM_IDENTITY_BINDING'):
            core.freeze(self.metadata(snapshot,'package-manifest.v0.1.json',package))

    def test_rehashed_ir_witness_cannot_replace_projection(self):
        snapshot=deepcopy(self.bundle['plan']['snapshot'])
        system=deepcopy(self.bundle['plan']['system_ir']);system['architecture']['components'][0]['name']='Stronger claim'
        with self.assertRaisesRegex(ValueError,'SYSTEM_PROJECTION_DRIFT'):
            core.freeze(self.metadata(snapshot,'system-ir.v0.1.json',system))

    def test_question_state_binding_prevents_response_reuse(self):
        def mutate(bundle):
            exchange=bundle['exchanges'][0]['exchange'];request=json.loads(core._decode(exchange['request']))
            request['state']['evaluation_scope']='INCIDENT_IR_ONLY';exchange['request']=core.wire(reference.canonical(request))
        with self.assertRaisesRegex(ValueError,'REPLAY_REQUEST_BINDING'):core.evaluate(self.changed(mutate))

    def test_duplicate_or_foreign_batches_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'SYSTEM_DUPLICATE_ATTEMPT'):
            core.evaluate(self.changed(lambda v:v['exchanges'].__setitem__(1,deepcopy(v['exchanges'][0]))))
        with self.assertRaisesRegex(ValueError,'SYSTEM_REPLAY_BATCH'):
            core.evaluate(self.changed(lambda v:v['exchanges'][0].update(batch_id='other-lane')))

    def test_missing_and_failed_answers_remain_unknown_with_no_retry(self):
        missing,_=core.evaluate(self.changed(lambda v:v['exchanges'].pop()))
        self.assertEqual(missing['status'],'REPLAY_PARTIAL');self.assertEqual(missing['missing_or_failed_answers'],1)
        def fail(v):
            e=v['exchanges'][0]['exchange'];e.update(http_status=503,response=core.wire(b'{"error":"owned control"}'))
        failed,_=core.evaluate(self.changed(fail));self.assertEqual(failed['missing_or_failed_answers'],1)
        self.assertEqual(failed['provider_calls'],0)
        self.assertEqual(failed['judgments'][0]['route']['reason'],'NO_VALID_JEV_JUDGMENT')

    def test_invalid_model_answer_remains_unknown(self):
        def bad(v):
            e=v['exchanges'][0]['exchange'];body=core._json(core._decode(e['response']));body['model']='other'
            e['response']=core.wire(reference.canonical(body))
        result,_=core.evaluate(self.changed(bad));self.assertEqual(result['missing_or_failed_answers'],1)

    def test_routing_preserves_insufficient_contradicted_and_below_floor(self):
        for choice,confidence,reason in [('INSUFFICIENT_INFORMATION',1,'INSUFFICIENT_INFORMATION'),
            ('CONTRADICTED',1,'CONTRADICTED'),('SUPPORTED',.84,'BELOW_UNCALIBRATED_OPERATING_FLOOR')]:
            answer=dict(choice=choice,confidence=confidence,probabilities={k:float(k==choice) for k in core.CRITERIA})
            self.assertEqual(core.route(answer)['reason'],reason)
            self.assertEqual(core.route(answer)['decision'],'TERMINAL_QUARANTINE')

    def test_method_drift_and_duplicate_json_and_path_traversal_are_rejected(self):
        with patch.object(core,'method_binding',return_value={'other':'0'*64}):
            with self.assertRaisesRegex(ValueError,'SYSTEM_PLAN_OR_METHOD_DRIFT'):core.evaluate(self.bundle)
        with self.assertRaisesRegex(ValueError,'SYSTEM_DUPLICATE_JSON_FIELD'):core._json(b'{"x":1,"x":2}')
        for path in ('/etc/passwd','../secret','a/../b','a\\b'):
            with self.assertRaisesRegex(ValueError,'SYSTEM_SOURCE_PATH'):core._path(path)
        with self.assertRaisesRegex(ValueError,'SYSTEM_NONFINITE_JSON'):core._json(b'{"x":NaN}')

    def test_bounded_ast_excerpts_do_not_execute_source_or_expand_bare_module_refs(self):
        files={'src/owned.py':b'raise RuntimeError("must not execute")\nclass Worker:\n    def run(self):\n        return 1\n'}
        self.assertIsNone(core._excerpt('owned',files,{}))
        self.assertEqual(core._excerpt('owned::Worker.run',files,{})['resolution'],'PYTHON_AST_SYMBOL')
        with self.assertRaisesRegex(ValueError,'SYSTEM_EXCERPT_LINE_BOUND'):
            core._excerpt('src/owned.py',{'src/owned.py':b'x'*6001},{})

    def test_cli_prepare_export_replay_keep_private_original_bytes(self):
        from reqlox import knowledge_cli
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=fixture.build_package(root/'package');state=root/'state'
            output=io.StringIO()
            with redirect_stdout(output):code=knowledge_cli.main(['system-prepare','--package',str(package),'--state-dir',str(state)])
            self.assertEqual(code,0);plan=storage.checked_record(json.loads(output.getvalue())['plan'])
            self.assertEqual(plan,self.bundle['plan'])
            storage.save(root/'exchanges.json',self.bundle['exchanges'])
            saved=core.export_archive(json.loads(output.getvalue())['plan'],root/'exchanges.json',state_dir=state)
            left=core.replay(saved['bundle'],state_dir=state);right=core.replay(saved['bundle'],state_dir=state)
            self.assertEqual(left['result_sha256'],right['result_sha256'])
            directory=Path(left['output']);row=self.bundle['exchanges'][0]
            self.assertEqual((directory/'original-exchanges'/(row['batch_id']+'-response.json')).read_bytes(),
                             core._decode(row['exchange']['response']))
            self.assertTrue(all(p.stat().st_mode&0o077==0 for p in directory.rglob('*')))

    def test_capture_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=fixture.build_package(root/'package')
            p=package/'source/stream_recovery_control/src/owned.py';p.unlink();p.symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError,'SYSTEM_SOURCE_FILE_BOUND'):core.capture_package(package)

    def test_invalid_source_schema_is_sanitized_and_never_fetched(self):
        snapshot=deepcopy(self.bundle['plan']['snapshot'])
        path='harness/contracts/evidence_lineage.v1.schema.json'
        snapshot['files'][path]=core._blob(b'{"$ref":"https://example.invalid/never-fetch"}')
        manifest=core._json(core._decode(snapshot['metadata']['source-manifest.v0.1.json']))
        next(r for r in manifest['source_files'] if r['path']==path)['sha256']=snapshot['files'][path]['sha256']
        snapshot=self.metadata(snapshot,'source-manifest.v0.1.json',manifest)
        rows=[core._json(line) for line in core._decode(snapshot['metadata']['evidence.v0.1.jsonl']).splitlines()]
        row=next(r for r in rows if r['source_file']['path']==path)
        digest=snapshot['files'][path]['sha256'];row['source_file']['sha256']=digest
        row['content_sha256']=digest;row['extraction']['input_sha256']=digest
        payload=b''.join(reference.canonical(r)+b'\n' for r in rows)
        snapshot['metadata']['evidence.v0.1.jsonl']=core._blob(payload)
        package=core._json(core._decode(snapshot['metadata']['package-manifest.v0.1.json']))
        next(r for r in package['artifacts'] if r['path']=='evidence.v0.1.jsonl')['sha256']=core.hashlib.sha256(payload).hexdigest()
        snapshot=self.metadata(snapshot,'package-manifest.v0.1.json',package)
        with self.assertRaisesRegex(ValueError,'SYSTEM_SOURCE_SCHEMA'):core.freeze(snapshot)


if __name__=='__main__':unittest.main()
