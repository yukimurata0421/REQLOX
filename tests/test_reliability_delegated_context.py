"Finite reliability controls and verification."

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT / 'tests')]
from reqlox_core import reliability_reuse as reuse
from reqlox_core import reliability_reuse_worker as worker
from reqlox_core import reliability_source_conditions as natural
from reqlox_core import run_reliability_reuse as runner
from test_reliability_natural_conditions import TEXT

DELEGATED='''import contextlib
import io
import os
import tempfile

class Stager:
    def __init__(owner, path, mode="w", overwrite=False, **options):
        owner.target = path
        owner.mode = mode
        owner.overwrite = overwrite
        owner.options = options

    def open(this):
        return this._enter(this._create)

    @contextlib.contextmanager
    def _enter(this, factory):
        """Keep this actual method and its public entry."""
        handle = None
        with factory(**this.options) as handle:
            yield handle
            this.sync(handle)
        this.publish(handle)

    def _create(owner, suffix="", prefix=tempfile.gettempprefix(), directory=None, **options):
        if directory is None:
            directory = os.path.normpath(os.path.dirname(owner.target))
        descriptor, temporary = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=directory)
        os.close(descriptor)
        options['mode'] = owner.mode
        options['file'] = temporary
        return io.open(**options)

    def sync(owner, handle):
        handle.flush()
        os.fsync(handle.fileno())

    def publish(owner, handle):
        os.replace(handle.name, owner.target)

    def unrelated(owner):
        return 19

def begin(destination, writer=Stager, **options):
    return writer(destination, **options).open()
'''

POLICY={'atomic_context':dict(basis='\u6240\u6709\u3059\u308b\u4fdd\u5b58\u306f\u65e2\u5b58\u5024\u3068\u4ed6\u8005\u306efile\u3092\u4fdd\u6301\u3057、\u6240\u6709temporary\u3092\u56de\u53ce\u3059\u308b',scope='\u69cb\u6210\u3057\u305f\u516c\u958bfactory\u306e\u6709\u9650\u9694\u96e2\u5bfe\u7167')}


def site_for(source=DELEGATED):
    return next(s for s in reuse.inventory({'pkg/storage.py':source})['accepted']
                if s['binding'].get('kind')==reuse.delegated.KIND)


def plan(source=DELEGATED):
    sources={'pkg/storage.py':source};site=site_for(source)
    contracts={family:dict(id=reuse.CONTRACTS[family],**policy) for family,policy in POLICY.items()}
    cfg=natural.prepare(sources,contracts,{'constructed':TEXT})
    hs=[reuse.hypothesis(h,cfg['source_texts']) for h in cfg['hypotheses']]
    return runner.build_plan(site,reuse.bind_contract(site,contracts),None,sources,hs,'SOURCE',3,None)


