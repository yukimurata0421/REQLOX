"""Local Target UI uses explicit registration and the same finite CLI path."""
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_target_workspace as fixtures
from reqlox_demo.target_ui import TargetLab
from reqlox_demo.server import Server
import run_reliability_reuse as runner


class TargetUITests(unittest.TestCase):
    setUp = fixtures.WorkspaceTests.setUp
    tearDown = fixtures.WorkspaceTests.tearDown

    def request(self):
        return dict(target='owned-system', all=True, repositories=[], seconds=120, campaigns=0, rounds=3)

    def test_only_startup_registered_targets_are_available(self):
        lab = TargetLab([self.manifest])
        self.assertEqual(lab.configuration('token')['targets'], ['owned-system'])
        with self.assertRaises(ValueError): lab.dispatch('plan', dict(self.request(), target=str(self.manifest)))
        with self.assertRaises(ValueError): lab.dispatch('plan', dict(self.request(), path=str(self.manifest)))
        with self.assertRaises(ValueError): TargetLab([self.manifest, self.manifest])

    def test_preparation_plan_stop_and_audit_share_cli_logic(self):
        lab = TargetLab([self.manifest])
        request = self.request()
        result = lab.dispatch('prepare', dict(target=request['target'], all=True,
            source_texts={'incident': 'fsync returned an error.'}))
        request['preparation_id'] = result['preparation_id']
        planned = lab.dispatch('plan', request)
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            stopped = lab.dispatch('run', dict(request, plan_sha256=planned['plan_sha256']))
            audited = lab.dispatch('audit', {'run_id': stopped['run_id']})
        self.assertEqual(stopped['status'], 'STOPPED')
        self.assertEqual(audited['historical_status'], 'STOPPED')
        self.assertEqual(stopped['native_attempts'], 0)
        self.assertNotIn('output', stopped)
        self.assertNotIn('sources', planned)

    def test_changed_plan_and_native_without_startup_flag_stop_before_dispatch(self):
        lab = TargetLab([self.manifest]); request = self.request()
        planned = lab.dispatch('plan', request)
        with self.assertRaisesRegex(ValueError, 'PLAN_CHANGED'):
            lab.dispatch('run', dict(request, rounds=4, plan_sha256=planned['plan_sha256']))
        request['campaigns'] = 1; planned = lab.dispatch('plan', request)
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            with self.assertRaisesRegex(ValueError, 'NATIVE_NOT_ENABLED'):
                lab.dispatch('run', dict(request, plan_sha256=planned['plan_sha256']))

    def test_snapshot_then_preparation_uses_only_the_copied_roots(self):
        lab = TargetLab([self.manifest])
        copied = lab.dispatch('snapshot', {'target':'owned-system', 'repositories':['api','worker']})
        self.assertEqual([r['name'] for r in copied['repositories']], ['api','worker'])
        self.assertFalse(copied['repair_verified'])
        self.assertNotIn('output', copied); self.assertNotIn('original_root', json.dumps(copied))
        request = dict(self.request(), snapshot_id=copied['snapshot_id'])
        prepared = lab.dispatch('prepare', {k:v for k,v in request.items() if k in ('target','snapshot_id','all','repositories')})
        request['preparation_id'] = prepared['preparation_id']
        (self.root/'api/storage.py').write_text('raise AssertionError("Original must not be imported")\n')
        planned, entries, roots = lab.plan(request)
        self.assertEqual(planned['plan']['selected_repositories'], ['api','worker'])
        self.assertTrue(all(root.is_relative_to(self.state/'target-snapshots') for root in roots.values()))
        with patch.object(runner,'execute',side_effect=AssertionError('Native execution forbidden')):
            result = lab.dispatch('run', dict(request, plan_sha256=planned['plan_sha256']))
            audit = lab.dispatch('audit', {'run_id':result['run_id']})
        self.assertEqual(result['native_attempts'], 0)
        self.assertEqual(audit['historical_status'], 'STOPPED')

    def test_snapshot_tampering_and_preparation_from_another_snapshot_are_rejected(self):
        lab = TargetLab([self.manifest])
        first = lab.dispatch('snapshot', {'target':'owned-system','all':True})
        second = lab.dispatch('snapshot', {'target':'owned-system','all':True})
        prepared = lab.dispatch('prepare', {'target':'owned-system','all':True,'snapshot_id':first['snapshot_id']})
        with self.assertRaisesRegex(ValueError, 'PREPARATION_SNAPSHOT'):
            lab.plan(dict(self.request(), preparation_id=prepared['preparation_id'], snapshot_id=second['snapshot_id']))
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_ID'):
            lab.plan(dict(self.request(), snapshot_id='unknown'))
        manifest = lab.snapshots[first['snapshot_id']][1]
        (manifest.parent/'repositories/api/storage.py').write_text('changed = True\n')
        with self.assertRaisesRegex(ValueError, 'FILE_DRIFT'):
            lab.plan(dict(self.request(), snapshot_id=first['snapshot_id']))
        self.assertFalse((self.state / 'target-runs').exists())

    def test_http_page_static_routes_and_same_origin_gate(self):
        server = Server(0, SimpleNamespace(cache=self.root/'demo', model=None), [self.manifest])
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            for path in ('/targets', '/targets.js', '/targets.css', '/api/targets/config'):
                connection.request('GET', path); response = connection.getresponse(); response.read()
                self.assertEqual(response.status, 200, path)
            body = json.dumps(self.request())
            connection.request('POST', '/api/targets/plan', body, {'Content-Type':'application/json'})
            response=connection.getresponse(); response.read(); self.assertEqual(response.status, 403)
            headers={'Content-Type':'application/json','X-REQLOX-Token':server.token}
            connection.request('POST', '/api/targets/plan', body, headers)
            response=connection.getresponse(); value=json.loads(response.read());self.assertEqual(response.status, 200)
            self.assertEqual(value['status'], 'PLANNED')
            connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_saved_stopped_result_is_audited_and_redacts_sources_paths_and_traces(self):
        lab = TargetLab([self.manifest]); request = self.request()
        planned = lab.dispatch('plan', request)
        with patch.object(runner, 'execute', side_effect=AssertionError('Native execution forbidden')):
            stopped = lab.dispatch('run', dict(request, plan_sha256=planned['plan_sha256']))
            summary = lab.dispatch('result', {'run_id': stopped['run_id']})
        self.assertEqual(summary['status'], 'STOPPED')
        self.assertEqual(summary['native_attempts'], 0)
        self.assertEqual(summary['audit']['new_native_campaigns'], 0)
        self.assertFalse(summary['audit']['child_semantics_verified'])
        self.assertEqual(lab.configuration('token')['saved_runs'],
            [dict(run_id=stopped['run_id'], target='owned-system')])
        raw = json.dumps(summary)
        for private in (str(self.root), 'candidate_code', 'source_texts', 'plan_sha256', 'stderr.log'):
            self.assertNotIn(private, raw)
        self.assertTrue(all(not r['candidate_files'] for r in summary['repositories']))
        self.assertFalse(summary['repositories'][0]['observations_verified'])
        with self.assertRaises(ValueError):lab.dispatch('result', {'run_id':'../outside'})
        with self.assertRaises(ValueError):lab.dispatch('result', {'run_id':stopped['run_id'],'path':'outside'})
        unknown = TargetLab([])
        with self.assertRaisesRegex(ValueError, 'UNREGISTERED_TARGET'):
            unknown.dispatch('result', {'run_id':stopped['run_id']})


if __name__ == '__main__': unittest.main()
