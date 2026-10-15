"""Exercise CI release admission and rollback with owned fake cloud effects."""
import base64
import copy
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_deploy', ROOT/'scripts/cloud_ci_deploy.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def fixture():
    cfg = ci.load_configuration(ROOT/'infra/gcp/cicd.json')
    runtime = dict(host_id='reqlox-web', project_id='reqlox', release_sha256='a'*64,
        artifact_bucket=cfg['releases_bucket'], artifact_object='releases/'+'a'*64+'.tar.gz',
        paid_model_calls_enabled=False, access='CLOUDFLARE_OWNER_LOGIN', data_disk='owned-state',
        web=dict(assets_bucket=cfg['assets_bucket'], owner_secret_resource=cfg['owner_secret_version'],
                 public_origin=cfg['origin'], authentication='OWNER_BASIC_AUTH'))
    vm = dict(id=cfg['instance_id'], name=cfg['instance'], status='RUNNING',
        metadata=dict(fingerprint='owned', items=[dict(key='reqlox-runtime', value=json.dumps(runtime)),
            dict(key='reqlox-release-sha256', value='a'*64),dict(key='startup-script', value='owned old startup')]),
        disks=[dict(source='owned-state-disk')], scheduling=dict(automaticRestart=False),
        serviceAccounts=[dict(email='owned-runtime-account')])
    return cfg, vm


def policy():
    return dict(mode='OFFLINE_RECORDS_ONLY', cumulative_campaigns=15, maximum_campaigns=15,
        charged_seconds=62, maximum_seconds=120, remaining_campaigns=0,
        native_execution_enabled=False, model_calls_enabled=False, source_fetch_enabled=False)


def host(vm):
    runtime=json.loads(next(r['value'] for r in vm['metadata']['items'] if r['key']=='reqlox-runtime'))
    contract=dict(host_id='reqlox-web', project_id='reqlox', role='REQLOX bounded isolated demo',
        release_sha256=runtime['release_sha256'], preserved='owned-history')
    raw=json.dumps(contract)
    context=dict(boot_id='owned-boot', host_id='reqlox-web', project_id='reqlox',
        contract_sha256=ci.digest(raw.encode()), release_sha256=runtime['release_sha256'],
        generated_jst=datetime.datetime.now(datetime.timezone.utc).isoformat(), state_disk_mounted=True,
        units={'reqlox.service':dict(ActiveState='active')})
    evidence=dict(collector_unit='/etc/codex-host-context/host.json /etc/codex-host-context/AGENTS.md '
        '/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md',
        instructions='BEGIN MANAGED: codex-host-contract-v1',contract=raw,
        context='```json\n'+json.dumps(context)+'\n```',boot_id='owned-boot',physical_instance_id=vm['id'])
    deployment=dict(status='READY',paid_model_calls_enabled=False,release_sha256=runtime['release_sha256'])
    return evidence,deployment


class FakeCloud:
    def __init__(self, vm):
        self.vm=copy.deepcopy(vm);self.opener=None;self.uploads=[];self.effects=[];self.tag=None;self.promoted=False
        self.break_after_cutover=False;self.fail_rollback_identity=False

    def api(self,url,method='GET',value=None,**kwargs):
        if ':access' in url:
            return dict(payload=dict(data=base64.b64encode(b'p'*32).decode()))
        if method=='GET':
            return copy.deepcopy(self.vm)
        self.effects.append((url.rsplit('/',1)[-1],copy.deepcopy(value)))
        if url.endswith('/setMetadata'):
            self.vm['metadata']=copy.deepcopy(value)
        elif url.endswith('/stop'):
            self.vm['status']='TERMINATED'
        elif url.endswith('/start'):
            self.vm['status']='RUNNING'
        return {'selfLink':'owned-operation'}

    def poll(self,operation,seconds=180):
        return None

    def upload(self,bucket,name,raw,kind):
        if name in self.uploads:
            raise ValueError('DUPLICATE_ADMISSION')
        self.uploads.append(name)
        return dict(name=name,generation='1',sha256=ci.digest(raw))

    def command(self,args,**kwargs):
        if args[:3]==['run','services','describe']:
            rows=[dict(revisionName='old-revision',percent=100)]
            if self.tag:
                rows.append(dict(revisionName='new-revision',percent=0,tag=self.tag,url='https://owned.run.app'))
            if self.promoted:
                rows=[dict(revisionName='new-revision',percent=100)]
            return dict(status=dict(traffic=rows))
        if args[:2]==['run','deploy']:
            self.tag=next(a.split('=',1)[1] for a in args if a.startswith('--tag='))
            if self.break_after_cutover:
                if self.fail_rollback_identity:
                    self.vm['id']='foreign'
                raise ValueError('OWNED_DEPLOY_FAILURE')
        if args[:3]==['run','services','update-traffic']:
            self.promoted='--to-revisions=new-revision=100' in args
        return {}