class DelegatedBindingTests(unittest.TestCase):
    def test_public_entry_and_repair_method_have_separate_exact_identity(self):
        site=site_for();bound=site['binding']
        self.assertEqual((site['symbol'],bound['entry_symbol']),('Stager._enter','begin'))
        self.assertEqual(bound['dependency_scope'],'FROZEN_MEMBER_AND_STDLIB')
        self.assertEqual(bound['lifecycle_style'],'PLAIN');self.assertFalse(bound['protected'])
        self.assertFalse(bound['ownership_semantics_certified']);self.assertFalse(site['semantics_inferred'])

    def test_repair_preserves_constructor_entry_creator_signature_doc_and_neighbors(self):
        site=site_for();fixed=reuse.candidate(site);revised=reuse.apply_candidate({'pkg/storage.py':DELEGATED},site,fixed)
        before=ast.parse(DELEGATED);after=ast.parse(revised['pkg/storage.py'])
        left=next(n for n in before.body if isinstance(n,ast.ClassDef));right=next(n for n in after.body if isinstance(n,ast.ClassDef))
        for original in left.body:
            updated=next(n for n in right.body if n.name==original.name)
            if original.name!='_enter':self.assertEqual(ast.dump(original),ast.dump(updated))
            else:
                self.assertEqual(ast.dump(original.args),ast.dump(updated.args))
                self.assertEqual(ast.dump(original.decorator_list[0]),ast.dump(updated.decorator_list[0]))
                self.assertEqual(original.body[0].value.value,updated.body[0].value.value)
        self.assertEqual(ast.dump(before.body[-1]),ast.dump(after.body[-1]))
        self.assertNotIn('@staticmethod',revised['pkg/storage.py'])
        self.assertTrue(site_for(revised['pkg/storage.py'])['binding']['protected'])
        self.assertEqual(site_for(revised['pkg/storage.py'])['code'],fixed)

    def test_aliases_and_renamed_receiver_methods_are_supported_without_target_names(self):
        source=DELEGATED.replace('import os','import os as system').replace('os.','system.')
        source=source.replace('Stager','Envelope').replace('_enter','_scope').replace('begin','start')
        site=site_for(source);self.assertEqual(site['symbol'],'Envelope._scope')
        revised=reuse.apply_candidate({'pkg/storage.py':source},site,reuse.candidate(site))['pkg/storage.py']
        self.assertIn('system.unlink',revised);self.assertTrue(site_for(revised)['binding']['protected'])

    def test_literal_and_python_major_default_modes_are_closed_without_eval(self):
        source=DELEGATED.replace('class Stager:', 'PY2 = sys.version_info[0] == 2\nDEFAULT_MODE = "wb" if PY2 else "w"\nclass Stager:')
        source=source.replace('import io','import io\nimport sys').replace('mode="w"','mode=DEFAULT_MODE')
        self.assertEqual(site_for(source)['binding']['default_mode'],'w')
        source=source.replace('DEFAULT_MODE = "wb" if PY2 else "w"','DEFAULT_MODE = choose_mode()')
        self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_mixed_or_ambiguous_public_entries_are_held(self):
        variants=[DELEGATED+'\ndef another(path, writer=Stager, **options):\n    return writer(path, **options).open()\n',
                  DELEGATED.replace('writer(destination, **options)','writer("/different", **options)'),
                  DELEGATED.replace('return this._enter(this._create)','return this._enter(unknown_factory)'),
                  DELEGATED.replace('class Stager:','class Stager(Other):')]
        for source in variants:
            with self.subTest(source=source):
                self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_creator_cannot_rebind_path_mode_directory_or_descriptor(self):
        variants=[DELEGATED.replace("options['file'] = temporary","options['file'] = owner.target"),
                  DELEGATED.replace('os.path.dirname(owner.target)','"/elsewhere"'),
                  DELEGATED.replace('options[\'mode\'] = owner.mode',"options['mode'] = 'a'"),
                  DELEGATED.replace('os.close(descriptor)','os.close(temporary)'),
                  DELEGATED.replace('return io.open(**options)','return io.open(**options)\n        owner.target = temporary')]
        for source in variants:
            with self.subTest(source=source):
                self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_constructor_effect_unknown_decorator_and_external_dependency_are_held(self):
        variants=[DELEGATED.replace('owner.target = path','owner.target = path\n        os.unlink(path)'),
                  DELEGATED.replace('owner.target = path','owner.target = path\n        owner.target = path'),
                  DELEGATED.replace('@contextlib.contextmanager','@unknown'),
                  DELEGATED+'\nimport requests\n',DELEGATED+'\nStager._create = unknown\n']
        for source in variants:
            with self.subTest(source=source):
                self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_extra_yield_changed_factory_kwargs_or_swallowed_body_error_are_held(self):
        variants=[DELEGATED.replace('yield handle','yield handle\n            yield handle'),
                  DELEGATED.replace('factory(**this.options)','factory()'),
                  DELEGATED.replace('this.publish(handle)','this.publish(handle)\n        return 7'),
                  DELEGATED.replace('yield handle','try:\n                yield handle\n            except OSError:\n                pass')]
        for source in variants:
            with self.subTest(source=source):
                self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_candidate_cannot_redirect_sync_commit_or_stream_cleanup(self):
        site=site_for();fixed=reuse.candidate(site)
        for candidate in (fixed.replace('this.publish(handle)','this.unrelated(handle)'),
                          fixed.replace('os.unlink(handle.name)','os.unlink(this.target)'),
                          fixed.replace('this.sync(handle)','this.publish(handle)')):
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):reuse.apply_candidate({'pkg/storage.py':DELEGATED},site,candidate)


