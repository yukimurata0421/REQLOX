"Finite reliability controls and verification."

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

pass  # Package imports resolve from the repository root.
from reqlox_core import reliability_reuse as reuse
from reqlox_core import reliability_reuse_cache as cache

INSTANCE = '''import os as kernel
from pathlib import Path as Location

class Archive:
    def __init__(owner, destination: Location):
        owner.target = Location(destination)

    def persist(this, payload: bytes) -> None:
        """\u4e0e\u3048\u3089\u308c\u305fbytes\u3092\u4fdd\u5b58\u3059\u308b。"""
        pending = this.target.with_name(this.target.name + f'.{kernel.getpid()}.pending')
        with pending.open('xb') as output:
            output.write(payload)
            output.flush()
            kernel.fsync(output.fileno())
        this._publish(pending=pending)

    def _publish(owner, pending):
        kernel.replace(pending, owner.target)

    def neighboring(this):
        return 17
'''


def discover(sources):
    return next(s for s in reuse.inventory(sources)['accepted'] if s['symbol'].endswith('.persist'))


class InstanceClosureTests(unittest.TestCase):
    def setUp(self):
        self.sources = {'src/package/storage.py':INSTANCE}

    def test_constructor_field_and_keyword_helper_are_projected(self):
        site = discover(self.sources);b = site['binding']['instance']
        self.assertEqual((b['class_name'],b['path_field'],b['path_conversion']),('Archive','target','Path'))
        self.assertEqual(b['helper_closure'][0]['name'],'_publish')
        self.assertIn('os.replace(pending, instance_destination)',site['code'])
        self.assertFalse(site['semantics_inferred'])

    def test_patch_preserves_constructor_signature_annotations_doc_and_neighbor(self):
        site = discover(self.sources);fixed = reuse.candidate(site)
        revised = reuse.apply_candidate(self.sources,site,fixed)
        before = ast.parse(INSTANCE).body[2];after = ast.parse(revised[site['member']]).body[2]
        self.assertEqual(ast.dump(before.body[0]),ast.dump(after.body[0]))
        self.assertEqual(ast.dump(before.body[-1]),ast.dump(after.body[-1]))
        self.assertEqual(ast.dump(before.body[1].args),ast.dump(after.body[1].args))
        self.assertEqual(ast.dump(before.body[1].returns),ast.dump(after.body[1].returns))
        self.assertEqual(before.body[1].body[0].value.value,after.body[1].body[0].value.value)
        self.assertNotIn('@staticmethod',revised[site['member']])
        self.assertEqual(discover(revised)['code'],fixed)

    def test_direct_imported_helper_closure_has_member_identity(self):
        source = INSTANCE.replace('from pathlib import Path as Location','from pathlib import Path as Location\nfrom .support import exchange as commit')
        source = source.replace('kernel.replace(pending, owner.target)','commit(source=pending, destination=owner.target)')
        sources = {**self.sources,'src/package/storage.py':source,'src/package/support.py':'import os as system\ndef exchange(source, *, destination):\n    system.replace(source, destination)\n'}
        site = discover(sources);helpers = site['binding']['instance']['helper_closure']
        imported = next(h for h in helpers if h['owner'] is None)
        self.assertEqual(imported['member'],'src/package/support.py')
        self.assertEqual(imported['member_sha256'],reuse.sha(sources[imported['member']]))
        changed = dict(sources);changed[imported['member']] += '\nmarker = 1\n'
        self.assertNotEqual(discover(changed)['binding'],site['binding'])
        revised = reuse.apply_candidate(sources,site,reuse.candidate(site))
        self.assertEqual(revised[imported['member']],sources[imported['member']])

    def test_helper_keyword_only_and_literal_default_binding(self):
        source = INSTANCE.replace('def _publish(owner, pending):','def _publish(owner, pending, *, ignored=None):')
        self.assertEqual(discover({'module.py':source})['family'],'atomic_file')

    def test_constructor_and_payload_keyword_only_invocation_are_retained(self):
        source = INSTANCE.replace('owner, destination:', 'owner, *, destination:').replace('this, payload:', 'this, *, payload:')
        bound = discover({'module.py':source})['binding']['instance']
        self.assertTrue(bound['constructor_keyword_only']);self.assertTrue(bound['payload_keyword_only'])

    def test_ambiguous_external_and_reassigned_helpers_are_held(self):
        source = INSTANCE.replace('kernel.replace(pending, owner.target)','commit(pending, owner.target)')
        for addition,extra in [('\nfrom missing import commit\n',{}),('\nfrom package.support import commit\n',{'package/support.py':'def commit(a,b):\n    pass\n','src/package/support.py':'def commit(a,b):\n    pass\n'}),
                              ('\ndef commit(a,b):\n    kernel.replace(a,b)\ncommit = None\n',{})]:
            inventory = reuse.inventory({'src/package/storage.py':source+addition,**extra})
            self.assertFalse(inventory['accepted'])

    def test_dynamic_constructor_protocol_field_mutation_and_return_are_held(self):
        variants = [INSTANCE.replace('class Archive:','class Archive(object):'),
                    INSTANCE.replace('owner.target = Location(destination)','owner.target = Location(destination)\n        owner.target.unlink()'),
                    INSTANCE.replace('class Archive:','@unknown\nclass Archive:'),
                    INSTANCE.replace('        this._publish(pending=pending)','        this.target = pending\n        this._publish(pending=pending)'),
                    INSTANCE.replace('        this._publish(pending=pending)','        this._publish(pending=pending)\n        return payload'),
                    INSTANCE+'\nArchive._publish = None\n',
                    INSTANCE+'\nArchive = None\n',
                    INSTANCE+'\nif True:\n    Archive = None\n',
                    INSTANCE+'\nsetattr(Archive, "_publish", None)\n',
                    INSTANCE+'\nArchive = unknown()\n',
                    INSTANCE.replace('    def neighboring(this):','    def __getattribute__(this, name):')]
        for source in variants:
            with self.subTest(source=source):self.assertFalse(reuse.inventory({'module.py':source})['accepted'])

    def test_helper_cycles_effectful_arguments_and_duplicate_bindings_are_held(self):
        variants = [INSTANCE.replace('kernel.replace(pending, owner.target)','owner._publish(pending=pending)'),
                    INSTANCE.replace('this._publish(pending=pending)','this._publish(pending=Location(pending))'),
                    INSTANCE.replace('this._publish(pending=pending)','this._publish(pending, pending=pending)'),
                    INSTANCE.replace('kernel.replace(pending, owner.target)','kernel.replace(pending, owner.target)\n        kernel.fsync(1)')]
        for source in variants:
            with self.subTest(source=source):self.assertFalse(reuse.inventory({'module.py':source})['accepted'])

    def test_helper_member_changes_invalidate_selective_key(self):
        site = discover(self.sources)
        plan = dict(site=site,sources=self.sources,contract={},proposal={},candidate_code=None,dependency_sha256=None)
        key = cache.key(plan,'SOURCE',{}, {},'DEVELOPMENT_CONTROL',reuse.c.digest(self.sources))
        changed = deepcopy(plan);changed['site']['binding']['instance']['helper_closure'][0]['member_sha256'] = '0'*64
        self.assertNotEqual(key,cache.key(changed,'SOURCE',{}, {},'DEVELOPMENT_CONTROL',reuse.c.digest(self.sources)))

    def test_mutable_field_loads_are_restored_instead_of_literal_inlining(self):
        source = INSTANCE.replace('owner, destination: Location','owner, destination: Location, *, suffix=".pending"')
        source = source.replace('owner.target = Location(destination)','owner.target = Location(destination)\n        owner.suffix = suffix')
        source = source.replace("f'.{kernel.getpid()}.pending'","f'.{kernel.getpid()}' + this.suffix")
        sources = {'module.py':source};site = discover(sources)
        bound = site['binding']['instance']
        self.assertEqual(bound['field_projections'],[dict(field='suffix',name='instance_field_0',value='.pending')])
        revised = reuse.apply_candidate(sources,site,reuse.candidate(site))['module.py']
        self.assertIn('this.suffix',revised)
        self.assertNotIn('instance_field_0',revised)
        self.assertIn('suffix=".pending"',revised)

    def test_effectful_or_additional_required_constructor_arguments_are_held(self):
        for source in [INSTANCE.replace('owner, destination: Location','owner, destination: Location, suffix'),
                       INSTANCE.replace('owner, destination: Location','owner, destination: Location, suffix=unknown()')]:
            self.assertFalse(reuse.inventory({'module.py':source})['accepted'])


if __name__ == '__main__':unittest.main()
