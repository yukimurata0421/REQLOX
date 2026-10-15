"Finite reliability controls and verification."

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import zipfile

from reqlox_demo import contracts, model, targets
from reqlox_demo.engine import Demo, public_view
from reqlox_demo.server import Server


class ContractTests(unittest.TestCase):
    def test_original_quote_offsets_and_hashes(self):
        report = "  Unicode\u5f15\u7528：\u4f8b\u5916\u306e\u5f8c、\u30ed\u30c3\u30af\u304c\u89e3\u653e\u3055\u308c\u305a\u6b62\u307e\u3063\u305f。\n\n" + "\u9577" * 601
        rows = contracts.evidence(report)
        self.assertTrue(all(len(r["text"]) <= 300 for r in rows))
        for r in rows:
            self.assertEqual(report[r["start_char"]:r["end_char"]], r["text"])
            self.assertEqual(hashlib.sha256(r["text"].encode()).hexdigest(), r["sha256"])

    def test_three_source_states(self):
        for s, expected in zip(contracts.SAMPLES, ["SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT_INFORMATION"]):
            self.assertEqual(contracts.baseline(s["report"])["choice"], expected)

    def test_hypothetical_and_conflicting_quotes_are_held(self):
        for report in ["\u8a13\u7df4\u3067\u306f\u30ed\u30c3\u30af\u304c\u89e3\u653e\u3055\u308c\u305a\u6b62\u307e\u308b\u3053\u3068\u3092\u60f3\u5b9a\u3057\u3066\u3044\u308b。", "Hypothetically, the lock remained held.", "\u30ed\u30c3\u30af\u304c\u89e3\u653e\u3055\u308c\u305a\u6b62\u307e\u3063\u305f。\u5225\u306eepisode\u3067\u306f\u30ed\u30c3\u30af\u306f\u6b63\u5e38\u306b\u89e3\u653e\u3055\u308c\u305f。"]:
            self.assertEqual(contracts.baseline(report)["choice"], "INSUFFICIENT_INFORMATION")

    def test_timeout_alone_does_not_establish_cleanup_failure(self):
        self.assertEqual(contracts.baseline("TimeoutError\u3067\u51e6\u7406\u304c\u9045\u5ef6\u3057\u305f。")["choice"], "INSUFFICIENT_INFORMATION")

    def test_ast_translation_binds_full_body(self):
        self.assertEqual(contracts.caller_policy(contracts.LEAK_CALLER)["policy"], "OMIT_EXIT")
        self.assertEqual(contracts.caller_policy(contracts.REPAIRED_CALLER)["policy"], "BALANCED_CONTEXT")
        for bad in [contracts.LEAK_CALLER + "\nimport os\n", contracts.LEAK_CALLER.replace("do_work()", "print('unexpected')"), contracts.LEAK_CALLER.replace("None, None, None", "0, 0, 0")]:
            with self.assertRaises(ValueError):
                contracts.caller_policy(bad)

    def test_repair_changes_fault_stage_only(self):
        self.assertEqual(contracts.stages("OMIT_EXIT")[1]["policy"], "OMIT_EXIT")
        self.assertEqual(contracts.stages("BALANCED_CONTEXT")[1]["policy"], "BALANCED_CONTEXT")
        self.assertEqual(contracts.stages("OMIT_EXIT")[3], contracts.stages("BALANCED_CONTEXT")[3])

    def test_input_bounds_and_unknown_target(self):
        for text in ["", "x" * 12001, "x.\n" * 70]:
            with self.assertRaises(ValueError):
                contracts.evidence(text)
        with self.assertRaises(ValueError):
            contracts.cases("arbitrary-package")