class DelegatedObservationTests(unittest.TestCase):
    def test_public_factory_close_counterexample_is_repaired_in_actual_method(self):
        p=plan();observed=worker.observe(p)
        self.assertTrue(observed['fault_discovered']);self.assertTrue(observed['repair_pass'])
        close=observed['probes'][0]
        self.assertTrue(close['fault_injected']);self.assertEqual(close['public_entry_symbol'],'begin')
        self.assertEqual(close['repair_symbol'],'Stager._enter')
        self.assertEqual(close['condition_hits'][0]['operation'],'STREAM_CLOSE')
        self.assertTrue(all(row['contract_pass'] is True for row in observed['reinjection']+observed['regression']))

    def test_default_text_and_explicit_bytes_are_observed_at_the_public_entry(self):
        observed=worker.observe(plan())
        self.assertEqual(observed['regression'][0]['invocation_kwargs'],dict(overwrite=True,mode='wb'))
        self.assertEqual(observed['regression'][1]['invocation_kwargs'],dict(overwrite=True))
        self.assertEqual(observed['regression'][1]['write_input_kind'],'TEXT')

    def test_unreachable_second_close_remains_unknown(self):
        p=plan();program=deepcopy(next(iter(p['proposal']['condition_programs'].values())))
        raw={k:program[k] for k in reuse.conditions.FIELDS};raw['occurrence']=2
        text=TEXT;raw['source_id']='constructed'
        condition=reuse.conditions.bind(raw,{'constructed':text})
        observed=worker.context_case(DELEGATED,p['site']['symbol'],condition['condition_id'],p['site']['binding'],condition=condition)
        self.assertIsNone(observed['contract_pass']);self.assertFalse(observed['fault_injected'])
        self.assertEqual(observed['condition_seen'],1)

    def test_named_temporary_generator_has_one_instrumentation_layer(self):
        from test_reliability_context_lifecycle import GENERATOR
        site=reuse.inventory({'storage.py':GENERATOR})['accepted'][0]
        hypotheses,_=reuse.conditions.owned_qualification()
        for hypothesis in hypotheses:
            condition=hypothesis['condition_programs'][0]
            observed=worker.context_case(GENERATOR,site['symbol'],condition['condition_id'],site['binding'],condition=condition)
            self.assertEqual(observed['condition_seen'],1)
            self.assertEqual(observed['fault_injection_count'],1)
            self.assertEqual(observed['condition_hits'],[dict(operation=condition['operation'],phase=condition['phase'],occurrence=1)])

    def test_class_reassignment_and_custom_attribute_protocol_are_held(self):
        for source in (DELEGATED+'\nStager = replacement\n',
                       DELEGATED.replace('    def unrelated(owner):','    def __getattribute__(owner, name):\n        return 19\n\n    def unrelated(owner):'),
                       DELEGATED+'\nValueError = custom_error\n'):
            self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND
                                 for s in reuse.inventory({'pkg/storage.py':source})['accepted']))

    def test_unused_public_argument_or_unknown_option_is_held(self):
        for signature in ('def begin(destination, ignored, writer=Stager, **options):',
                          'def begin(destination, writer=Stager, *, ignored=True, **options):'):
            source=DELEGATED.replace('def begin(destination, writer=Stager, **options):',signature)
            self.assertFalse(any(s['binding'].get('kind')==reuse.delegated.KIND
                                 for s in reuse.inventory({'pkg/storage.py':source})['accepted']))


if __name__=='__main__':unittest.main()
