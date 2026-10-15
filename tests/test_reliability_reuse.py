
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from reqlox import _runtime
_runtime()
from reqlox_core.reqlox_paths import state_root
"""\u5171\u901abinding\u306e\u610f\u5473\u5883\u754c、\u5b9f\u4fee\u5fa9、\u9694\u96e2、\u518d\u5229\u7528\u306e\u5931\u52b9\u3092\u691c\u67fb\u3059\u308b。"""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
pass  # Package imports resolve from the repository root.
from reqlox_core import reliability_reuse as r
from reqlox_core import reliability_reuse_worker as w
from reqlox_core import run_reliability_reuse as runner

ATOMIC = '''import os as operating
from pathlib import Path as FilePath

def sync_output(stream):
    operating.fsync(stream.fileno())

class Records:
    @staticmethod
    def persist(destination: FilePath, data: bytes) -> None:
        """Save bytes; preserve this API documentation."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_name(destination.name + f".tmp-{operating.getpid()}")
        with pending.open("xb") as output:
            output.write(data)
            output.flush()
            sync_output(output)
        operating.replace(pending, destination)
'''
ASYNC = '''async def use_resource(resource, operation):
    await resource.acquire()
    await operation()
    resource.release()
'''
CLOCK = '''from cachetools import TTLCache as Cache
def new_cache(civil, elapsed):
    return Cache(maxsize=16, ttl=4, timer=civil)
'''


def contracts():
    return {f:dict(id=v, basis='Explicit owned test purpose; not inferred from Source', scope='Finite frozen functions only') for f,v in r.CONTRACTS.items()}


def plan(site, sources, hypotheses=(), code=None):
    return dict(site=site, sources=sources, contract=r.bind_contract(site, contracts()),
                proposal=r.propose(site, hypotheses), candidate_code=r.candidate(site) if code is None else code,
                dependency_sha256=None)


