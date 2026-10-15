"""Carry a terminal native ledger into one explicitly bounded continuation.

The guard performs no Target imports or execution. Live identity and observation
readers belong to the caller's trusted supervisor, not to Target configuration.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time

from . import targets

KIND = 'INHERITED_FINITE_EVALUATION_SCOPE_V1'
FIELDS = {'kind', 'status', 'host', 'scope_root', 'inherited_ledger',
          'inherited_reservations', 'reservation_directory', 'method_refs',
          'scope_method_sha256', 'observation_ref', 'observation_helper',
          'preparation_deadline', 'native_deadline', 'maximum_total_native',
          'maximum_total_seconds', 'maximum_new_native', 'maximum_window_seconds',
          'maximum_evidence_bytes', 'allowed_plan_bindings', 'native_authority',
          'automatic_retry', 'production_mutations', 'cross_host_mutations',
          'deadline_jst', 'maximum_http_requests', 'maximum_metadata_projects',
          'maximum_archive_acquisitions'}
HOST_FIELDS = {'host_id', 'hostname', 'hardware_model', 'boot_id',
               'host_contract_sha256', 'workspace_head'}
CYCLIC_UNIT = 'stream-v3-fast-recovery-controller.service'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(ref):
    require(type(ref) is dict and set(ref) == {'path', 'sha256'}
            and type(ref['sha256']) is str and re.fullmatch('[0-9a-f]{64}', ref['sha256']),
            'EVALUATION_SCOPE_REFERENCE')
    path = targets.path_at(ref['path'], Path.cwd())
    require(path.stat().st_size <= 1048576 and file_hash(path) == ref['sha256'],
            'EVALUATION_SCOPE_REFERENCE_DRIFT')
    return path


def private_directory(path):
    path = targets.path_at(str(path), Path.cwd(), directory=True)
    require(path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077,
            'EVALUATION_SCOPE_PRIVATE_DIRECTORY')
    return path


def timestamp(value):
    require(type(value) is str, 'EVALUATION_SCOPE_DEADLINE_REQUIRED')
    parsed = datetime.datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'EVALUATION_SCOPE_DEADLINE_TIMEZONE')
    return parsed


def plan_binding(plan):
    require(type(plan) is dict and plan.get('kind') == 'FINITE_PATH_CONTEXT_EXECUTION_PLAN_V1',
            'EVALUATION_SCOPE_PLAN_KIND')
    # These two fields are produced after the frozen input is registered.
    return targets.digest({k: v for k, v in plan.items() if k not in ('record_sha256', 'forecast_ref')})


def reservation_state(value, ledger, reservation):
    prior = ledger['cumulative_native_campaigns']
    entries = list(reservation.iterdir())
    require(len(entries) <= 32 and not any(p.is_symlink() for p in entries),
            'EVALUATION_SCOPE_FENCE_BOUND_OR_LINK')
    claim_path = reservation / 'continuation-claim.json'
    claim = targets.read_json(claim_path) if claim_path.exists() else None
    charged = ledger['cumulative_charged_seconds']
    if claim is not None:
        require(claim['inherited_ledger'] == value['inherited_ledger']
                and claim['cumulative_native_campaigns_before'] == prior
                and type(claim['charged_window_seconds']) is int and claim['charged_window_seconds'] >= 5
                and claim['cumulative_charged_seconds'] == charged + claim['charged_window_seconds']
                and claim['cumulative_charged_seconds'] <= value['maximum_total_seconds']
                and claim['automatic_retry'] is False, 'EVALUATION_SCOPE_CLAIM_DRIFT')
        charged = claim['cumulative_charged_seconds']
    numbers = []
    for path in reservation.glob('native-reservation-*.json'):
        match = re.fullmatch(r'native-reservation-(\d{3})\.json', path.name)
        require(match is not None, 'EVALUATION_SCOPE_RESERVATION_NAME')
        number = int(match[1])
        require(number <= value['maximum_total_native'], 'EVALUATION_SCOPE_NATIVE_BOUND')
        if number <= prior:
            continue
        row = targets.read_json(path)
        require(claim is not None and row['attempt'] == number
                and row['inherited_ledger'] == value['inherited_ledger']
                and row['claim_sha256'] == file_hash(claim_path)
                and row['scope_sha256'] == claim['scope_sha256']
                and row['reservation_released'] is False, 'EVALUATION_SCOPE_RESERVATION_DRIFT')
        numbers.append(number)
    require(sorted(numbers) == list(range(prior + 1, prior + 1 + len(numbers))),
            'EVALUATION_SCOPE_RESERVATION_GAP')
    return prior + len(numbers), charged, claim is not None


def inspect(path):
    """Read scope identities and remaining capacity without claims or commands."""
    path = targets.path_at(str(path), Path.cwd())
    private_directory(path.parent)
    value = targets.read_json(path)
    require(type(value) is dict and set(value) - {'record_sha256'} == FIELDS and value['kind'] == KIND,
            'EVALUATION_SCOPE_INHERITED_LEDGER_REQUIRED')
    if 'record_sha256' in value:
        require(value['record_sha256'] == targets.digest({k:v for k,v in value.items() if k != 'record_sha256'}),
                'EVALUATION_SCOPE_RECORD_DRIFT')
    require(value['status'] in ('APPROVAL_REQUIRED', 'APPROVED')
            and type(value['host']) is dict and set(value['host']) == HOST_FIELDS
            and all(type(v) is str and v for v in value['host'].values())
            and value['automatic_retry'] is False
            and type(value['production_mutations']) is int and value['production_mutations'] == 0
            and type(value['cross_host_mutations']) is int and value['cross_host_mutations'] == 0,
            'EVALUATION_SCOPE_AUTHORITY')
    root = private_directory(value['scope_root'])
    ledger_path = reference(value['inherited_ledger'])
    ledger = targets.read_json(ledger_path)
    require(ledger_path.is_relative_to(root) and path.is_relative_to(root)
            and ledger['schema'] == 'reqlox.cumulative-continuation-terminal.v1'
            and ledger['status'] == 'TERMINAL' and ledger['automatic_retry'] is False,
            'EVALUATION_SCOPE_LEDGER_TERMINAL')
    names = ('cumulative_native_campaigns', 'maximum_native_campaigns',
             'cumulative_charged_seconds', 'maximum_experiment_seconds',
             'prior_native_campaigns', 'new_native_campaigns',
             'prior_charged_seconds', 'charged_continuation_window_seconds')
    require(all(type(ledger[n]) is int and ledger[n] >= 0 for n in names),
            'EVALUATION_SCOPE_LEDGER_COUNTS')
    require(ledger['cumulative_native_campaigns'] == ledger['prior_native_campaigns'] + ledger['new_native_campaigns']
            and ledger['cumulative_charged_seconds'] == ledger['prior_charged_seconds'] + ledger['charged_continuation_window_seconds'],
            'EVALUATION_SCOPE_LEDGER_ACCOUNTING')
    remaining = ledger['maximum_native_campaigns'] - ledger['cumulative_native_campaigns']
    seconds = ledger['maximum_experiment_seconds'] - ledger['cumulative_charged_seconds']
    integers = ('maximum_total_native', 'maximum_total_seconds', 'maximum_new_native',
                'maximum_window_seconds', 'maximum_evidence_bytes')
    require(all(type(value[k]) is int for k in integers)
            and value['maximum_total_native'] == ledger['maximum_native_campaigns'] <= 12
            and value['maximum_total_seconds'] == ledger['maximum_experiment_seconds'] <= 120
            and 0 <= value['maximum_new_native'] <= remaining
            and 0 <= value['maximum_window_seconds'] <= seconds
            and 0 < value['maximum_evidence_bytes'] <= 268435456,
            'EVALUATION_SCOPE_LIMIT_RESET')
    reservation = private_directory(value['reservation_directory'])
    require(reservation == ledger_path.parent / 'authorization-reservations',
            'EVALUATION_SCOPE_FENCE_RESET')
    require(type(value['inherited_reservations']) is list
            and len(value['inherited_reservations']) == len(ledger['reservations'])
            and [reference(ref) for ref in value['inherited_reservations']] ==
                [reservation / name for name in ledger['reservations']],
            'EVALUATION_SCOPE_PRIOR_RESERVATIONS')
    require(type(value['method_refs']) is list and 1 <= len(value['method_refs']) <= 32,
            'EVALUATION_SCOPE_METHODS')
    for ref in value['method_refs']:
        reference(ref)
    reference(value['observation_helper'])
    baseline = targets.read_json(reference(value['observation_ref']))
    require(value['scope_method_sha256'] == file_hash(__file__), 'EVALUATION_SCOPE_METHOD_DRIFT')
    require(type(value['allowed_plan_bindings']) is list and len(value['allowed_plan_bindings']) <= 24
            and len(set(value['allowed_plan_bindings'])) == len(value['allowed_plan_bindings'])
            and all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v) for v in value['allowed_plan_bindings']),
            'EVALUATION_SCOPE_PLAN_BINDINGS')
    timestamp(value['preparation_deadline'])
    require(value['deadline_jst'] == value['preparation_deadline']
            and type(value['maximum_http_requests']) is int and 0 <= value['maximum_http_requests'] <= 20
            and type(value['maximum_metadata_projects']) is int and 0 <= value['maximum_metadata_projects'] <= 12
            and type(value['maximum_archive_acquisitions']) is int and 0 <= value['maximum_archive_acquisitions'] <= 8,
            'EVALUATION_SCOPE_ACQUISITION_BOUND')
    if value['status'] == 'APPROVED':
        timestamp(value['native_deadline'])
        require(value['native_authority'] == 'CURRENT_USER_EXPLICIT_BOUNDED_CONTINUATION'
                and value['maximum_new_native'] > 0 and value['maximum_window_seconds'] >= 5
                and value['allowed_plan_bindings'], 'EVALUATION_SCOPE_NATIVE_AUTHORITY')
    else:
        require(value['native_authority'] is None and value['native_deadline'] is None,
                'EVALUATION_SCOPE_APPROVAL_NOT_RECORDED')
    attempts, charged, claimed = reservation_state(value, ledger, reservation)
    stop_path = reservation / 'execution-stop.json'
    stop = targets.read_json(stop_path) if stop_path.exists() else None
    if stop is not None:
        require(stop['native_execution_disabled'] is True
                and stop['inherited_ledger'] == value['inherited_ledger'], 'EVALUATION_SCOPE_STOP_RECORD_DRIFT')
        successor = targets.read_json(reference(stop['successor_ledger']))
        require(successor['status'] == 'TERMINAL' and successor['automatic_retry'] is False
                and successor['cumulative_native_campaigns'] == stop['cumulative_native_campaigns']
                and successor['cumulative_charged_seconds'] == stop['cumulative_charged_seconds']
                and attempts <= successor['cumulative_native_campaigns'] <= value['maximum_total_native']
                and charged <= successor['cumulative_charged_seconds'] <= value['maximum_total_seconds'],
                'EVALUATION_SCOPE_STOP_RECORD_DRIFT')
        attempts, charged = successor['cumulative_native_campaigns'], successor['cumulative_charged_seconds']
    return value, ledger, baseline, dict(status=value['status'],
        cumulative_native_campaigns=attempts, cumulative_charged_seconds=charged,
        remaining_scope_native_campaigns=ledger['maximum_native_campaigns'] - attempts,
        remaining_scope_seconds=ledger['maximum_experiment_seconds'] - charged,
        maximum_new_native_campaigns=value['maximum_new_native'],
        native_authorized=value['status'] == 'APPROVED' and stop is None, new_native_campaigns=0,
        new_provider_calls=0, continuation_already_claimed=claimed,
        execution_stopped=stop is not None, inspection_creates_reservations=False)


class Guard:
    def __init__(self, path, output, *, identity_reader, observation_reader):
        self.path = targets.path_at(str(path), Path.cwd())
        self.value, self.ledger, self.baseline, self.view = inspect(self.path)
        self.scope_hash = file_hash(self.path)
        self.output = Path(os.path.abspath(output))
        require(not any(p.is_symlink() for p in (self.output, *self.output.parents))
                and self.output.is_relative_to(self.path.parent) and self.output != self.path.parent
                and not self.output.exists(), 'EVALUATION_SCOPE_OUTPUT_BOUND')
        self.identity_reader, self.observation_reader = identity_reader, observation_reader
        self.reservation = Path(self.value['reservation_directory'])
        self.claim = self.reservation / 'continuation-claim.json'
        self.started = None
        self.pid = os.getpid()

    def _attempts(self):
        return reservation_state(self.value, self.ledger, self.reservation)[0]

    def _observation(self, current):
        for key in ('host_id', 'hardware_model', 'boot_id', 'release_id', 'source_commit',
                    'pod_uid', 'containers', 'ffmpeg_pid', 'ffmpeg_generation', 'lifecycle_state'):
            require(current[key] == self.baseline[key], 'EVALUATION_SCOPE_RUNTIME_DRIFT:' + key)
        now = datetime.datetime.now(datetime.timezone.utc)
        require(0 <= (now - timestamp(current['observed_at_jst'])).total_seconds() < 30
                and 0 <= current['evidence_age_seconds'] < 30
                and 0 <= current['transport_age_seconds'] < 30, 'EVALUATION_SCOPE_OBSERVATION_STALE')
        require(current['lifecycle_state'] == 'RUNNING' and all(c['ready'] for c in current['containers'])
                and current['transport_ffmpeg_pid'] == current['ffmpeg_pid'] == current['recovery']['last_pid']
                and current['transport_metrics']['bytes_sent_delta'] > 0
                and not any(current['transport_metrics'][k] for k in ('network_down', 'remote_warning', 'low_upload_pressure'))
                and current['recovery']['last_reason'] == 'healthy'
                and not current['recovery']['pending_recovery_actions'], 'EVALUATION_SCOPE_NEW_STREAM_ANOMALY')
        require(set(current['units']) == set(self.baseline['units']), 'EVALUATION_SCOPE_UNIT_DRIFT')
        for name, state in current['units'].items():
            if name == CYCLIC_UNIT:
                require(current['controller_type'] == 'oneshot' and current['controller_exit_status'] == '0'
                        and state['Result'] == 'success'
                        and (state['ActiveState'], state['SubState']) in
                            (('inactive', 'dead'), ('activating', 'start'), ('active', 'running')),
                        'EVALUATION_SCOPE_CONTROLLER_FAILURE')
            else:
                require(state == self.baseline['units'][name], 'EVALUATION_SCOPE_UNIT_DRIFT:' + name)

    def __call__(self):
        require(os.getpid() == self.pid, 'EVALUATION_SCOPE_SUPERVISOR_CHANGED')
        require(file_hash(self.path) == self.scope_hash, 'EVALUATION_SCOPE_PREFLIGHT_DRIFT')
        now = datetime.datetime.now(datetime.timezone.utc)
        require(now + datetime.timedelta(seconds=5) < timestamp(self.value['preparation_deadline']),
                'EVALUATION_SCOPE_PREPARATION_DEADLINE')
        if self.started is not None:
            require(time.monotonic() - self.started < self.value['maximum_window_seconds'],
                    'EVALUATION_SCOPE_NATIVE_WINDOW_EXPIRED')
            require(now + datetime.timedelta(seconds=5) < timestamp(self.value['native_deadline']),
                    'EVALUATION_SCOPE_NATIVE_DEADLINE')
        inspect(self.path)  # Includes all inherited receipts and active method hashes.
        identity = self.identity_reader()
        require(all(identity.get(k) == v for k, v in self.value['host'].items()),
                'EVALUATION_SCOPE_HOST_DRIFT')
        now = datetime.datetime.now(datetime.timezone.utc)
        require(0 <= (now - timestamp(identity['generated_at'])).total_seconds() < 600,
                'EVALUATION_SCOPE_CONTEXT_STALE')
        # Preparation cannot dispatch a Target. A native-authorized supervisor
        # must obtain fresh runtime facts before each dispatch and while active.
        if self.value['status'] == 'APPROVED':
            self._observation(self.observation_reader())
        count = 0
        total = 0
        for directory, folders, files in os.walk(self.path.parent):
            for name in folders + files:
                path = Path(directory) / name
                require(not path.is_symlink(), 'EVALUATION_SCOPE_EVIDENCE_LINK')
                count += 1
                require(count <= 20000, 'EVALUATION_SCOPE_EVIDENCE_BOUND')
                if path.is_file():
                    total += path.stat().st_size
                    require(total + 50331648 <= self.value['maximum_evidence_bytes'],
                            'EVALUATION_SCOPE_EVIDENCE_BOUND')
        require(self._attempts() <= self.value['maximum_total_native'], 'EVALUATION_SCOPE_NATIVE_BOUND')

    @staticmethod
    def _save(path, value):
        with path.open('x', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())

    def before_native(self, plan=None):
        require(not (self.reservation / 'execution-stop.json').exists(), 'EVALUATION_SCOPE_EXECUTION_STOPPED')
        require(self.value['status'] == 'APPROVED', 'EVALUATION_SCOPE_APPROVAL_REQUIRED')
        require(plan is not None and plan_binding(plan) in self.value['allowed_plan_bindings'],
                'EVALUATION_SCOPE_PLAN_NOT_AUTHORIZED')
        self()
        if self.started is None:
            require(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self.value['maximum_window_seconds'])
                    <= timestamp(self.value['native_deadline']), 'EVALUATION_SCOPE_NATIVE_WINDOW_UNAVAILABLE')
        with (self.reservation / 'continuation.lock').open('a') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            self()
            attempts = self._attempts()
            require(attempts < min(self.value['maximum_total_native'],
                                  self.ledger['cumulative_native_campaigns'] + self.value['maximum_new_native']),
                    'EVALUATION_SCOPE_NATIVE_BOUND')
            if self.started is None:
                require(not self.claim.exists(), 'EVALUATION_SCOPE_ALREADY_CLAIMED')
                self._save(self.claim, dict(status='CLAIMED_BEFORE_DISPATCH', scope_sha256=self.scope_hash,
                    inherited_ledger=self.value['inherited_ledger'], output=str(self.output),
                    cumulative_native_campaigns_before=self.ledger['cumulative_native_campaigns'],
                    cumulative_charged_seconds=self.ledger['cumulative_charged_seconds'] + self.value['maximum_window_seconds'],
                    charged_window_seconds=self.value['maximum_window_seconds'],
                    native_deadline=self.value['native_deadline'], automatic_retry=False))
                self.started = time.monotonic()
            else:
                require(targets.read_json(self.claim)['scope_sha256'] == self.scope_hash,
                        'EVALUATION_SCOPE_CLAIM_DRIFT')
            number = attempts + 1
            self._save(self.reservation / f'native-reservation-{number:03d}.json',
                dict(attempt=number, status='RESERVED_BEFORE_DISPATCH', outcome='UNKNOWN_UNTIL_CHILD_RECEIPT',
                     inherited_ledger=self.value['inherited_ledger'], scope_sha256=self.scope_hash,
                     claim_sha256=file_hash(self.claim), plan_binding=plan_binding(plan),
                     reservation_released=False, automatic_retry=False))
            return number

    reserve_plan = before_native
