"""Check public asset scope, owner authentication, and origin boundaries."""
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import base64
import io
import threading
import urllib.request
import urllib.error
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


assets = module("cloud_web_assets", "scripts/cloud_web_assets.py")
bootstrap = module("web_bootstrap", "infra/gcp/public_web/web_bootstrap.py")
edge = module("cloudflare_deploy", "scripts/cloudflare_deploy.py")
preflight = module("cloud_web_preflight", "scripts/cloud_web_preflight.py")
gateway = module("web_gateway", "infra/gcp/public_web/gateway/main.py")


class WebBoundaryTests(unittest.TestCase):
    def test_record_routes_are_exported_and_forwarded_without_private_state(self):
        for route, filename in {'/records':'records.html','/records.js':'records.js',
                                '/workspace.js':'workspace.js','/workspace.css':'workspace.css'}.items():
            self.assertIn(filename, assets.FILES)
            self.assertEqual(gateway.STATIC[route], filename)
            self.assertIn('location = '+route, bootstrap.nginx_config('demo.example.dev','fixture-reqlox-web-assets'))
        terraform = (ROOT / 'infra/gcp/public_web/main.tf').read_text()
        static = re.search(r'static_files\s*=\s*toset\((\[[^\]]+\])\)', terraform).group(1)
        self.assertEqual(set(json.loads(static)), set(assets.FILES))
        self.assertNotIn('archived-records.json', assets.FILES)
        self.assertFalse(any('state' in value or 'corpus' in value for value in assets.FILES))

    def test_reload_waits_only_for_connection_readiness(self):
        with patch.object(bootstrap, "verify_web_once", side_effect=[urllib.error.URLError("refused"), None]) as check:
            with patch.object(bootstrap.time, "sleep"):
                bootstrap.verify_web(None, None, None)
        self.assertEqual(check.call_count, 2)
        for failure in [ValueError("release differs"), urllib.error.HTTPError("url", 403, "forbidden", {}, None)]:
            with patch.object(bootstrap, "verify_web_once", side_effect=failure) as check:
                with self.assertRaises(type(failure)):
                    bootstrap.verify_web(None, None, None)
            self.assertEqual(check.call_count, 1)
        with patch.object(bootstrap, "verify_web_once", side_effect=urllib.error.URLError("refused")) as check:
            with patch.object(bootstrap.time, "sleep"):
                with self.assertRaises(ValueError): bootstrap.verify_web(None, None, None)
        self.assertEqual(check.call_count, 15)

    def test_export_is_a_fixed_public_asset_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            for name in assets.OWNER_FILES:
                (source / name).write_text("<body>Inputs stay local</body>")
            for name in assets.PUBLIC_FILES:
                if not name.endswith(".json"):
                    (source/name).write_bytes((ROOT/"reqlox_demo/static"/name).read_bytes())
            (source / "state.sqlite").write_bytes(b"private fixture")
            (source / "private.md").write_text("private fixture")
            result = assets.export(source, root / "export")
            self.assertEqual(set(p.name for p in (root / "export").iterdir()), set(assets.FILES))
            self.assertFalse(result["documents_exported"])
            self.assertIn("Inputs stay on this VM", (root / "export/index.html").read_text())
            (source / "index.html").unlink()
            (source / "index.html").symlink_to(source / "private.md")
            with self.assertRaises(ValueError):
                assets.export(source, root / "bad")

    def test_public_proxy_requires_owner_auth_and_strips_credentials_before_gcs(self):
        config = bootstrap.nginx_config("demo.example.dev", "fixture-reqlox-web-assets")
        self.assertIn("listen 127.0.0.1:8081", config)
        self.assertIn('auth_basic "REQLOX owner"', config)
        for block in config.split("proxy_pass https://storage.googleapis.com/")[1:]:
            self.assertIn('proxy_set_header Authorization ""', block.split("}")[0])
            self.assertIn('proxy_set_header Cookie ""', block.split("}")[0])
            self.assertIn("proxy_ssl_verify on", block.split("}")[0])
        self.assertIn('"https://demo.example.dev" 1', config)
        for domain,bucket in [("demo.example.dev; evil", "fixture-reqlox-web-assets"),
                              ("demo.example.dev", "private-release-bucket")]:
            with self.assertRaises(ValueError):
                bootstrap.nginx_config(domain,bucket)

    def test_https_origin_is_allowed_only_when_explicitly_pinned(self):
        from reqlox_demo.server import Handler
        handler=Handler.__new__(Handler)
        handler.server=SimpleNamespace(server_port=8765)
        handler.headers={"Origin":"https://demo.example.dev"}
        self.assertFalse(handler.valid_origin())
        handler.server.allowed_origins=["https://demo.example.dev"]
        self.assertTrue(handler.valid_origin())
        for origin in ["https://evil.example.dev","http://demo.example.dev","https://demo.example.dev.evil.test","null"]:
            handler.headers={"Origin":origin}
            self.assertFalse(handler.valid_origin())

    def test_web_runtime_contract_cannot_remove_owner_authentication(self):
        from reqlox_demo.cloud_server import load_runtime
        valid={"access":"CLOUDFLARE_OWNER_LOGIN","paid_model_calls_enabled":False,
               "application_port":8765,"release_sha256":"a"*64,
               "web":{"public_origin":"https://demo.example.dev","authentication":"OWNER_BASIC_AUTH",
                      "owner_secret_resource":"projects/reqlox/secrets/reqlox-web-owner-login/versions/1"}}
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"runtime.json"
            p.write_text(json.dumps(valid))
            # load_runtime deliberately requires root-owned immutable metadata.
            with patch("reqlox_demo.cloud_server.Path.stat",return_value=SimpleNamespace(st_uid=0,st_mode=0o100644)):
                with patch("reqlox_demo.cloud_server.Path.is_file",return_value=True):
                    self.assertEqual(load_runtime(p)["access"],"CLOUDFLARE_OWNER_LOGIN")
                    for changed in [dict(valid,paid_model_calls_enabled=True),
                                    dict(valid,web=dict(valid['web'],authentication='NONE')),
                                    dict(valid,web=dict(valid['web'],public_origin='http://demo.example.dev')),
                                    dict(valid,web=dict(valid['web'],owner_secret_resource='projects/reqlox/secrets/reqlox-web-owner-login/versions/latest'))]:
                        p.write_text(json.dumps(changed))
                        with self.assertRaises(ValueError):load_runtime(p)

    def test_edge_plan_cannot_claim_an_unrelated_domain_or_route(self):
        config=dict(name='reqlox-web',project='reqlox',domain='demo.example.dev',root_domain='example.dev',tunnel_secret='reqlox-web-tunnel-token')
        self.assertEqual(edge.validate(config),config)
        for changed in [dict(config,domain='other.dev'),dict(config,name='existing-service'),dict(config,tunnel_secret='existing-secret')]:
            with self.assertRaises(ValueError):edge.validate(changed)
        route=edge.ingress(config['domain'])['config']['ingress']
        self.assertEqual(route[0]['service'],'http://127.0.0.1:8081')
        self.assertEqual(route[-1],{'service':'http_status:404'})

    def test_infrastructure_gate_rejects_private_bucket_publication_and_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'release';p.write_bytes(b'fixture')
            variables={k:{'value':v} for k,v in dict(project_id='reqlox',name='reqlox-web',domain='demo.example.dev',
                        release_archive=str(p),release_bucket='private-releases',iap_members=['user:owner@example.dev']).items()}
            resource=dict(mode='managed',type='google_storage_bucket_iam_member',address='fixture',
                          change=dict(actions=['create'],after=dict(bucket='reqlox-reqlox-web-assets',role='roles/storage.objectViewer',member='allUsers')))
            plan=dict(variables=variables,resource_changes=[resource])
            self.assertEqual(preflight.validate(plan,'reqlox','demo.example.dev')['status'],'PASS')
            resource['change']['after']['bucket']='private-releases'
            with self.assertRaises(ValueError):preflight.validate(plan,'reqlox','demo.example.dev')
            resource['change']['after']['bucket']='reqlox-reqlox-web-assets'
            resource['change']['actions']=['delete','create']
            with self.assertRaises(ValueError):preflight.validate(plan,'reqlox','demo.example.dev')


