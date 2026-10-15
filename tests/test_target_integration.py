"""Offline boundary checks: synthetic observations, no Target import or launch."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from reqlox import target_integration as m
from reqlox import integration_cli


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
        self.scope = self.root / m.SCOPE; self.scope.mkdir(mode=0o700)
        self.prepared = self.scope / 'prepared'; self.prepared.mkdir(mode=0o700)
        self.run = self.prepared / 'execution'; self.run.mkdir(mode=0o700)
        self.reservations = self.scope / Path(m.FENCE).parent
        self.reservations.mkdir(mode=0o700, parents=True)
        self.bundle = dict(scope=str(self.scope), source_bindings=dict(refs={}), runtime_identity={})
        m._save(self.prepared / 'bundle.json', self.bundle)
        self.plan = dict(schema='reqlox.module-integration-plan.v1', attempt=13, variant='original',
                         sources={}, method=m.methods(), scenario=m.SCENARIO,
                         scenario_sha256=m.digest(m.SCENARIO), limits=m.LIMITS,
                         parent_namespaces={k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net')})
        self.grant = self.root / 'grant.json'
        self.current = m.now()

    def tearDown(self):
        self.tmp.cleanup()  # Only synthetic fixtures; never native evidence.

    def save_grant(self, **changes):
        value = dict(schema='reqlox.module-integration-final-grant.v1', status='APPROVED_FINAL_EXECUTION',
                     bundle_sha256=m.sha(self.prepared / 'bundle.json'), received_at_jst=self.current.isoformat(),
                     user_approval_reference='synthetic offline test approval', maximum_new_campaigns=3,
                     window_seconds=20, approval_to_finish_seconds=300)
        value.update(changes); m._save(self.grant, value)

    def guard(self):
        return m.Continuation(self.bundle, self.run, m.now() + dt.timedelta(seconds=300))

    def observation(self):
        keys = ('injection_reached', 'acquired', 'exception_preserved', 'destination_preserved',
                'lock_released', 'scratch_removed', 'owned_pending_removed', 'unrelated_preserved',
                'following_normal_pass', 'passed')
        cases = [*m.FAULTS, *['NORMAL'] * 4, 'PREEXISTING_PENDING']
        payloads = [m.SCENARIO['payloads_sha256'][0]] * 5 + m.SCENARIO['payloads_sha256'] + [m.SCENARIO['payloads_sha256'][0]]
        rows = [dict(case=case, payload_sha256=payload, **{k: True for k in keys})
                for case, payload in zip(cases, payloads)]
        for row, error in zip(rows, ['InjectedError'] * 4 + ['CancelledError'] + [None] * 4 + ['FileExistsError']):
            row.update(exception_type=error, following_normal_error=None)
        return dict(schema='reqlox.module-integration-observation.v1', plan_sha256=m.digest(self.plan),
                    scenario_sha256=m.digest(m.SCENARIO), sources={}, method=self.plan['method'],
                    module_imported=True, external_action_attempts=[], held_atomic_bindings=4,
                    temppath_repair_performed=False,
                    origins=dict(api='/target/api/storage.py', worker='/target/worker/resource.py',
                                 temppath='/target/temppath/temppath/temppath.py'),
                    execution_boundary=dict(uid=1000, effective_capabilities=0, home_visible=False,
                                            cpu=[2, 2], memory=[134217728] * 2, output=[131072] * 2, core=[0, 0]),
                    namespaces={k: 'child' for k in ('user', 'mnt', 'pid', 'net')},
                    rows=rows)

    def validate(self, observed):
        return m.validate_observation(observed, self.plan, self.plan['parent_namespaces'])

    def test_final_approval_pending_denies_before_process_or_workspace(self):
        self.save_grant(status='PENDING_FINAL_APPROVAL', received_at_jst=None)
        with patch.object(m.subprocess, 'Popen') as popen, patch.object(m, 'retained_workspace') as workspace:
            with self.assertRaisesRegex(ValueError, 'FINAL_APPROVAL_REQUIRED'):
                m.execute(self.prepared, self.grant)
        popen.assert_not_called(); workspace.assert_not_called()

    def test_expired_grant(self):
        self.save_grant(received_at_jst=(self.current - dt.timedelta(seconds=292)).isoformat())
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            m.check_grant(self.prepared, self.grant, self.current)

    def test_future_approval_denied(self):
        self.save_grant(received_at_jst=(self.current + dt.timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(ValueError, 'EXPIRED'):
            m.check_grant(self.prepared, self.grant, self.current)

    def test_grant_cannot_raise_campaigns(self):
        self.save_grant(maximum_new_campaigns=4)
        with self.assertRaisesRegex(ValueError, 'GRANT_BINDING'):
            m.check_grant(self.prepared, self.grant, self.current)

    def test_grant_cannot_raise_window(self):
        self.save_grant(window_seconds=21)
        with self.assertRaisesRegex(ValueError, 'GRANT_BINDING'):
            m.check_grant(self.prepared, self.grant, self.current)

    def test_grant_cannot_change_bundle(self):
        self.save_grant(bundle_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'GRANT_BINDING'):
            m.check_grant(self.prepared, self.grant, self.current)

    def test_valid_grant_deadline_exactly_five_minutes(self):
        self.save_grant()
        self.assertEqual(m.check_grant(self.prepared, self.grant, self.current), self.current + dt.timedelta(seconds=300))

    def test_first_reservation_charges_twenty_seconds_and_thirteenth_attempt(self):
        guard = self.guard(); guard.reserve(13, 'plan')
        claim = m.read(self.scope / m.FENCE)
        self.assertEqual((claim['cumulative_campaigns_at_claim'], claim['cumulative_charged_seconds']), (13, 62))
        self.assertFalse(claim['reservation_release'])
        self.assertTrue((self.reservations / 'integration-native-013.json').exists())

    def test_new_output_cannot_reset_scope(self):
        self.guard().reserve(13, 'plan')
        other = self.prepared / 'another'; other.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'ALREADY_CLAIMED'):
            m.Continuation(self.bundle, other, m.now() + dt.timedelta(seconds=300))

    def test_prepared_inspector_reads_shared_consumption_after_claim(self):
        self.guard().reserve(13, 'plan')
        value = m.capacity(self.bundle)
        self.assertEqual((value['cumulative_native_campaigns'], value['cumulative_charged_seconds']), (13, 62))
        self.assertEqual(value['conditional_unclaimed_campaigns'], 0)

    def test_repeat_reservation_denied(self):
        guard = self.guard(); guard.reserve(13, 'plan')
        with self.assertRaisesRegex(ValueError, 'CONTINUATION_LIMIT'):
            guard.reserve(13, 'plan')

    def test_no_sixteenth_campaign(self):
        guard = self.guard()
        for number in (13, 14, 15): guard.reserve(number, 'plan')
        with self.assertRaisesRegex(ValueError, 'CONTINUATION_LIMIT'):
            guard.reserve(16, 'plan')

    def test_skip_phase_denied(self):
        with self.assertRaisesRegex(ValueError, 'CONTINUATION_LIMIT'):
            self.guard().reserve(14, 'plan')

    def test_window_expiration_never_releases_charge(self):
        guard = self.guard(); guard.reserve(13, 'plan'); guard.started -= 12
        with self.assertRaisesRegex(ValueError, 'DEADLINE'):
            guard.reserve(14, 'plan')
        self.assertEqual(m.read(guard.fence)['cumulative_charged_seconds'], 62)

    def test_approval_deadline_denies_dispatch(self):
        guard = self.guard(); guard.deadline = m.now() + dt.timedelta(seconds=8)
        with self.assertRaisesRegex(ValueError, 'DEADLINE'):
            guard.reserve(13, 'plan')
        self.assertFalse(guard.fence.exists())

    def test_changed_claim_stops_next_dispatch(self):
        guard = self.guard(); guard.reserve(13, 'plan'); guard.fence.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'FENCE_DRIFT'):
            guard.reserve(14, 'plan')

    def test_changed_reservation_stops_next_dispatch(self):
        guard = self.guard(); guard.reserve(13, 'plan')
        p = self.reservations / 'integration-native-013.json'; value = m.read(p)
        value['plan_sha256'] = 'different'; p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'RESERVATION_DRIFT'): guard.reserve(14, 'plan')

    def test_orphan_reservation_denies_new_run(self):
        m._save(self.reservations / 'integration-native-014.json', {})
        with self.assertRaisesRegex(ValueError, 'ALREADY_CLAIMED'):
            self.guard()

    def test_failed_spawn_counts_and_keeps_files(self):
        guard = self.guard(); phase = self.run / 'phase-13'
        with patch.object(m.subprocess, 'Popen', side_effect=OSError('synthetic failed spawn')) as popen:
            with self.assertRaisesRegex(ValueError, 'RESULT_UNKNOWN'):
                m.launch(self.prepared, phase, self.plan, guard)
        popen.assert_called_once()
        self.assertEqual(guard.attempts, 13)
        for name in ('plan.json', 'launch.json', 'observed.json', 'stderr.log', 'error.json', 'receipt.json'):
            self.assertTrue((phase / name).exists(), name)
        self.assertEqual(m.read(phase / 'receipt.json')['status'], 'UNKNOWN')
        self.assertEqual(m.read(guard.fence)['cumulative_charged_seconds'], 62)

    def test_denied_reservation_never_spawns(self):
        guard = self.guard(); guard.deadline = m.now()
        with patch.object(m.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'RESULT_UNKNOWN'):
                m.launch(self.prepared, self.run / 'phase-13', self.plan, guard)
        popen.assert_not_called(); self.assertEqual(guard.attempts, 12)

    def test_command_exposes_only_staged_inputs(self):
        cmd = m.child_command(self.prepared, self.run, self.plan)
        self.assertEqual(cmd[:5], ['/usr/bin/prlimit', '--cpu=2:2', '--as=134217728:134217728', '--fsize=131072:131072', '--core=0:0'])
        self.assertIn('--unshare-all', cmd); self.assertIn('--clearenv', cmd); self.assertIn('--cap-drop', cmd)
        self.assertNotIn(str(self.scope), cmd)
        self.assertIn(str(self.prepared / 'original'), cmd)
        self.assertNotIn('/home', cmd); self.assertNotIn('/root', cmd)

    def test_symlink_and_shared_file_rejected(self):
        p = self.root / 'file'; p.write_text('x'); alias = self.root / 'alias'; alias.symlink_to(p)
        with self.assertRaisesRegex(ValueError, 'PATH_LINK'): m.sha(alias)
        alias.unlink(); os.link(p, alias)
        with self.assertRaisesRegex(ValueError, 'FILE_BOUND'): m.sha(p)

    def test_synthetic_full_pass_is_valid(self):
        value = self.validate(self.observation())
        self.assertTrue(value['all_pass']); self.assertFalse(value['counterexample'])

    def test_original_counterexample_requires_fault_and_acquisition(self):
        value = self.observation(); value['rows'][0].update(lock_released=False, passed=False)
        self.assertTrue(self.validate(value)['counterexample'])
        value['rows'][0]['injection_reached'] = False
        with self.assertRaisesRegex(ValueError, 'FAULT_NOT_REACHED'): self.validate(value)

    def test_empty_rows_not_pass(self):
        value = self.observation(); value['rows'] = []
        with self.assertRaisesRegex(ValueError, 'CASE_COVERAGE'): self.validate(value)

    def test_missing_condition_not_pass(self):
        value = self.observation(); value['rows'][0]['case'] = 'UNSUPPORTED'
        with self.assertRaisesRegex(ValueError, 'CASE_COVERAGE'): self.validate(value)

    def test_changed_payload_not_same_conditions(self):
        value = self.observation(); value['rows'][8]['payload_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'CASE_COVERAGE'): self.validate(value)

    def test_inconsistent_verdict_rejected(self):
        value = self.observation(); value['rows'][0]['lock_released'] = False
        with self.assertRaisesRegex(ValueError, 'ROW_VERDICT'): self.validate(value)

    def test_home_or_capability_leak_rejected(self):
        for key, altered in [('home_visible', True), ('effective_capabilities', 1), ('memory', [268435456] * 2)]:
            value = self.observation(); value['execution_boundary'][key] = altered
            with self.assertRaisesRegex(ValueError, 'CHILD_LIMITS'): self.validate(value)

    def test_same_network_namespace_rejected(self):
        value = self.observation(); value['namespaces']['net'] = self.plan['parent_namespaces']['net']
        with self.assertRaisesRegex(ValueError, 'NAMESPACE'): self.validate(value)

    def test_extracted_or_other_module_rejected(self):
        value = self.observation(); value['origins']['api'] = '/tmp/extracted-function.py'
        with self.assertRaisesRegex(ValueError, 'OBSERVATION_BINDING'): self.validate(value)

    def test_held_cannot_be_reclassified(self):
        value = self.observation(); value['held_atomic_bindings'] = 0
        with self.assertRaisesRegex(ValueError, 'OBSERVATION_BINDING'): self.validate(value)

    def test_cli_prepare_and_execute_are_separate(self):
        with patch.object(m, 'prepare', return_value={'status': 'synthetic prepared'}) as prepare, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(integration_cli.main(['prepare', '--scope', str(self.scope), '--output', str(self.prepared), '--baseline', 'fixture']), 0)
        prepare.assert_called_once_with(self.scope, self.prepared, runtime_baseline=Path('fixture'))

    def test_cli_delegation(self):
        from reqlox import cli
        with patch.object(integration_cli, 'main', return_value=7) as delegate:
            self.assertEqual(cli.main(['integration', 'inspect', '--output', 'fixture']), 7)
        delegate.assert_called_once_with(['inspect', '--output', 'fixture'])

    def supervisor(self, summaries, *, anomaly=False):
        for number in (13, 14, 15):
            m._save(self.prepared / f'plan-{number}.json', dict(self.plan, attempt=number))
        def launch(prepared, phase, plan, guard):
            guard.reserve(plan['attempt'], 'synthetic-plan')
            return summaries[plan['attempt'] - 13]
        # Exercise orchestration with synthetic dispatch, separately from UID admission.
        with patch.object(m, '_require_non_root'), \
             patch.object(m, 'check_grant', return_value=m.now() + dt.timedelta(seconds=300)), \
             patch.object(m, 'check_bundle', return_value=self.bundle), \
             patch.object(m, 'observe', return_value={}), \
             patch.object(m, 'validate_runtime', side_effect=[{} ,ValueError('synthetic new anomaly')] if anomaly else None,
                          return_value={}), patch.object(m, 'launch', side_effect=launch) as dispatch:
            m._save(self.grant, {'synthetic_grant': True})
            value = m.execute(self.prepared, self.grant)
        return value, dispatch.call_count

    def test_no_counterexample_stops_after_first_phase(self):
        value, count = self.supervisor([dict(counterexample=False, normal_pass=True)])
        self.assertEqual(count, 1); self.assertEqual(value['cumulative_native_campaigns'], 13)
        self.assertEqual(value['adoption'], 'NOT_PERFORMED')

    def test_normal_baseline_failure_stops_after_first_phase(self):
        value, count = self.supervisor([dict(counterexample=True, normal_pass=False)])
        self.assertEqual(count, 1); self.assertIn('NORMAL_BASELINE_FAILED', value['stop_reason'])

    def test_candidate_failure_stops_without_fresh_retry(self):
        value, count = self.supervisor([dict(counterexample=True, normal_pass=True), dict(all_pass=False)])
        self.assertEqual(count, 2); self.assertEqual(value['adoption'], 'NOT_PERFORMED')
        self.assertEqual(value['cumulative_charged_seconds'], 62)

    def test_adoption_requires_third_same_candidate_phase(self):
        value, count = self.supervisor([dict(counterexample=True, normal_pass=True), dict(all_pass=True), dict(all_pass=True)])
        self.assertEqual(count, 3); self.assertEqual(value['cumulative_native_campaigns'], 15)
        self.assertEqual(value['adoption'], 'ADOPT_EXISTING_CANDIDATE_FOR_ISOLATED_COMPOSED_CALLER')
        self.assertTrue((Path(value['output']) / 'retention-terminal.json').exists())

    def test_fresh_failure_is_not_adopted(self):
        value, count = self.supervisor([dict(counterexample=True, normal_pass=True), dict(all_pass=True), dict(all_pass=False)])
        self.assertEqual(count, 3); self.assertEqual(value['adoption'], 'NOT_ADOPTED')

    def test_new_runtime_anomaly_stops_and_retains_charge(self):
        value, count = self.supervisor([dict(counterexample=True, normal_pass=True)], anomaly=True)
        self.assertEqual(count, 1); self.assertEqual(value['adoption'], 'UNKNOWN_NOT_ADOPTED')
        self.assertEqual(value['cumulative_charged_seconds'], 62)

    def test_audit_missing_reserved_phase_is_unknown(self):
        value, _ = self.supervisor([dict(counterexample=False, normal_pass=True)])
        audit = m.audit(value['output'])
        self.assertEqual(audit['phases'][0]['status'], 'UNKNOWN_MISSING_PHASE')
        self.assertEqual(audit['phases'][1]['status'], 'NOT_PERFORMED')

    def test_audit_detects_retained_terminal_tamper(self):
        value, _ = self.supervisor([dict(counterexample=False, normal_pass=True)])
        terminal = Path(value['output']) / 'terminal.json'; terminal.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'RETAINED_EVIDENCE_DRIFT'): m.audit(value['output'])

    def test_audit_cannot_adopt_mock_success_without_native_receipts(self):
        value, _ = self.supervisor([dict(counterexample=True, normal_pass=True), dict(all_pass=True), dict(all_pass=True)])
        with self.assertRaisesRegex(ValueError, 'AUDIT_ADOPTION'): m.audit(value['output'])


class RuntimeTests(unittest.TestCase):
    def value(self):
        return dict(observed_at_jst=m.now().isoformat(), host_id='dell-stream-runtime',
                    hardware_model='Precision Tower 5810', hostname='synthetic', boot_id='synthetic-boot',
                    target_host_id='target', configured_target_host_id='target', release_id='release',
                    configured_release_id='release', source_commit='commit', configured_source_commit='commit',
                    evidence_age_seconds=1, transport_age_seconds=1, lifecycle_state='RUNNING',
                    pod_uid='synthetic-pod', containers=[dict(name=str(i), ready=True, restartCount=0) for i in range(4)],
                    ffmpeg_pid=10, ffmpeg_generation='generation', transport_ffmpeg_pid=10,
                    recovery=dict(last_pid=10, last_reason='healthy', net_fail_streak=0, stall_streak=0,
                                  remote_warning_streak=0, restart_failure_count=0, pending_recovery_actions=[]),
                    transport_metrics=dict(bytes_sent_delta=1, network_down=False, remote_warning=False,
                                           low_upload_pressure=False), raw_sha256=dict(config='config-hash'),
                    units={'k3s.service':dict(ActiveState='active', SubState='running', Result='success'),
                           'stream-v3-fast-recovery-controller.service':dict(Type='oneshot', ExecMainStatus='0',
                                        ActiveState='inactive', SubState='dead', Result='success'),
                           'stream-v3-fast-recovery-controller.timer':dict(Unit='stream-v3-fast-recovery-controller.service',
                                        ActiveState='active', SubState='waiting', Result='success'),
                           'stream-v3-postboot-verification.service':dict(ActiveState='failed', SubState='failed', Result='exit-code')})

    def test_expected_oneshot_and_timer_cycles_do_not_fake_anomaly(self):
        value = self.value(); baseline = m.validate_runtime(value)
        value['units']['stream-v3-fast-recovery-controller.service'].update(ActiveState='activating', SubState='start')
        value['units']['stream-v3-fast-recovery-controller.timer']['SubState'] = 'running'
        self.assertEqual(m.validate_runtime(value, baseline), baseline)

    def test_failed_oneshot_is_not_cycle(self):
        value = self.value(); value['units']['stream-v3-fast-recovery-controller.service']['ExecMainStatus'] = '1'
        with self.assertRaisesRegex(ValueError, 'RUNTIME_UNIT'): m.validate_runtime(value)

    def test_new_delivery_warning_stops(self):
        value = self.value(); value['transport_metrics']['remote_warning'] = True
        with self.assertRaisesRegex(ValueError, 'DELIVERY_ANOMALY'): m.validate_runtime(value)

    def test_stale_operational_evidence_stops(self):
        value = self.value(); value['observed_at_jst'] = (m.now() - dt.timedelta(seconds=11)).isoformat()
        with self.assertRaisesRegex(ValueError, 'RUNTIME_STALE'): m.validate_runtime(value)

    def test_boot_pod_release_or_container_drift_stops(self):
        baseline = m.validate_runtime(self.value())
        for key in ('boot_id', 'pod_uid', 'ffmpeg_generation'):
            value = self.value(); value[key] = 'changed'
            with self.assertRaisesRegex(ValueError, 'RUNTIME_DRIFT'): m.validate_runtime(value, baseline)

    def test_running_release_disagrees_with_config_stops(self):
        value = self.value(); value['configured_release_id'] = 'other-release'
        with self.assertRaisesRegex(ValueError, 'RUNTIME_IDENTITY'): m.validate_runtime(value)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.scope = self.root / m.SCOPE; self.scope.mkdir(mode=0o700)
        def save(name, value):
            p = self.scope / name; p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            m._save(p, value); return m.sha(p)
        self.save = save
        target = 'target/local-system-v02/'
        files = {}
        for name in ('repositories/api/storage.py', 'repositories/worker/resource.py',
                     'repositories/temppath/temppath/__init__.py', 'repositories/temppath/temppath/temppath.py'):
            p = self.scope / target / name; p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            p.write_text('# Synthetic static source; never imported\n'); files[name] = m.sha(p)
        for name in ('api', 'worker', 'temppath'):
            files['contracts/' + name + '.json'] = save(target + 'contracts/' + name + '.json', {'synthetic': True})
        files['target.json'] = save(target + 'target.json', {'synthetic': True})
        self.pins = {target + 'target.json': files['target.json']}
        self.pins[target + 'snapshot.json'] = save(target + 'snapshot.json', dict(files=files,
            selected_repositories=['api', 'worker', 'temppath'], output=str(self.scope / 'target/local-system-v02')))
        self.pins[m.LEDGER] = save(m.LEDGER, dict(status='TERMINAL', cumulative_native_campaigns=12, cumulative_charged_seconds=42))
        self.pins[m.STOP] = save(m.STOP, dict(native_execution_disabled=True))
        for repo, member in [('api', 'storage.py'), ('worker', 'resource.py')]:
            base = 'execution-v01/adopted-snapshots/' + repo + '/'; p = self.scope / base / member
            p.parent.mkdir(mode=0o700, parents=True); p.write_text('# Synthetic candidate\n')
            self.pins[base + 'manifest.json'] = save(base + 'manifest.json', dict(schema='reqlox.adopted-copy.v1',
                candidate_scope='ISOLATED_SNAPSHOT_ONLY', repository=repo, files={member:m.sha(p)}))
        config = dict(path_context=dict(contract=dict(scope='DOCUMENTED_WITH_EXIT_ONLY',
                  evidence=dict(document='README', span=dict(start=0, end=4, sha256=m.hashlib.sha256(b'with').hexdigest()))),
                  documents={'README':'with'}, recipe=dict(binding=dict(module='temppath', symbol='TemporaryPathContext', args=[], kwargs={}))))
        name = 'path-context-cli-v01/prepared/temppath.configuration.json'; self.pins[name] = save(name, config)
        observer = self.scope / 'execution-v01/observe_stream.py'; observer.write_text('# Synthetic observer; never executed\n')
        save('execution-v01/evidence-manifest.json', dict(files={'observe_stream.py':dict(sha256=m.sha(observer))}))
        self.baseline = self.scope / 'baseline.json'; save('baseline.json', RuntimeTests().value())
        original_sha = m.sha
        def offline_sha(path):
            return 'a' * 64 if str(path).startswith('/usr/') else original_sha(path)
        self.patches = [patch.object(m, 'PINS', self.pins), patch.object(m, 'check_contract'),
                        patch.object(m, 'sha', side_effect=offline_sha)]
        for p in self.patches: p.start()
        self.output = self.scope / 'prepared'

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def prepare(self):
        return m.prepare(self.scope, self.output, runtime_baseline=self.baseline)

    def test_prepare_imports_no_target_and_creates_pending_grant(self):
        with patch.object(m.subprocess, 'Popen') as popen, patch('importlib.import_module') as importer:
            self.prepare(); m.check_bundle(self.output)
        popen.assert_not_called(); importer.assert_not_called()
        self.assertIsNone(m.read(self.output / 'pending-grant.json')['received_at_jst'])
        self.assertEqual(m.read(self.output / 'pending-grant.json')['status'], 'PENDING_FINAL_APPROVAL')
        self.assertFalse((self.scope / m.FENCE).exists())

    def test_receipted_file_drift_stops(self):
        (self.scope / 'target/local-system-v02/repositories/api/storage.py').write_text('# changed\n')
        with self.assertRaisesRegex(ValueError, 'RECEIPT_DRIFT'): self.prepare()

    def test_candidate_drift_stops(self):
        (self.scope / 'execution-v01/adopted-snapshots/worker/resource.py').write_text('# changed\n')
        with self.assertRaisesRegex(ValueError, 'CANDIDATE_DRIFT'): self.prepare()

    def test_duplicate_copy_cannot_reset_fence(self):
        p = self.scope / 'target/local-system-v02/snapshot.json'; value = m.read(p); value['output'] = '/other/copied-target'
        p.write_text(json.dumps(value)); self.pins['target/local-system-v02/snapshot.json'] = m.sha(p)
        with self.assertRaisesRegex(ValueError, 'ROOT_REDIRECT'): self.prepare()

    def test_staged_source_drift_stops(self):
        self.prepare(); p = self.output / 'original/api/storage.py'; p.chmod(0o600); p.write_text('# changed\n')
        with self.assertRaisesRegex(ValueError, 'STAGED_SOURCE_DRIFT'): m.check_bundle(self.output)

    def test_staged_directory_symlink_stops(self):
        self.prepare(); (self.output / 'original/extra').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'ENTRY_BOUND_OR_LINK'): m.check_bundle(self.output)

    def test_plan_changes_do_not_preserve_conditions(self):
        self.prepare(); p = self.output / 'plan-14.json'; value = m.read(p); value['scenario']['faults'] = []
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'PLAN_DRIFT'): m.check_bundle(self.output)

    def test_method_drift_stops(self):
        self.prepare()
        with patch.object(m, 'methods', return_value={}):
            with self.assertRaisesRegex(ValueError, 'METHOD_DRIFT'): m.check_bundle(self.output)

    def test_budget_reset_stops(self):
        self.prepare(); p = self.output / 'bundle.json'; value = m.read(p); value['prior_seconds'] = 0
        p.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'BUDGET_RESET'): m.check_bundle(self.output)

    def test_existing_preparation_is_not_overwritten(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'NEW_PREPARATION_REQUIRED'): self.prepare()

    def test_pending_grant_denies_actual_execute(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'FINAL_APPROVAL_REQUIRED'):
            m.execute(self.output, self.output / 'pending-grant.json')


class ContractTests(unittest.TestCase):
    def test_numeric_fifteen_alone_does_not_authorize_exception(self):
        value = dict(host_id='dell-stream-runtime', forbidden=['a', 'b', '15回'])
        contract = Mock(); contract.stat.return_value = SimpleNamespace(st_uid=0, st_mode=0o644)
        with patch.object(m, 'CONTRACT', contract), patch.object(m, 'read', return_value=value), \
             patch.object(m, 'CONTRACT_SHA', m.digest(value)):
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_EXCEPTION_REQUIRED'): m.check_contract()


class ExecutionIdentityTests(unittest.TestCase):
    """No process, Target, real grant or campaign reservation is used."""

    def test_root_real_or_effective_identity_is_rejected(self):
        for real, effective in [(0, 0), (0, 1000), (1000, 0)]:
            with self.subTest(real=real, effective=effective), \
                 patch.object(m.os, 'getuid', return_value=real), \
                 patch.object(m.os, 'geteuid', return_value=effective):
                with self.assertRaisesRegex(ValueError, 'INTEGRATION_NON_ROOT_REQUIRED'):
                    m._require_non_root()

    def test_non_root_identity_is_accepted_by_identity_gate_only(self):
        with patch.object(m.os, 'getuid', return_value=1000), \
             patch.object(m.os, 'geteuid', return_value=1000):
            m._require_non_root()

    def test_approval_rejection_precedes_identity_gate(self):
        with patch.object(m, 'private_dir', return_value=Path('/synthetic')), \
             patch.object(m, 'check_grant', side_effect=ValueError('FINAL_APPROVAL_REQUIRED')), \
             patch.object(m, '_require_non_root') as identity, \
             patch.object(m.subprocess, 'Popen') as process, \
             patch.object(m, 'retained_workspace') as workspace:
            with self.assertRaisesRegex(ValueError, 'FINAL_APPROVAL_REQUIRED'):
                m.execute('/synthetic', '/synthetic/grant')
        identity.assert_not_called()
        process.assert_not_called()
        workspace.assert_not_called()

    def test_approved_root_execution_stops_before_bundle_workspace_or_process(self):
        with patch.object(m, 'private_dir', return_value=Path('/synthetic')), \
             patch.object(m, 'check_grant', return_value=m.now()), \
             patch.object(m.os, 'getuid', return_value=0), \
             patch.object(m, 'check_bundle') as bundle, \
             patch.object(m.subprocess, 'Popen') as process, \
             patch.object(m, 'retained_workspace') as workspace:
            with self.assertRaisesRegex(ValueError, 'INTEGRATION_NON_ROOT_REQUIRED'):
                m.execute('/synthetic', '/synthetic/grant')
        bundle.assert_not_called()
        process.assert_not_called()
        workspace.assert_not_called()
