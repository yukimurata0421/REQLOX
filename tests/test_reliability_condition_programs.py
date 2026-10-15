
from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from reqlox import _runtime
_runtime()
from reqlox_core.reqlox_paths import state_root
"""\u56fa\u5b9a\u6545\u969c\u540d\u306e\u5916\u306e\u4f4d\u7f6e\u30fb\u56de\u6570\u6307\u5b9a\u3092Source\u3078\u7d50\u3073\u4ed8\u3051、\u6b63\u89e3\u5224\u5b9a\u3068\u672a\u5230\u9054\u3092\u5206\u96e2\u3059\u308b。"""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

pass  # Package imports resolve from the repository root.
from reqlox_core import reliability_conditions as conditions
from reqlox_core import reliability_reuse as reuse
from reqlox_core import run_reliability_reuse as runner
from reqlox_core import prepare_reliability_reuse as prepare
from reqlox_core import run_reliability_improvement_loop as loop
from test_reliability_context_lifecycle import GENERATOR

SPLIT_GUARDS = '''from contextlib import contextmanager
import os
import tempfile

@contextmanager
def store(destination, mode='wb'):
    with tempfile.NamedTemporaryFile(mode=mode, delete=False, dir=os.path.dirname(destination)) as output:
        pending = output.name
        try:
            yield output
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            os.unlink(pending)
            raise
    try:
        os.replace(pending, destination)
    except BaseException:
        os.unlink(pending)
        raise
'''
TEXT = 'Constructed reference: flush and close are separate lifecycle operations.'


def hypothesis(occurrence=1, operation='STREAM_CLOSE', phase='AFTER'):
    sources = {'control':TEXT};span = dict(start=0,end=len(TEXT),sha256=reuse.sha(TEXT))
    program = conditions.bind(dict(kind='LIFECYCLE_CONDITION_V1',family='atomic_context',operation=operation,
        phase=phase,occurrence=occurrence,source_id='control',span=span,origin='INFERRED_FROM_REFERENCE'),sources)
    h = reuse.hypothesis(dict(family='atomic_context',conditions=['close\u5b8c\u4e86\u5f8c、\u7f6e\u63db\u524d\u306e\u4f8b\u5916'],faults=[program['condition_id']],
                             source_id='control',span=span,condition_programs=[program]),sources)
    return h,sources


