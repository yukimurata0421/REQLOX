"""Inherited counts, immutable dispatch reservations and fresh observation gates."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reqlox import evaluation_scope as scope
from reqlox import scope_cli


class EvaluationScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.phase = self.root / 'phase'
        self.phase.mkdir(mode=0o700)
        prior = self.root / 'previous'
        prior.mkdir(mode=0o700)
        self.reservations = prior / 'authorization-reservations'
        self.reservations.mkdir(mode=0o700)
        self.ledger = prior / 'ledger.json'
        self.save(self.ledger, dict(schema='reqlox.cumulative-continuation-terminal.v1',
            status='TERMINAL', automatic_retry=False, cumulative_native_campaigns=10,
            maximum_native_campaigns=12, cumulative_charged_seconds=37,
            maximum_experiment_seconds=120, prior_native_campaigns=8, new_native_campaigns=2,
            prior_charged_seconds=7, charged_continuation_window_seconds=30,
            reservations=['native-reservation-009.json', 'native-reservation-010.json']))
        for number in (9, 10):
            self.save(self.reservations / f'native-reservation-{number:03d}.json', dict(attempt=number))
        self.host = dict(host_id='fixture', hostname='fixture', hardware_model='fixture',
            boot_id='fixture-boot', host_contract_sha256='0' * 64, workspace_head='fixture-head')
        self.baseline = dict(host_id='fixture', hardware_model='fixture', boot_id='fixture-boot',
            release_id='fixture-release', source_commit='fixture-commit', pod_uid='fixture-pod',
            containers=[dict(name='engine', ready=True, restartCount=0)],
            ffmpeg_pid=123, ffmpeg_generation='fixture-generation', lifecycle_state='RUNNING',
            observed_at_jst=self.now(), evidence_age_seconds=1, transport_age_seconds=1,
            transport_ffmpeg_pid=123, transport_metrics=dict(bytes_sent_delta=1, network_down=False,
                remote_warning=False, low_upload_pressure=False),
            recovery=dict(last_pid=123, last_reason='healthy', pending_recovery_actions=[]),
            units={'runtime.service':dict(ActiveState='active',SubState='running',Result='success'),
                scope.CYCLIC_UNIT:dict(ActiveState='inactive',SubState='dead',Result='success')},
            controller_type='oneshot', controller_exit_status='0')
        self.save(self.phase / 'observation.json', self.baseline)
        (self.phase / 'observer.py').write_text('# fixture; never executed\n')
        (self.phase / 'method.py').write_text('# fixture method\n')
        self.plan = dict(kind='FINITE_PATH_CONTEXT_EXECUTION_PLAN_V1', sources={'pkg.py':'pass\n'},
                         recipe={'module':'pkg','symbol':'Context'}, documents={'README':'with Context()'},
                         method={'worker':'fixed'}, forecast_ref=None, record_sha256='0' * 64)
        self.value = dict(kind=scope.KIND, status='APPROVAL_REQUIRED', host=self.host,
            scope_root=str(self.root), inherited_ledger=self.ref(self.ledger),
            inherited_reservations=[self.ref(self.reservations / f'native-reservation-{n:03d}.json') for n in (9,10)],
            reservation_directory=str(self.reservations), method_refs=[self.ref(self.phase / 'method.py')],
            scope_method_sha256=scope.file_hash(scope.__file__), observation_ref=self.ref(self.phase / 'observation.json'),
            observation_helper=self.ref(self.phase / 'observer.py'), preparation_deadline=self.now(600),
            native_deadline=None, maximum_total_native=12, maximum_total_seconds=120,
            maximum_new_native=0, maximum_window_seconds=0, maximum_evidence_bytes=67108864,
            allowed_plan_bindings=[], native_authority=None, automatic_retry=False,
            production_mutations=0, cross_host_mutations=0,
            deadline_jst=None, maximum_http_requests=20, maximum_metadata_projects=12,
            maximum_archive_acquisitions=8)
        self.path = self.phase / 'preflight.json'
        self.original_ledger = self.ledger.read_bytes()

    @staticmethod
    def now(seconds=0):
        return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)).isoformat()

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value))

    @staticmethod
    def ref(path):
        return dict(path=str(path), sha256=scope.file_hash(path))

    def guard(self, *, approved=False, output='output', identity=None, observation=None):
        self.value['deadline_jst']=self.value['preparation_deadline']
        if approved:
            self.value.update(status='APPROVED', native_authority='CURRENT_USER_EXPLICIT_BOUNDED_CONTINUATION',
                native_deadline=self.now(120), maximum_new_native=2, maximum_window_seconds=30,
                allowed_plan_bindings=[scope.plan_binding(self.plan)])
        self.save(self.path, self.value)
        return scope.Guard(self.path, self.phase / output,
            identity_reader=identity or (lambda:dict(self.host,generated_at=self.now())),
            observation_reader=observation or (lambda:dict(self.baseline,observed_at_jst=self.now())))

    def test_read_only_inspection_and_preparation_preserve_ten_and_thirty_seven(self):
        guard = self.guard()
        guard()
        _, _, _, view = scope.inspect(self.path)
        self.assertEqual((view['cumulative_native_campaigns'],view['cumulative_charged_seconds']),(10,37))
        self.assertEqual((view['remaining_scope_native_campaigns'],view['remaining_scope_seconds']),(2,83))
        self.assertFalse(view['native_authorized'])
        self.assertFalse((self.reservations / 'continuation.lock').exists())
        self.assertFalse(guard.output.exists())
        self.assertEqual(self.ledger.read_bytes(),self.original_ledger)

    def test_unapproved_native_request_creates_no_claim_or_reservation(self):
        guard = self.guard()
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):
            guard.reserve_plan(self.plan)
        self.assertEqual(len(list(self.reservations.iterdir())),2)

    def test_failed_dispatch_remains_charged_and_another_run_cannot_retry_it(self):
        guard = self.guard(approved=True)
        self.assertEqual(guard.reserve_plan(self.plan),11)
        # A process failure after this reservation has no receipt and no refund.
        _, _, _, view = scope.inspect(self.path)
        self.assertEqual((view['cumulative_native_campaigns'],view['cumulative_charged_seconds']),(11,67))
        second = scope.Guard(self.path,self.phase / 'other-run',identity_reader=guard.identity_reader,
                             observation_reader=guard.observation_reader)
        with self.assertRaisesRegex(ValueError,'ALREADY_CLAIMED'):
            second.reserve_plan(self.plan)
        self.assertEqual(self.ledger.read_bytes(),self.original_ledger)
        self.assertTrue((self.reservations / 'native-reservation-011.json').exists())
        self.assertFalse((self.reservations / 'native-reservation-012.json').exists())

    def test_two_reservations_are_serial_and_the_third_is_refused(self):
        guard = self.guard(approved=True)
        self.assertEqual(guard.reserve_plan(self.plan),11)
        self.assertEqual(guard.reserve_plan(self.plan),12)
        guard()  # Audit remains possible after the last launch.
        with self.assertRaisesRegex(ValueError,'NATIVE_BOUND'):
            guard.reserve_plan(self.plan)
        self.assertEqual(scope.inspect(self.path)[3]['cumulative_native_campaigns'],12)

    def test_deleted_claim_cannot_reset_time_after_a_failed_reservation(self):
        guard = self.guard(approved=True)
        guard.reserve_plan(self.plan)
        (self.reservations / 'continuation-claim.json').unlink()
        with self.assertRaisesRegex(ValueError,'RESERVATION_DRIFT'):
            scope.inspect(self.path)

    def test_count_time_and_fence_resets_are_refused(self):
        for changes in ({'maximum_total_native':256},{'maximum_total_seconds':121},
                        {'maximum_new_native':3},{'maximum_window_seconds':84},
                        {'reservation_directory':str(self.phase)}):
            with self.subTest(changes=changes):
                original = deepcopy(self.value)
                self.value.update(changes)
                with self.assertRaisesRegex(ValueError,'LIMIT_RESET|FENCE_RESET'):
                    self.guard()
                self.value = original

    def test_expired_scope_stops_before_live_readers(self):
        self.value['preparation_deadline']=self.now(-1)
        reader=lambda:(_ for _ in ()).throw(AssertionError('Live reader called'))
        guard=self.guard(identity=reader,observation=reader)
        with self.assertRaisesRegex(ValueError,'PREPARATION_DEADLINE'):
            guard()

    def test_expired_native_deadline_cannot_create_a_claim(self):
        guard=self.guard(approved=True)
        self.value['native_deadline']=self.now(-1)
        guard=self.guard()
        with self.assertRaisesRegex(ValueError,'NATIVE_WINDOW_UNAVAILABLE'):
            guard.reserve_plan(self.plan)
        self.assertFalse((self.reservations / 'continuation-claim.json').exists())

    def test_method_ledger_and_prior_reservation_drift_each_stop_before_dispatch(self):
        for path in (self.phase / 'method.py',self.ledger,self.reservations / 'native-reservation-009.json'):
            with self.subTest(path=path):
                guard=self.guard(approved=True);original=path.read_bytes();path.write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError,'REFERENCE_DRIFT'):
                    guard.reserve_plan(self.plan)
                path.write_bytes(original)
                self.assertFalse((self.reservations / 'continuation-claim.json').exists())

    def test_plan_drift_is_rejected_before_any_reservation(self):
        guard=self.guard(approved=True);plan=deepcopy(self.plan);plan['sources']['pkg.py']='changed\n'
        with self.assertRaisesRegex(ValueError,'PLAN_NOT_AUTHORIZED'):
            guard.reserve_plan(plan)
        self.assertFalse((self.reservations / 'continuation.lock').exists())

    def test_forecast_attachment_does_not_change_frozen_target_inputs(self):
        guard=self.guard(approved=True);plan=deepcopy(self.plan)
        plan.update(forecast_ref={'path':'fixed-forecast','sha256':'1'*64},record_sha256='2'*64)
        self.assertEqual(guard.reserve_plan(plan),11)

    def test_runtime_identity_transport_warning_and_stale_observation_stop(self):
        variants=[dict(ffmpeg_generation='other-generation'),dict(observed_at_jst=self.now(-31)),
                  dict(transport_metrics=dict(self.baseline['transport_metrics'],remote_warning=True))]
        for changed in variants:
            with self.subTest(changed=changed):
                guard=self.guard(approved=True,observation=lambda:dict(self.baseline,**changed))
                with self.assertRaisesRegex(ValueError,'RUNTIME_DRIFT|OBSERVATION_STALE|NEW_STREAM_ANOMALY'):
                    guard.reserve_plan(self.plan)
                self.assertFalse((self.reservations / 'continuation-claim.json').exists())

    def test_normal_oneshot_transition_is_allowed_but_failed_exit_is_not(self):
        current=deepcopy(self.baseline)
        current['units'][scope.CYCLIC_UNIT].update(ActiveState='active',SubState='running')
        guard=self.guard(approved=True,observation=lambda:dict(current,observed_at_jst=self.now()));guard()
        current['controller_exit_status']='1'
        with self.assertRaisesRegex(ValueError,'CONTROLLER_FAILURE'):
            guard()

    def test_native_window_cannot_restart_after_elapsed_time(self):
        guard=self.guard(approved=True)
        with patch.object(scope.time,'monotonic',return_value=10):
            guard.reserve_plan(self.plan)
        with patch.object(scope.time,'monotonic',return_value=41), \
             self.assertRaisesRegex(ValueError,'NATIVE_WINDOW_EXPIRED'):
            guard.reserve_plan(self.plan)

    def test_inspection_cli_creates_no_runtime_state(self):
        self.guard()
        with patch('sys.stdout',new=io.StringIO()) as out:
            self.assertEqual(scope_cli.main(['inspect','--preflight',str(self.path)]),0)
        self.assertEqual(json.loads(out.getvalue())['cumulative_native_campaigns'],10)
        self.assertEqual(len(list(self.reservations.iterdir())),2)

    def test_legacy_scope_is_rejected_before_any_live_reader(self):
        self.save(self.path,dict(kind='EXPLICIT_FINITE_LOCAL_SUCCESSOR_SCOPE',maximum_total_native=256))
        with self.assertRaisesRegex(ValueError,'INHERITED_LEDGER_REQUIRED'):
            scope.Guard(self.path,self.phase / 'output',identity_reader=None,observation_reader=None)

    def test_output_escape_and_links_cannot_start_a_scope(self):
        self.guard()
        with self.assertRaisesRegex(ValueError,'OUTPUT_BOUND'):
            scope.Guard(self.path,self.root / 'outside',identity_reader=None,observation_reader=None)
        (self.phase / 'linked').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'OUTPUT_BOUND'):
            scope.Guard(self.path,self.phase / 'linked/output',identity_reader=None,observation_reader=None)

    def test_stop_record_carries_reconciled_consumption_and_blocks_old_scope(self):
        guard=self.guard(approved=True)
        successor=self.phase / 'corrected-ledger.json'
        corrected=json.loads(self.ledger.read_text())
        corrected.update(prior_native_campaigns=10,new_native_campaigns=2,cumulative_native_campaigns=12,
                         prior_charged_seconds=37,charged_continuation_window_seconds=5,cumulative_charged_seconds=42)
        self.save(successor,corrected)
        self.save(self.reservations / 'execution-stop.json',dict(native_execution_disabled=True,
            inherited_ledger=self.value['inherited_ledger'],successor_ledger=self.ref(successor),
            cumulative_native_campaigns=12,cumulative_charged_seconds=42))
        view=scope.inspect(self.path)[3]
        self.assertEqual((view['cumulative_native_campaigns'],view['cumulative_charged_seconds']),(12,42))
        self.assertFalse(view['native_authorized'])
        with self.assertRaisesRegex(ValueError,'EXECUTION_STOPPED'):
            guard.reserve_plan(self.plan)
        self.assertEqual(self.ledger.read_bytes(),self.original_ledger)

    def test_stop_record_cannot_invent_a_lower_successor_count(self):
        self.guard()
        successor=self.phase / 'invalid-ledger.json'
        corrected=json.loads(self.ledger.read_text());corrected['cumulative_native_campaigns']=9
        self.save(successor,corrected)
        self.save(self.reservations / 'execution-stop.json',dict(native_execution_disabled=True,
            inherited_ledger=self.value['inherited_ledger'],successor_ledger=self.ref(successor),
            cumulative_native_campaigns=9,cumulative_charged_seconds=37))
        with self.assertRaisesRegex(ValueError,'STOP_RECORD_DRIFT'):
            scope.inspect(self.path)

    def test_preparation_does_not_invoke_a_runtime_reader_or_grant_native_authority(self):
        def unavailable():
            raise AssertionError('Runtime reader belongs to an authorized native supervisor')
        guard=self.guard(observation=unavailable)
        guard()
        with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):
            guard.reserve_plan(self.plan)
        self.assertFalse((self.reservations / 'continuation.lock').exists())


if __name__=='__main__':
    unittest.main()