class OwnerGatewayTests(unittest.TestCase):
    def setUp(self):
        self.server=gateway.ThreadingHTTPServer(('127.0.0.1',0),gateway.Handler)
        self.server.public_host='demo.example.dev'
        self.server.bucket='public-assets'
        self.server.backend='http://127.0.0.1:1'
        self.server.release='a'*64
        self.server.authorization=b'Basic '+base64.b64encode(b'reqlox:unit-test-owner-password')
        self.server.bound=threading.BoundedSemaphore(8)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)

    def request(self,path,headers=None):
        request=urllib.request.Request(self.url+path,headers=headers or {})
        try:return urllib.request.urlopen(request,timeout=3)
        except urllib.error.HTTPError as exc:return exc

    def test_missing_and_incorrect_credentials_require_login_without_fetching(self):
        for auth in ('','Basic incorrect'):
            with self.request('/api/config',{'Authorization':auth}) as response:
                self.assertEqual(response.status,401)
                self.assertIn('Basic',response.headers['WWW-Authenticate'])
                self.assertEqual(response.headers['Cache-Control'],'no-store, no-transform')

    def test_cross_origin_request_is_rejected_even_with_valid_owner_credentials(self):
        with self.request('/api/config',{'Authorization':self.server.authorization.decode(),'Origin':'https://evil.example.dev'}) as response:
            self.assertEqual(response.status,403)

    def test_gcs_never_receives_browser_authorization_or_token(self):
        observed=[]
        real=gateway.urllib.request.urlopen
        def fetch(request,*args,**kwargs):
            if request.full_url.startswith('https://storage.googleapis.com/'):
                observed.append(request)
                value=io.BytesIO(b'<body>public</body>');value.status=200;value.headers={'Content-Type':'text/html'}
                return value
            return real(request,*args,**kwargs)
        with patch.object(gateway.urllib.request,'urlopen',side_effect=fetch):
            with self.request('/',{'Authorization':self.server.authorization.decode(),'Cookie':'private-cookie','X-REQLOX-Token':'private-fixture'}) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.read(),b'<body>public</body>')
        self.assertEqual(len(observed),1)
        self.assertEqual(observed[0].header_items(),[])

    def test_anonymous_demo_is_exact_static_allowlist_without_workspace_proxy(self):
        from reqlox_demo.public_demo import ROUTES
        self.assertEqual(gateway.PUBLIC, ROUTES)
        self.assertEqual(assets.PUBLIC_ROUTES, ROUTES)
        observed=[];real=gateway.urllib.request.urlopen
        def fetch(request,*args,**kwargs):
            if request.full_url.startswith('https://storage.googleapis.com/'):
                observed.append(request)
                value=io.BytesIO(b'curated fixture');value.status=200;value.headers={'Content-Type':'text/plain'}
                return value
            return real(request,*args,**kwargs)
        with patch.object(gateway.urllib.request,'urlopen',side_effect=fetch):
            for path in ROUTES:
                with self.request(path,{'Cookie':'private-cookie','X-REQLOX-Token':'private-token'}) as response:
                    self.assertEqual(response.status,200)
                    self.assertEqual(response.headers['Cache-Control'],'no-store, no-transform')
                    self.assertNotIn('WWW-Authenticate',response.headers)
            self.assertEqual(len(observed),len(ROUTES))
            self.assertTrue(all(r.header_items()==[] for r in observed))
            for path in ['/api/workspace/config','/api/config','/workspace.js','/records']:
                with self.request(path) as response:self.assertEqual(response.status,401)
            for path in ['/demo/api/workspace/config','/demo/../api/config','/demo/%2e%2e/api/config','/demo/private.json']:
                with self.request(path) as response:self.assertEqual(response.status,404)
            self.assertEqual(len(observed),len(ROUTES))

    def test_public_write_methods_are_denied_before_any_fetch(self):
        with patch.object(gateway.urllib.request,'urlopen',wraps=urllib.request.urlopen) as fetch:
            for method in ['POST','PUT','PATCH','DELETE','OPTIONS']:
                request=urllib.request.Request(self.url+'/demo/public-demo.json',method=method)
                with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(request,timeout=3)
                self.assertEqual(exc.exception.code,405)
            self.assertEqual(fetch.call_count,5)  # Only the loopback client calls, never GCS/backend.


if __name__ == "__main__":
    unittest.main()
