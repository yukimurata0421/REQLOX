from reqlox import _runtime
_runtime()
from reqlox_paths import state_root
"""\u81ea\u7136\u6587\u6295\u5f71、Source\u60c5\u5831\u306e\u9694\u96e2、\u72ec\u7acb\u3057\u305f\u4ed5\u69d8\u30fb\u6240\u6709policy\u306e\u5883\u754c。"""
from copy import deepcopy
import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'reqlox_core'),str(ROOT/'tests')]
import reliability_source_conditions as natural
import reliability_specifications as specs
import reliability_reuse as reuse
import run_reliability_reuse as runner
import run_reliability_improvement_loop as loop
from test_reliability_condition_programs import SPLIT_GUARDS
from test_reliability_context_lifecycle import contracts

TEXT='An OSError was raised after the first file close call.'
SPEC='\u5931\u6557\u6642\u306b\u306f\u65e2\u5b58\u306e\u4fdd\u5b58\u5148\u3092\u5909\u66f4\u3057\u306a\u3044。\u4f8b\u5916\u306f\u547c\u51fa\u3057\u5143\u3078\u4f1d\u64ad\u3059\u308b。\u6240\u6709\u3059\u308b\u4e00\u6642\u30d5\u30a1\u30a4\u30eb\u3060\u3051\u3092\u524a\u9664\u3059\u308b。'
SOURCES={'storage.py':SPLIT_GUARDS}
POLICY={'atomic_context':dict(basis='\u6240\u6709\u3059\u308b\u6709\u9650bytes\u4fdd\u5b58\u306e\u5931\u6557\u56de\u53ce\u5951\u7d04',scope='\u9694\u96e2\u3055\u308c\u305f\u65b0\u898ffile\u3068\u65e2\u5b58\u4fdd\u5b58\u5148\u306e\u307f')}


def hypotheses(configuration):
    return [reuse.hypothesis(h,configuration['source_texts']) for h in configuration['hypotheses']]


