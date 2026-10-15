"""Deployment inputs must not weaken local isolation or include private files."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import zipfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


bootstrap = module("bootstrap", "infra/gcp/runtime_bootstrap.py")
preflight = module("cloud_preflight", "scripts/cloud_preflight.py")
release = module("cloud_release", "scripts/cloud_release.py")


class CloudLocationTests(unittest.TestCase):
    def test_hosted_pages_describe_where_inputs_are_stored(self):
        from reqlox_demo.cloud_server import cloud_page
        raw = cloud_page(b"<html><body><strong>Inputs stay local</strong></body></html>")
        self.assertIn(b"stored on that VM", raw)
        self.assertIn(b"Inputs stay on this VM", raw)
        self.assertNotIn(b"Inputs stay local", raw)


class ReleaseSafetyTests(unittest.TestCase):
    def test_system_namespace_is_allowed_but_private_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);wheel=root/'reqlox-0.1.0-py3-none-any.whl'
            def write(member):
                with zipfile.ZipFile(wheel,'w') as bundle:
                    bundle.writestr('reqlox-0.1.0.dist-info/METADATA','Name: reqlox\nVersion: 0.1.0\n')
                    bundle.writestr(member,'owned fixture')
            write('reqlox_system/pipeline.py')
            self.assertIn('reqlox==0.1.0',release.build_manifest(root))
            for member in ['corpus/private.json','targets/target.json','database/state.sqlite','reqlox_system/../escape.py']:
                write(member)
                with self.assertRaises(ValueError):release.build_manifest(root)

    def test_reviewed_method_changes_release_identity_without_changing_wheels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wheelhouse").mkdir()
            (root / "wheelhouse/example.whl").write_bytes(b"test fixture")
            (root / "requirements.txt").write_text("example==1\n")
            results = []
            manifests = []
            for method in ("a" * 64, "b" * 64):
                archive = root / (method + ".tar.gz")
                results.append(release.archive_release(root, archive, rollout_method_sha256=method))
                with tarfile.open(archive, "r:gz") as bundle:
                    manifests.append(json.load(bundle.extractfile("release.json")))
                    self.assertEqual(bundle.extractfile("wheelhouse/example.whl").read(), b"test fixture")
            self.assertNotEqual(results[0]["sha256"], results[1]["sha256"])
            self.assertEqual(manifests[0]["files"], manifests[1]["files"])
            self.assertEqual(manifests[1]["rollout_method_sha256"], "b" * 64)

    def test_invalid_method_binding_cannot_create_an_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "invalid.tar.gz"
            for method in (True, "A" * 64, "a" * 63, "a" * 65, "../method"):
                with self.subTest(method=method), self.assertRaises(ValueError):
                    release.archive_release(root, archive, rollout_method_sha256=method)
                self.assertFalse(archive.exists())

    def test_readiness_requires_the_actual_release_and_isolation(self):
        runtime=dict(release_sha256='1'*64,host_id='reqlox-demo',project_id='reqlox')
        valid=dict(runtime,status='READY',isolation_probe_passed=True,jev_credential_loaded=True,paid_model_calls_enabled=False)
        with patch.object(bootstrap,'request',return_value=json.dumps(valid).encode()):
            bootstrap.verify_ready(runtime,attempts=1)
        for changed in (dict(valid,release_sha256='2'*64),dict(valid,isolation_probe_passed=False),
                        dict(valid,jev_credential_loaded=False),dict(valid,paid_model_calls_enabled=True)):
            with self.subTest(changed=changed),patch.object(bootstrap,'request',return_value=json.dumps(changed).encode()),patch.object(bootstrap.time,'sleep'):
                with self.assertRaises(ValueError):bootstrap.verify_ready(runtime,attempts=1)

    def malicious_archive(self, name, kind=tarfile.REGTYPE):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        archive = root / "input.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.linkname = "/etc/passwd"
            entry.size = 1 if kind == tarfile.REGTYPE else 0
            bundle.addfile(entry, io.BytesIO(b"x") if entry.size else None)
        return temp, root, archive

    def test_root_extraction_rejects_traversal_links_and_unlisted_files(self):
        for name, kind in (("../etc/passwd", tarfile.REGTYPE), ("/etc/passwd", tarfile.REGTYPE),
                           ("wheelhouse/package.whl", tarfile.SYMTYPE), ("docs/private.md", tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                temp, root, archive = self.malicious_archive(name, kind)
                with temp, self.assertRaises(ValueError):
                    bootstrap.extract_release(archive, root / "output")

    def test_release_inventory_and_file_hashes_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "wheelhouse").mkdir()
            (root / "wheelhouse/example.whl").write_bytes(b"test fixture")
            (root / "requirements.txt").write_text("example==1 --hash=sha256:fixture\n")
            archive = root / "bundle.tar.gz"
            result = release.archive_release(root, archive)
            output = root / "output"
            output.mkdir()
            value = bootstrap.extract_release(archive, output)
            self.assertFalse(value["documentation_included"])
            self.assertFalse(result["docs_uploaded"])
            # A changed body is rejected, even in an otherwise valid inventory.
            value["files"][0]["sha256"] = "0" * 64
            (root / "release.json").write_text(json.dumps(value))
            bad = root / "bad.tar.gz"
            with tarfile.open(bad, "w:gz") as bundle:
                for relative in ("release.json", "requirements.txt", "wheelhouse/example.whl"):
                    bundle.add(root / relative, arcname=relative)
            another = root / "another"
            another.mkdir()
            with self.assertRaises(ValueError):
                bootstrap.extract_release(bad, another)


class PlanBoundaryTests(unittest.TestCase):
    def plan(self, actions=None, kind="google_compute_network"):
        return {"variables": {"project_id": {"value": "reqlox"}, "name": {"value": "reqlox-demo"}},
                "resource_changes": [{"mode": "managed", "address": "fixture", "type": kind,
                  "change": {"actions": actions or ["create"], "after": {"name": "reqlox-demo", "project": "reqlox"}}}]}

    def test_cross_project_replacements_and_secret_state_are_rejected(self):
        for plan in (self.plan(["delete", "create"]), self.plan(kind="google_secret_manager_secret_version")):
            with self.assertRaises(ValueError):
                preflight.validate(plan, "reqlox", "reqlox-demo")
        plan = self.plan()
        plan["resource_changes"][0]["change"]["after"]["project"] = "other-project"
        with self.assertRaises(ValueError):
            preflight.validate(plan, "reqlox", "reqlox-demo")
        self.assertEqual(preflight.validate(self.plan(), "reqlox", "reqlox-demo")["deletes"], 0)

    def test_standard_e2_maintenance_and_finite_lease_are_enforced(self):
        plan = self.plan(kind="google_compute_instance")
        after = plan['resource_changes'][0]['change']['after']
        after.update(machine_type='e2-medium',scheduling=[dict(instance_termination_action='STOP',
            max_run_duration=[dict(seconds=86400)],on_host_maintenance='MIGRATE',automatic_restart=False)])
        self.assertEqual(preflight.validate(plan,'reqlox','reqlox-demo')['status'],'PASS')
        for key,value in [('on_host_maintenance','TERMINATE'),('automatic_restart',True),
                          ('max_run_duration',[dict(seconds=90000)])]:
            changed=json.loads(json.dumps(plan));changed['resource_changes'][0]['change']['after']['scheduling'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                preflight.validate(changed,'reqlox','reqlox-demo')

    def test_persistent_state_and_unobserved_instances_cannot_be_replaced(self):
        plan=self.plan(['delete','create'],kind='google_compute_disk')
        with self.assertRaises(ValueError):preflight.validate(plan,'reqlox','reqlox-demo',replace_instance_id='123')
        plan=self.plan(['delete','create'],kind='google_compute_instance')
        plan['resource_changes'][0]['change']['before']=dict(name='reqlox-demo',project='reqlox',instance_id='other')
        with self.assertRaises(ValueError):preflight.validate(plan,'reqlox','reqlox-demo',replace_instance_id='123')
        with self.assertRaises(ValueError):preflight.validate(self.plan(kind='google_project_iam_member'),'reqlox','reqlox-demo')

    def test_canonical_iap_identity_preserves_only_the_existing_owned_grant(self):
        plan=self.plan(['delete','create'],kind='google_iap_tunnel_instance_iam_member')
        plan['variables'].update(zone={'value':'asia-northeast1-b'},iap_members={'value':['user:owner@example.org']})
        after=plan['resource_changes'][0]['change']['after']
        after.update(instance='reqlox-demo',member='user:owner@example.org',role='roles/iap.tunnelResourceAccessor')
        before=dict(after,instance='projects/reqlox/iap_tunnel/zones/asia-northeast1-b/instances/reqlox-demo')
        plan['resource_changes'][0]['change']['before']=before
        self.assertEqual(preflight.validate(plan,'reqlox','reqlox-demo',replace_instance_id='123')['deletes'],1)
        before['instance']='projects/other-project/iap_tunnel/zones/asia-northeast1-b/instances/reqlox-demo'
        with self.assertRaises(ValueError):preflight.validate(plan,'reqlox','reqlox-demo',replace_instance_id='123')


if __name__ == "__main__":
    unittest.main()
