
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from reqlox import _runtime
_runtime()
from reqlox_core.reqlox_paths import state_root
"""\u5909\u66f4\u4f9d\u5b58\u306e\u5931\u52b9\u3068、\u5909\u66f4\u306e\u306a\u3044site\u306e\u5b9f\u8a3c\u6e08\u307f\u89b3\u6e2c\u3060\u3051\u306e\u518d\u5229\u7528\u3092\u691c\u67fb\u3059\u308b。"""
from copy import deepcopy
import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests')]
from reqlox_core import reliability_reuse as reuse
from reqlox_core import reliability_reuse_cache as cache
from reqlox_core import run_reliability_reuse as runner
from test_reliability_reuse import ATOMIC, ASYNC, contracts


class DependencyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.sources = {'src/storage.py': ATOMIC, 'src/work.py': ASYNC}
        self.site = reuse.inventory(self.sources)['accepted'][0]
        self.plan = runner.build_plan(self.site, reuse.bind_contract(self.site, contracts()), None,
                                     self.sources, [], 'SOURCE', 3, None)
        self.method = {'compiler': 'frozen'}; self.runtime = {'python': 'frozen'}

    def key(self, plan=None, method=None, runtime=None, snapshot=None, kind='DEVELOPMENT_CONTROL', arm='SOURCE'):
        return cache.key(plan or self.plan, arm, method or self.method, runtime or self.runtime,
                         kind, reuse.c.digest(snapshot or self.sources))

    def test_unrelated_member_does_not_invalidate_fixed_compiler_boundary(self):
        self.assertEqual(self.key(), self.key(snapshot=dict(self.sources, extra='value=1')))

    def test_target_helper_contract_source_candidate_method_runtime_and_wheel_change_key(self):
        baseline = self.key()
        for mutate in (
            lambda p:p['sources'].__setitem__(self.site['member'], ATOMIC+'\n'),
            lambda p:p['contract']['declaration'].__setitem__('scope','changed'),
            lambda p:p['proposal'].__setitem__('hypotheses',['changed-source-anchor']),
            lambda p:p.__setitem__('candidate_code',reuse.candidate(self.site)),
            lambda p:p.__setitem__('dependency_sha256','changed-wheel'),
        ):
            p=deepcopy(self.plan);mutate(p)
            if p['sources'] != self.plan['sources']:
                with self.assertRaisesRegex(ValueError,'MEMBER_CLOSURE'):self.key(plan=p)
            else:self.assertNotEqual(baseline,self.key(plan=p))
        self.assertNotEqual(baseline,self.key(method={'compiler':'changed'}))
        self.assertNotEqual(baseline,self.key(runtime={'python':'changed'}))
        self.assertNotEqual(baseline,self.key(kind='UNUSED_INDEPENDENT_TARGET'))
        self.assertNotEqual(baseline,self.key(arm='NO_SOURCE'))

    def test_context_keeps_whole_repository_boundary(self):
        p=deepcopy(self.plan);p['site']['family']='atomic_context'
        self.assertNotEqual(self.key(plan=p),self.key(plan=p,snapshot=dict(self.sources,extra='value=1')))


@unittest.skip('Archived native tests require a separate retained-scope authorized harness')
class NativeSelectiveReuseTests(unittest.TestCase):
    def test_unrelated_and_changed_member_source_contract_and_corrupt_evidence(self):
        base=state_root()
        with tempfile.TemporaryDirectory(prefix='selective-reuse-',dir=base) as directory:
            d=Path(directory);sources={'src/storage.py':ATOMIC,'src/work.py':ASYNC}
            initial=runner.run(sources,contracts(),[],d/'initial')
            self.assertEqual(initial['native_campaigns'],4)
            different=dict(sources,**{'src/unrelated.py':'constant=1\n'})
            with patch.object(runner,'execute',side_effect=AssertionError('Unnecessary execution')):
                cached=runner.run(different,contracts(),[],d/'unrelated',site_cache=d/'initial',maximum_native_campaigns=0)
                again=runner.run(dict(different,**{'src/unrelated.py':'constant=2\n'}),contracts(),[],d/'again',site_cache=d/'unrelated',maximum_native_campaigns=0)
            self.assertEqual(cached['reused_arms'],4);self.assertEqual(again['native_campaigns'],0)
            self.assertTrue(all(e['reference']['directory']==str(d/'initial')
                                for e in runner.read(d/'again/study.json')['entries']))
            changed=dict(different,**{'src/work.py':ASYNC+'\n'})
            revised=runner.run(changed,contracts(),[],d/'changed',site_cache=d/'initial',maximum_native_campaigns=2)
            self.assertEqual((revised['native_campaigns'],revised['reused_arms']),(2,2))
            text='fsync returned an error.'
            h=reuse.hypothesis(dict(family='atomic_file',conditions=[text],faults=['FSYNC'],source_id='source',
                span=dict(start=0,end=len(text),sha256=reuse.sha(text))),{'source':text})
            informed=runner.run(sources,contracts(),[h],d/'source',site_cache=d/'initial',source_texts={'source':text},maximum_native_campaigns=1)
            self.assertEqual((informed['native_campaigns'],informed['reused_arms']),(1,3))
            owner=contracts();owner['async_resource']['scope']='new approved scope'
            rebound=runner.run(sources,owner,[],d/'contract',site_cache=d/'initial',maximum_native_campaigns=2)
            self.assertEqual((rebound['native_campaigns'],rebound['reused_arms']),(2,2))
            observed=next((d/'initial').glob('*-source/observed.json'));observed.write_text('{}')
            with patch.object(runner,'execute',side_effect=AssertionError('Corrupt evidence replay')):
                with self.assertRaisesRegex(ValueError,'OBSERVATION_DRIFT'):
                    runner.run(different,contracts(),[],d/'bad',site_cache=d/'initial')
            self.assertFalse((d/'bad').exists())

    def test_budget_and_expired_or_naive_deadline_stop_before_execution(self):
        base=state_root()
        with tempfile.TemporaryDirectory(prefix='reuse-budget-',dir=base) as directory:
            d=Path(directory);sources={'src/work.py':ASYNC}
            past=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=1)).isoformat()
            for name,kwargs,reason in [('budget',dict(maximum_native_campaigns=1),'CAMPAIGN_LIMIT'),
                                       ('past',dict(deadline=past),'DEADLINE'),
                                       ('naive',dict(deadline='2026-10-10T00:00:00'),'TIMEZONE')]:
                with patch.object(runner,'execute',side_effect=AssertionError('Unexpected execution')):
                    with self.assertRaisesRegex(ValueError,reason):runner.run(sources,contracts(),[],d/name,**kwargs)
                self.assertFalse((d/name).exists())


if __name__=='__main__':unittest.main()