@unittest.skip('Archived native tests require a separate retained-scope authorized harness')
class ConditionProgramTests(unittest.TestCase):
    def setUp(self):
        self.site = reuse.inventory({'storage.py':SPLIT_GUARDS})['accepted'][0]

    def test_split_guards_are_bound_and_outer_cleanup_is_added(self):
        self.assertEqual(self.site['binding']['lifecycle_style'],'SPLIT_GUARDS')
        fixed = reuse.candidate(self.site)
        rebound = reuse.inventory(reuse.apply_candidate({'storage.py':SPLIT_GUARDS},self.site,fixed))['accepted'][0]
        self.assertTrue(rebound['binding']['protected'])
        self.assertEqual(rebound['binding']['lifecycle_style'],'SPLIT_GUARDS')

    def test_program_is_outside_legacy_catalog_without_execution_authority(self):
        h,sources = hypothesis();program = h['condition_programs'][0]
        self.assertNotIn(program['condition_id'],reuse.OPERATIONS['atomic_context'])
        self.assertFalse(program['execution_authority']);self.assertFalse(program['semantic_support_certified'])
        self.assertEqual(reuse.hypothesis(reuse.hypothesis_input(h),sources),h)

    def test_both_arms_share_the_same_qualification_envelope_and_capability(self):
        h,_ = hypothesis();left = reuse.propose(self.site,[h],3,qualification_hypotheses=[h])
        right = reuse.propose(self.site,[],3,qualification_hypotheses=[h])
        self.assertEqual(left['qualification_faults'],right['qualification_faults'])
        self.assertEqual(left['condition_programs'],right['condition_programs'])
        self.assertEqual(len(left['faults']),len(right['faults']))
        self.assertEqual(right['faults'],list(reuse.OPERATIONS['atomic_context']))
        self.assertEqual(left['faults'][0],h['faults'][0])
        self.assertFalse(left['source_text_to_program_automatic'])

    def test_full_confirmation_contains_all_old_and_new_conditions_in_both_arms(self):
        h,_ = hypothesis()
        for hs in ([h],[]):
            proposal = reuse.propose(self.site,hs,loop.confirmation_limit([h]),qualification_hypotheses=[h])
            self.assertEqual(set(proposal['faults']),set(proposal['qualification_faults']))
            self.assertEqual(len(proposal['faults']),4)
        self.assertEqual(loop.confirmation_limit([]),3)
        self.assertEqual(loop.confirmation_limit([h]),4)

    def test_before_and_after_operation_use_actual_call_count(self):
        for phase in ('BEFORE','AFTER'):
            h,_ = hypothesis(occurrence=2,operation='STREAM_FLUSH',phase=phase)
            injector = conditions.Injector(h['condition_programs'][0]);calls = []
            self.assertEqual(injector.call('STREAM_FLUSH',lambda:calls.append(1) or 17),17)
            with self.assertRaises(OSError):injector.call('STREAM_FLUSH',lambda:calls.append(2))
            self.assertEqual(calls,[1] if phase == 'BEFORE' else [1,2])
            self.assertEqual(injector.hits,[dict(operation='STREAM_FLUSH',phase=phase,occurrence=2)])

    def test_unmatched_operation_does_not_inject_or_count(self):
        h,_ = hypothesis();injector = conditions.Injector(h['condition_programs'][0])
        self.assertEqual(injector.call('STREAM_FLUSH',lambda:19),19)
        self.assertEqual((injector.seen,injector.hits),(0,[]))

    def test_span_program_semantic_flag_and_source_drift_are_rejected(self):
        h,sources = hypothesis()
        for changed in ('source','span','flag','id'):
            p = deepcopy(h['condition_programs'][0]);texts = dict(sources)
            if changed == 'source':texts['control'] += ' drift'
            if changed == 'span':p['span']['sha256'] = '0'*64
            if changed == 'flag':p['semantic_support_certified'] = True
            if changed == 'id':p['condition_id'] = 'CONDITION_'+'0'*64
            p = reuse.c.seal({k:v for k,v in p.items() if k != 'record_sha256'})
            with self.assertRaises(ValueError):conditions.checked(p,texts)

    def test_code_like_operations_unbounded_occurrence_and_close_before_are_rejected(self):
        h,sources = hypothesis();record = {k:h['condition_programs'][0][k] for k in conditions.FIELDS}
        for values in (dict(operation='__import__("os").system'),dict(occurrence=0),dict(occurrence=4),dict(occurrence=True),dict(phase='BEFORE')):
            with self.assertRaises(ValueError):conditions.bind(dict(record,**values),sources)

    def test_program_without_matching_hypothesis_fault_is_rejected(self):
        h,sources = hypothesis();record = reuse.hypothesis_input(h);record['faults'] = ['WRITE']
        with self.assertRaises(ValueError):reuse.hypothesis(record,sources)

    def test_unbound_condition_string_is_rejected(self):
        h,sources = hypothesis();record = reuse.hypothesis_input(h);del record['condition_programs']
        with self.assertRaises(ValueError):reuse.hypothesis(record,sources)

    def test_non_generator_binding_retains_unsupported_program_as_held(self):
        h,_ = hypothesis();site = deepcopy(self.site);site['binding']['kind'] = 'CLASS_FACTORY'
        proposal = reuse.propose(site,[h],qualification_hypotheses=[h])
        self.assertEqual(proposal['held_conditions'][0]['reason'],'UNSUPPORTED_CONDITION_BINDING')
        self.assertEqual(proposal['faults'],list(reuse.OPERATIONS['atomic_context']))

    def test_legacy_plain_generator_remains_supported(self):
        self.assertEqual(reuse.inventory({'storage.py':GENERATOR})['accepted'][0]['binding']['lifecycle_style'],'PLAIN')

    def test_generator_delegating_replace_to_local_helper_is_discovered(self):
        source = SPLIT_GUARDS.replace('os.replace(pending, destination)','publish(pending, destination)')
        source += '\ndef publish(source, destination):\n    os.replace(source, destination)\n'
        inventory = reuse.inventory({'storage.py':source})
        site = next(s for s in inventory['accepted'] if s['symbol'] == 'store')
        self.assertEqual(site['family'],'atomic_context')
        revised = reuse.apply_candidate({'storage.py':source},site,reuse.candidate(site))
        self.assertIn('def publish(source, destination):',revised['storage.py'])
        self.assertTrue(next(s for s in reuse.inventory(revised)['accepted'] if s['symbol'] == 'store')['binding']['protected'])

    def test_generator_with_unresolved_replace_helper_is_held_instead_of_skipped(self):
        source = SPLIT_GUARDS.replace('os.replace(pending, destination)','missing_publish(pending, destination)')
        inventory = reuse.inventory({'storage.py':source})
        self.assertFalse(inventory['accepted'])
        self.assertIn('store',[s['symbol'] for s in inventory['held']])

    def test_common_preparation_retains_selected_and_unsupported_condition_denominators(self):
        h,sources = hypothesis();record = {k:h['condition_programs'][0][k] for k in conditions.FIELDS}
        unsupported = dict(record,operation='NETWORK_DISCONNECT')
        config = prepare.prepare_conditions({'storage.py':SPLIT_GUARDS},{},[record,unsupported],sources)
        self.assertEqual(config['selection']['candidate_count'],2)
        self.assertEqual(config['selection']['selected_count'],1)
        self.assertEqual(len(config['selection']['held']),1)
        self.assertFalse(config['selection']['source_text_to_program_automatic'])
        self.assertEqual(config['hypotheses'][0]['condition_programs'],h['condition_programs'])
        self.assertEqual(config['hypotheses'][0]['span'],h['span'])

    def test_condition_input_cli_loads_tracked_repository_and_saves_common_configuration(self):
        h,texts = hypothesis();record = {k:h['condition_programs'][0][k] for k in conditions.FIELDS}
        quarantine = runner.state_root()
        with tempfile.TemporaryDirectory(prefix='condition-cli-',dir=quarantine) as directory:
            root = Path(directory)/'repository';root.mkdir()
            (root/'storage.py').write_text(SPLIT_GUARDS)
            for command in (['git','init','--quiet',str(root)],['git','-C',str(root),'add','--','storage.py']):
                subprocess.run(command,check=True,capture_output=True,timeout=5)
            inputs = Path(directory)/'inputs.json';contracts = Path(directory)/'contracts.json';output = Path(directory)/'configuration.json'
            inputs.write_text(json.dumps(dict(records=[record,dict(record,operation='UNKNOWN')],source_texts=texts)))
            contracts.write_text(json.dumps({}))
            result = subprocess.run([sys.executable,'-B',str(runner.ROOT/'reqlox_core/prepare_reliability_reuse.py'),
                '--root',str(root),'--contracts',str(contracts),'--condition-input',str(inputs),'--output',str(output)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            value = runner.read(output);reuse.c.check_seal(value)
            self.assertEqual((value['selection']['candidate_count'],value['selection']['selected_count'],len(value['selection']['held'])),(2,1,1))
            self.assertFalse(value['selection']['source_text_to_program_automatic'])

    def test_preparation_holds_unsupported_target_binding(self):
        h,sources = hypothesis();record = {k:h['condition_programs'][0][k] for k in conditions.FIELDS}
        config = prepare.prepare_conditions({'module.py':'value=1\n'},{},[record],sources)
        self.assertEqual(config['selection']['selected_count'],0)
        self.assertEqual(config['selection']['held'][0]['reason'],'UNSUPPORTED_CONDITION_BINDING')

    def test_preparation_capacity_and_duplicate_are_explicit_holds(self):
        h,sources = hypothesis();record = {k:h['condition_programs'][0][k] for k in conditions.FIELDS}
        records = [dict(record,occurrence=i) for i in (1,2,3)]
        records.extend([dict(record,operation='STREAM_FLUSH'),record])
        config = prepare.prepare_conditions({'storage.py':SPLIT_GUARDS},{},records,sources)
        self.assertEqual((config['selection']['candidate_count'],config['selection']['selected_count']),(5,3))
        self.assertEqual([v['reason'] for v in config['selection']['held']],['CONDITION_PROGRAM_CAPACITY','DUPLICATE_CONDITION_RECORD'])

    def test_shared_runner_keeps_program_fields_when_verifying_hypotheses(self):
        h,sources = hypothesis()
        quarantine = runner.state_root()
        with tempfile.TemporaryDirectory(prefix='condition-input-',dir=quarantine) as directory:
            with patch.object(runner,'execute',side_effect=AssertionError('Unexpected native execution')):
                result = runner.run({'module.py':'value = 1\n'},{},[h],Path(directory)/'run',
                                    source_texts=sources,maximum_native_campaigns=0)
                self.assertEqual(result['native_campaigns'],0)
                study,verified = runner.verify(Path(directory)/'run')
                self.assertEqual(study['hypotheses'],[h]);self.assertEqual(verified,result)


if __name__ == '__main__':unittest.main()