class DeployJobImportTests(unittest.TestCase):
    def test_static_verification_needs_no_installed_application_in_deploy_job(self):
        import sys
        sys.path.insert(0, str(ROOT/'scripts'))
        cfg,vm=fixture();job=ci.Deployment(cfg,'b'*40,ROOT,ROOT/'unused',FakeCloud(vm))
        routes={'/demo/':'public-demo.html','/demo/public-demo.html':'public-demo.html',
                '/demo/public-demo.js':'public-demo.js','/demo/public-demo.css':'public-demo.css',
                '/demo/public-demo.json':'public-demo.json'}
        def response(path,**kwargs):
            if path in routes:
                return (405,b'{}') if kwargs.get('value') is not None else (200,b'owned static asset')
            return (401,b'{}') if path=='/api/workspace/config' else (404,b'{}')
        manifest=dict(files=[dict(name=n,sha256=ci.digest(b'owned static asset')) for n in set(routes.values())])
        with patch.dict(sys.modules, {'reqlox_demo':None,'reqlox_demo.public_demo':None}),patch.object(job,'public',side_effect=response):
            job.verify_public_demo(None,manifest)
        self.assertTrue(job.result['anonymous_demo_verified'])


class AdmissionTests(unittest.TestCase):
    def test_only_fixed_host_project_and_budget_are_accepted(self):
        cfg,_=fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'
            for key in ('project','instance','instance_id','gateway','origin','native_campaigns','charged_seconds'):
                p.write_text(json.dumps(dict(cfg,**{key:'changed'})))
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'SCOPE_DRIFT'):
                    ci.load_configuration(p)

    def test_every_execution_capability_remains_disabled(self):
        ci.check_policy(policy())
        for key in ('native_execution_enabled','model_calls_enabled','source_fetch_enabled'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'POLICY_DRIFT'):
                ci.check_policy(dict(policy(),**{key:True}))
        for key in ('cumulative_campaigns','maximum_campaigns','charged_seconds','remaining_campaigns'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                ci.check_policy(dict(policy(),**{key:0 if key!='remaining_campaigns' else 1}))

    def test_physical_context_release_collector_and_root_role_drift_stop(self):
        cfg,vm=fixture();evidence,deployment=host(vm)
        self.assertEqual(ci.validate_host(vm,evidence,deployment,cfg)['release_sha256'],'a'*64)
        variants=[dict(evidence,physical_instance_id='other'),dict(evidence,collector_unit='other'),
            dict(evidence,instructions='missing'),dict(evidence,boot_id='other'),
            dict(evidence,contract=evidence['contract'].replace('isolated demo','production'))]
        for changed in variants:
            with self.assertRaises(ValueError):ci.validate_host(vm,changed,deployment,cfg)
        with self.assertRaises(ValueError):
            ci.validate_host(vm,evidence,dict(deployment,release_sha256='b'*64),cfg)

    def test_stale_signed_context_never_becomes_authority(self):
        cfg,vm=fixture();evidence,deployment=host(vm)
        value=json.loads(evidence['context'].split('```json\n')[1].split('\n```')[0])
        value['generated_jst']='2000-01-01T00:00:00+00:00'
        evidence['context']='```json\n'+json.dumps(value)+'\n```'
        with self.assertRaisesRegex(ValueError,'CONTEXT_STALE'):
            ci.validate_host(vm,evidence,deployment,cfg)

    def test_startup_binds_existing_rollout_and_never_includes_private_state(self):
        cfg,vm=fixture();evidence,deployment=host(vm)
        old=ci.validate_host(vm,evidence,deployment,cfg);new=dict(old,release_sha256='b'*64)
        bound=ci.rollout_config(vm,evidence,old,new,cfg)
        script=ci.startup_script(bound)
        self.assertIn('timeout 600 python3',script)
        self.assertNotIn('reqlox-state',script)
        with self.assertRaisesRegex(ValueError,'METHOD_DRIFT'):
            ci.startup_script(dict(bound,rollout_method_sha256='0'*64))

    def test_non_main_non_push_and_rerun_contexts_have_no_cloud_effect(self):
        cfg,vm=fixture()
        for changes in ({'GITHUB_REF':'refs/pull/1/merge'}, {'GITHUB_EVENT_NAME':'pull_request'},
                        {'GITHUB_RUN_ATTEMPT':'2'}, {'GITHUB_REPOSITORY':'foreign/repo'}):
            cloud=FakeCloud(vm)
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,self.env()|changes):
                job=ci.Deployment(cfg,'b'*40,Path(d),Path(d)/'out',cloud)
                with self.assertRaisesRegex(ValueError,'WORKFLOW_CONTEXT'):job.run()
                self.assertEqual(cloud.effects,[]);self.assertEqual(cloud.uploads,[])

    def env(self):
        return dict(GITHUB_REPOSITORY='yukimurata0421/REQLOX',GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='push',GITHUB_SHA='b'*40,GITHUB_RUN_ATTEMPT='1')