class ModelTests(unittest.TestCase):
    def answers(self, choice="SUPPORTED", p=.98, anchor="e1"):
        return {"support": {"choice": choice, "probabilities": {"SUPPORTED": p, "NOT_SUPPORTED": 1-p, "INSUFFICIENT_INFORMATION": 0}},
                "anchor": {"choice": anchor}, "forecast": {"choice": "INSUFFICIENT_INFORMATION", "probabilities": {"ALL_STAGES_MATCH": .2, "STAGE_MISMATCH": .2, "INSUFFICIENT_INFORMATION": .6}}}

    def test_low_support_or_no_quote_is_held(self):
        baseline = contracts.baseline(contracts.SAMPLES[0]["report"])
        for answer in [self.answers(p=.84), self.answers(anchor="NO_EVIDENCE")]:
            value = model.materialize(baseline, answer, "LIVE_MODEL_JUDGMENT")
            self.assertEqual(value["choice"], "INSUFFICIENT_INFORMATION")
            self.assertEqual(value["raw_choice"], "SUPPORTED")

    def test_unknown_quote_is_not_repaired(self):
        with self.assertRaises(ValueError):
            model.materialize(contracts.baseline(contracts.SAMPLES[0]["report"]), self.answers(anchor="invented"), "LIVE_MODEL_JUDGMENT")

    def test_record_binding_covers_report_target_and_caller(self):
        keys = {model.record_key(text, target, policy) for text in ["one", "two"] for target in ["py-cachify", "readerwriterlock"] for policy in ["OMIT_EXIT", "BALANCED_CONTEXT"]}
        self.assertEqual(len(keys), 8)

    def test_recorded_choices_match_all_samples_and_reject_edited_source(self):
        data = self.owned_records()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'owned-test-records.json'
            p.write_text(json.dumps(data))
            with patch.object(model, 'RECORDS', p):
                for target in ['py-cachify', 'readerwriterlock']:
                    for s in contracts.SAMPLES:
                        baseline = contracts.baseline(s['report'])
                        policy = contracts.caller_policy(s['caller'])['policy']
                        value = model.recorded(s['report'], target, baseline, policy)
                        self.assertEqual(value['choice'], baseline['choice'])
                        self.assertEqual(value['method'], 'RECORDED_MODEL_JUDGMENT')
                with self.assertRaises(ValueError):
                    model.recorded(contracts.SAMPLES[0]['report']+' edited', 'py-cachify',
                                   contracts.baseline(contracts.SAMPLES[0]['report']), 'OMIT_EXIT')

    def owned_records(self):
        records = []
        for target in ['py-cachify', 'readerwriterlock']:
            for sample in contracts.SAMPLES:
                baseline = contracts.baseline(sample['report'])
                choice = baseline['choice']
                probabilities = {k: .9 if k == choice else .05 for k in
                                 ['SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_INFORMATION']}
                answers = {'support': {'choice': choice, 'probabilities': probabilities},
                           'anchor': {'choice': baseline['evidence'][0]['id'] if baseline['evidence'] else 'NO_EVIDENCE'},
                           'forecast': {'choice': 'ALL_STAGES_MATCH', 'probabilities':
                                        {'ALL_STAGES_MATCH': .8, 'STAGE_MISMATCH': .1, 'INSUFFICIENT_INFORMATION': .1}}}
                records.append({'binding_sha256': model.record_key(sample['report'], target,
                               contracts.caller_policy(sample['caller'])['policy']),
                               'answers': answers, 'answers_sha256': contracts.sha(answers)})
        return {'origin': 'OWNED_UNIT_TEST_FIXTURE_NOT_PROVIDER_RESPONSE', 'records': records}

    def test_recorded_choice_integrity_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'records.json';data=self.owned_records();data['records'][0]['answers']['support']['choice']='NOT_SUPPORTED';p.write_text(json.dumps(data))
            s=contracts.SAMPLES[0]
            with patch.object(model,'RECORDS',p), self.assertRaises(ValueError):
                model.recorded(s['report'],'py-cachify',contracts.baseline(s['report']),'OMIT_EXIT')



