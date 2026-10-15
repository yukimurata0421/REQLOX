"Finite reliability controls and verification."

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests')]
from reqlox_core import reliability_reuse as reuse
from reqlox_core import run_reliability_reuse as runner
from reqlox_core import reliability_reuse_cache as cache
from test_reliability_serialized_flow import FD, site_for
from test_reliability_serialized_flow import JSON

FACTORY = FD.replace("tempfile.mkstemp(dir=os.path.dirname(destination), prefix='owned-')", '_create(destination)') + '''
def _create(path):
    """Create an exclusively owned descriptor and path."""
    return tempfile.mkstemp(dir=os.path.dirname(path), prefix='owned-')
'''

BACKEND = JSON[:JSON.index('\ndef store(')]
MODULES = {'pkg/__init__.py':'', 'pkg/storage.py':BACKEND,
           'pkg/api.py':'''import json
from .storage import _stage as persist

def store(destination, record):
    return persist(destination, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
'''}


def graph_site(sources=MODULES):
    inventory = reuse.inventory(sources)
    if not inventory['accepted']:
        raise AssertionError(inventory['held'])
    return next(s for s in inventory['accepted'] if s['member'].endswith('api.py'))


class TemporaryFactoryTests(unittest.TestCase):
    def test_factory_is_bound_by_exclusive_creation_role_without_execution(self):
        site = site_for(FACTORY); creator = site['binding']['temporary_creator']
        self.assertEqual(creator['kind'], 'EXCLUSIVE_MKSTEMP_FACTORY_V1')
        self.assertTrue(creator['exclusive_creation']); self.assertFalse(creator['concurrent_behavior_qualified'])
        self.assertFalse(creator['creation_failure_qualified']); self.assertFalse(site['modules_imported'])

    def test_factory_and_public_signature_are_preserved_by_backend_only_repair(self):
        site = site_for(FACTORY)
        changed = reuse.apply_candidate({'store.py':FACTORY}, site, reuse.candidate(site))['store.py']
        before = next(n for n in ast.parse(FACTORY).body if isinstance(n,ast.FunctionDef) and n.name=='_create')
        after = next(n for n in ast.parse(changed).body if isinstance(n,ast.FunctionDef) and n.name=='_create')
        self.assertEqual(ast.dump(before), ast.dump(after)); self.assertIn('_create(destination)', changed)
        rebound = site_for(changed); self.assertTrue(rebound['binding']['protected'])
        self.assertEqual(rebound['code'], reuse.candidate(site))

    def test_name_only_foreign_directory_effectful_or_nonexclusive_creators_are_held(self):
        for source in (FACTORY.replace('return tempfile.mkstemp', 'return make_name'),
                       FACTORY.replace('os.path.dirname(path)', "'/elsewhere'"),
                       FACTORY.replace('return tempfile.mkstemp', 'touch()\n    return tempfile.mkstemp'),
                       FACTORY.replace('return tempfile.mkstemp', 'return open'),
                       FACTORY.replace("prefix='owned-'", 'prefix=setting')):
            with self.subTest(source=source[-140:]):
                self.assertFalse(reuse.inventory({'store.py':source})['accepted'])

    def test_creator_path_and_arity_are_not_guessed(self):
        for source in (FACTORY.replace('_create(destination)', '_create(content)'),
                       FACTORY.replace('_create(destination)', '_create(destination, content)'),
                       FACTORY.replace('def _create(path):', 'def _create(path, option=None):')):
            self.assertFalse(reuse.inventory({'store.py':source})['accepted'])

    def test_candidate_cannot_change_the_frozen_creation_expression(self):
        site = site_for(FACTORY); code = reuse.candidate(site)
        with self.assertRaisesRegex(ValueError, 'CREATOR_SEMANTICS'):
            reuse.apply_candidate({'store.py':FACTORY}, site, code.replace("prefix='owned-'", "prefix='foreign-'"))

    def test_creator_import_aliases_and_role_renaming_are_preserved(self):
        source = FACTORY.replace('import tempfile', 'from tempfile import mkstemp as allocate').replace('tempfile.mkstemp', 'allocate')
        source = source.replace('_create', '_allocate_owned')
        site = site_for(source); changed = reuse.apply_candidate({'store.py':source}, site, reuse.candidate(site))['store.py']
        self.assertTrue(site_for(changed)['binding']['protected']); self.assertIn('_allocate_owned(destination)', changed)


