"""Boundary checks for source-to-IR replay and exact request/response association."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import importlib.util
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reqlox import knowledge
from reqlox_knowledge import generation, generator, ir, judge_client, pipeline, provider, reference, storage

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('owned_replay_fixture',ROOT/'examples/knowledge/create_replay_fixture.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class IncidentReplayTests(unittest.TestCase):
    def setUp(self):
        self.bundle=fixture.build_fixture()

    def changed(self, mutate):
        value=deepcopy(self.bundle);mutate(value);return reference.seal(value)

    def test_same_bundle_reproduces_candidate_questions_and_route_without_keys_or_network(self):
        with (patch.object(generator,'gcloud_access_token',side_effect=AssertionError('Credential read')),
              patch.object(generator,'urllib_transport',side_effect=AssertionError('Network')),
              patch.object(judge_client,'api_key',side_effect=AssertionError('Credential read')),
              patch.object(judge_client,'urllib_transport',side_effect=AssertionError('Network'))):
            left=pipeline.evaluate(self.bundle);right=pipeline.evaluate(self.bundle)
        for name in ('candidate','review_plan','judgments','route','result'):
            self.assertEqual(left[name],right[name])
        self.assertEqual(left['result']['status'],'REPLAY_COMPLETE')
        self.assertIsNotNone(left['route']['atomic_projection'])
        self.assertEqual(left['result']['provider_calls'],0)
        self.assertFalse(left['result']['saved_response_origin_certified'])

    def test_source_drift_cannot_reuse_an_old_prompt(self):
        def mutate(v):
            p=v['generation_plan'];p['source_text']+=' Different source.'
            v['generation_plan']=reference.seal(p)
        with self.assertRaisesRegex(ValueError,'GENERATION_PLAN_DRIFT'):
            pipeline.evaluate(self.changed(mutate))

    def test_request_from_another_source_is_rejected_even_after_rehashing(self):
        def mutate(v):
            body=json.loads(pipeline._body(v['generation_exchange']['request']))
            body['contents'][0]['parts'][0]['text']='Another source prompt'
            v['generation_exchange']['request']=pipeline.wire(generator._json_bytes(body))
        with self.assertRaisesRegex(ValueError,'REPLAY_REQUEST_BINDING'):
            pipeline.evaluate(self.changed(mutate))

    def test_judge_state_cannot_be_changed_while_keeping_the_same_question_ids(self):
        def mutate(v):
            row=v['judge_exchanges'][0];body=json.loads(pipeline._body(row['exchange']['request']))
            body['state']['trust_boundary']='Different state'
            row['exchange']['request']=pipeline.wire(judge_client.canonical_json_bytes(body))
        with self.assertRaisesRegex(ValueError,'REPLAY_REQUEST_BINDING'):
            pipeline.evaluate(self.changed(mutate))

    def test_duplicate_attempt_does_not_supply_a_missing_repeat(self):
        def mutate(v):v['judge_exchanges'][-1]=deepcopy(v['judge_exchanges'][0])
        with self.assertRaisesRegex(ValueError,'REPLAY_DUPLICATE_ATTEMPT'):
            pipeline.evaluate(self.changed(mutate))

    def test_missing_repeat_remains_partial_without_atomic_projection(self):
        value=pipeline.evaluate(self.changed(lambda v:v['judge_exchanges'].pop()))
        self.assertEqual(value['result']['status'],'REPLAY_PARTIAL')
        self.assertGreater(value['result']['unknown_or_partial_questions'],0)
        self.assertIsNone(value['route']['atomic_projection'])

    def test_archived_http_failure_keeps_unknown_and_never_retries(self):
        def mutate(v):
            row=v['judge_exchanges'][0]['exchange'];row['http_status']=503
            row['response']=pipeline.wire(b'{"error":"owned failure control"}')
        value=pipeline.evaluate(self.changed(mutate))
        self.assertEqual(value['result']['status'],'REPLAY_PARTIAL')
        self.assertEqual(len(value['result']['archived_failures']),1)
        self.assertEqual(value['result']['provider_calls'],0)

    def test_full_unknown_answers_are_complete_replay_without_acceptance(self):
        def mutate(v):
            for item in v['judge_exchanges']:
                row=item['exchange'];body=json.loads(pipeline._body(row['response']))
                for answer in body['answers'].values():
                    answer.update(choice='INSUFFICIENT_INFORMATION',confidence=1,
                                  probabilities={key:float(key=='INSUFFICIENT_INFORMATION') for key in answer['probabilities']})
                row['response']=pipeline.wire(reference.canonical(body))
        value=pipeline.evaluate(self.changed(mutate))
        self.assertEqual(value['result']['status'],'REPLAY_COMPLETE')
        self.assertIsNone(value['route']['atomic_projection'])
        self.assertFalse(value['result']['natural_truth_certified'])

    def test_changed_wire_hash_and_duplicate_json_fields_fail(self):
        bad=self.changed(lambda v:v['generation_exchange']['response'].update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError,'REPLAY_WIRE_HASH'):pipeline.evaluate(bad)
        bad=self.changed(lambda v:v['generation_exchange'].update(response=pipeline.wire(b'{"x":1,"x":2}')))
        with self.assertRaisesRegex(ValueError,'REPLAY_DUPLICATE_FIELD'):pipeline.evaluate(bad)

    def test_changed_method_is_rejected(self):
        value=deepcopy(self.bundle)
        with patch.object(ir,'method_binding',return_value={'different.py':'0'*64}):
            with self.assertRaisesRegex(ValueError,'GENERATION_PLAN_DRIFT'):pipeline.evaluate(value)

    def test_private_outputs_keep_original_exchange_bytes_and_semantic_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle=root/'input.json';storage.save(bundle,self.bundle)
            left=knowledge.replay_incident(bundle,state_dir=root/'one')
            right=knowledge.replay_incident(bundle,state_dir=root/'two')
            self.assertEqual(left['result_sha256'],right['result_sha256'])
            a,b=Path(left['output']),Path(right['output'])
            for name in ('candidate.json','review-plan.json','route.json','result.json'):
                self.assertEqual((a/name).read_bytes(),(b/name).read_bytes())
            self.assertEqual((a/'original-exchanges/generation-response.json').read_bytes(),
                             pipeline._body(self.bundle['generation_exchange']['response']))
            self.assertTrue(all(p.stat().st_mode&0o077==0 for p in a.rglob('*')))

    def test_state_root_does_not_require_target_runtime_and_refuses_relative_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ,{'REQLOX_STATE_DIR':str(Path(temp)/'private')},clear=True):
                self.assertTrue(storage.state_directory().is_absolute())
            with patch.dict(os.environ,{'REQLOX_STATE_DIR':'relative'},clear=True):
                with self.assertRaisesRegex(ValueError,'ABSOLUTE_STATE'):storage.state_directory()

    def test_generation_hands_review_plan_to_judge_and_exports_replayable_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);gplan=self.bundle['generation_plan']
            def scope(plan,ident):
                return provider.make_scope(plan,identifier=ident,
                    deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
                    maximum_reserved=str(plan['maximum_calls']*.01),per_call_reserved='.01',
                    maximum_concurrent_calls=2,external_disclosure_allowed=True)
            gp=root/'generation.json';gs=root/'generation-scope.json'
            storage.save(gp,gplan);storage.save(gs,scope(gplan,'owned-generation'))
            def gen_transport(url,headers,payload,timeout):
                self.assertEqual(payload,pipeline._body(self.bundle['generation_exchange']['request']))
                return 200,pipeline._body(self.bundle['generation_exchange']['response'])
            client=generator.VertexGeminiFlashClient(project_id=gplan['project_id'],total_attempts=1,
                token_provider=lambda:'OWNED_TEST_CONTROL',transport=gen_transport)
            generated=generation.execute(gp,gs,state_dir=root/'state',execute=True,client=client)
            self.assertEqual(generated['status'],'COMPLETE')
            review=storage.checked_record(generated['review_plan']);js=root/'judge-scope.json'
            storage.save(js,scope(review,'owned-judge'))
            exchanges={pipeline._body(row['exchange']['request']):pipeline._body(row['exchange']['response'])
                       for row in self.bundle['judge_exchanges']}
            def judge_transport(url,headers,payload,timeout):return 200,exchanges[payload],{}
            with patch.object(judge_client,'api_key',return_value='OWNED_TEST_CONTROL'):
                judged=provider.execute(generated['review_plan'],js,state_dir=root/'state',execute=True,
                    client_factory=lambda:judge_client.JevSystemOneClient('OWNED_TEST_CONTROL',transport=judge_transport))
            self.assertEqual(judged['status'],'COMPLETE')
            exported=pipeline.export_archive(generated['output'],judged['output'],state_dir=root/'exported')
            left=pipeline.replay(exported['bundle'],state_dir=root/'replayed')
            original=storage.checked_record(Path(judged['output'])/'route.json')
            replayed=storage.checked_record(Path(left['output'])/'route.json')
            self.assertEqual(original,replayed)
            self.assertEqual(left['provider_calls'],0)

    def test_archive_without_original_generation_request_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);gen=root/'gen';judge=root/'judge'
            storage.private_directory(gen);storage.private_directory(judge)
            storage.save(gen/'generation-plan.json',self.bundle['generation_plan'])
            value=pipeline.evaluate(self.bundle)['review_plan']
            storage.save(gen/'review-plan.json',value);storage.save(judge/'review-plan.json',value)
            with self.assertRaisesRegex(ValueError,'KNOWLEDGE_INPUT_BOUND'):
                pipeline.export_archive(gen,judge,state_dir=root/'output')


if __name__=='__main__':unittest.main()
