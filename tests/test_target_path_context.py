"""Documented context dispatch and inherited authorization, without Target execution."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reqlox
reqlox._runtime()
from reqlox import targets, target_context, target_prepare, target_audit, target_authorization
from reqlox_core import reliability_path_context as context
from reqlox_core import run_reliability_path_context as native
from reqlox_core import run_reliability_reuse as storage

SOURCES = {'pkg/__init__.py': 'from .resource import Resource\n', 'pkg/resource.py': '''from pathlib import Path
from tempfile import gettempdir
class Resource:
    def __enter__(self):
        self.path = Path(gettempdir()) / 'owned-resource'
        self.path.touch()
        return self.path
    def __exit__(self, kind, value, traceback):
        self.path.unlink()
'''}
README = '''The file is removed when you leave the `with` context.
```python
from pkg import Resource
with Resource() as path:
    path.write_text('data')
```
'''


def configuration():
    documents = {'README.md': README}
    quote = README.splitlines()[0]
    return dict(contracts={}, path_context=dict(profile=target_context.PROFILE, documents=documents,
        recipe=context.recipes(SOURCES, documents)['rows'][0],
        contract=dict(id=target_context.CONTRACT, scope='DOCUMENTED_WITH_EXIT_ONLY',
            evidence=dict(document='README.md', span=dict(start=0, end=len(quote), sha256=hashlib.sha256(quote.encode()).hexdigest())))))


def observation(plan, parent, *, label='PASS'):
    rows = []
    for case in range(2):
        for fault in context.FAULTS:
            rows.append(dict(other_file_case=case, fault=fault, contract_pass=True, repeat_pass=True,
                entry_acquired=True, resource_witness=True, prior_owned_fds=[], remaining_owned_fds=[],
                other_file_preserved=True, owned_path_resource_released=True, body_failure_propagated=fault != 'NONE',
                context_instance_module='pkg.resource', unexpected_error=None,
                repeat_remaining_owned_fds=[], repeat_other_file_preserved=True, repeat_owned_path_resource_released=True))
    if label == 'FAIL':
        rows = rows[:1]; rows[-1].update(contract_pass=False, repeat_pass=False, owned_path_resource_released=False)
    return context.c.seal(dict(kind='FINITE_PATH_CONTEXT_OBSERVATION_V1', plan_sha256=context.c.digest(plan),
        method=plan['method'], source_snapshot_sha256=context.c.digest(plan['sources']), raw_source_bundle_verified=True,
        namespaces={k:v+'-owned-test' for k,v in parent.items()}, external_action_attempts=[],
        original_implementation_mutated=False, public_module=plan['recipe']['binding']['module'],
        public_symbol=plan['recipe']['binding']['symbol'], callable_source_member='pkg/resource.py',
        callable_module='pkg.resource', callable_kind='CLASS', label=label, label_authority='NATIVE_FINITE_REQUIREMENT_ORACLE',
        rows=rows, native_import_capability=plan['native_import_capability'],
        pinned_standard_import_capabilities=plan['pinned_standard_import_capabilities'],
        execution_boundary=dict(uid=1000, effective_capabilities=0, home_visible=False, cpu_seconds=[2,2],
            memory_bytes=[134217728,134217728], file_bytes=[131072,131072], core_bytes=[0,0])))


class ContextTargetTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        base = root / 'corpus/knowledge/semantic-experiments/local-private-quarantine' if (root / 'tools').is_dir() else None
        temporary = tempfile.TemporaryDirectory(prefix='target-path-context-test-', dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root / 'state'
        self.environment = patch.dict(os.environ, {'REQLOX_STATE_DIR': str(self.state)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        for name, text in SOURCES.items():
            dest = self.repo / name; dest.parent.mkdir(exist_ok=True); dest.write_text(text)
        self.configuration = self.root / 'context.json'; self.configuration.write_text(json.dumps(configuration()))
        self.manifest = self.root / 'target.json'
        targets.init(self.manifest, 'owned-context')
        targets.add(self.manifest, 'resource', self.repo, self.configuration)
        self.commands = []
        self.observation_label = 'PASS'
        # Fixtures are ordinary directories: enumerate text without spawning git.
        snapshots = patch.object(storage, 'load_snapshot', side_effect=lambda root:
            {str(p.relative_to(root)):p.read_text() for p in sorted(Path(root).rglob('*.py'))})
        snapshots.start(); self.addCleanup(snapshots.stop)

    def plan(self, **options):
        return targets.prepare(self.manifest, ['resource'], **options)

    def execute(self, prepared, name='run'):
        planned, entries, roots = prepared
        return targets.execute(planned, entries, roots, self.state, name=name)

    def process(self, command, *, stdout, stderr, start_new_session):
        self.commands.append(command)
        self.assertTrue(start_new_session)
        self.assertEqual(command[:7], ['/usr/bin/prlimit','--cpu=2:2','--as=134217728:134217728',
                                      '--fsize=131072:131072','--core=0:0','--','/usr/bin/bwrap'])
        self.assertIn('--unshare-all', command); self.assertIn('--clearenv', command)
        child = Path(stdout.name).parent
        plan = json.loads((child / 'plan.json').read_text())
        launch = json.loads((child / 'launch.json').read_text())
        raw = observation(plan, launch['parent_namespaces'], label=self.observation_label)
        stdout.write(json.dumps(raw).encode()); stdout.flush()
        class Process:
            def wait(self, timeout=None):
                assert timeout == 5 or timeout is None
                return 0
            def poll(self): return 0
        return Process()

    def grant(self, status='APPROVAL_REQUIRED', deadline=None):
        self.ledger = self.root / 'prior-ledger.json'; self.summary = self.root / 'prior-summary.json'
        self.ledger.write_text(json.dumps(dict(status='TERMINAL', automatic_retry=False, native_attempts=8,
            maximum_native_campaigns=12, maximum_seconds=120, elapsed_seconds=5.89)))
        self.summary.write_text(json.dumps(dict(native_campaigns=8, maximum_native_campaigns=12,
            maximum_experiment_seconds=120, experiment_elapsed_seconds=6.02)))
        planned = self.plan(seconds=30)[0]['plan']
        method = dict(planned['method'], authorization=hashlib.sha256(Path(target_authorization.__file__).read_bytes()).hexdigest())
        def ref(path): return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        value = dict(schema='reqlox.authorization-continuation.v1', status=status,
            authority='CURRENT_USER_EXPLICIT_BOUNDED_CONTINUATION', prior_ledger=ref(self.ledger),
            prior_execution_summary=ref(self.summary), prior_native_attempts=8, prior_charged_seconds=7,
            maximum_native_campaigns=12, maximum_seconds=120, maximum_new_native_campaigns=2,
            maximum_window_seconds=30, deadline=deadline,
            reservation_directory=str(self.root / 'authorization-reservations'),
            bindings=[{k:row[k] for k in ('name','sources_sha256','configuration_sha256','execution_method')}
                      for row in planned['repositories']], method_sha256=targets.digest(method), single_run=True, automatic_retry=False)
        self.authorization = self.root / 'authorization.json'; self.authorization.write_text(json.dumps(value))
        return self.authorization

    def test_explicit_profile_plans_one_context_and_retains_atomic_holds_without_import(self):
        original_import = context.importlib.import_module
        def standard_only(name, *args, **kwargs):
            if name == 'pkg' or name.startswith('pkg.'):
                raise AssertionError('TARGET_IMPORT')
            return original_import(name, *args, **kwargs)
        with patch.object(context.importlib, 'import_module', side_effect=standard_only):
            plan = self.plan()[0]['plan']
        row = plan['repositories'][0]
        self.assertEqual((row['accepted_sites'],row['executable_sites'],row['held_sites']),(1,1,0))
        self.assertTrue(row['atomic_held_bindings'])
        self.assertEqual(row['execution_method'], target_context.PROFILE)
        self.assertFalse(self.state.exists())

    def test_negated_missing_or_tampered_release_evidence_is_rejected(self):
        for quote in ('The file is not removed when you leave the context.', 'Retry EIO once.', 'Caller handles cleanup.'):
            value = configuration(); value['path_context']['documents']['README.md'] = quote+'\n'+README
            span = value['path_context']['contract']['evidence']['span'];span.update(end=len(quote),sha256=hashlib.sha256(quote.encode()).hexdigest())
            with self.subTest(quote=quote), self.assertRaises(ValueError): targets.validate_configuration(value)
        value = configuration();value['path_context']['contract']['evidence']['span']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'RELEASE_SPAN'):targets.validate_configuration(value)

    def test_new_fault_policy_and_mixed_source_requirements_are_rejected(self):
        value = configuration();value['path_context']['contract']['faults']=['EIO']
        with self.assertRaisesRegex(ValueError,'TARGET_CONTEXT_CONTRACT'):targets.validate_configuration(value)
        for key in ('source_texts','hypotheses','specification_texts'):
            value = configuration();value[key]={'source':'fsync'} if key!='hypotheses' else [{}]
            with self.assertRaisesRegex(ValueError,'MIXED_REQUIREMENTS'):targets.validate_configuration(value)
        with self.assertRaisesRegex(ValueError,'PAIRED_OR_DEPENDENCY'):self.plan(paired=True)

    def test_preparation_preserves_documents_and_rejects_source_reclassification(self):
        self.state.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError,'SOURCE_MODE_UNSUPPORTED'):
            target_prepare.save_bundle(self.manifest,['resource'],self.state/'bad',natural_source={'source_texts':{}})
        result = target_prepare.save_bundle(self.manifest,['resource'],self.state/'prepared')
        saved = targets.read_json(Path(result['target']).parent/'resource.configuration.json')
        self.assertEqual(saved,configuration())

    def test_mocked_native_dispatch_has_initial_and_fresh_confirmation_and_read_only_audit(self):
        prepared = self.plan()
        with patch.object(native.subprocess,'Popen',side_effect=self.process):result=self.execute(prepared)
        self.assertEqual((result['status'],result['native_attempts']),('COMPLETE',2))
        output=Path(result['output']); before=target_audit.files(output)
        with patch.object(native.subprocess,'Popen',side_effect=AssertionError('ARCHIVED_CODE_EXECUTION')):
            audited=target_audit.audit(output)
        self.assertEqual(audited['status'],'VERIFIED');self.assertEqual(target_audit.files(output),before)
        child=json.loads((output/'repositories/resource/result.json').read_text())
        self.assertFalse(child['repair_attempted']);self.assertEqual(child['adopted_files'],{})

    def test_failed_dispatch_consumes_one_reservation_and_never_retries(self):
        prepared=self.plan()
        with patch.object(native.subprocess,'Popen',side_effect=OSError('mocked owned launch failure')) as launch:
            result=self.execute(prepared)
        self.assertEqual((result['status'],result['native_attempts'],launch.call_count),('STOPPED',1,1))
        self.assertFalse(target_audit.audit(result['output'])['child_semantics_verified'])

    def test_counterexample_is_preserved_without_inventing_a_retry_repair(self):
        self.observation_label = 'FAIL'
        with patch.object(native.subprocess,'Popen',side_effect=self.process):result=self.execute(self.plan())
        self.assertEqual((result['status'],result['native_attempts']),('PARTIAL',1))
        self.assertEqual(target_audit.audit(result['output'])['status'],'VERIFIED')
        saved=json.loads((Path(result['output'])/'repositories/resource/result.json').read_text())
        self.assertEqual(saved['status'],'COUNTEREXAMPLE_NO_SUPPORTED_REPAIR')
        self.assertFalse(saved['repair_attempted'])

    def test_source_drift_stops_before_native_reservation(self):
        prepared=self.plan();(self.repo/'pkg/resource.py').write_text('changed = True\n')
        with patch.object(native.subprocess,'Popen') as launch:result=self.execute(prepared)
        launch.assert_not_called();self.assertEqual(result['native_attempts'],0)

    def test_pending_or_expired_approval_cannot_create_run_state(self):
        for status,deadline in [('APPROVAL_REQUIRED',None),('APPROVED','2000-01-01T00:00:00+00:00')]:
            grant=self.grant(status,deadline);prepared=self.plan(seconds=30,authorization=grant)
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED|DEADLINE_EXPIRED'):
                self.execute(prepared)
            self.assertFalse(self.state.exists());self.assertFalse((self.root/'authorization-reservations').exists())

    def test_manifest_authorization_cannot_be_omitted_or_overridden(self):
        grant=self.grant();manifest=json.loads(self.manifest.read_text());manifest['authorization']=grant.name
        self.manifest.write_text(json.dumps(manifest))
        prepared=self.plan(seconds=30)
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):self.execute(prepared)
        other=self.root/'other-authorization.json';other.write_bytes(grant.read_bytes())
        with self.assertRaisesRegex(ValueError,'MANIFEST_OVERRIDE'):self.plan(seconds=30,authorization=other)

    def test_safe_ui_summarizes_context_observations_and_preserves_other_method_holds(self):
        from reqlox_demo.target_ui import TargetLab
        with patch.object(native.subprocess,'Popen',side_effect=self.process):result=self.execute(self.plan())
        summary=TargetLab([self.manifest]).saved_result({'run_id':Path(result['output']).name})
        row=summary['repositories'][0]
        self.assertTrue(row['observations_verified']);self.assertTrue(row['atomic_held_sites'])
        self.assertEqual(row['observations']['baseline']['passed'],4)
        self.assertEqual(row['observations']['discovery']['passed'],8)
        self.assertEqual(row['observations']['confirmation']['passed'],12)
        text=json.dumps(summary)
        self.assertNotIn(str(self.root),text);self.assertNotIn('def __enter__',text);self.assertNotIn(README,text)

    def test_counter_time_and_scope_resets_are_rejected(self):
        grant=self.grant();original=json.loads(grant.read_text())
        for edit in ({'prior_native_attempts':0},{'prior_charged_seconds':0},{'maximum_native_campaigns':16},
                     {'maximum_new_native_campaigns':5},{'maximum_window_seconds':120},{'single_run':False}):
            grant.write_text(json.dumps(dict(original,**edit)))
            with self.subTest(edit=edit),self.assertRaises(ValueError):self.plan(seconds=30,authorization=grant)

    def test_approved_mocked_run_inherits_eight_and_fences_a_second_run(self):
        deadline=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=5)).isoformat()
        grant=self.grant('APPROVED',deadline);ledger_before=self.ledger.read_bytes()
        prepared=self.plan(seconds=30,authorization=grant)
        with patch.object(native.subprocess,'Popen',side_effect=self.process):result=self.execute(prepared)
        self.assertEqual((result['native_attempts'],result['prior_native_attempts'],result['new_native_attempts']),(10,8,2))
        self.assertEqual(self.ledger.read_bytes(),ledger_before)
        self.assertEqual(sorted(p.name for p in Path(result['output']).glob('native-reservation-*')),
                         ['native-reservation-009.json','native-reservation-010.json'])
        self.assertEqual(target_audit.audit(result['output'])['native_attempts'],10)
        with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):self.execute(prepared,name='another-run')

    def test_observation_boundary_and_saved_confirmation_tampering_are_rejected(self):
        prepared=self.plan()
        with patch.object(native.subprocess,'Popen',side_effect=self.process):result=self.execute(prepared)
        output=Path(result['output']);path=output/'repositories/resource/confirmation/observed.json'
        value=json.loads(path.read_text());value['execution_boundary']['home_visible']=True
        path.write_bytes(context.c.canonical(context.c.seal(value)))
        with self.assertRaisesRegex(ValueError,'FILE_DRIFT'):target_audit.audit(output)


if __name__=='__main__':unittest.main()