class ModuleGraphTests(unittest.TestCase):
    def test_entry_backend_and_closed_source_bundle_are_bound_without_import(self):
        site=graph_site(); graph=site['binding']['module_graph']
        self.assertEqual(site['member'],'pkg/api.py'); self.assertEqual(site['repair_member'],'pkg/storage.py')
        self.assertEqual(site['symbol'],'store'); self.assertEqual(site['binding']['repair_symbol'],'_stage')
        self.assertEqual(set(graph['modules']),set(MODULES)); self.assertFalse(site['modules_imported'])
        plan=runner.build_plan(site,{},None,MODULES,{},'NO_SOURCE',6,None)
        self.assertEqual(plan['sources'],MODULES)

    def test_only_backend_member_is_patched_and_original_public_api_is_preserved(self):
        site=graph_site(); changed=reuse.apply_candidate(MODULES,site,reuse.candidate(site))
        self.assertEqual(changed['pkg/api.py'],MODULES['pkg/api.py'])
        self.assertEqual(changed['pkg/__init__.py'],'')
        self.assertNotEqual(changed['pkg/storage.py'],MODULES['pkg/storage.py'])
        self.assertTrue(graph_site(changed)['binding']['protected'])

    def test_src_layout_renames_and_relative_function_aliases_preserve_roles(self):
        renamed={('src/'+n).replace('pkg/','package/'):v.replace('_stage','_commit').replace('persist','save_owned') for n,v in MODULES.items()}
        site=graph_site(renamed)
        self.assertEqual(site['binding']['module_graph']['modules']['src/package/api.py'],'package.api')
        self.assertTrue(graph_site(reuse.apply_candidate(renamed,site,reuse.candidate(site)))['binding']['protected'])

    def test_dependency_change_invalidates_patch_and_memo_identity(self):
        site=graph_site(); changed=dict(MODULES); changed['pkg/storage.py']+='\n# changed dependency\n'
        with self.assertRaisesRegex(ValueError,'DEPENDENCY_DRIFT'):
            reuse.apply_candidate(changed,site,reuse.candidate(site))
        self.assertNotEqual(runner.inventory_for(MODULES),runner.inventory_for(changed))

    def test_missing_ambiguous_and_nonfunction_dependencies_are_held(self):
        missing=dict(MODULES);del missing['pkg/storage.py']
        ambiguous={**MODULES,'pkg/storage/__init__.py':BACKEND}
        value={**MODULES,'pkg/storage.py':'_stage=7\n'}
        for sources in (missing,ambiguous,value):
            self.assertFalse(reuse.inventory(sources)['accepted'])

    def test_relative_namespace_and_package_escape_are_held(self):
        for code in (MODULES['pkg/api.py'].replace('from .storage import _stage as persist','from . import storage as persist'),
                     MODULES['pkg/api.py'].replace('from .storage','from ...outside'),
                     MODULES['pkg/api.py'].replace('from .storage','from other.storage')):
            self.assertFalse(reuse.inventory({**MODULES,'pkg/api.py':code})['accepted'])

    def test_module_effects_import_cycles_and_initializer_effects_are_held(self):
        for sources in ({**MODULES,'pkg/storage.py':BACKEND+'\nside_effect()\n'},
                        {**MODULES,'pkg/storage.py':BACKEND+'\nfrom .api import store\n'},
                        {**MODULES,'pkg/__init__.py':'touch()\n'},
                        {**MODULES,'pkg/__init__.py':'from .api import store\nstore = unknown\n'}):
            self.assertFalse(reuse.inventory(sources)['accepted'])

    def test_import_rebinding_is_held_even_if_the_latest_alias_points_to_a_function(self):
        source=MODULES['pkg/api.py'].replace('from .storage import _stage as persist',
            'from .storage import _stage as persist\nfrom .storage import _stage as persist')
        self.assertFalse(reuse.inventory({**MODULES,'pkg/api.py':source})['accepted'])

    def test_two_function_edges_and_four_modules_remain_finite(self):
        sources={**MODULES,'pkg/api.py':MODULES['pkg/api.py'].replace('from .storage import _stage as persist',
            'from .relay import relay as persist'),'pkg/relay.py':'from .storage import _stage\ndef relay(path,payload):\n    return _stage(path,payload)\n'}
        self.assertEqual(graph_site(sources)['binding']['serialized_flow_ir']['helper_depth'],2)
        deep={**sources,'pkg/relay.py':sources['pkg/relay.py'].replace('.storage import _stage','.second import second').replace('_stage(path,payload)','second(path,payload)'),
              'pkg/second.py':'from .storage import _stage\ndef second(path,payload):\n    return _stage(path,payload)\n'}
        self.assertFalse(any(s['member']=='pkg/api.py' for s in reuse.inventory(deep)['accepted']))

    def test_external_factory_and_shared_backend_patch_are_composed_once(self):
        backend=FACTORY.replace('def write_text(', 'def _stage(')
        backend=backend[:backend.index('\ndef _create(')]+'\nfrom .temporary import _create\n'
        sources={**MODULES,'pkg/storage.py':backend,'pkg/temporary.py':"import os\nimport tempfile\ndef _create(path):\n    return tempfile.mkstemp(dir=os.path.dirname(path),prefix='owned-')\n"}
        site=graph_site(sources)
        self.assertEqual(site['binding']['temporary_creator']['member'],'pkg/temporary.py')
        revised=reuse.apply_candidate(sources,site,reuse.candidate(site))
        self.assertEqual(revised['pkg/temporary.py'],sources['pkg/temporary.py'])
        self.assertTrue(graph_site(revised)['binding']['protected'])

    def test_same_symbol_in_different_members_does_not_create_a_false_function_cycle(self):
        sources={**MODULES,'pkg/storage.py':BACKEND.replace('_stage','store'),
                 'pkg/api.py':MODULES['pkg/api.py'].replace('_stage as persist','store as persist')}
        self.assertEqual(graph_site(sources)['binding']['repair_symbol'],'store')

    def test_cache_rejects_extra_missing_and_changed_frozen_module_sources(self):
        site=graph_site();plan=runner.build_plan(site,{},None,MODULES,[],'NO_SOURCE',6,None)
        identity=cache.key(plan,'NO_SOURCE',{}, {}, 'CONSTRUCTED_CONTROL',reuse.c.digest(MODULES))
        self.assertEqual(identity,cache.key(plan,'NO_SOURCE',{}, {}, 'CONSTRUCTED_CONTROL',reuse.c.digest(MODULES)))
        for sources in ({**MODULES,'extra.py':''},{n:v for n,v in MODULES.items() if n!='pkg/storage.py'},
                        {**MODULES,'pkg/storage.py':BACKEND+'\n# changed\n'}):
            altered=deepcopy(plan);altered['sources']=sources
            with self.assertRaises(ValueError):cache.key(altered,'NO_SOURCE',{}, {}, 'CONSTRUCTED_CONTROL',reuse.c.digest(sources))

    def test_patch_rejects_repair_member_identity_substitution(self):
        site=graph_site();site['repair_member']='pkg/api.py'
        with self.assertRaisesRegex(ValueError,'MODULE_IDENTITY'):
            reuse.apply_candidate(MODULES,site,reuse.candidate(site))






if __name__ == '__main__':
    unittest.main()