class TargetTests(unittest.TestCase):
    def test_zip_paths_duplicates_and_links_are_rejected(self):
        for names in [["../escape.py"], ["/escape.py"], ["a\\b.py"], ["x.py", "x.py"]]:
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, "w") as archive:
                for name in names:
                    archive.writestr(name, "x=1")
            with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
                targets.extract(raw.getvalue(), Path(d))
        raw = io.BytesIO();item = zipfile.ZipInfo("link");item.external_attr = 0o120777 << 16
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr(item, "destination")
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            targets.extract(raw.getvalue(), Path(d))

    def test_cache_drift_is_not_refetched(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / "targets/py-cachify-3.1.0";directory.mkdir(parents=True)
            (directory / "snapshot.json").write_text(json.dumps({"package": "py-cachify", "distribution_sha256": targets.PACKAGES['py-cachify']['sha256'], "files": []}))
            (directory / "changed.py").write_text('changed=True')
            with patch("urllib.request.urlopen") as download, self.assertRaises(ValueError):
                targets.acquire(d, "py-cachify")
            download.assert_not_called()


class EngineTests(unittest.TestCase):
    def request(self, sample=0):
        s=contracts.SAMPLES[sample]
        return {"report": s['report'], "caller": s['caller'], "target": "py-cachify", "method": "baseline"}

    def test_unsupported_and_unknown_sources_do_not_execute(self):
        with tempfile.TemporaryDirectory() as d, patch("reqlox_demo.targets.acquire") as acquire:
            engine=Demo(d)
            for i, expected in [(1,"NOT_SUPPORTED"),(2,"INSUFFICIENT_INFORMATION")]:
                result=engine.run(self.request(i));self.assertEqual(result['status'],expected)
                self.assertEqual(result['native_attempts'],0);self.assertEqual(result['native_executions'],0)
            acquire.assert_not_called()

    def test_missing_model_configuration_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as d, patch("reqlox_demo.targets.acquire") as acquire:
            result=Demo(d).run({**self.request(),"method":"live","send_to_model":True})
            self.assertEqual(result['status'],"STOPPED");acquire.assert_not_called()

    def test_download_excludes_user_source_and_caller(self):
        with tempfile.TemporaryDirectory() as d:
            result=Demo(d).run(self.request(2));download=public_view(result)
            self.assertNotIn('evidence',download['assessment']);self.assertNotIn('all_evidence_handles',download['assessment'])
            self.assertNotIn('code',download['repair_candidate']);self.assertFalse(download['raw_user_text_or_code_included'])
            self.assertNotIn(contracts.SAMPLES[2]['report'],json.dumps(download))
            data=copy.deepcopy(download);digest=data.pop('export_sha256');self.assertEqual(contracts.sha(data),digest)

    def test_unknown_input_field_and_unbounded_caller_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for request in [{**self.request(),'command':'anything'},{**self.request(),'caller':'import os'}]:
                with self.assertRaises(ValueError):Demo(d).run(request)

    def test_cache_link_is_rejected_before_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'real').mkdir();(root/'link').symlink_to(root/'real',target_is_directory=True)
            with self.assertRaises(ValueError):Demo(root/'link')

    def test_native_failure_preserves_unknown_attempt(self):
        with tempfile.TemporaryDirectory() as d, patch('reqlox_demo.targets.acquire',return_value=(Path(d),{'files':[]})), patch('reqlox_demo.engine.api.inventory',return_value={}), patch('reqlox_demo.engine.context.validate',return_value={}), patch('reqlox_demo.isolation.run',side_effect=[({'both_oracles_agree':True},{}),ValueError('unknown')]):
            result=Demo(d).run(self.request())
            self.assertEqual(result['status'],'STOPPED');self.assertEqual(result['native_attempts'],1)
            self.assertIsNone(result['native_executions']);self.assertEqual(result['native_execution_status'],'ATTEMPTED_OUTCOME_UNKNOWN')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.server=Server(0,Demo(self.tmp.name))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def post(self,data,**headers):
        request=urllib.request.Request(self.url+'/api/run',data=contracts.encode(data),headers={'Content-Type':'application/json',**headers},method='POST')
        return urllib.request.urlopen(request,timeout=5)

    def test_same_origin_token_and_hold_flow(self):
        config=json.load(urllib.request.urlopen(self.url+'/api/config',timeout=5))
        s=contracts.SAMPLES[2]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({'report':s['report'],'caller':s['caller'],'target':'py-cachify'},**{'X-REQLOX-Token':config['token'],'Origin':self.url})
        self.assertEqual(caught.exception.code,403)
        self.assertEqual(json.load(caught.exception)['error'],'UI_EXECUTION_DISABLED');caught.exception.close()

    def test_cross_origin_and_missing_token_rejected(self):
        for headers in [{},{'X-REQLOX-Token':self.server.token,'Origin':'http://untrusted.example'}]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.post({},**headers)
            self.assertEqual(error.exception.code,403)
            error.exception.close()

    def test_only_named_static_assets_served(self):
        for path in ['/../README.md','/api/config/extra','/model-records.json']:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.url+path,timeout=5)
            self.assertEqual(error.exception.code,404)
            error.exception.close()
        response=urllib.request.urlopen(self.url+'/',timeout=5)
        self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])
        self.assertIn('Incident report', response.read().decode())


if __name__ == '__main__':
    unittest.main()
