"""Exercise the reusable document, native IR, and bounded provider interfaces."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from reqlox import knowledge
from reqlox_knowledge import corpus, generation, ir, judge_client, native, observed_v2, provider, reference, storage

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / 'reqlox_demo/data/knowledge-example.json').read_text())
DRAFT = json.loads((ROOT / 'examples/knowledge/draft.json').read_text())


def plan():
    return ir.freeze(deepcopy(EXAMPLE['candidate']), deepcopy(EXAMPLE['source_texts']))


def answers(value):
    result = {}
    for request in value['requests']:
        purpose = request['purpose']
        wanted = value['control_key'].get(request['id'], {}).get('wanted') or (
            observed_v2.ATOMIC if purpose == observed_v2.PURPOSE else native.EXPECTED[purpose])
        result[request['id']] = [dict(type='choice', choice=wanted, confidence=.95,
            probabilities={key:float(key == wanted) for key in request['choices']}) for _ in range(3)]
    return result


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reqlox-knowledge-test-')
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, name, value):
        path = self.root / name
        storage.save(path, value)
        return path

    def scope(self, value, identifier='owned-scope', disclose=True, **changes):
        options = dict(identifier=identifier, deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
            maximum_reserved=str(value['maximum_calls'] * .01), per_call_reserved='.01',
            maximum_concurrent_calls=2, external_disclosure_allowed=disclose)
        options.update(changes)
        return provider.make_scope(value, **options)

    def test_import_index_search_preserve_offsets_and_private_state(self):
        imported = knowledge.import_documents(EXAMPLE['documents'], state_dir=self.state)
        indexed = knowledge.build_index(imported['corpus'], dimension=64)
        for mode in ('hybrid','vector','fts'):
            result = knowledge.search(indexed['index'],'worker lock', mode=mode)
            self.assertEqual(len(result['results']),1)
            self.assertFalse(result['ranking_score_is_probability'])
            self.assertIn('renewed the lock',result['results'][0]['excerpt'])
        self.assertEqual(knowledge.search(indexed['index'],'lock',publisher=['Other'])['results'],[])
        for path in self.state.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o077,0)

    def test_changed_document_or_index_component_is_rejected(self):
        imported=knowledge.import_documents(EXAMPLE['documents'],state_dir=self.state)
        manifest=storage.checked_record(imported['corpus'])
        original=storage.private_path(Path(imported['corpus']).parent,manifest['pairs'][0]['document']['storage']['text_path'])
        original.write_text('Different text.')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):knowledge.build_index(imported['corpus'])
        other=knowledge.import_documents(EXAMPLE['documents'],state_dir=self.state)
        indexed=knowledge.build_index(other['corpus'],dimension=64)
        component=Path(indexed['index']).parent/'model-config.json'
        component.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):knowledge.search(indexed['index'],'lock')

    def test_duplicate_urls_and_oversize_inputs_stop_before_import(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_URL'):
            knowledge.import_documents(EXAMPLE['documents']*2,state_dir=self.state)
        with self.assertRaisesRegex(ValueError,'TEXT_BOUND'):
            knowledge.import_documents([dict(EXAMPLE['documents'][0],text='x'*524289)],state_dir=self.state)
        self.assertFalse(self.state.exists())

    def test_explicit_fetch_preserves_acquisition_and_stops_without_retry(self):
        from reqlox_knowledge import retrieval
        from types import SimpleNamespace
        fake=SimpleNamespace(get=lambda *a,**k:None,close=lambda:None)
        with patch.object(retrieval,'fetch_public_document',side_effect=AssertionError('HTTP')):
            self.assertEqual(knowledge.fetch_documents(['https://example.org/report'])['network_calls'],0)
        def fetched(session,url,timeout,bound):
            session.get(url)
            return b'<main><p>The worker renewed the lock.</p></main>',dict(content_type='text/html',final_url=url)
        with patch.object(retrieval,'fetch_public_document',side_effect=fetched):
            result=knowledge.fetch_documents(['https://example.org/report'],state_dir=self.state,execute=True,session=fake)
        self.assertEqual(result['network_calls'],1);self.assertEqual(result['status'],'COMPLETE')
        self.assertTrue((Path(result['output'])/'response-0.bin').is_file())
        with patch.object(retrieval,'fetch_public_document',side_effect=RuntimeError('unavailable')) as transport:
            stopped=knowledge.fetch_documents(['https://example.org/report'],state_dir=self.state,execute=True,session=fake)
        self.assertEqual(stopped['status'],'STOPPED');self.assertEqual(transport.call_count,1)
        self.assertIsNone(stopped['corpus']);self.assertFalse(stopped['automatic_retry'])
        for url in ['http://example.org/report','https://user:pass@example.org','https://example.org:8443/report']:
            with self.assertRaises(ValueError):knowledge.fetch_documents([url])

    def test_storage_refuses_symlink_traversal_and_public_runtime_paths(self):
        with self.assertRaisesRegex(ValueError,'INSIDE_PACKAGE'):storage.private_directory(ROOT/'state')
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):storage.private_directory(link/'state')
        with self.assertRaisesRegex(ValueError,'RELATIVE_PATH'):storage.private_path(self.root,'../outside')
        bad=self.root/'duplicate.json';bad.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON'):storage.read(bad)
        bad.write_text('{"a":NaN}')
        with self.assertRaisesRegex(ValueError,'NONFINITE_JSON'):storage.read(bad)

    def test_native_ir_source_hash_quote_offsets_and_plan_binding(self):
        frozen=plan();ir.validate_plan(frozen)
        changed=deepcopy(EXAMPLE['source_texts']);changed['owned-lock-report']+=' changed'
        with self.assertRaisesRegex(ValueError,'IR_SOURCE_HASH'):ir.freeze(EXAMPLE['candidate'],changed)
        candidate=deepcopy(EXAMPLE['candidate']);candidate['evidence_spans'][0]['start_char']=1
        candidate=reference.seal(candidate)
        with self.assertRaises((ValueError,RuntimeError)):ir.freeze(candidate,EXAMPLE['source_texts'])
        tampered=deepcopy(frozen);tampered['batches'][0]['state']['items']['q000']={}
        with self.assertRaisesRegex(ValueError,'DRIFT'):ir.validate_plan(reference.seal(tampered))

    def test_ir_unknown_missing_repeats_and_negative_control_do_not_promote(self):
        frozen=plan();empty=knowledge.route_ir(frozen,{})
        self.assertIsNone(empty['atomic_projection']);self.assertFalse(empty['structural_comparator_assessment']['gate_passed'])
        good=answers(frozen);routed=knowledge.route_ir(frozen,good)
        self.assertIsNotNone(routed['atomic_projection']);self.assertFalse(routed['natural_truth_certified'])
        assertion=next(r['id'] for r in frozen['requests'] if r['purpose']=='assertion_evidence_fidelity')
        missing=deepcopy(good);missing[assertion]=missing[assertion][:2]
        self.assertIsNone(knowledge.route_ir(frozen,missing)['atomic_projection'])
        negative=next(key for key,value in frozen['control_key'].items() if value['wanted']==observed_v2.NON_ATOMIC)
        bad=deepcopy(good)
        bad[negative]=[dict(choice=observed_v2.ATOMIC,confidence=1,probabilities={c:float(c==observed_v2.ATOMIC) for c in observed_v2.CHOICES})]*3
        routed=knowledge.route_ir(frozen,bad)
        self.assertEqual(routed['structural_comparator_assessment']['false_accepts'],3)
        self.assertIsNone(routed['atomic_projection'])

    def test_ir_alternatives_remain_unresolved(self):
        candidate=deepcopy(EXAMPLE['candidate'])
        event=deepcopy(candidate['event_hypotheses'][0]);event['event_hypothesis_id']='evh_'+'4'*20;event['alternative_index']=1
        candidate['event_hypotheses'].append(event);candidate=reference.seal(candidate)
        frozen=ir.freeze(candidate,EXAMPLE['source_texts']);routed=ir.route(frozen,answers(frozen))
        self.assertIsNone(routed['fidelity_projection']);self.assertIsNone(routed['atomic_projection'])
        self.assertEqual(len(frozen['candidate']['event_hypotheses']),2)

    def test_dry_runs_read_no_credentials_or_tokens_and_disclosure_is_required_to_execute(self):
        frozen=plan();p=self.save('plan.json',frozen);s=self.save('scope.json',self.scope(frozen,disclose=False))
        with patch.object(judge_client,'api_key',side_effect=AssertionError('credentials read')):
            self.assertEqual(knowledge.judge(p,s,state_dir=self.state)['provider_calls'],0)
            with self.assertRaisesRegex(ValueError,'DISCLOSURE'):knowledge.judge(p,s,state_dir=self.state,execute=True)
        generated=generation.freeze(EXAMPLE['source_texts']['owned-lock-report'],source_id='owned-lock-report',project_id='example-project')
        gp=self.save('generation.json',generated);gs=self.save('generation-scope.json',self.scope(generated,disclose=False))
        with patch('subprocess.run',side_effect=AssertionError('authentication')):
            self.assertEqual(knowledge.generate(gp,gs,state_dir=self.state)['provider_calls'],0)
            with self.assertRaisesRegex(ValueError,'DISCLOSURE'):knowledge.generate(gp,gs,state_dir=self.state,execute=True)

    def test_scope_bounds_are_validated_before_it_can_be_saved(self):
        frozen=plan()
        for changes in [dict(maximum_reserved='.001'),dict(per_call_reserved='NaN'),dict(maximum_concurrent_calls=0),
                        dict(identifier='../escape'),dict(deadline_utc='2000-01-01T00:00:00+00:00')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.scope(frozen,**changes)

    def test_ledger_reservations_are_shared_between_parallel_instances(self):
        frozen=plan();scope=self.scope(frozen,maximum_reserved='.06')
        directory=self.root/'ledger';ledgers=[provider.Ledger(directory,scope) for _ in range(2)]
        succeeded=[];lock=threading.Lock()
        def run(i):
            try:ledgers[i%2].reserve('attempt-'+str(i))
            except ValueError:return
            with lock:succeeded.append(i)
        threads=[threading.Thread(target=run,args=(i,)) for i in range(12)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        budget=storage.read(directory/'ledger.json')
        self.assertEqual(len(succeeded),6);self.assertEqual(budget['reserved'],'0.06')
        self.assertTrue(all(row['status']=='OUTCOME_UNKNOWN' for row in budget['attempts']))

    def test_parallel_judge_retains_wire_rounding_and_closed_route(self):
        frozen=plan();expected=answers(frozen);p=self.save('plan.json',frozen);s=self.save('scope.json',self.scope(frozen))
        key=self.root/'api-key';storage.write_bytes(key,b'not-a-real-key')
        active=peak=calls=0;lock=threading.Lock()
        def transport(url,headers,payload,timeout):
            nonlocal active,peak,calls
            body=json.loads(payload)
            with lock:active+=1;peak=max(peak,active);calls+=1
            time.sleep(.015)
            batch=next(b for b in frozen['batches'] if b['state']==body['state'])
            result={}
            for qid,identifier in batch['mapping'].items():
                answer=deepcopy(expected[identifier][0]);answer['probabilities']={k:v*.99 for k,v in answer['probabilities'].items()};result[qid]=answer
            with lock:active-=1
            return 200,json.dumps(dict(model=judge_client.PINNED_MODEL,answers=result,usage=dict(input_tokens=20,output_tokens=10))).encode(),{}
        factory=lambda:judge_client.JevSystemOneClient('not-a-real-key',transport=transport)
        result=provider.execute(p,s,state_dir=self.state,execute=True,api_key_file=key,client_factory=factory)
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual(calls,frozen['maximum_calls']);self.assertEqual(peak,2)
        directory=Path(result['output']);journal=storage.read(directory/'batch-0000-repeat-0.json')
        self.assertTrue(journal['answers']['q000']['normalization_applied'])
        self.assertEqual(journal['answers']['q000']['provider_probability_sum'],.99)
        self.assertEqual(len(list(directory.glob('*-response.json'))),calls)
        routed=storage.checked_record(directory/'route.json');self.assertIsNotNone(routed['atomic_projection'])
        self.assertNotIn('not-a-real-key',repr(factory()))
        self.assertNotIn('not-a-real-key',json.dumps(result))
        with self.assertRaisesRegex(ValueError,'SUCCESSOR'):provider.execute(p,s,state_dir=self.state,execute=True,api_key_file=key,client_factory=factory)

    def test_failed_judge_retains_reservation_response_and_unknowns_without_retry(self):
        frozen=plan();p=self.save('plan.json',frozen);s=self.save('scope.json',self.scope(frozen))
        key=self.root/'api-key';storage.write_bytes(key,b'not-a-real-key')
        calls=[]
        def transport(*args):calls.append(1);return 429,b'{"error":{"code":"RATE_LIMIT"}}',{}
        result=provider.execute(p,s,state_dir=self.state,execute=True,workers=1,api_key_file=key,
            client_factory=lambda:judge_client.JevSystemOneClient('not-a-real-key',transport=transport))
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(len(calls),1)
        directory=Path(result['output']);ledger=storage.read(directory/'ledger.json')
        self.assertTrue(ledger['blocked']);self.assertEqual(ledger['reserved'],'0.01')
        self.assertEqual(len(list(directory.glob('*failed-response.json'))),1)
        self.assertIsNone(storage.checked_record(directory/'route.json')['atomic_projection'])

    def test_key_permissions_and_explicit_key_file_priority(self):
        key=self.root/'api-key';storage.write_bytes(key,b'not-a-real-key')
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'different-key'}):
            self.assertEqual(judge_client.api_key(key_file=key),'not-a-real-key')
        key.chmod(0o644)
        with self.assertRaises(RuntimeError):judge_client.api_key(key_file=key)

    def test_generation_selected_quotes_validated_and_bad_output_preserved(self):
        value=generation.freeze(EXAMPLE['source_texts']['owned-lock-report'],source_id='owned-lock-report',project_id='example-project')
        candidate=generation.materialize(value,dict(payload_json=json.dumps(DRAFT)))
        self.assertEqual(len(candidate['evidence_spans']),1);self.assertFalse(candidate['authority']['gold_truth'])
        bad=deepcopy(DRAFT);bad['observed_assertions'][0]['evidence_ids']=['ev_'+'f'*20]
        with self.assertRaisesRegex(ValueError,'EVIDENCE_SELECTION'):generation.materialize(value,dict(payload_json=json.dumps(bad)))
        p=self.save('generation.json',value);s=self.save('scope.json',self.scope(value,identifier='generation-owned'))
        class Fake:
            def generate_structured(self,**kwargs):
                return dict(output=dict(payload_json=json.dumps(bad)),usage_metadata=dict(promptTokenCount=10,candidatesTokenCount=10,totalTokenCount=20))
        result=generation.execute(p,s,state_dir=self.state,execute=True,client=Fake())
        self.assertEqual(result['status'],'STOPPED');self.assertIsNone(result['candidate'])
        directory=Path(result['output']);self.assertTrue((directory/'response.json').exists())
        self.assertTrue(storage.read(directory/'ledger.json')['blocked'])
        with self.assertRaisesRegex(ValueError,'SUCCESSOR'):generation.execute(p,s,state_dir=self.state,execute=True,client=Fake())

    def test_existing_generation_adapter_wire_protocol_and_incomplete_response_are_checked(self):
        from reqlox_knowledge import generator
        value=generation.freeze(EXAMPLE['source_texts']['owned-lock-report'],source_id='owned-lock-report',project_id='example-project')
        p=self.save('generation.json',value)
        calls=[]
        response=dict(modelVersion=generator.MODEL_ID,usageMetadata=dict(promptTokenCount=10,candidatesTokenCount=20,totalTokenCount=30),
            candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(dict(payload_json=json.dumps(DRAFT))))]))])
        def transport(url,headers,payload,timeout):
            calls.append(url)
            body=json.loads(payload)
            self.assertTrue(url.endswith(generator.MODEL_ID+':generateContent'))
            self.assertEqual(body['generationConfig']['maxOutputTokens'],4096)
            return 200,json.dumps(response).encode()
        def client():return generator.VertexGeminiFlashClient(project_id='example-project',total_attempts=1,
            token_provider=lambda:'owned-token',transport=transport)
        s=self.save('scope.json',self.scope(value,identifier='generator-good'))
        result=generation.execute(p,s,state_dir=self.state,execute=True,client=client())
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual(len(calls),1)
        candidate=storage.checked_record(result['candidate']);ir.check_source(candidate,EXAMPLE['source_texts'])
        self.assertNotIn('owned-token',Path(result['output'],'response.json').read_text())
        response['candidates'][0]['finishReason']='MAX_TOKENS'
        s=self.save('scope-bad.json',self.scope(value,identifier='generator-incomplete'))
        result=generation.execute(p,s,state_dir=self.state,execute=True,client=client())
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(len(calls),2)
        self.assertTrue(Path(result['output'],'failed-response-body.json').exists())
        self.assertIsNone(result['candidate'])

    def test_partial_scores_keep_missing_label_vector_and_infinite_log_loss(self):
        values=EXAMPLE['scores'];result=knowledge.partial_scores(values['rows'],values['categories'])
        self.assertEqual(result['attempted_rows'],2);self.assertEqual(result['scored_rows'],1)
        self.assertEqual(result['unknown_vectors'],1);self.assertEqual(result['unknown_labels'],1)
        self.assertAlmostEqual(result['full_denominator']['brier_bounds'][0],.04)
        self.assertGreater(result['full_denominator']['brier_bounds'][1],1)
        self.assertTrue(result['full_denominator']['log_loss_upper_infinite'])
        self.assertFalse(result['probabilities_calibrated'])
        zero=[dict(values['rows'][0],probabilities=dict(PASS=0.,FAIL=1.))]
        self.assertEqual(knowledge.partial_scores(zero,values['categories'])['known_infinite_log_loss_rows'],1)

    def test_cli_help_import_and_installed_reference_ddl_are_usable(self):
        documents=self.save('documents.json',EXAMPLE['documents'])
        process=subprocess.run([sys.executable,'-m','reqlox','knowledge','import','--documents',str(documents),'--state-dir',str(self.state)],
            cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(process.returncode,0,process.stderr);self.assertEqual(json.loads(process.stdout)['documents'],1)
        ddl=knowledge.schema_path();self.assertTrue(ddl.is_file());self.assertIn('vector',ddl.read_text())


if __name__=='__main__':unittest.main()
