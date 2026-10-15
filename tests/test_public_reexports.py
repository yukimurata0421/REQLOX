"""Check current public reexports and distinct API and repair-unit accounting."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

import reqlox
reqlox._runtime()
from reqlox_core import reliability_reuse as reuse
from reqlox_core import run_reliability_reuse as runner
from reqlox_core.reqlox_paths import state_root
from test_reliability_modular_flow import MODULES
from test_reliability_reuse import contracts

SOURCES=dict(MODULES,**{'pkg/__init__.py':"from .api import store as save\nfrom .api import store as persist\n__all__ = ['save', 'persist']\n"})


class PublicReexportTests(unittest.TestCase):
    def test_declared_public_aliases_bind_original_function_and_repair_member(self):
        inventory=reuse.inventory(SOURCES)
        entries=[site for site in inventory['accepted'] if site['member']=='pkg/__init__.py']
        self.assertEqual({site['symbol'] for site in entries},{'save','persist'})
        for site in entries:
            resolution=site['binding']['module_graph']['public_entry_resolution']
            self.assertEqual(resolution['function_member'],'pkg/api.py')
            self.assertEqual(resolution['function_symbol'],'store')
            self.assertEqual(site['repair_member'],'pkg/storage.py');self.assertFalse(site['modules_imported'])
            updated=reuse.apply_candidate(SOURCES,site,reuse.candidate(site))
            self.assertEqual(updated['pkg/__init__.py'],SOURCES['pkg/__init__.py'])
            self.assertEqual(updated['pkg/api.py'],SOURCES['pkg/api.py'])

    def test_rebound_effectful_missing_and_too_many_exports_are_held(self):
        for initializer in ["from .api import store as save\nsave = unknown\n", "from .api import store\nstore()\n",
            "from .api import store\n__all__ = ['missing']\n",
            "from .api import store as a, store as b, store as c, store as d, store as e\n"]:
            with self.subTest(initializer=initializer):
                value=reuse.inventory(dict(MODULES,**{'pkg/__init__.py':initializer}))
                self.assertFalse(value['accepted'])

    def test_multiple_public_apis_do_not_become_independent_repair_units(self):
        inventory=reuse.inventory(SOURCES)
        rows=[dict(site_id=site['id'],arm='SOURCE',observed=dict(fault_discovered=True,repair_pass=True)) for site in inventory['accepted']]
        summary=runner.exposure_accounting(inventory,rows)
        arm=summary['arms']['SOURCE']
        self.assertEqual(arm['api_entries'],3);self.assertEqual(arm['entry_functions'],1);self.assertEqual(arm['repair_units'],1)
        self.assertEqual(arm['faulty_api_entries'],3);self.assertEqual(arm['faulty_repair_units'],1)
        self.assertFalse(summary['statistical_independence_certified'])
        rows[-1]['observed']['repair_pass']=None
        self.assertEqual(runner.exposure_accounting(inventory,rows)['arms']['SOURCE']['candidate_passed_repair_units'],0)

    @unittest.skip('Archived native tests require a separate retained-scope authorized harness')
    def test_isolated_public_invocation_repairs_once_and_verifies_accounting(self):
        with tempfile.TemporaryDirectory(prefix='reqlox-reexport-',dir=state_root()) as tmp:
            output=Path(tmp)/'run'
            result=runner.run(SOURCES,contracts(),[],output,maximum_probes=2)
            runner.verify(output)
            for arm in runner.ARMS:
                counts=result['api_exposure_accounting']['arms'][arm]
                self.assertEqual(counts['entry_functions'],1);self.assertEqual(counts['repair_units'],1)
                self.assertEqual(counts['candidate_passed_repair_units'],1)
            self.assertEqual(list(result['composed_candidate_files']),['pkg/storage.py'])
            tampered=deepcopy(result);tampered['api_exposure_accounting']['arms']['SOURCE']['repair_units']=3
            (output/'result.json').write_bytes(reuse.c.canonical(reuse.c.seal(tampered)))
            with self.assertRaisesRegex(ValueError,'EXPOSURE_ACCOUNTING_DRIFT'):runner.verify(output)
