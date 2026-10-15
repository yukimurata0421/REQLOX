"""The native catalog inspects source without collecting or executing tests."""
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('native_inventory_check',
    Path(__file__).resolve().parents[1] / 'scripts/native_test_inventory.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class NativeInventoryTests(unittest.TestCase):
    def fixture(self, body):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'tests').mkdir()
        (root / 'tests/test_owned.py').write_text(body)
        return root

    def test_catalog_does_not_import_a_side_effecting_test_module(self):
        root = self.fixture('''from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()
raise AssertionError('must never be imported')
import unittest
@unittest.skip('archived native')
class Owned(unittest.TestCase):
    def setUp(self):
        native.execute()
    def test_held(self):
        native.execute()
''')
        value = catalog.inventory(root)
        self.assertEqual(value['test_files'], 1)
        self.assertEqual(value['held_methods'], 1)
        self.assertTrue(value['all_import_guards_present'])
        self.assertFalse(value['native_execution_verified'])
        self.assertEqual(value['files'][0]['fixtures'][0]['boundary_calls'], ['native.execute'])

    def test_environment_switch_and_import_before_guard_are_reported(self):
        root = self.fixture('''import native
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()
import os, unittest
@unittest.skipUnless(os.environ.get('REQLOX_RUN_NATIVE_TESTS') == '1', 'opt in')
class Owned(unittest.TestCase):
    def test_run(self):
        native.execute()
''')
        value = catalog.inventory(root)
        self.assertFalse(value['all_import_guards_present'])
        self.assertFalse(value['no_environment_reenable'])
        self.assertEqual(value['held_methods'], 0)
        self.assertEqual(value['boundary_review_methods'], 1)