class FakeDeploymentTests(AdmissionTests):
    def run_owned(self,failure=False,identity_drift=False):
        import sys
        sys.path.insert(0,str(ROOT/'scripts'))
        import cloud_web_assets
        cfg,vm=fixture();cloud=FakeCloud(vm);cloud.break_after_cutover=failure
        cloud.fail_rollback_identity=identity_drift
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,self.env()):
            root=Path(d);bundle=root/'bundle';(bundle/'release').mkdir(parents=True)
            (bundle/'release/cloud-release.tar.gz').write_bytes(b'owned fake archive')
            assets=cloud_web_assets.export(ROOT/'reqlox_demo/static',bundle/'assets')
            (bundle/'assets.json').write_text(json.dumps(assets))
            job=ci.Deployment(cfg,'b'*40,bundle,root/'out',cloud)
            def public(path,*,base=None,headers=None,value=None,authenticate=True):
                if path.startswith('/demo/'):
                    from reqlox_demo.public_demo import ROUTES
                    if path not in ROUTES:return 404,b'{}'
                    if value is not None:return 405,b'{}'
                    return 200,(bundle/'assets'/ROUTES[path]).read_bytes()
                if not authenticate:return 401,b'{}'
                if headers and headers.get('Origin')=='https://wrong.example':return 403,b'{}'
                evidence,deployment=host(cloud.vm)
                responses={'/api/config':dict(token='owned-token'),'/api/host-context':evidence,
                    '/api/deployment':deployment,'/api/workspace/config':dict(execution_policy=policy(),history=['owned-record'])}
                if value is not None:return 403,b'{"error":"UI_EXECUTION_DISABLED"}'
                if path in responses:return 200,json.dumps(responses[path]).encode()
                name={'/':'index.html','/study':'study.html','/knowledge':'knowledge.html',
                    '/targets':'targets.html','/records':'records.html'}.get(path,path.removeprefix('/'))
                return 200,(bundle/'assets'/name).read_bytes()
            with patch.object(job,'public',side_effect=public),patch.object(job,'build_gateway',return_value='owned-image@sha256:'+'b'*64):
                if failure:
                    with self.assertRaisesRegex(ValueError,'OWNED_DEPLOY_FAILURE'):job.run()
                else:job.run()
            result=json.loads((root/'out/result.json').read_text())
            return result,cloud,vm

    def test_tested_release_is_promoted_after_same_budget_history_and_stop_checks(self):
        result,cloud,old=self.run_owned()
        self.assertEqual(result['status'],'DEPLOYED_AND_HTTP_VERIFIED')
        self.assertEqual(len(result['execution_stop_checked']),3)
        self.assertEqual(result['new_native_campaigns'],0);self.assertEqual(result['new_model_calls'],0)
        self.assertTrue(result['private_history_preserved']);self.assertEqual(cloud.vm['disks'],old['disks'])
        self.assertTrue(result['anonymous_demo_verified'])
        self.assertEqual([k for k,v in cloud.effects],['setMetadata','stop','start'])

    def test_failed_cutover_restores_old_metadata_once_and_keeps_admission_history(self):
        result,cloud,old=self.run_owned(failure=True)
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(cloud.vm['metadata']['items'],old['metadata']['items'])
        self.assertEqual(sum(k=='start' for k,v in cloud.effects),2)
        self.assertTrue(any(name.startswith('deployments/') for name in cloud.uploads))

    def test_rollback_identity_drift_never_signals_a_foreign_vm(self):
        result,cloud,_=self.run_owned(failure=True,identity_drift=True)
        self.assertEqual(result['rollback'],'OUTCOME_UNKNOWN_STOP_NO_RETRY')
        self.assertEqual(sum(k=='stop' for k,v in cloud.effects),1)


if __name__=='__main__':unittest.main()
