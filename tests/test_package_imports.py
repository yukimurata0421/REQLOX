"""Import boundaries and offline refusals; no native or provider execution."""
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import reqlox
from reqlox.offline_testing import check_event, command_allowed
from reqlox_core.archive_loader import archived_method


class PackageImportTests(unittest.TestCase):
    def test_public_helpers_keep_import_paths_and_flat_module_cache_unchanged(self):
        before = list(sys.path)
        reqlox.inventory({'owned.py': 'raise RuntimeError("never imported")\n'})
        reqlox.source_conditions('owned', 'fsync failed')
        self.assertEqual(sys.path, before)
        self.assertNotIn('reliability_reuse', sys.modules)
        self.assertNotIn('workflow_effort', sys.modules)

    def archive(self, relative):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        sources = {'saved_helper.py': b'VALUE = 41\n', 'saved_entry.py': (
            b'from .saved_helper import VALUE\nRESULT = VALUE + 1\n' if relative else
            b'from saved_helper import VALUE\nRESULT = VALUE + 1\n')}
        for name, source in sources.items():
            (root / name).write_bytes(source)
        return root, {name: hashlib.sha256(source).hexdigest() for name, source in sources.items()}

    def test_verified_flat_and_relative_archives_use_their_own_bytes_and_clean_up(self):
        before = list(sys.path)
        for relative in (False, True):
            with self.subTest(relative=relative):
                root, hashes = self.archive(relative)
                with archived_method(root, hashes) as load:
                    self.assertEqual(load('saved_entry').RESULT, 42)
                    self.assertEqual(Path(load('saved_helper').__file__).parent, root)
                self.assertNotIn('saved_helper', sys.modules)
                self.assertNotIn('_reqlox_saved_method.saved_helper', sys.modules)
        self.assertEqual(sys.path, before)

    def test_archive_drift_is_rejected_before_import(self):
        root, hashes = self.archive(True)
        (root / 'saved_helper.py').write_text('raise AssertionError("must not execute")\n')
        with self.assertRaisesRegex(ValueError, 'METHOD_DRIFT'):
            with archived_method(root, hashes):
                self.fail('drift accepted')

    def test_flat_archive_refuses_current_module_collisions(self):
        root, hashes = self.archive(False)
        with patch.dict(sys.modules, {'saved_helper': object()}):
            with self.assertRaisesRegex(ValueError, 'FRESH_PROCESS_REQUIRED'):
                with archived_method(root, hashes):
                    self.fail('collision accepted')

    def test_archive_rejects_paths_and_unlisted_module_requests(self):
        root, hashes = self.archive(True)
        with self.assertRaisesRegex(ValueError, 'METHOD_DRIFT'):
            with archived_method(root, {'../escape.py': '0' * 64}):
                self.fail('path accepted')
        with archived_method(root, hashes) as load:
            with self.assertRaisesRegex(ValueError, 'METHOD_MISSING'):
                load('current_runtime')


class OfflineGuardTests(unittest.TestCase):
    def test_native_shell_model_and_python_code_children_are_refused_before_dispatch(self):
        vectors = [['bwrap', '/usr/bin/true'], ['prlimit', 'python3'],
                   ['python3', '/owned/reliability_reuse_worker.py'],
                   ['python3', '-c', 'print("--dry-run --help")'],
                   ['python3', '-m', 'reqlox', 'run'],
                   ['python3', '-m', 'reqlox', 'check'], ['gcloud', 'ai'], ['sh', '-c', 'true']]
        for argv in vectors:
            with self.subTest(argv=argv):
                self.assertFalse(command_allowed(argv[0], argv, '/tmp'))
                self.assertEqual(check_event('subprocess.Popen', (argv[0], argv, '/tmp', {})),
                                 'CHILD_COMMAND_DENIED')

    def test_allowed_python_entry_points_are_static_and_exact(self):
        for args in (['--help'], ['--version'], ['inventory', '--root', '/tmp'],
                     ['target', '--manifest', '/tmp/target.json', '--dry-run']):
            self.assertTrue(command_allowed('python3', ['python3', '-B', '-m', 'reqlox', *args]))
        self.assertFalse(command_allowed('python3', ['python3', '/foreign/prepare_reliability_reuse.py']))
        self.assertFalse(command_allowed('python3', ['python3', '-m', 'reqlox', 'knowledge', 'import',
                                                   '--documents', '/home/private', '--state-dir', '/tmp/state']))

    def test_git_mutations_are_limited_to_temporary_fixture_repositories(self):
        self.assertTrue(command_allowed('git', ['git', '-C', '/tmp/owned', 'commit', '-m', 'fixture']))
        self.assertFalse(command_allowed('git', ['git', 'commit', '-m', 'fixture'], '/home/repository'))
        self.assertFalse(command_allowed('git', ['git', 'config', '--global', 'key', 'value'], '/tmp/owned'))
        self.assertFalse(command_allowed('git', ['git', '-C', '/tmp/owned', 'push']))

    def test_posix_spawn_uses_the_same_static_child_allowlist(self):
        self.assertIsNone(check_event('os.posix_spawn', ('python3',
            ['python3', '-m', 'reqlox', '--help'], {})))
        self.assertEqual(check_event('os.posix_spawn', ('python3',
            ['python3', '-m', 'reqlox', 'run'], {})), 'PROCESS_ESCAPE_DENIED')

    def test_process_escape_and_external_network_are_refused(self):
        for event in ('os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty'):
            self.assertEqual(check_event(event, ()), 'PROCESS_ESCAPE_DENIED')
        self.assertEqual(check_event('socket.connect', (None, ('example.invalid', 443))),
                         'EXTERNAL_CONNECTION_DENIED')
        self.assertEqual(check_event('socket.getaddrinfo', ('example.invalid', 443)), 'EXTERNAL_DNS_DENIED')
        self.assertIsNone(check_event('socket.connect', (None, ('127.0.0.1', 8000))))
