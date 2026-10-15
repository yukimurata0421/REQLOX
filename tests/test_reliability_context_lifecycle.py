
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from reqlox import _runtime
_runtime()
from reqlox_core.reqlox_paths import state_root
"""contextmanager\u306e\u5b9fmodule\u4fee\u5fa9\u3068、\u672a\u5230\u9054fault\u3092\u6545\u969c\u3078\u8aa4\u8a8d\u3057\u306a\u3044\u3053\u3068。"""
import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT / 'tests')]
from reqlox_core import reliability_reuse as reuse
from reqlox_core import reliability_reuse_worker as worker
from reqlox_core import run_reliability_reuse as runner
from reqlox_core import run_reliability_improvement_loop as loop

GENERATOR='''import os as operating
import tempfile as temporary_files
from contextlib import contextmanager as transaction

@transaction
def save(path, file_mode="w"):
    """Preserve the public mode and documentation."""
    with temporary_files.NamedTemporaryFile(mode=file_mode, delete=False, dir=operating.path.dirname(path)) as stream:
        pending = stream.name
        yield stream
        stream.flush()
        operating.fsync(stream.fileno())
    operating.replace(pending, path)

def neighboring():
    return 17
'''

UNREACHED='''import os
import tempfile
from contextlib import contextmanager
class Writer:
    def __init__(self,path,overwrite=True,mode="wb"):
        self.path=path;self.mode=mode
    @contextmanager
    def open(self):
        stream=tempfile.NamedTemporaryFile(mode=self.mode,delete=False,dir=os.path.dirname(self.path))
        try:
            with stream:
                yield stream
            self.commit(stream.name)
        finally:
            if os.path.exists(stream.name):self.rollback(stream.name)
    def commit(self,temporary):os.rename(temporary,self.path)
    def rollback(self,temporary):os.unlink(temporary)
def begin(path,overwrite=True,mode="wb"):
    return Writer(path,overwrite=overwrite,mode=mode).open()
'''


def contracts():
    return {'atomic_context':dict(id='owned.atomic-context.v1',basis='\u6240\u6709\u3059\u308b\u4fdd\u5b58\u306f\u5931\u6557\u524d\u306e\u5024\u3068\u4ed6\u8005\u306efile\u3092\u4fdd\u6301\u3059\u308b',scope='\u69cb\u6210\u3057\u305f\u6709\u9650\u5bfe\u7167')}


def plan(source):
    sources={'src/storage.py':source};site=reuse.inventory(sources)['accepted'][0]
    return dict(site=site,sources=sources,contract=reuse.bind_contract(site,contracts()),
                proposal=reuse.propose(site,[],3),candidate_code=None,dependency_sha256=None)


