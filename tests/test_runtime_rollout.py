"""Offline guards for the dedicated demo release update; no cloud operations."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('rollout', Path(__file__).parents[1]/'infra/gcp/runtime_rollout.py')
rollout = importlib.util.module_from_spec(spec); spec.loader.exec_module(rollout)


class RolloutScopeTests(unittest.TestCase):
    def inputs(self):
        old = dict(host_id='reqlox-web', project_id='reqlox', release_sha256='a'*64,
                   artifact_object='releases/'+'a'*64+'.tar.gz', paid_model_calls_enabled=False,
                   access='CLOUDFLARE_OWNER_LOGIN', data_disk='preserved',
                   web=dict(authentication='OWNER_BASIC_AUTH', owner_secret_resource='pinned-version'))
        new = copy.deepcopy(old)
        new.update(release_sha256='b'*64, artifact_object='releases/'+'b'*64+'.tar.gz')
        contract = dict(host_id='reqlox-web', project_id='reqlox', release_sha256='a'*64,
                        role='REQLOX bounded isolated demo', scope='existing scope')
        expected = dict(old_release_sha256='a'*64, new_release_sha256='b'*64)
        return copy.deepcopy((old, new, contract, expected))

    def test_changes_only_the_reviewed_release_binding(self):
        old, new, contract, expected = self.inputs()
        self.assertEqual(rollout.validate_change(old, new, contract, expected), dict(contract, release_sha256='b'*64))

    def test_other_host_project_and_production_role_rejected(self):
        for key, value in [('host_id','other'), ('project_id','other'), ('role','production')]:
            old, new, contract, expected = self.inputs(); contract[key] = value
            with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)

    def test_current_contract_and_release_drift_rejected(self):
        old, new, contract, expected = self.inputs(); old['release_sha256'] = 'c'*64
        with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)

    def test_wrong_release_object_rejected(self):
        old, new, contract, expected = self.inputs(); new['artifact_object'] = 'private-data'
        with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)

    def test_paid_model_and_access_cannot_change(self):
        for key,value in [('paid_model_calls_enabled',True), ('access','PUBLIC')]:
            old, new, contract, expected = self.inputs(); new[key] = value
            with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)

    def test_disk_and_secret_versions_preserved(self):
        old, new, contract, expected = self.inputs(); new['data_disk'] = 'replacement'
        with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)
        old, new, contract, expected = self.inputs(); new['web']['owner_secret_resource'] = 'latest'
        with self.assertRaises(ValueError): rollout.validate_change(old, new, contract, expected)
