"""Saved evidence rejects ambiguous JSON, unsafe paths, and false claims."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reqlox import target_audit as audit


class AuditIoBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def artifact(self, text):
        path = self.root / 'artifact.json'
        path.write_text(text)
        return path

    def test_nested_duplicate_json_keys_are_rejected(self):
        for text in ('{"status":1,"status":2}', '{"outer":{"status":1,"status":2}}'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_DUPLICATE_KEY'):
                audit.read(self.artifact(text))

    def test_nonfinite_json_values_are_rejected_at_any_depth(self):
        for constant in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(constant=constant), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_NONFINITE'):
                audit.read(self.artifact('{"values":[' + constant + ']}'))

    def test_valid_nested_json_and_unicode_preserve_types(self):
        value = {'説明': ['同じkey', {'key': False}, {'key': 0}], 'unknown': None}
        path = self.artifact(json.dumps(value, ensure_ascii=False))
        before = path.read_bytes()
        self.assertEqual(audit.read(path), value)
        self.assertIs(audit.read(path)['説明'][1]['key'], False)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_directory_and_malformed_artifact_are_rejected(self):
        for path in (self.root / 'missing', self.root):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_ARTIFACT_PATH'):
                audit.read(path)
        with self.assertRaises(json.JSONDecodeError):
            audit.read(self.artifact('{'))

    def test_artifact_symlink_and_symlink_ancestor_are_rejected(self):
        path = self.artifact('{}')
        (self.root / 'alias.json').symlink_to(path)
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        for link in (self.root / 'alias.json', self.root / 'alias/artifact.json'):
            with self.subTest(link=link), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_ARTIFACT_PATH'):
                audit.read(link)

    def sized_stat(self, sizes):
        original = Path.stat
        def stat(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path in sizes:
                fields = list(value)
                fields[6] = sizes[path]
                return os.stat_result(fields)
            return value
        return patch.object(Path, 'stat', stat)

    def test_artifact_size_limit_is_checked_before_reading_bytes(self):
        path = self.artifact('{}')
        with self.sized_stat({path: 67108865}), patch.object(Path, 'read_text') as read:
            with self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_ARTIFACT_PATH'):
                audit.read(path)
            read.assert_not_called()

    def test_missing_child_directory_has_no_evidence_and_regular_file_is_rejected(self):
        self.assertEqual(audit.files(self.root / 'absent'), {})
        with self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_CHILD_PATH'):
            audit.files(self.artifact('{}'))

    def test_file_hashes_include_nested_and_hidden_files_without_modifying_them(self):
        child = self.root / 'child'
        (child / 'nested').mkdir(parents=True)
        contents = {'.receipt': b'private fixture', 'nested/result.json': b'{"status":"STOPPED"}\n'}
        for relative, data in contents.items():
            (child / relative).write_bytes(data)
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        self.assertEqual(audit.files(child), expected)
        self.assertEqual({name: (child / name).read_bytes() for name in contents}, contents)

    def test_child_file_directory_and_dangling_symlinks_are_rejected(self):
        child = self.root / 'child'
        child.mkdir()
        for target in (self.artifact('{}'), self.root, self.root / 'absent'):
            link = child / 'alias'
            link.symlink_to(target)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_SYMLINK'):
                audit.files(child)
            link.unlink()

    def test_file_count_limit_is_checked_before_hashing(self):
        child = self.root / 'child'
        child.mkdir()
        with patch.object(audit.os, 'walk', return_value=[(str(child), [], ['owned'] * 8193)]):
            with patch.object(Path, 'read_bytes') as read:
                with self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_FILE_LIMIT'):
                    audit.files(child)
                read.assert_not_called()

    def test_child_file_size_limit_is_checked_before_hashing(self):
        path = self.artifact('{}')
        with self.sized_stat({path: 67108865}), patch.object(Path, 'read_bytes') as read:
            with self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_FILE_BOUND'):
                audit.files(self.root)
            read.assert_not_called()

    def test_aggregate_size_limit_rejects_many_individually_allowed_files(self):
        sizes = {}
        for number in range(5):
            path = self.root / str(number)
            path.write_bytes(b'owned fixture')
            sizes[path] = 67108864
        with self.sized_stat(sizes):
            with self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_BYTES_LIMIT'):
                audit.files(self.root)

    def claims(self):
        return dict.fromkeys(('checkout_write_authority', 'independent_generalization_certified',
            'natural_source_added_value_certified', 'probability_calibration_certified',
            'automatic_failed_trial_retry'), False) | {'provider_calls': 0}

    def test_claim_flags_require_explicit_false_instead_of_false_like_values(self):
        for key in self.claims().keys() - {'provider_calls'}:
            for value in (None, 0, '', True, [], {}):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_CLAIM_DRIFT'):
                    audit.claims(self.claims() | {key: value})
            missing = self.claims()
            del missing[key]
            with self.subTest(key=key, missing=True), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_CLAIM_DRIFT'):
                audit.claims(missing)

    def test_provider_zero_requires_an_integer_instead_of_boolean_or_float(self):
        for value in (False, True, 0.0, '0', None, -1, 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'TARGET_AUDIT_PROVIDER_DRIFT'):
                audit.claims(self.claims() | {'provider_calls': value})
        audit.claims(self.claims())


if __name__ == '__main__':
    unittest.main()