class BindingTests(unittest.TestCase):
    def test_alias_class_and_helper_are_bound_without_import(self):
        found = r.inventory({'src/records.py': ATOMIC})
        site = found['accepted'][0]
        self.assertEqual(site['symbol'], 'Records.persist')
        self.assertEqual(site['family'], 'atomic_file')
        self.assertIn('os.fsync(output.fileno())', site['code'])
        self.assertFalse(site['semantics_inferred'])
        self.assertEqual(found['target_specific_adapter_count'], 0)

    def test_patch_preserves_aliases_annotations_docstring_and_neighbors(self):
        sources = {'src/records.py': ATOMIC}
        site = r.inventory(sources)['accepted'][0]
        fixed = r.candidate(site)
        revised = r.apply_candidate(sources, site, fixed)
        self.assertIn('operating.fsync', revised[site['member']])
        self.assertIn('destination: FilePath, data: bytes', revised[site['member']])
        self.assertIn('Save bytes; preserve', revised[site['member']])
        self.assertTrue(revised[site['member']].startswith(ATOMIC.split('class Records:')[0]))
        self.assertEqual(r.inventory(revised)['accepted'][0]['code'], fixed)
        self.assertEqual(sources[site['member']], ATOMIC)

    def test_original_module_with_restored_aliases_actually_executes(self):
        sources = {'module.py': ATOMIC}
        site = r.inventory(sources)['accepted'][0]
        revised = r.apply_candidate(sources, site, r.candidate(site))
        scope = {}; exec(revised['module.py'], scope)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)/'record'; destination.write_bytes(b'prior')
            with patch.object(scope['operating'], 'fsync', side_effect=OSError('failure')):
                with self.assertRaises(OSError): scope['Records'].persist(destination, b'new')
            self.assertEqual(list(Path(tmp).iterdir()), [destination])
            self.assertEqual(destination.read_bytes(), b'prior')

    def test_contract_is_required_and_source_is_not_oracle(self):
        site = r.inventory({'a.py': ASYNC})['accepted'][0]
        with self.assertRaisesRegex(ValueError, 'OWNER_CONTRACT'): r.bind_contract(site, {})
        self.assertFalse(r.bind_contract(site, contracts())['source_is_oracle'])

    def test_shadowed_import_and_instance_method_are_held(self):
        changed = ATOMIC.replace('pending = destination', 'operating = None\n        pending = destination')
        self.assertFalse(r.inventory({'a.py':changed})['accepted'])
        changed = ATOMIC.replace('    @staticmethod\n', '')
        self.assertFalse(r.inventory({'a.py':changed})['accepted'])

    def test_unknown_helper_and_side_effect_are_held(self):
        for changed in (ATOMIC.replace('sync_output(output)', 'unknown(output)'),
                        ATOMIC.replace('output.flush()', 'operating.system("true")')):
            self.assertFalse(r.inventory({'a.py':changed})['accepted'])

    def test_helper_recursion_and_depth_are_bounded(self):
        changed = ATOMIC.replace('operating.fsync(stream.fileno())', 'sync_output(stream)')
        self.assertFalse(r.inventory({'a.py':changed})['accepted'])

    def test_local_helper_shadow_and_reassigned_module_import_are_held(self):
        local=ATOMIC.replace('pending = destination', 'sync_output = None\n        pending = destination')
        self.assertFalse(r.inventory({'a.py':local})['accepted'])
        global_shadow=ATOMIC.replace('from pathlib', 'operating = None\nfrom pathlib')
        self.assertFalse(r.inventory({'a.py':global_shadow})['accepted'])

    def test_import_alias_shadowed_by_definition_or_control_flow_is_held(self):
        for addition in ('class operating: pass\n','def operating(): pass\n',
                         'if True:\n    operating = None\n'):
            source=ATOMIC.replace('def sync_output',addition+'\ndef sync_output')
            self.assertFalse(r.inventory({'src/a.py':source})['accepted'])

    def test_mutated_imported_api_is_held_but_function_local_assignment_is_separate(self):
        changed=ATOMIC.replace('def sync_output','operating.replace = None\n\ndef sync_output')
        self.assertFalse(r.inventory({'src/a.py':changed})['accepted'])
        separate='def unrelated():\n    operating = None\n\n'+ATOMIC
        self.assertEqual(len(r.inventory({'src/a.py':separate})['accepted']),1)

    def test_nonstandard_class_indent_preserves_neighbor_method_and_rebinds(self):
        source='\n'.join(line[2:] if line.startswith('  ') else line for line in ATOMIC.splitlines())+'\n'
        source+='\n  @staticmethod\n  def untouched():\n      return 1\n'
        sources={'src/api.py':source};site=r.inventory(sources)['accepted'][0]
        revised=r.apply_candidate(sources,site,r.candidate(site))
        self.assertIn('  def untouched():\n      return 1\n',revised['src/api.py'])
        self.assertEqual(r.inventory(revised)['accepted'][0]['code'],r.candidate(site))

    def test_extra_statement_decorator_or_return_annotation_in_candidate_is_rejected(self):
        sources={'src/api.py':ASYNC};site=r.inventory(sources)['accepted'][0];fixed=r.candidate(site)
        for code in (fixed+'marker = 1\n','@staticmethod\n'+fixed,
                     fixed.replace('resource, operation):','resource, operation) -> int:')):
            with self.assertRaises(ValueError):r.apply_candidate(sources,site,code)

    def test_path_escape_and_oversized_source_are_rejected(self):
        for sources in ({'../outside.py': ASYNC}, {'x.py':' '*262145}):
            with self.assertRaises(ValueError): r.inventory(sources)

    def test_generated_candidate_cannot_change_signature_or_add_execution(self):
        sources={'a.py':ASYNC};site=r.inventory(sources)['accepted'][0]
        for code in (ASYNC.replace('resource, operation','resource, operation, third'),
                     ASYNC.replace('resource.release()', 'resource.release()\n    print("extra")')):
            with self.assertRaises(ValueError):r.apply_candidate(sources,site,code)

    def test_changed_member_invalidates_patch(self):
        sources={'a.py':ASYNC};site=r.inventory(sources)['accepted'][0]
        with self.assertRaisesRegex(ValueError,'SOURCE_DRIFT'):
            r.apply_candidate({'a.py':ASYNC+'\n'},site,r.candidate(site))

    def test_context_factory_default_class_is_data_binding(self):
        source='''class OwnedWriter:
    def open(self): pass
    def commit(self): pass
    def rollback(self): pass
def begin(path, writer=OwnedWriter, **options):
    return writer(path, **options).open()
'''
        found=r.inventory({'storage.py':source})
        self.assertEqual(found['accepted'][0]['family'],'atomic_context')
        self.assertEqual(found['accepted'][0]['binding']['factory_class'],'OwnedWriter')


