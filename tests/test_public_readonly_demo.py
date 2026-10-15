"""Publication boundary checks with owned summaries and loopback HTTP only."""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from reqlox_demo import public_demo as demo


class PublicProjectionTests(unittest.TestCase):
    def fixtures(self, directory):
        p = Path(directory)
        for name in ('archived-records.json', 'copied-module-integration-summary.json'):
            (p/name).write_bytes((demo.ROOT/'data'/name).read_bytes())
        return p

    def test_archive_keeps_held_gap_and_finite_claims(self):
        result = demo.payload()
        self.assertEqual([r['id'] for r in result['records']], list(demo.RECORD_IDS))
        self.assertEqual(result['ledger']['campaigns'], 15)
        self.assertEqual(result['ledger']['charged_seconds'], 62)
        row = next(r for r in result['records'] if r['id'] == 'temppath-readme-v01')
        self.assertEqual(row['held_atomic_bindings'], 4)
        self.assertIs(row['temppath_repair_performed'], False)
        self.assertEqual(row['steps'][2]['status'], 'NOT_PERFORMED')
        self.assertTrue(any(r['historical_raw_evidence_gap'] for r in result['records']))
        self.assertFalse(any(result['claims'].values()))

    def test_private_fields_and_extra_records_cannot_enter_projection(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.fixtures(d); path = p/'archived-records.json'; raw = json.loads(path.read_bytes())
            for row in raw['records']:
                row['token'] = 'PRIVATE_HISTORY_CANARY'
                row['source']['private_path'] = '/home/owner/private'
                row['steps'][0]['raw_response'] = 'PRIVATE_HISTORY_CANARY'
                row['record_sha256'] = hashlib.sha256(demo.encode({k:v for k,v in row.items() if k != 'record_sha256'})).hexdigest()
            raw['history'] = ['PRIVATE_HISTORY_CANARY']
            raw['records'].append(dict(id='private-record', raw_response='PRIVATE_HISTORY_CANARY'))
            path.write_bytes(demo.encode(raw)); result = demo.encode(demo.payload(p))
            for value in [b'PRIVATE_HISTORY_CANARY', b'/home/', b'private_path', b'raw_response', b'"token"', b'"history"']:
                self.assertNotIn(value, result)

    def test_hash_and_ledger_drift_stop_publication(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.fixtures(d); path=p/'archived-records.json'; raw=json.loads(path.read_bytes())
            raw['records'][0]['title']='changed';path.write_bytes(demo.encode(raw))
            with self.assertRaisesRegex(ValueError,'RECORD_HASH'): demo.payload(p)
            p=self.fixtures(d); path=p/'copied-module-integration-summary.json'; raw=json.loads(path.read_bytes())
            raw['summary']['maximum_campaigns']=16;path.write_bytes(demo.encode(raw))
            with self.assertRaisesRegex(ValueError,'LEDGER_DRIFT'): demo.payload(p)

    def test_export_is_deterministic_static_and_has_no_cloud_notice(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); a=demo.export(p/'a');b=demo.export(p/'b')
            self.assertEqual(a,b)
            self.assertEqual(set(x.name for x in (p/'a').iterdir()),set(demo.FILES))
            self.assertNotIn(b'Inputs stay on this VM',(p/'a/public-demo.html').read_bytes())
            with self.assertRaisesRegex(ValueError,'OUTPUT_NOT_EMPTY'): demo.export(p/'a')
            (p/'link').symlink_to(p/'b', target_is_directory=True)
            with self.assertRaises(ValueError): demo.export(p/'link')

    def test_input_symlink_oversize_and_private_text_are_rejected(self):
        for value in ['/home/owner/private', 'https://private.invalid', 'Bearer private', 'owner@example.invalid']:
            with self.assertRaises(ValueError): demo.text(value)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'a').write_bytes(b'x'*(demo.MAXIMUM_BYTES+1))
            with self.assertRaises(ValueError): demo.read(p/'a')
            (p/'link').symlink_to(demo.ROOT/'data/archived-records.json')
            with self.assertRaises(ValueError): demo.read(p/'link')


class PreviewBoundaryTests(unittest.TestCase):
    def test_no_workspace_or_execution_routes_and_read_methods_only(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),demo.PreviewHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}'
            for path,method,status in [('/demo/','GET',200),('/demo/public-demo.json','GET',200),
                    ('/demo/public-demo.js','HEAD',200),('/api/workspace/config','GET',404),
                    ('/demo/api/workspace/config','GET',404),('/demo/../api/config','GET',404),
                    ('/demo/%2e%2e/api/config','GET',404),('/demo/','POST',405),
                    ('/api/run','POST',405),('/demo/','DELETE',405)]:
                request=urllib.request.Request(root+path, method=method)
                try: response=urllib.request.urlopen(request,timeout=3)
                except urllib.error.HTTPError as error: response=error
                with response: self.assertEqual(response.status,status,(path,method))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


if __name__ == '__main__': unittest.main()
