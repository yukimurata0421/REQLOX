"""Restore real temporary files; cloud, service and secret effects remain fake."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('runtime_return',ROOT/'infra/gcp/runtime_rollback.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def fixture():
    old=dict(host_id='reqlox-web',project_id='reqlox',release_sha256='a'*64,
             artifact_object='releases/'+'a'*64+'.tar.gz',paid_model_calls_enabled=False,
             state_disk='retained',owner_secret_resource='unchanged-version-1')
    contract=dict(host_id='reqlox-web',project_id='reqlox',role='REQLOX bounded isolated demo',release_sha256='a'*64)
    raw=lambda x:(json.dumps(x,sort_keys=True)+'\n').encode()
    backup=[raw(old),raw(contract),b'fixed managed instructions',b'old nginx',b'old web source']
    new=dict(old,release_sha256='b'*64,artifact_object='releases/'+'b'*64+'.tar.gz')
    current=[raw(new),raw(dict(contract,release_sha256='b'*64)),backup[2],b'new nginx',b'new web source']
    cfg=dict(old_release_sha256='a'*64,failed_release_sha256='b'*64,
        instructions_sha256=r.digest(backup[2]),old_runtime_sha256=r.digest(backup[0]),
        old_contract_sha256=r.digest(backup[1]),new_nginx_sha256=r.digest(current[3]),
        new_web_bootstrap_sha256=r.digest(current[4]),legacy_backup_sha256=list(map(r.digest,backup)),
        physical_instance_id='3115344231848612081',base_bootstrap_sha256=r.digest(b'base source'),
        rollback_method_sha256=r.digest((ROOT/'infra/gcp/runtime_rollback.py').read_bytes()),request_id='owned-return')
    return cfg,backup,current,old


class ValidationTests(unittest.TestCase):
    def test_new_and_already_old_runtime_keep_the_same_authority_and_state(self):
        cfg,b,c,old=fixture()
        self.assertEqual(r.validate(cfg,b,c,'/opt/reqlox/releases/'+'b'*64+'/site'),old)
        self.assertEqual(r.validate(cfg,b,b,'/opt/reqlox/releases/'+'a'*64+'/site'),old)

    def test_foreign_release_authority_sources_and_pointer_are_rejected(self):
        cfg,b,c,_=fixture()
        cases=[]
        for index,key,value in [(0,'release_sha256','c'*64),(0,'host_id','foreign'),
            (0,'state_disk','foreign'),(0,'owner_secret_resource','version-2'),
            (0,'paid_model_calls_enabled',True),(1,'role','production'),(1,'extra_authority',True)]:
            changed=copy.deepcopy(c);v=json.loads(changed[index]);v[key]=value;changed[index]=json.dumps(v).encode();cases.append(changed)
        for index in (2,3,4):
            changed=copy.deepcopy(c);changed[index]=b'foreign';cases.append(changed)
        for current in cases:
            with self.subTest(current=current),self.assertRaises(ValueError):
                r.validate(cfg,b,current,'/opt/reqlox/releases/'+'b'*64+'/site')
        with self.assertRaisesRegex(ValueError,'SITE_POINTER'):
            r.validate(cfg,b,c,'/foreign/site')


class FilesystemTests(unittest.TestCase):
    def run_files(self,mutation=None,fail_web=False,twice=False,legacy=False):
        cfg,b,c,old=fixture();effects=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def path(value):
                value=str(value)
                return root/value.lstrip('/') if value.startswith(('/etc/','/var/lib/','/opt/','/usr/local/')) else Path(value)
            def write(name,raw):
                p=path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            unit=b'/etc/codex-host-context/host.json /etc/codex-host-context/AGENTS.md /var/lib/reqlox-host-context/HOST_CONTEXT.generated.md'
            cfg['collector_unit_sha256']=r.digest(unit)
            write('/etc/systemd/system/codex-host-context-refresh.service',unit)
            write('/usr/local/libexec/reqlox-base-bootstrap.py',b'base source')
            backup='/var/lib/reqlox-reviewed-rollouts/'+'b'*64+'/before/'
            for i,name in enumerate(r.FILES):write(name,c[i]);write(backup+str(i),b[i])
            if not legacy:
                write(backup+'manifest.json',json.dumps(dict(sha256=cfg.pop('legacy_backup_sha256'))).encode())
            pointer=path('/opt/reqlox/site');pointer.parent.mkdir(parents=True,exist_ok=True)
            target=path('/opt/reqlox/releases/'+'b'*64+'/site');target.mkdir(parents=True);pointer.symlink_to(target)
            private=path('/var/lib/private-state');private.mkdir(parents=True);(private/'history').write_bytes(b'keep all 37 records')
            metadata={'instance/id':b'3115344231848612081','instance/name':b'reqlox-web',
                      'project/project-id':b'reqlox','instance/attributes/reqlox-runtime':json.dumps(old).encode()}
            if mutation:mutation(cfg,path,metadata)
            def web():
                effects.append('web-load-existing-secret-versions')
                if fail_web:raise RuntimeError('owned web failure')
            base=types.SimpleNamespace(metadata=lambda key:metadata[key])
            module=lambda name,p:base if name=='rollback_base' else types.SimpleNamespace(main=web)
            original=r.validate
            def validate(cfg,backup,current,p):return original(cfg,backup,current,p.removeprefix(str(root)))
            def read(p):return path(p).read_bytes()
            with patch.object(r,'Path',side_effect=path),patch.object(r,'protected',side_effect=read),patch.object(r,'module',side_effect=module),patch.object(r,'command',side_effect=lambda *args:effects.append(args)),patch.object(r,'validate',side_effect=validate),patch.object(r.os,'getuid',return_value=0),patch.object(r.sys,'version_info',(3,11)):
                try:
                    r.main(cfg)
                    if twice:r.main(cfg)
                except BaseException as exc:return effects,type(exc).__name__,str(exc),list(path('/var/lib/reqlox-reviewed-returns').rglob('*.json'))
            self.assertEqual([path(name).read_bytes() for name in r.FILES],b)
            self.assertEqual(str(pointer.readlink()),'/opt/reqlox/releases/'+'a'*64+'/site')
            self.assertEqual((private/'history').read_bytes(),b'keep all 37 records')
            return effects,None,None,None

    def test_applied_release_is_restored_from_real_files_and_history_is_untouched(self):
        effects,error,_,_=self.run_files();self.assertIsNone(error)
        self.assertEqual(effects,[('systemctl','stop','reqlox.service','nginx.service'),'web-load-existing-secret-versions'])

    def test_foreign_vm_and_tampered_backup_stop_before_service_effect(self):
        variants=[lambda c,p,m:m.update({'instance/id':b'foreign'}),
                  lambda c,p,m:p('/var/lib/reqlox-reviewed-rollouts/'+'b'*64+'/before/3').write_bytes(b'corrupt'),
                  lambda c,p,m:m.update({'instance/attributes/reqlox-runtime':b'{}'})]
        for change in variants:
            effects,error,_,_=self.run_files(change);self.assertEqual(effects,[]);self.assertEqual(error,'ValueError')

    def test_failed_return_is_durable_and_is_never_reported_restored(self):
        effects,error,reason,paths=self.run_files(fail_web=True)
        self.assertEqual(error,'RuntimeError');self.assertEqual(reason,'owned web failure')
        self.assertIn('failed.json',[p.name for p in paths]);self.assertNotIn('ready.json',[p.name for p in paths])

    def test_completed_return_reloads_on_a_later_boot_without_a_second_restore(self):
        effects,error,_,_=self.run_files(twice=True);self.assertIsNone(error)
        self.assertEqual(effects.count(('systemctl','stop','reqlox.service','nginx.service')),1)
        self.assertEqual(effects.count('web-load-existing-secret-versions'),2)

    def test_incomplete_reservation_is_not_retried(self):
        def reserve(cfg,path,metadata):
            state=path('/var/lib/reqlox-reviewed-returns/owned-return');state.mkdir(parents=True)
            (state/'reserved.json').write_text('{}')
        effects,error,reason,_=self.run_files(reserve)
        self.assertEqual(effects,[]);self.assertEqual(error,'ValueError');self.assertIn('NO_RETRY',reason)

    def test_explicitly_frozen_legacy_backup_supports_the_scoped_recovery(self):
        effects,error,_,_=self.run_files(legacy=True);self.assertIsNone(error)
        self.assertEqual(effects.count(('systemctl','stop','reqlox.service','nginx.service')),1)


if __name__=='__main__':unittest.main()