class HypothesisTests(unittest.TestCase):
    def record(self):
        text='Observed synchronization failure before replacement.'
        row=dict(family='atomic_file',conditions=['successful create','synchronization raises'],
                 faults=['FSYNC'],source_id='report',span=dict(start=0,end=len(text),sha256=r.sha(text)))
        return row,{'report':text}

    def test_anchor_holds_semantics_and_authority_separate(self):
        row,texts=self.record();h=r.hypothesis(row,texts)
        self.assertFalse(h['semantic_support_certified'])
        self.assertFalse(h['execution_authority'])

    def test_changed_span_or_unsupported_fault_is_rejected(self):
        for key,value in [('faults',['HOST_RESTART']),('span',dict(start=0,end=1,sha256='0'*64))]:
            row,texts=self.record();row[key]=value
            with self.assertRaises(ValueError):r.hypothesis(row,texts)

    def test_source_and_no_source_have_same_capabilities(self):
        site=r.inventory({'a.py':ATOMIC})['accepted'][0]
        row,texts=self.record();h=r.hypothesis(row,texts)
        left=r.propose(site,[h]);right=r.propose(site,[])
        self.assertEqual(set(left['faults']),set(right['faults']))
        self.assertEqual(left['faults'][0],'FSYNC')
        self.assertEqual(right['faults'][0],'WRITE')

    def test_unrelated_family_does_not_override_experiment(self):
        site=r.inventory({'a.py':ASYNC})['accepted'][0]
        row,texts=self.record();h=r.hypothesis(row,texts)
        self.assertEqual(r.propose(site,[h]),r.propose(site,[]))

    def test_existing_incident_ir_is_projected_and_unknown_conditions_remain(self):
        text='fsync returned EIO'
        ir=r.c.seal(dict(contract_type='IncidentHypothesisSet', status='SILVER_CANDIDATE',
            source=dict(source_record_id='existing',source_document_sha256=r.sha(text)),
            evidence_spans=[dict(evidence_id='ev',start_char=0,end_char=len(text),content_hash=r.sha(text),text=text)],
            observed_assertions=[dict(assertion_id='a',statement=text,arguments=[dict(role='primitive',value='fsync_error')],evidence_ids=['ev']),
                                 dict(assertion_id='b',statement='unknown',arguments=[dict(role='primitive',value='other')],evidence_ids=['ev'])]))
        value=r.project_incident_set(ir,text)
        self.assertEqual(value['hypotheses'][0]['faults'],['FSYNC'])
        self.assertEqual(value['held'][0]['assertion_id'],'b')
        self.assertFalse(value['semantic_support_certified'])
        with self.assertRaisesRegex(ValueError,'INCIDENT_SOURCE'):r.project_incident_set(ir,text+' changed')

    def test_counterexample_required_before_default_repair_is_generated(self):
        sources={'a.py':ASYNC};site=r.inventory(sources)['accepted'][0]
        p=plan(site,sources);p['candidate_code']=None
        loop=asyncio.new_event_loop()
        try:
            value=w.observe(p,loop=loop)
            self.assertTrue(value['repair_pass'])
            self.assertEqual(value['candidate_code'],r.candidate(site))
        finally:loop.close()


class ExecutionTests(unittest.TestCase):
    def test_resource_exception_and_real_task_cancellation_are_repaired(self):
        site=r.inventory({'a.py':ASYNC})['accepted'][0]
        loop=asyncio.new_event_loop()
        try:
            original=loop.run_until_complete(w.async_case(site['code'],'TASK_CANCEL'))
            self.assertFalse(original['contract_pass'])
            self.assertFalse(original['different_task_reacquired'])
            value=w.observe(plan(site,{'a.py':ASYNC}),loop=loop)
            self.assertTrue(value['repair_pass'])
            self.assertTrue(all(x['different_task_reacquired'] for x in value['reinjection']))
        finally:loop.close()

    def test_wrong_repair_stays_failed(self):
        site=r.inventory({'a.py':ASYNC})['accepted'][0]
        loop=asyncio.new_event_loop()
        try:
            value=w.observe(plan(site,{'a.py':ASYNC},code=site['code']),loop=loop)
            self.assertEqual(value['status'],'REPAIR_FAILED')
        finally:loop.close()

    def test_three_families_share_discovery_and_patch_protocol(self):
        sources={'a.py':ATOMIC,'b.py':ASYNC,'c.py':CLOCK}
        found=r.inventory(sources)
        self.assertEqual({x['family'] for x in found['accepted']},{'atomic_file','async_resource','elapsed_ttl'})
        for site in found['accepted']:
            revised=r.apply_candidate(sources,site,r.candidate(site))
            self.assertEqual(next(s for s in r.inventory(revised)['accepted'] if s['id']==site['id'])['code'],r.candidate(site))

    def test_generic_result_key_changes_on_dependencies_and_contract(self):
        sources={'a.py':ASYNC};site=r.inventory(sources)['accepted'][0]
        args=(site,sources,r.bind_contract(site,contracts()),r.propose(site,[]),{'worker':'hash'},{'runtime':'hash'})
        self.assertNotEqual(r.dependency_key(*args,dependency='old'),r.dependency_key(*args,dependency='new'))
        changed=list(args);changed[2]=dict(changed[2],new_condition=True)
        self.assertNotEqual(r.dependency_key(*args),r.dependency_key(*changed))

    def test_two_repairs_in_one_file_are_composed_and_both_release_resources(self):
        sources={'combined.py':ASYNC+'\n'+ASYNC.replace('use_resource','run_operation')}
        sites=r.inventory(sources)['accepted']
        rows=[dict(site_id=s['id'],observed=dict(repair_pass=True,candidate_code=r.candidate(s))) for s in sites]
        files=r.compose_patches(sources,rows)
        revised=r.inventory(files)['accepted']
        self.assertEqual(len(revised),2)
        loop=asyncio.new_event_loop()
        try:
            for s in revised:self.assertTrue(loop.run_until_complete(w.async_case(s['code'],'EXCEPTION'))['contract_pass'])
        finally:loop.close()
        conflict=deepcopy(rows[0]);conflict['observed']['candidate_code']=sites[0]['code']
        with self.assertRaisesRegex(ValueError,'CONFLICTING_REPAIRS'):r.compose_patches(sources,rows+[conflict])


