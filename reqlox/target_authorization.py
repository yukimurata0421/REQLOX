"""Explicit, single-use continuation of a frozen finite authorization ledger."""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path

from . import targets


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def reference(value):
    require(type(value) is dict and set(value) == {'path', 'sha256'}, 'TARGET_AUTHORIZATION_REFERENCE')
    path = targets.path_at(value['path'], Path.cwd())
    require(hashlib.sha256(path.read_bytes()).hexdigest() == value['sha256'], 'TARGET_AUTHORIZATION_REFERENCE_DRIFT')
    return targets.read_json(path)


def inspect(path, *, for_execution=False):
    path = targets.path_at(str(path), Path.cwd())
    value = targets.read_json(path)
    fields = {'schema', 'status', 'authority', 'prior_ledger', 'prior_execution_summary',
              'prior_native_attempts', 'prior_charged_seconds', 'maximum_native_campaigns', 'maximum_seconds',
              'maximum_new_native_campaigns', 'maximum_window_seconds', 'deadline', 'reservation_directory',
              'bindings', 'method_sha256', 'single_run', 'automatic_retry'}
    require(type(value) is dict and set(value) == fields
            and value['schema'] == 'reqlox.authorization-continuation.v1'
            and value['status'] in ('APPROVAL_REQUIRED', 'APPROVED')
            and value['authority'] == 'CURRENT_USER_EXPLICIT_BOUNDED_CONTINUATION'
            and value['single_run'] is True and value['automatic_retry'] is False,
            'TARGET_AUTHORIZATION_RECORD')
    ledger = reference(value['prior_ledger']); summary = reference(value['prior_execution_summary'])
    require(ledger['status'] == 'TERMINAL' and ledger['automatic_retry'] is False
            and type(ledger['native_attempts']) is int and ledger['native_attempts'] >= 0
            and value['prior_native_attempts'] == ledger['native_attempts'] == summary['native_campaigns']
            and value['maximum_native_campaigns'] == ledger['maximum_native_campaigns'] == summary['maximum_native_campaigns']
            and value['maximum_seconds'] == ledger['maximum_seconds'] == summary['maximum_experiment_seconds'],
            'TARGET_AUTHORIZATION_LEDGER_BINDING')
    require(type(value['prior_charged_seconds']) is int
            and value['prior_charged_seconds'] >= math.ceil(max(ledger['elapsed_seconds'], summary['experiment_elapsed_seconds'])),
            'TARGET_AUTHORIZATION_TIME_RESET')
    remaining = value['maximum_native_campaigns'] - value['prior_native_attempts']
    remaining_seconds = value['maximum_seconds'] - value['prior_charged_seconds']
    require(type(value['maximum_new_native_campaigns']) is int and 1 <= value['maximum_new_native_campaigns'] <= remaining
            and type(value['maximum_window_seconds']) is int and 5 <= value['maximum_window_seconds'] <= remaining_seconds,
            'TARGET_AUTHORIZATION_LIMIT_RESET')
    reservation = Path(os.path.abspath(value['reservation_directory']))
    require(reservation.parent == path.parent and reservation.name == 'authorization-reservations'
            and not any(p.is_symlink() for p in (reservation, *reservation.parents)), 'TARGET_AUTHORIZATION_RESERVATION_SCOPE')
    require(path.parent.stat().st_uid == os.getuid() and not path.parent.stat().st_mode & 0o077,
            'TARGET_AUTHORIZATION_PRIVATE_DIRECTORY')
    require(type(value['bindings']) is list and value['bindings'] and all(type(row) is dict
        and set(row) == {'name', 'sources_sha256', 'configuration_sha256', 'execution_method'} for row in value['bindings']),
        'TARGET_AUTHORIZATION_BINDINGS')
    if for_execution:
        require(value['status'] == 'APPROVED', 'TARGET_AUTHORIZATION_APPROVAL_REQUIRED')
        require(type(value['deadline']) is str, 'TARGET_AUTHORIZATION_DEADLINE_REQUIRED')
        deadline = datetime.datetime.fromisoformat(value['deadline'])
        require(deadline.tzinfo is not None
                and (deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() >= 5,
                'TARGET_AUTHORIZATION_DEADLINE_EXPIRED')
        require(not (reservation / 'claim.json').exists(), 'TARGET_AUTHORIZATION_ALREADY_STARTED')
    # Approval and its concrete deadline do not change the reviewed input/method binding.
    stable = {key: value[key] for key in fields - {'status', 'deadline'}}
    view = dict(path=str(path), record_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                status=value['status'], reviewed_binding_sha256=targets.digest(stable),
                prior_native_attempts=value['prior_native_attempts'], prior_charged_seconds=value['prior_charged_seconds'],
                remaining_native_campaigns=remaining, remaining_seconds=remaining_seconds,
                maximum_new_native_campaigns=value['maximum_new_native_campaigns'],
                maximum_window_seconds=value['maximum_window_seconds'],
                approval_recorded=value['status'] == 'APPROVED')
    return value, view


def check_plan(value, plan):
    bindings = [{k: row.get(k, 'FINITE_REPAIR_LOOP') for k in
        ('name', 'sources_sha256', 'configuration_sha256', 'execution_method')} for row in plan['repositories']]
    require(bindings == value['bindings'] and targets.digest(plan['method']) == value['method_sha256'],
            'TARGET_AUTHORIZATION_PLAN_DRIFT')
    require(plan['maximum_native_campaigns'] == value['maximum_native_campaigns']
            and plan['seconds'] <= value['maximum_window_seconds'], 'TARGET_AUTHORIZATION_PLAN_LIMIT')


class Budget(targets.Budget):
    def __init__(self, value, deadline, output, plan_sha256):
        super().__init__(value['maximum_native_campaigns'], deadline, output, plan_sha256)
        self.prior_attempts = self.attempts = value['prior_native_attempts']
        self.maximum_new = value['maximum_new_native_campaigns']
        self.reservation_directory = Path(value['reservation_directory'])
        self.reservation_directory.mkdir(mode=0o700, exist_ok=True)
        require(self.reservation_directory.stat().st_uid == os.getuid()
                and not self.reservation_directory.stat().st_mode & 0o077, 'TARGET_AUTHORIZATION_PRIVATE_DIRECTORY')
        # Exclusive creation is the single-run fence, including failed dispatches.
        with (self.reservation_directory / 'claim.json').open('x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(dict(status='CLAIMED_BEFORE_DISPATCH', plan_sha256=plan_sha256,
                prior_ledger=value['prior_ledger'], prior_native_attempts=self.prior_attempts,
                prior_charged_seconds=value['prior_charged_seconds'],
                charged_window_seconds=value['maximum_window_seconds'],
                maximum_native_campaigns=self.maximum, deadline=deadline.isoformat(),
                automatic_retry=False), stream)
    def reserve(self):
        require(self.attempts - self.prior_attempts < self.maximum_new, 'TARGET_AUTHORIZATION_CONTINUATION_LIMIT')
        super().reserve()
        import run_reliability_reuse as storage
        path = self.reservation_directory / f'native-reservation-{self.attempts:03d}.json'
        with path.open('x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(storage.read(self.output / path.name), stream)