class NaturalConditionTests(unittest.TestCase):
    def test_source_only_projection_is_repeatable_and_offset_preserving(self):
        text='\u524d\u7f6e\u304d🙂\n\n'+TEXT
        p=natural.project('report',text);row=p['candidates'][0]
        self.assertEqual((row['operation'],row['phase'],row['occurrence']),('STREAM_CLOSE','AFTER',1))
        self.assertEqual(text[row['span']['start']:row['span']['end']],TEXT)
        self.assertEqual(natural.checked(p,text),p)
        self.assertFalse(row['semantic_support_certified']);self.assertFalse(row['execution_authority'])

    def test_reference_without_failure_is_not_a_condition(self):
        self.assertEqual(natural.project('reference','Flush and close this stream.')['candidate_count'],0)

    def test_phase_is_not_inferred_from_an_unrelated_after(self):
        p=natural.project('report','After restarting, an OSError occurred during file.close().')
        self.assertEqual(p['candidates'][0]['reason'],'UNRESOLVED_LIFECYCLE_PHASE')

    def test_socket_close_cannot_become_file_condition(self):
        p=natural.project('report','An error occurred after the first socket.close() call.')
        self.assertEqual(p['candidates'][0]['status'],'HELD')
        self.assertEqual(p['candidates'][0]['reason'],'UNRESOLVED_RESOURCE_KIND')

    def test_negations_are_retained_as_held(self):
        for text in ('os.replace() did not fail.','os.replace() completed without error.','file.close()\u306e\u5f8c\u306b\u30a8\u30e9\u30fc\u306f\u306a\u3044。'):
            with self.subTest(text=text):
                row=natural.project('report',text)['candidates'][0]
                self.assertEqual(row['reason'],'NEGATED_OR_MIXED_FAILURE_CLAIM')

    def test_mixed_operation_paragraph_is_not_disambiguated_by_target(self):
        row=natural.project('report','file.flush() and file.close() failed with OSError.')['candidates'][0]
        self.assertEqual(row['reason'],'AMBIGUOUS_OPERATION')

    def test_during_close_and_unknown_occurrence_are_held(self):
        for text in ('The file.close() call raised OSError.','Error after the 4th file close call.',
                     'Error before the first file close call.','Error after the second file close call and third close call.'):
            self.assertEqual(natural.project('report',text)['candidates'][0]['status'],'HELD')

    def test_explicit_second_occurrence_and_japanese_phase(self):
        row=natural.project('report','An error occurred after the second file close call.')['candidates'][0]
        self.assertEqual((row['occurrence'],row['occurrence_basis']),(2,'EXPLICIT_SOURCE_ORDINAL'))
        row=natural.project('report','\u30d5\u30a1\u30a4\u30eb\u306eclose()\u5b8c\u4e86\u5f8c\u306b\u4f8b\u5916\u304c\u767a\u751f\u3057\u305f。')['candidates'][0]
        self.assertEqual((row['status'],row['phase']),('CANDIDATE','AFTER'))

    def test_unrelated_paragraph_error_does_not_bind_operation(self):
        p=natural.project('report','file.close() completed.\n\nA network error occurred.')
        self.assertEqual(p['candidates'][0]['reason'],'UNSUPPORTED_OPERATION')

    def test_capacity_preserves_all_candidate_blocks(self):
        p=natural.project('report','\n\n'.join(['os.replace() failed.']*130))
        self.assertEqual((p['candidate_count'],len(p['candidates']),p['overflow_count']),(130,128,2))
        value=natural.prepare(SOURCES,contracts(),{'report':'\n\n'.join(['os.replace() failed.']*130)})
        self.assertEqual(value['selection']['held'][0]['count'],2)

    def test_source_and_program_drift_are_detected(self):
        p=natural.project('report',TEXT)
        with self.assertRaisesRegex(ValueError,'PROJECTION_DRIFT'):natural.checked(p,TEXT+' drift')
        value=natural.prepare(SOURCES,contracts(),{'report':TEXT})
        changed=deepcopy(value);changed['hypotheses'][0]['faults']=['WRITE']
        with self.assertRaisesRegex(ValueError,'CONFIGURATION_DRIFT'):
            natural.verify_prepared(reuse.c.seal(changed),SOURCES)

    def test_source_fault_catalog_candidate_and_no_binding_hold(self):
        value=natural.prepare(SOURCES,contracts(),{'report':'os.replace() raises OSError; the temporary file remains.'})
        self.assertEqual(value['hypotheses'][0]['faults'],['REPLACE'])
        value=natural.prepare({'module.py':'value=1\n'},contracts(),{'report':TEXT})
        self.assertEqual(value['selection']['held'][0]['reason'],'NO_SUPPORTED_TARGET_BINDING')

    def test_same_compiler_budget_with_different_information_access(self):
        configuration=natural.prepare(SOURCES,contracts(),{'report':TEXT});hs=hypotheses(configuration)
        site=reuse.inventory(SOURCES)['accepted'][0];contract=reuse.bind_contract(site,contracts())
        left=runner.build_plan(site,contract,None,SOURCES,hs,'SOURCE',3,None,'ISOLATED_SOURCE_KNOWLEDGE')
        right=runner.build_plan(site,contract,None,SOURCES,hs,'NO_SOURCE',3,None,'ISOLATED_SOURCE_KNOWLEDGE')
        self.assertEqual(left['site'],right['site']);self.assertEqual(left['contract'],right['contract'])
        self.assertEqual(len(left['proposal']['faults']),len(right['proposal']['faults']))
        self.assertTrue(all(p['source_id']=='owned-model-qualification-grid-v1' for p in right['proposal']['condition_programs'].values()))
        self.assertNotIn(hs[0]['faults'][0],reuse.c.canonical(right).decode())
        self.assertEqual(right['proposal']['hypotheses'],[])
        self.assertEqual(right,runner.build_plan(site,contract,None,SOURCES,[],'NO_SOURCE',3,None,'ISOLATED_SOURCE_KNOWLEDGE'))
        expanded=runner.build_plan(site,contract,None,SOURCES,[],'NO_SOURCE',6,None,'ISOLATED_SOURCE_KNOWLEDGE')
        self.assertEqual(len(expanded['proposal']['faults']),6)
        self.assertEqual(expanded['proposal']['generic_program_pool_source_input_independent'],True)
        self.assertEqual(right,runner.build_plan(site,contract,None,SOURCES,hs,'NO_SOURCE',3,None))

    def test_discovery_policy_changes_study_and_cache_identity(self):
        base=dict(sources={},contracts={},hypotheses=[],source_texts={},incident_sets=[],method={},runtime={},
                  dependency_sha256=None,maximum_probes=3,supplied_candidates={},evaluation_kind='CONTROL')
        self.assertNotEqual(runner.study_identity(dict(base,discovery_policy='LEGACY_SHARED_POOL')),
                            runner.study_identity(dict(base,discovery_policy='ISOLATED_SOURCE_KNOWLEDGE')))

    def test_specification_candidate_requires_owner_and_three_predicates(self):
        value=specs.prepare(SOURCES,{'target-spec':SPEC})
        self.assertEqual(value['candidates'][0]['reasons'],['OWNER_POLICY_REQUIRED']);self.assertFalse(value['contracts'])
        value=specs.prepare(SOURCES,{'target-spec':'The destination remains unchanged.'},POLICY)
        self.assertFalse(value['contracts']);self.assertEqual(len(value['candidates'][0]['missing_predicates']),2)

    def test_specification_catalog_ids_and_owner_policy_are_separate(self):
        value=specs.prepare(SOURCES,{'target-spec':SPEC},POLICY)
        self.assertEqual(value['contracts']['atomic_context']['id'],reuse.CONTRACTS['atomic_context'])
        self.assertEqual(value['contracts']['atomic_context']['scope'],POLICY['atomic_context']['scope'])
        self.assertFalse(value['ownership_derived_from_source']);self.assertFalse(value['specification_semantics_certified'])
        self.assertEqual(specs.verify(value,SOURCES),value)
        value['evidence']['destination_preserved']=[]
        with self.assertRaisesRegex(ValueError,'CANDIDATE_DRIFT'):specs.verify(reuse.c.seal(value),SOURCES)

    def test_negated_or_hypothetical_specification_is_held(self):
        for text in ('The write does not '+SPEC,'The write should preserve the existing destination, propagate the original exception, and remove only the temporary path owned by that call.'):
            value=specs.prepare(SOURCES,{'target-spec':text},POLICY)
            self.assertFalse(value['contracts']);self.assertTrue(value['held'])
        value=specs.prepare(SOURCES,{'target-spec':SPEC+'\n\nThe write does not remove only the temporary path owned by that call.'},POLICY)
        self.assertFalse(value['contracts']);self.assertIn('SPECIFICATION_CONFLICT_OR_AMBIGUITY',value['candidates'][0]['reasons'])
        value=specs.prepare(SOURCES,{'target-spec':SPEC+'\n\n\u6240\u6709\u3059\u308b\u4e00\u6642\u30d5\u30a1\u30a4\u30eb\u306f\u524a\u9664\u3055\u308c\u307e\u305b\u3093。'},POLICY)
        self.assertFalse(value['contracts'])

    def test_natural_source_and_specification_cli_share_no_caller_adapter(self):
        quarantine=state_root()
        with tempfile.TemporaryDirectory(prefix='natural-cli-',dir=quarantine) as directory:
            directory=Path(directory);root=directory/'repository';root.mkdir();(root/'storage.py').write_text(SPLIT_GUARDS)
            for command in (['git','init','--quiet',str(root)],['git','-C',str(root),'add','--','storage.py']):
                subprocess.run(command,check=True,capture_output=True,timeout=5)
            source=directory/'source.json';specification=directory/'spec.json';output=directory/'configuration.json'
            source.write_text(json.dumps(dict(source_texts={'report':TEXT})))
            specification.write_text(json.dumps(dict(specification_texts={'target-spec':SPEC},owner_policies=POLICY)))
            result=subprocess.run([sys.executable,'-B',str(ROOT/'reqlox_core/prepare_reliability_reuse.py'),
                '--root',str(root),'--natural-source-input',str(source),'--specification-input',str(specification),
                '--output',str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            value=runner.read(output);natural.verify_prepared(value,SOURCES)
            self.assertEqual(value['discovery_policy'],'ISOLATED_SOURCE_KNOWLEDGE')
            source.write_text(json.dumps(dict(source_texts={'report':SPEC+'\n\n'+TEXT})))
            result=subprocess.run([sys.executable,'-B',str(ROOT/'reqlox_core/prepare_reliability_reuse.py'),
                '--root',str(root),'--natural-source-input',str(source),'--specification-input',str(specification),
                '--output',str(directory/'collision.json')],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertIn('SOURCE_SPECIFICATION_ROLE_COLLISION',result.stderr)
            self.assertFalse((directory/'collision.json').exists())

    def test_multiple_statement_helper_is_bound_without_target_specific_adapter(self):
        source=SPLIT_GUARDS.replace('            output.flush()\n            os.fsync(output.fileno())','            sync_output(output)')
        source+='\ndef sync_output(output):\n    """Flush user buffers and sync file data."""\n    output.flush()\n    os.fsync(output.fileno())\n'
        site=next(s for s in reuse.inventory({'storage.py':source})['accepted'] if s['symbol']=='store')
        revised=reuse.apply_candidate({'storage.py':source},site,reuse.candidate(site))
        self.assertIn('def sync_output(output):',revised['storage.py'])
        self.assertTrue(reuse.inventory(revised)['accepted'][0]['binding']['protected'])

    def test_multiple_helper_return_and_unknown_effect_are_held(self):
        for body in ('output.flush()\n    return os.fsync(output.fileno())','output.flush()\n    os.system("true")'):
            source=SPLIT_GUARDS.replace('            output.flush()\n            os.fsync(output.fileno())','            sync_output(output)')
            source+='\ndef sync_output(output):\n    '+body+'\n'
            self.assertFalse(reuse.inventory({'storage.py':source})['accepted'])




if __name__=='__main__':unittest.main()
