"""Verify local knowledge HTTP flows and disclosure boundaries."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import reqlox
reqlox._runtime()
from reqlox_demo.engine import Demo
from reqlox_demo.server import Server

EXAMPLE = json.loads((Path(__file__).resolve().parents[1]/'reqlox_demo/data/knowledge-example.json').read_text())


class KnowledgeUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='reqlox-knowledge-ui-')
        self.root=Path(self.tmp.name)
        self.environment=patch.dict(os.environ,{'REQLOX_STATE_DIR':str(self.root)})
        self.environment.start()
        self.server=Server(0,Demo(self.root/'cache'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        self.environment.stop();self.tmp.cleanup()

    def post(self,operation,value,headers=None):
        request=urllib.request.Request(self.url+'/api/knowledge/'+operation,data=json.dumps(value).encode(),
            headers={'Content-Type':'application/json','X-REQLOX-Token':self.server.token,**(headers or {})})
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)

    def test_assets_owned_config_and_navigation(self):
        for path,text in [('/knowledge','Freeze and review IR'),('/knowledge.js','reqloxKnowledgeReady'),('/', 'href="/knowledge"'),('/study','href="/knowledge"')]:
            with urllib.request.urlopen(self.url+path,timeout=5) as response:
                self.assertIn(text,response.read().decode());self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        with urllib.request.urlopen(self.url+'/api/knowledge/config',timeout=5) as response:config=json.load(response)
        self.assertEqual(config['example']['fixture_kind'],'OWNED_SYNTHETIC_CONTROL')
        self.assertFalse(config['external_disclosure_allowed'])

    def test_import_search_uses_local_supplied_documents(self):
        with patch('requests.Session.get',side_effect=AssertionError('Network call')):
            imported=self.post('import',dict(documents=EXAMPLE['documents']))
            indexed=self.post('index',dict(corpus_id=imported['id']))
            found=self.post('search',dict(index_id=indexed['id'],query='worker lock'))
        self.assertEqual(len(found['results']),1);self.assertIn('renewed the lock',found['results'][0]['excerpt'])
        self.assertNotIn(str(self.root),json.dumps(imported));self.assertNotIn('corpus',imported)
        self.assertNotIn(str(self.root),json.dumps(indexed));self.assertFalse(found['ranking_score_is_probability'])

    def test_unknown_ir_and_partial_scores_are_preserved_without_provider_call(self):
        with patch('reqlox_knowledge.judge_client.api_key',side_effect=AssertionError('Credential read')):
            prepared=self.post('ir-prepare',dict(candidate=EXAMPLE['candidate'],source_texts=EXAMPLE['source_texts']))
            routed=self.post('ir-route',dict(plan_id=prepared['id'],judgments={}))
            scored=self.post('score',EXAMPLE['scores'])
        self.assertFalse(routed['atomic_projection_present']);self.assertTrue(routed['all_original_candidates_preserved'])
        self.assertEqual(scored['attempted_rows'],2);self.assertEqual(scored['unknown_vectors'],1)
        self.assertNotIn('owned-1',json.dumps(scored));self.assertNotIn('owned-lock-report',json.dumps(routed))

    def test_origin_token_path_and_paid_operation_are_rejected(self):
        for operation,value,headers,status in [
            ('import',dict(documents=EXAMPLE['documents']),{'Origin':'https://example.org'},403),
            ('import',dict(documents=EXAMPLE['documents']),{'X-REQLOX-Token':'bad'},403),
            ('index',dict(corpus_id='/etc/passwd'),{},400),
            ('judge',{}, {},404),
            ('import',dict(documents=EXAMPLE['documents'],api_key='not-a-real-key'),{},400)]:
            with self.subTest(operation=operation,headers=headers),self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(operation,value,headers)
            self.assertEqual(caught.exception.code,status);caught.exception.close()

    def test_shared_run_lock_blocks_new_work(self):
        self.server.run_lock.acquire()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.post('import',dict(documents=EXAMPLE['documents']))
            self.assertEqual(caught.exception.code,409);caught.exception.close()
        finally:self.server.run_lock.release()


if __name__=='__main__':unittest.main()