class NativeAndReuseTests(unittest.TestCase):
    @unittest.skip('Archived native scenario; an authorized retained-scope harness is required')
    def test_native_two_families_and_verified_reuse_without_rerun(self):
        base=state_root()
        with tempfile.TemporaryDirectory(prefix='reuse-test-',dir=base) as directory:
            output=Path(directory)/'run'
            sources={'src/one.py':ATOMIC,'package/two.py':ASYNC}
            result=runner.run(sources,contracts(),[],output)
            self.assertEqual(result['native_campaigns'],4)
            self.assertEqual(result['repaired_arms'],4)
            self.assertEqual(result['source_faults'],result['no_source_faults'])
            runner.verify(output)
            audit=subprocess.run([sys.executable,'-B',str(ROOT/'reqlox_core/audit_reliability_reuse.py'),'--output',str(output)],
                                 capture_output=True,text=True,timeout=5)
            self.assertEqual(audit.returncode,0,audit.stderr)
            self.assertTrue(json.loads(audit.stdout)['historical_method_used'])
            with patch.object(runner,'execute',side_effect=AssertionError('Unexpected replay')):
                reused=runner.run(sources,contracts(),[],Path(directory)/'cached',cache=output)
            self.assertEqual(reused['new_native_campaigns'],0)
            with self.assertRaisesRegex(ValueError,'CACHE_INPUT_CHANGED'):
                runner.run(dict(sources,**{'src/unrelated.py':'value=1\n'}),contracts(),[],Path(directory)/'changed',cache=output)
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_OUTPUT'):
                runner.run(sources,contracts(),[],output)
            observed=next(output.glob('*-source/observed.json'))
            observed.write_text('{}')
            with self.assertRaisesRegex(ValueError,'OBSERVATION_DRIFT'):runner.verify(output)

    def test_missing_contract_is_reported_in_full_denominator(self):
        base=state_root()
        with tempfile.TemporaryDirectory(prefix='reuse-held-',dir=base) as directory:
            with patch.object(runner, 'execute', side_effect=AssertionError('NATIVE_DISPATCH_FORBIDDEN')) as execute:
                result=runner.run({'a.py':ASYNC},{},[],Path(directory)/'run')
            execute.assert_not_called()
            self.assertEqual(result['accepted_sites'],1)
            self.assertEqual(result['executed_sites'],0)
            self.assertEqual(result['held_sites'],1)
            self.assertEqual(result['native_campaigns'],0)


if __name__=='__main__':unittest.main()


class NativeSelectionBoundaryTests(unittest.TestCase):
    def test_archived_native_case_never_dispatches_from_unit_suite(self):
        case = NativeAndReuseTests('test_native_two_families_and_verified_reuse_without_rerun')
        result = unittest.TestResult()
        with patch.object(runner, 'execute', side_effect=AssertionError('NATIVE_DISPATCH_FORBIDDEN')) as execute:
            case.run(result)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        execute.assert_not_called()