class ContextLifecycleTests(unittest.TestCase):
    def test_unreached_fsync_is_unknown_and_not_discovered(self):
        p=plan(UNREACHED);value=worker.observe(p)
        row=next(x for x in value['probes'] if x['fault']=='FSYNC')
        self.assertFalse(row['fault_injected']);self.assertEqual(row['fault_injection_count'],0)
        self.assertIsNone(row['contract_pass']);self.assertFalse(value['fault_discovered'])
        self.assertEqual(loop.repair_decision({'rows':[{'observed':value}]}),'HELD_FAULT_NOT_REACHED')
        value.update(plan_sha256=reuse.c.digest(p),namespaces={'net':'child'},external_action_attempts=0,maximum_rss_kib=100)
        runner.check_observation(value,p,{'net':'parent'})
        row['contract_pass']=False
        with self.assertRaisesRegex(ValueError,'ORACLE_DRIFT'):runner.check_observation(value,p,{'net':'parent'})

    def test_generator_repairs_actual_module_and_preserves_default_text_and_neighbor(self):
        p=plan(GENERATOR);value=worker.observe(p)
        self.assertTrue(value['fault_discovered']);self.assertTrue(value['repair_pass'])
        self.assertTrue(all(x['fault_injected'] for x in value['probes']))
        revised=reuse.apply_candidate(p['sources'],p['site'],value['candidate_code'])['src/storage.py']
        self.assertEqual(revised.count('@transaction'),1);self.assertIn('file_mode=\'w\'',revised)
        self.assertIn('def neighboring():\n    return 17\n',revised)
        scope={};exec(revised,scope)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'record'
            with scope['save'](str(path)) as stream:stream.write('\u8a18\u9332')
            self.assertEqual(path.read_text(),'\u8a18\u9332')
            with patch.object(scope['temporary_files'],'NamedTemporaryFile',side_effect=OSError('creation')):
                with self.assertRaisesRegex(OSError,'creation'):
                    with scope['save'](str(path)):pass
            self.assertEqual(path.read_text(),'\u8a18\u9332')

    def test_unknown_directory_mode_extra_yield_and_import_mutation_are_held(self):
        changes=[GENERATOR.replace('operating.path.dirname(path)','"/other"'),
                 GENERATOR.replace('file_mode="w"','file_mode="a"'),
                 GENERATOR.replace('yield stream','yield stream\n        yield stream'),
                 GENERATOR+'\noperating.replace = None\n',
                 GENERATOR.replace('stream.flush()','print("extra")\n        stream.flush()')]
        for source in changes:
            with self.subTest(source=source):self.assertFalse(reuse.inventory({'src/a.py':source})['accepted'])

    def test_candidate_cannot_change_mode_or_remove_context_decorator(self):
        p=plan(GENERATOR);candidate=reuse.candidate(p['site'])
        with self.assertRaises(ValueError):reuse.apply_candidate(p['sources'],p['site'],candidate.replace("file_mode='w'","file_mode='wb'"))
        self.assertTrue(reuse.inventory(reuse.apply_candidate(p['sources'],p['site'],candidate))['accepted'][0]['binding']['protected'])

    def test_multiline_decorator_and_intervening_comment_patch_as_one_function(self):
        source=GENERATOR.replace('@transaction','@(\n    transaction\n)\n# decoration comment')
        p=plan(source);revised=reuse.apply_candidate(p['sources'],p['site'],reuse.candidate(p['site']))
        self.assertEqual(revised['src/storage.py'].count('@transaction'),1)
        self.assertIn('def neighboring():\n    return 17\n',revised['src/storage.py'])
        self.assertTrue(reuse.inventory(revised)['accepted'][0]['binding']['protected'])
        scope={};exec(revised['src/storage.py'],scope)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'record'
            with scope['save'](str(path)) as stream:stream.write('\u8a18\u9332')
            self.assertEqual(path.read_text(),'\u8a18\u9332')
        from test_reliability_reuse import ATOMIC
        source=ATOMIC.replace('    @staticmethod','    @(\n        staticmethod\n    )\n    # decoration comment')
        sources={'src/records.py':source};site=reuse.inventory(sources)['accepted'][0]
        revised=reuse.apply_candidate(sources,site,reuse.candidate(site));scope={};exec(revised['src/records.py'],scope)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'record';scope['Records'].persist(path,b'actual')
            self.assertEqual(path.read_bytes(),b'actual')


@unittest.skip('Archived native tests require a separate retained-scope authorized harness')
class NativeContextLoopTests(unittest.TestCase):
    def test_generator_is_adopted_after_fresh_confirmation_and_unreached_is_held(self):
        base=state_root()
        with tempfile.TemporaryDirectory(prefix='context-loop-',dir=base) as directory:
            end=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=2)).isoformat()
            adopted=loop.run({'src/storage.py':GENERATOR},contracts(),[],Path(directory)/'generator',deadline=end,maximum_native_campaigns=4)
            self.assertEqual(adopted['status'],'ADOPTED_IN_SNAPSHOT');self.assertEqual(adopted['native_campaigns'],4)
            held=loop.run({'src/storage.py':UNREACHED},contracts(),[],Path(directory)/'unreached',deadline=end,maximum_native_campaigns=2)
            self.assertEqual(held['status'],'HELD_FAULT_NOT_REACHED');self.assertEqual(held['adopted_files'],{})
            self.assertEqual(held['native_campaigns'],2)


if __name__=='__main__':unittest.main()
