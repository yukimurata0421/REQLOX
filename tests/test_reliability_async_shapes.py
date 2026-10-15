"Finite reliability controls and verification."
import asyncio
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reqlox_core'))
import reliability_reuse as reuse
import reliability_reuse_worker as worker

BARE_RESULT='''async def guarded(resource, operation):
    await resource.acquire()
    result = await operation()
    resource.release()
    return result
'''
EXCEPT_ONLY='''async def guarded(resource, operation):
    await resource.acquire()
    try:
        result = await operation()
    except Exception:
        resource.release()
        raise
    resource.release()
    return result
'''
DIRECT='''async def guarded(resource, operation):
    await resource.acquire()
    try:
        return await operation()
    finally:
        resource.release()
'''


class AsyncShapeTests(unittest.TestCase):
    def case(self,code,fault):return asyncio.run(worker.async_case(code,fault))

    def test_result_and_exception_only_shapes_are_repaired_without_losing_results(self):
        for source in (BARE_RESULT,EXCEPT_ONLY):
            with self.subTest(source=source):
                site=reuse.inventory({'src/api.py':source})['accepted'][0]
                self.assertTrue(site['binding']['returns_result'])
                self.assertTrue(self.case(site['code'],'NORMAL')['work_result_preserved'])
                self.assertFalse(self.case(site['code'],'TASK_CANCEL')['contract_pass'])
                fixed=reuse.candidate(site)
                self.assertTrue(all(self.case(fixed,f)['contract_pass'] for f in ('NORMAL',*reuse.OPERATIONS['async_resource'])))

    def test_exception_only_cleanup_handles_runtime_error_but_cancellation_is_counterexample(self):
        self.assertTrue(self.case(EXCEPT_ONLY,'EXCEPTION')['contract_pass'])
        self.assertFalse(self.case(EXCEPT_ONLY,'TASK_CANCEL')['contract_pass'])
        self.assertTrue(self.case(EXCEPT_ONLY,'ACQUIRE_CANCEL')['prior_owner_lock_preserved'])

    def test_finally_direct_return_and_baseexception_cleanup_are_supported(self):
        for source in (DIRECT,EXCEPT_ONLY.replace('except Exception:','except BaseException:')):
            site=reuse.inventory({'src/api.py':source})['accepted'][0]
            self.assertTrue(site['binding']['protected'])
            self.assertEqual(reuse.candidate(site),site['code'])
            self.assertTrue(all(self.case(site['code'],f)['contract_pass'] for f in ('NORMAL',*reuse.OPERATIONS['async_resource'])))

    def test_return_dropping_candidate_is_rejected_even_with_identical_signature(self):
        sources={'src/api.py':BARE_RESULT};site=reuse.inventory(sources)['accepted'][0]
        changed=reuse.candidate(site).replace('result = await operation()', 'await operation()').replace('    return result\n','')
        with self.assertRaisesRegex(ValueError,'RETURN_SEMANTICS'):reuse.apply_candidate(sources,site,changed)

    def test_cleanup_covering_acquisition_or_unknown_exception_and_builtin_shadow_are_held(self):
        before='''async def guarded(resource, operation):
    try:
        await resource.acquire()
        await operation()
    finally:
        resource.release()
'''
        for source in (before,EXCEPT_ONLY.replace('except Exception:','except LookupError:'),
                       'Exception = ValueError\n'+EXCEPT_ONLY,'class BaseException: pass\n'+EXCEPT_ONLY,
                       EXCEPT_ONLY.replace('        raise\n','        return result\n')):
            self.assertFalse(reuse.inventory({'src/api.py':source})['accepted'])


if __name__=='__main__':unittest.main()
