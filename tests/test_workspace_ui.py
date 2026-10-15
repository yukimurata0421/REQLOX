"""Offline HTTP gates, retained records, durable restoration and exact Source binding."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from reqlox_demo.engine import Demo
from reqlox_demo.server import Server
from reqlox_demo.study_ui import StudyLab
from reqlox_demo.workspace import Workspace
from reqlox_knowledge import storage


class WorkspaceUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'REQLOX_STATE_DIR':str(self.root)});self.env.start()
        self.server=Server(0,Demo(self.root/'cache'),allow_target_native=True,allow_study_native=True)
        self.server.engine.run=Mock(side_effect=AssertionError('Native engine must never be reached'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3);self.env.stop();self.tmp.cleanup()

    def post(self,path,value,**headers):
        request=urllib.request.Request(self.url+path,data=json.dumps(value).encode(),headers={
            'Content-Type':'application/json','X-REQLOX-Token':self.server.token,**headers})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)

    def failed(self,path,value,code=400,**headers):
        with self.assertRaises(urllib.error.HTTPError) as caught:self.post(path,value,**headers)
        self.assertEqual(caught.exception.code,code);value=json.load(caught.exception);caught.exception.close();return value

    def test_all_native_and_model_paths_reject_before_dispatch_even_with_legacy_flags(self):
        self.server.study.allow_native=True;self.server.target_lab.allow_native=True
        with patch('reqlox.studies.run_comparison') as comparison,patch('subprocess.Popen') as child:
            for path in ('/api/run','/api/targets/run','/api/study/compare-run'):
                value=self.failed(path,dict(method='live',repair='live',send_to_model=True),403)
                self.assertEqual(value['error'],'UI_EXECUTION_DISABLED')
                self.assertFalse(value['execution_policy']['model_calls_enabled'])
            child.assert_not_called();comparison.assert_not_called();self.server.engine.run.assert_not_called()

    def test_all_page_configs_advertise_identical_exhausted_scope(self):
        policies=[]
        for path in ('/api/config','/api/targets/config','/api/study/config','/api/knowledge/config','/api/workspace/config'):
            with urllib.request.urlopen(self.url+path,timeout=5) as response:policies.append(json.load(response)['execution_policy'])
        self.assertTrue(all(value==policies[0] for value in policies))
        self.assertEqual((policies[0]['cumulative_campaigns'],policies[0]['charged_seconds'],policies[0]['remaining_campaigns']),(15,62,0))

    def test_archived_records_keep_detection_repair_reinjection_and_adoption_distinct(self):
        for name in ('api-copy-v01','worker-copy-v01','temppath-readme-v01','integration-caller-v01'):
            value=self.post('/api/workspace/open',dict(id=name))
            self.assertEqual([r['stage'] for r in value['steps']],['input','detection','repair','reinjection','decision'])
            self.assertEqual(value['new_native_campaigns'],0)
        held=self.post('/api/workspace/open',dict(id='temppath-readme-v01'))
        self.assertEqual(held['held_atomic_bindings'],4);self.assertFalse(held['temppath_repair_performed'])
        self.assertEqual(held['steps'][2]['status'],'NOT_PERFORMED')
        self.assertEqual(held['steps'][3]['status'],'REPAIR_REINJECTION_NOT_PERFORMED')
        self.assertFalse(held['source']['original_source_available'])
        self.assertEqual(held['source']['text_sha256'],hashlib.sha256(held['source']['text'].encode()).hexdigest())

    def test_drafts_survive_workspace_restart_without_mutating_execution_evidence(self):
        data=dict(fields={'report':'owned input'},sourceId=None)
        self.post('/api/workspace/save-draft',dict(area='guided',data=data))
        second=Workspace(self.root/'cache');result=second.dispatch('restore-draft',dict(area='guided'))
        self.assertEqual(result['data'],data);self.assertEqual(result['status'],'DRAFT_RESTORED')
        self.assertEqual(second.configuration('owned')['execution_policy']['remaining_campaigns'],0)

    def test_tampered_draft_hash_and_path_traversal_are_rejected(self):
        self.failed('/api/workspace/restore-draft',dict(area='../escape'))
        self.failed('/api/workspace/open',dict(area='knowledge',id='../escape'))
        self.post('/api/workspace/save-draft',dict(area='guided',data={'text':'original'}))
        path=self.root/'cache/workspace/guided.json';value=json.loads(path.read_bytes());value['data']['text']='changed'
        storage.save(path,value,replace=True)
        self.assertEqual(self.failed('/api/workspace/restore-draft',dict(area='guided'))['error'],'UI_DRAFT_HASH')

    def prepare_quote(self):
        text='前提\r\n  A worker  kept the lock.\nThe second worker waited.\n'
        imported=self.post('/api/knowledge/import',dict(documents=[dict(url='https://example.org/owned-source',title='Owned text',text=text)]))
        indexed=self.post('/api/knowledge/index',dict(corpus_id=imported['id']))
        found=self.post('/api/knowledge/search',dict(index_id=indexed['id'],query='worker lock'))['results'][0]
        request={key:found[key] for key in ('source_ref','document_ref','source_location')};request['index_id']=indexed['id']
        return text,request

    def test_exact_source_quote_preserves_whitespace_hash_and_unicode_offsets(self):
        text,request=self.prepare_quote();bound=self.post('/api/knowledge/excerpt',request)
        location=bound['source_location'];self.assertEqual(bound['text'],text[location['start_offset']:location['end_offset']])
        self.assertEqual(bound['document_ref']['text_sha256'],hashlib.sha256(text.encode()).hexdigest())
        self.assertFalse(bound['natural_truth_certified']);self.assertTrue(bound['source_binding_verified'])
        self.post('/api/workspace/save-draft',dict(area='guided',data={'sourceId':bound['id'],'fields':{'report':bound['text']}}))
        before=len(self.server.workspace.history())
        restored=self.post('/api/knowledge/get-excerpt',dict(id=bound['id']))
        self.assertEqual(restored['text'],bound['text']);self.assertEqual(len(self.server.workspace.history()),before)

    def test_forged_source_span_hash_text_and_revision_are_rejected(self):
        _,request=self.prepare_quote()
        for change in ('offset','hash','source'):
            altered=deepcopy(request)
            if change=='offset':altered['source_location']['start_offset']+=1
            if change=='hash':altered['source_location']['chunk_sha256']='0'*64
            if change=='source':altered['source_ref']['revision_id']='forged'
            self.failed('/api/knowledge/excerpt',altered)
        self.failed('/api/knowledge/excerpt',dict(request,text='forged'))

    def test_private_history_and_record_lookup_survive_new_server_objects(self):
        value=self.post('/api/knowledge/import',dict(documents=[dict(url='https://example.org/owned',text='A worker held a lock.')]))
        second=Workspace(self.root/'cache');history=second.history()
        self.assertIn(value['id'],[row['id'] for row in history])
        result=second.dispatch('open',dict(area='knowledge',id=value['id']))
        self.assertEqual(result['summary']['documents'],1);self.assertNotIn('text',result['summary'])

    def test_saved_study_job_is_recovered_and_interrupted_job_is_unknown(self):
        cache=self.root/'cache/studies';storage.private_directory(cache)
        for identity in ('a'*32,'b'*32):storage.private_directory(cache/identity)
        storage.save(cache/('a'*32)/'summary.json',dict(id='a'*32,status='STOPPED',native_campaigns=0))
        storage.save(cache/('b'*32)/'job-started.json',dict(id='b'*32,status='RUNNING',native_campaigns=None))
        lab=StudyLab(self.root/'cache',threading.Lock())
        self.assertEqual(lab.job('a'*32)['status'],'STOPPED')
        unknown=lab.job('b'*32);self.assertEqual(unknown['status'],'OUTCOME_UNKNOWN_SERVER_RESTART')
        self.assertIsNone(unknown['native_campaigns']);self.assertFalse(unknown['automatic_retry'])

    def test_explicit_native_state_path_does_not_evaluate_home(self):
        import reqlox_paths
        base=Path(reqlox_paths.__file__).resolve().parents[1]/'corpus/knowledge/semantic-experiments/local-private-quarantine/owned-path-only'
        with patch.dict(os.environ,{'REQLOX_STATE_DIR':str(base)}),patch.object(Path,'home',side_effect=AssertionError('Home lookup forbidden')):
            self.assertEqual(reqlox_paths.state_root(),base)

    def test_private_draft_and_source_requests_require_token_and_origin(self):
        self.failed('/api/workspace/restore-draft',dict(area='guided'),403,**{'X-REQLOX-Token':''})
        self.failed('/api/workspace/history',{},403,Origin='https://untrusted.example')
        self.failed('/api/knowledge/get-excerpt',dict(id='ui-'+'a'*32),403,**{'X-REQLOX-Token':''})


if __name__=='__main__':unittest.main()
