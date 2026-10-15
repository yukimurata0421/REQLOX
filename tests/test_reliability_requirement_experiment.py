"Finite reliability controls and verification."
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'reqlox_core'),str(ROOT/'tests')]
import reliability_requirement_experiment as requirements
import reliability_specifications as specs
import reliability_reuse as reuse
import run_reliability_reuse as runner
import run_reliability_paired as paired
from test_reliability_natural_conditions import SOURCES, POLICY, SPEC, TEXT


class RequirementExperimentTests(unittest.TestCase):
    def test_unknown_spec_can_prepare_owned_requirement_without_natural_bug_claim(self):
        result=requirements.prepare(SOURCES,{'metadata':'An atomic writer.'},POLICY)
        self.assertTrue(result['contracts']);self.assertEqual(result['sites'][0]['status'],'PREPARED')
        self.assertTrue(all(row['status']=='UNKNOWN' for row in result['property_evidence'].values()))
        for field in ('execution_authority','target_bug_claim_eligible','specification_semantics_certified',
                      'independent_generalization_certified','ownership_derived_from_source'):
            self.assertFalse(result[field])
        self.assertFalse(specs.prepare(SOURCES,{'metadata':'An atomic writer.'},POLICY)['contracts'])

    def test_missing_owner_requirement_is_held_despite_complete_spec(self):
        result=requirements.prepare(SOURCES,{'spec':SPEC},{})
        self.assertEqual(result['sites'][0]['reasons'],['OWNER_REQUIREMENT_REQUIRED'])
        self.assertFalse(result['contracts'])

    def test_absent_spec_is_unknown_and_still_requires_owner(self):
        self.assertTrue(requirements.prepare(SOURCES,{},POLICY)['contracts'])
        self.assertFalse(requirements.prepare(SOURCES,{}, {})['contracts'])

    def test_conflicting_property_is_ambiguous_without_blocking_requirement_research(self):
        text=SPEC+'\n\nThe write does not remove only the temporary file owned by this call.'
        result=requirements.prepare(SOURCES,{'spec':text},POLICY)
        self.assertEqual(result['property_evidence']['owned_temporary_removed']['status'],'AMBIGUOUS')
        self.assertEqual(result['property_evidence']['exception_propagated']['status'],'LEXICAL_EVIDENCE')
        self.assertTrue(result['contracts']);self.assertFalse(result['target_bug_claim_eligible'])

    def test_snapshot_and_property_tampering_is_rejected(self):
        result=requirements.prepare(SOURCES,{},POLICY)
        changed=deepcopy(result);changed['property_evidence']['exception_propagated']['status']='LEXICAL_EVIDENCE'
        with self.assertRaisesRegex(ValueError,'EXPERIMENT_DRIFT'):requirements.verify(reuse.c.seal(changed),SOURCES)
        with self.assertRaisesRegex(ValueError,'EXPERIMENT_DRIFT'):requirements.verify(result,dict(SOURCES,**{'other.py':'x=1\n'}))

    def test_source_is_not_a_substitute_for_target_specification(self):
        with self.assertRaisesRegex(ValueError,'ROLE_COLLISION'):specs.check_roles({'spec':SPEC},{'report':SPEC+'\n'+TEXT})

    def test_unknown_dynamic_binding_is_not_prepared_by_owner_policy(self):
        result=requirements.prepare({'dynamic.py':'def writer(path):\n    return __import__(path)\n'}, {}, POLICY)
        self.assertEqual(result['sites'],[]);self.assertFalse(result['contracts'])

    def test_owner_catalog_and_bounds_are_enforced(self):
        for policy in ({'atomic_context':dict(basis='',scope='sandbox')},
                       {'atomic_context':dict(basis='owner',scope='sandbox',id='custom')},
                       {'other':dict(basis='owner',scope='sandbox')}):
            with self.subTest(policy=policy),self.assertRaises(ValueError):requirements.prepare(SOURCES,{},policy)

    def test_arm_selection_changes_identity_and_entry_denominator(self):
        site=reuse.inventory(SOURCES)['accepted'][0]
        eligible=[(site,None,None)]
        self.assertEqual(len(runner.entries_for(eligible)),2)
        self.assertEqual([e['arm'] for e in runner.entries_for(eligible,['NO_SOURCE'])],['NO_SOURCE'])
        base=dict(sources={},contracts={},hypotheses=[],source_texts={},incident_sets=[],method={},runtime={},
                  dependency_sha256=None,maximum_probes=3,supplied_candidates={},evaluation_kind='CONTROL')
        self.assertNotEqual(runner.study_identity(base),runner.study_identity(dict(base,enabled_arms=['SOURCE'])))
        for arms in ([],['SOURCE','SOURCE'],['unknown'], 'SOURCE'):
            with self.subTest(arms=arms),self.assertRaises(ValueError):runner.checked_arms(arms)

    def test_novelty_uses_geometry_instead_of_document_identifier(self):
        hs,_=paired.hypotheses_for(SOURCES,requirements.prepare(SOURCES,{},POLICY)['contracts'],{'report':TEXT})
        result=paired.novelty(SOURCES,hs)
        self.assertEqual(result[0]['source_lifecycle_conditions'],1)
        self.assertEqual(result[0]['conditions_already_in_owned_grid'],1)
        self.assertEqual(result[0]['conditions_outside_owned_grid'],0)
        hs,_=paired.hypotheses_for(SOURCES,requirements.prepare(SOURCES,{},POLICY)['contracts'],
                                 {'another-report':'An error occurred after the second file close call.'})
        self.assertEqual(paired.novelty(SOURCES,hs)[0]['conditions_outside_owned_grid'],1)


if __name__=='__main__':unittest.main()
