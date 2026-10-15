"""Verify HTTP boundaries, immutable stages, and public summary redaction."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import reqlox
reqlox._runtime()
from reqlox_demo.engine import Demo
from reqlox_demo.server import Server
from reqlox_demo.study_ui import StudyLab
from test_public_studies import wheel

EXAMPLE = json.loads((Path(__file__).resolve().parents[1]/'reqlox_demo/data/study-example.json').read_text())


class StudyUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.environment=patch.dict(os.environ,{'REQLOX_STATE_DIR':str(self.root)})
        self.environment.start()
        self.server=Server(0,Demo(self.root/'cache'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        self.environment.stop();self.tmp.cleanup()

    def post(self,operation,value,headers=None):
        request=urllib.request.Request(self.url+'/api/study/'+operation,data=json.dumps(value).encode(),
            headers={'Content-Type':'application/json','X-REQLOX-Token':self.server.token,**(headers or {})})
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)

    def get_job(self,identity):
        request=urllib.request.Request(self.url+'/api/study/job/'+identity,
                                      headers={'X-REQLOX-Token':self.server.token})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)

    def prepare(self,**changes):
        return self.post('prepare',dict(project=EXAMPLE['project'],sources=EXAMPLE['sources'],
                         documents=EXAMPLE['documents'],known_projects=[],**changes))

    def freeze(self,preparation):
        return self.post('freeze',dict(preparation_id=preparation['id'],source=EXAMPLE['source'],recipe_index=0,budget=4))

    def expect_error(self,operation,value,status=400,headers=None):
        with self.assertRaises(urllib.error.HTTPError) as caught:self.post(operation,value,headers)
        self.assertEqual(caught.exception.code,status)
        body=json.load(caught.exception);caught.exception.close();return body

    def test_static_assets_config_and_existing_demo_are_available(self):
        for path,text in [('/study','Prepare target'),('/study.js','reqloxStudyReady'),('/','Incident library')]:
            with urllib.request.urlopen(self.url+path,timeout=5) as response:
                self.assertIn(text,response.read().decode())
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        with urllib.request.urlopen(self.url+'/api/study/config',timeout=5) as response:config=json.load(response)
        self.assertEqual(config['example']['fixture_kind'],'OWNED_SYNTHETIC_CONTROL')
        self.assertFalse(config['detailed_records_public'])
        self.assertFalse(config['native_execution_enabled'])

    def test_prepare_and_freeze_use_existing_interfaces_without_importing_target(self):
        with patch('subprocess.Popen') as child:
            value=self.prepare();frozen=self.freeze(value);child.assert_not_called()
        self.assertEqual(value['status'],'READY_STATICALLY')
        self.assertFalse(value['target_code_imported'])
        self.assertEqual(frozen['discovery_budget_per_arm'],4)
        serialized=json.dumps(value)
        self.assertNotIn(EXAMPLE['sources']['owned_context.py'],serialized)
        self.assertNotIn('sources',value)
        artifact=self.root/'cache/studies'/value['id']/'artifact.json'
        self.assertEqual(artifact.stat().st_mode & 0o777,0o600)

    def test_declared_history_holds_preparation(self):
        value=self.post('prepare',dict(project=EXAMPLE['project'],sources=EXAMPLE['sources'],
            documents=EXAMPLE['documents'],known_projects=[EXAMPLE['project']]))
        self.assertEqual(value['status'],'HELD')
        self.assertIn('DECLARED_LOCAL_HISTORY_EXPOSURE',value['reasons'])
        self.expect_error('freeze',dict(preparation_id=value['id'],source=EXAMPLE['source'],recipe_index=0,budget=4))

    def test_source_paths_and_arbitrary_filesystem_inputs_are_rejected(self):
        for source in ['../escape.py','/tmp/escape.py','a\\b.py']:
            self.expect_error('prepare',dict(project='owned',sources={source:'pass\n'},documents={},known_projects=[]))
        self.expect_error('prepare',dict(project='owned',root='/tmp',documents={},known_projects=[]))
        self.expect_error('freeze',dict(preparation_id='../escape',source=EXAMPLE['source'],recipe_index=0,budget=4))

    def test_capsule_upload_checks_original_bytes_and_never_imports_package(self):
        spec=wheel(self.root)
        path=Path(spec['path'])
        item=dict(name=path.name,sha256=spec['sha256'],base64=base64.b64encode(path.read_bytes()).decode())
        value=self.post('capsule',dict(project='owned-example',wheels=[item]))
        self.assertEqual(value['status'],'READY_STATICALLY')
        self.assertFalse(value['target_code_imported'])
        self.expect_error('capsule',dict(project='owned-example',wheels=[dict(item,name='../escape.whl')]))
        self.expect_error('capsule',dict(project='owned-example',wheels=[dict(item,sha256='0'*64)]))

    def test_unknown_labels_and_missing_forecasts_remain_in_score_denominator(self):
        data=deepcopy(EXAMPLE['confirmation']);data['rows'][0]['answer']=None
        value=self.post('score',dict(dataset=data))
        self.assertEqual(value['scores']['total_rows'],3)
        self.assertEqual(value['scores']['scored_rows'],1)
        self.assertEqual(value['scores']['unknown_rows'],2)
        self.assertNotIn('rows',value['scores'])
        self.assertNotIn('confirm-source-',json.dumps(value))
        self.assertFalse(value['probability_calibration_certified'])

    def test_registration_and_review_are_held_and_do_not_replay_changed_forecasts(self):
        value=self.post('register',dict(training=EXAMPLE['training'],forecasts=EXAMPLE['forecasts']))
        review=self.post('review',dict(registration_id=value['id'],confirmation=EXAMPLE['confirmation']))
        self.assertEqual(review['status'],'HELD')
        self.assertEqual(review['serving']['mode'],'RAW')
        self.assertFalse(review['candidate_activated'])
        altered=deepcopy(EXAMPLE['confirmation']);altered['rows'][0]['answer']=None
        self.expect_error('review',dict(registration_id=value['id'],confirmation=altered))
        self.expect_error('register',dict(training=EXAMPLE['training'],forecasts=EXAMPLE['confirmation']))

    def test_request_token_origin_and_size_limits_apply_to_new_endpoints(self):
        self.expect_error('score',{},403,{'X-REQLOX-Token':''})
        self.expect_error('score',{},403,{'Origin':'http://untrusted.example'})
        self.expect_error('score',{'padding':'x'*(1024*1024)},400)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url+'/api/study/job/'+'a'*32,timeout=5)
        self.assertEqual(caught.exception.code,403);caught.exception.close()

    def test_comparison_requires_explicit_execution_and_zero_budget_never_launches(self):
        frozen=self.freeze(self.prepare())
        request=dict(freeze_id=frozen['id'],seconds=15,maximum_campaigns=0,execute_isolated_code=False)
        with patch('reqlox.studies.run_comparison') as execute:
            self.assertEqual(self.expect_error('compare-run',request,403)['error'],'UI_EXECUTION_DISABLED')
            execute.assert_not_called()
        self.server.study.allow_native=True  # Owned mock transport only.
        self.expect_error('compare-run',request,403)
        request['execute_isolated_code']=True
        with patch('subprocess.Popen') as child, patch('reqlox.studies.run_comparison',return_value=dict(status='STOPPED',native_campaigns=0)):
            job=self.server.study.start(request)
            for _ in range(100):
                result=self.get_job(job['id'])
                if result['status']!='RUNNING':break
                time.sleep(.01)
            self.assertEqual(result['status'],'STOPPED');self.assertEqual(result['native_campaigns'],0)
            child.assert_not_called()
        self.expect_error('compare-run',request,403)
        self.assertFalse(self.server.run_lock.locked())

    def test_background_job_holds_shared_demo_lock_and_returns_redacted_result(self):
        self.server.study.allow_native=True  # Owned mock transport only.
        frozen=self.freeze(self.prepare());entered=threading.Event();release=threading.Event()
        def execute(*args,**kwargs):
            entered.set();self.assertTrue(release.wait(3))
            return dict(native_campaigns=1,comparison_complete=True,source_added_adoptions=0,
                private_candidate_adopted={'SOURCE':False,'NO_SOURCE':False},
                discovery_faults={'SOURCE':['private-condition'],'NO_SOURCE':[]},unknown_conditions={},
                original_normal_context_verified=True,private_trace='do not export')
        with patch('reqlox.studies.run_comparison',side_effect=execute):
            job=self.server.study.start(dict(freeze_id=frozen['id'],seconds=15,maximum_campaigns=1,execute_isolated_code=True))
            self.assertTrue(entered.wait(2));self.assertTrue(self.server.run_lock.locked())
            self.expect_error('score',dict(dataset=EXAMPLE['confirmation']),409)
            release.set()
            for _ in range(100):
                result=self.get_job(job['id'])
                if result['status']!='RUNNING':break
                time.sleep(.01)
            self.assertEqual(result['status'],'COMPLETE')
            self.assertNotIn('private-condition',json.dumps(result));self.assertNotIn('private_trace',result)


if __name__=='__main__':unittest.main()
