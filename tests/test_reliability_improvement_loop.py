from reqlox import _runtime
_runtime()
from reqlox_paths import state_root
"""\u53cd\u4f8b、\u4fee\u5fa9、\u5225round\u3067\u306e\u5168catalog\u78ba\u8a8d、\u6761\u4ef6\u4ed8\u304d\u63a1\u7528\u306e\u5b9f\u7d4c\u8def。"""
import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'reqlox_core'),str(ROOT/'tests')]
import reliability_reuse as reuse
import run_reliability_reuse as runner
import run_reliability_improvement_loop as loop
from test_reliability_reuse import ATOMIC,contracts


PARTIAL=ATOMIC.replace('            output.write(data)\n            output.flush()',
    '            try:\n                output.write(data)\n                output.flush()\n'
    '            except:\n                pending.unlink()\n                raise')


def hypothesis():
    text='Constructed fsync-failure priority control.'
    h=reuse.hypothesis(dict(family='atomic_file',conditions=[text],faults=['FSYNC'],source_id='constructed',
        span=dict(start=0,end=len(text),sha256=reuse.sha(text))),{'constructed':text})
    return h,{'constructed':text}


@unittest.skipUnless(__import__("os").environ.get("REQLOX_RUN_NATIVE_TESTS") == "1", "native experiments are opt-in")
class FiniteLoopTests(unittest.TestCase):
    def setUp(self):
        base=state_root()
        self.temp=tempfile.TemporaryDirectory(prefix='repair-loop-',dir=base);self.directory=Path(self.temp.name)
        self.deadline=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=2)).isoformat()
        self.sources={'src/storage.py':PARTIAL};h,self.texts=hypothesis();self.hypotheses=[h]

    def tearDown(self):self.temp.cleanup()

    def run_loop(self,name,**kwargs):
        return loop.run(self.sources,contracts(),self.hypotheses,self.directory/name,
            source_texts=self.texts,deadline=self.deadline,maximum_probes=1,**kwargs)

    def test_source_priority_repair_full_confirmation_and_archived_audit(self):
        result=self.run_loop('qualified',maximum_native_campaigns=4)
        self.assertEqual(result['status'],'ADOPTED_IN_SNAPSHOT')
        self.assertEqual((result['rounds'][0]['source_faults'],result['rounds'][0]['no_source_faults']),(1,0))
        self.assertEqual(len(result['rounds']),2)
        self.assertEqual(runner.read(self.directory/'qualified/round-01/study.json')['maximum_probes'],3)
        self.assertIn('src/storage.py',result['adopted_files'])
        self.assertEqual(self.sources['src/storage.py'],PARTIAL)
        self.assertFalse(result['checkout_mutated']);self.assertFalse(result['natural_source_added_value_certified'])
        completed=subprocess.run([sys.executable,'-B',str(ROOT/'reqlox_core/audit_reliability_reuse.py'),
            '--kind','loop','--output',str(self.directory/'qualified')],capture_output=True,text=True,timeout=5)
        self.assertEqual(completed.returncode,0,completed.stderr)
        manifest=self.directory/'qualified/result.json';bad=runner.read(manifest);bad['adopted_files']={}
        manifest.write_bytes(reuse.c.canonical(reuse.c.seal(bad)))
        with self.assertRaisesRegex(ValueError,'ADOPTION_DRIFT'):loop.verify(self.directory/'qualified')

    def test_wrong_candidate_is_rejected_without_successor_or_adoption(self):
        site=reuse.inventory(self.sources)['accepted'][0]
        result=self.run_loop('wrong',supplied_candidates={site['id']:site['code']},maximum_native_campaigns=2)
        self.assertEqual(result['status'],'REJECTED_REPAIR_UNQUALIFIED')
        self.assertEqual(result['adopted_files'],{})
        self.assertEqual(len(result['rounds']),1)
        self.assertFalse((self.directory/'wrong/round-01').exists())

    def test_missing_contract_is_held_even_if_no_fault_was_executed(self):
        result=loop.run(self.sources,{},self.hypotheses,self.directory/'held',source_texts=self.texts,
                        deadline=self.deadline,maximum_native_campaigns=0)
        self.assertEqual(result['status'],'HELD_NO_EXECUTION')
        self.assertEqual((result['native_campaigns'],result['adopted_files']),(0,{}))

    def test_confirmation_budget_exhaustion_keeps_terminal_and_no_adoption(self):
        with self.assertRaisesRegex(ValueError,'CAMPAIGN_LIMIT'):self.run_loop('limited',maximum_native_campaigns=2)
        result=runner.read(self.directory/'limited/result.json')
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(result['adopted_files'],{})
        self.assertEqual(len(result['rounds']),1)
        self.assertFalse((self.directory/'limited/round-01').exists())
        self.assertEqual(runner.read(self.directory/'limited/round-00/result.json')['status'],'COMPLETE')


if __name__=='__main__':unittest.main()
