"""Evidence survives errors; denied launches consume no synthetic reservation."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reqlox
reqlox._runtime()
from reqlox.native_evidence import retained_workspace
import reliability_path_context as context
import run_reliability_path_context as native


class RetainedEvidenceTests(unittest.TestCase):
    def setUp(self):
        repo = Path(__file__).resolve().parents[1]
        base = repo / 'corpus/knowledge/semantic-experiments/local-private-quarantine' if (repo / 'tools').is_dir() else None
        temporary = tempfile.TemporaryDirectory(dir=base, prefix='offline-retention-fixture-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        environment = patch.dict(os.environ, {'REQLOX_STATE_DIR': str(self.base)})
        environment.start(); self.addCleanup(environment.stop)

    def terminal(self, root):
        return json.loads((root / 'retention-terminal.json').read_bytes())

    def test_return_keeps_bytes_and_does_not_certify_native_result(self):
        with retained_workspace(self.base, 'completed') as root:
            (root / 'observed.json').write_bytes(b'{"fixture":true}')
        terminal = self.terminal(root)
        self.assertEqual((root / 'observed.json').read_bytes(), b'{"fixture":true}')
        self.assertEqual(terminal['body_outcome'], 'BODY_RETURNED')
        self.assertEqual(terminal['files']['observed.json']['sha256'], hashlib.sha256(b'{"fixture":true}').hexdigest())
        self.assertFalse(terminal['native_result_certified'])
        self.assertFalse(terminal['automatic_cleanup'])

    def test_assertion_failure_keeps_partial_observation(self):
        with self.assertRaises(AssertionError):
            with retained_workspace(self.base, 'failed') as root:
                (root / 'observed.json').write_bytes(b'partial')
                raise AssertionError('fixture failure')
        self.assertEqual((root / 'observed.json').read_bytes(), b'partial')
        self.assertEqual(self.terminal(root)['body_outcome'], 'BODY_FAILED')
        self.assertFalse(self.terminal(root)['reservation_release'])

    def test_interruption_keeps_stderr_and_records_interrupted(self):
        with self.assertRaises(KeyboardInterrupt):
            with retained_workspace(self.base, 'interrupted') as root:
                (root / 'stderr.log').write_bytes(b'fixture stderr')
                raise KeyboardInterrupt()
        self.assertEqual((root / 'stderr.log').read_bytes(), b'fixture stderr')
        self.assertEqual(self.terminal(root)['body_outcome'], 'INTERRUPTED')

    def test_open_record_exists_before_any_test_work(self):
        manager = retained_workspace(self.base, 'open')
        root = manager.__enter__()
        try:
            self.assertEqual(json.loads((root / 'workspace.json').read_bytes())['status'], 'OPEN')
            self.assertFalse((root / 'retention-terminal.json').exists())
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / 'workspace.json').stat().st_mode & 0o777, 0o600)
        finally:
            manager.__exit__(None, None, None)
        self.assertTrue(root.exists())

    def test_repeated_label_creates_distinct_retained_workspaces(self):
        with retained_workspace(self.base, 'same') as first:
            (first / 'receipt.json').write_bytes(b'first')
        with retained_workspace(self.base, 'same') as second:
            (second / 'receipt.json').write_bytes(b'second')
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'receipt.json').read_bytes(), b'first')

    def test_nonprivate_base_and_linked_base_are_rejected(self):
        self.base.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'PRIVATE_BASE'):
            with retained_workspace(self.base, 'unsafe'):
                self.fail('entered unsafe workspace')
        self.base.chmod(0o700)
        link = self.base / 'link'; link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'PRIVATE_BASE'):
            with retained_workspace(link, 'unsafe'):
                self.fail('entered linked workspace')

    def test_inventory_does_not_follow_external_evidence_link(self):
        outside = self.base / 'outside'; outside.write_bytes(b'fixture-only')
        with retained_workspace(self.base, 'linked') as root:
            (root / 'observed.json').symlink_to(outside)
        terminal = self.terminal(root)
        self.assertEqual(terminal['inventory_status'], 'UNCONFIRMED')
        self.assertIsNone(terminal['files'])
        self.assertTrue((root / 'observed.json').is_symlink())
        self.assertFalse(terminal['native_result_certified'])

    def test_missing_native_guard_rejects_before_output_and_dispatch(self):
        output = self.base / 'no-grant'
        with patch.object(native.subprocess, 'Popen') as dispatch, self.assertRaisesRegex(ValueError, 'AUTHORIZATION_REQUIRED'):
            native.execute({}, output)
        dispatch.assert_not_called()
        self.assertFalse(output.exists())

    def plan(self):
        sources = {'pkg/__init__.py': '''class FileContext:
    def __init__(self, path):
        self.path = path
    def __enter__(self):
        self.file = open(self.path, 'a')
        return self.file
    def __exit__(self, kind, value, traceback):
        self.file.close()
'''}
        documents = {'README': "```python\nfrom pkg import FileContext\nwith FileContext('example'):\n    pass\n```"}
        return context.plan(sources, context.recipes(sources, documents)['rows'][0], documents,
                            provenance={'role': 'KNOWN_DEVELOPMENT', 'constructed_control': True})

    def test_budget_denial_keeps_inputs_and_no_native_attempt(self):
        def deny(): raise ValueError('fixture budget exhausted')
        with retained_workspace(self.base, 'denied') as root, patch.object(native.subprocess, 'Popen') as dispatch:
            receipt, observed = native.execute(self.plan(), root / 'native', before_native=deny)
        dispatch.assert_not_called()
        self.assertEqual(receipt['status'], 'STOPPED')
        self.assertEqual(receipt['native_campaigns'], 0)
        self.assertIsNone(observed)
        for name in ('plan.json', 'launch.json', 'observed.json', 'stderr.log', 'receipt.json'):
            self.assertIn('native/' + name, self.terminal(root)['files'])

    def test_mocked_spawn_failure_is_counted_once_and_retained(self):
        reservations = []
        with retained_workspace(self.base, 'spawn-failed') as root, \
             patch.object(native.subprocess, 'Popen', side_effect=OSError('fixture spawn failure')) as dispatch:
            receipt, observed = native.execute(self.plan(), root / 'native', before_native=lambda:reservations.append(1))
        self.assertEqual(reservations, [1])
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(receipt['native_campaigns'], 1)
        self.assertEqual(receipt['status'], 'STOPPED')
        self.assertIsNone(observed)
        self.assertFalse(receipt['automatic_retry'])
        self.assertIn('native/receipt.json', self.terminal(root)['files'])


if __name__ == '__main__':
    unittest.main()
