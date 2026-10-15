"""Explicit parallel dispatch with durable reservations and preserved unknowns."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import os
from pathlib import Path
import re
import threading

from . import ir, judge_client, reference, storage


def validate_scope(scope, plan, *, workers, currency='jev_usd', require_disclosure=True):
    reference.check_seal(scope)
    reference.require(scope.get('schema_version') == 'reqlox.local-provider-scope.v1', 'PROVIDER_SCOPE_CONTRACT')
    reference.require(type(scope.get('id')) is str and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', scope['id']), 'PROVIDER_SCOPE_ID')
    reference.require(scope['plan_sha256'] == plan['record_sha256'], 'PROVIDER_SCOPE_PLAN_BINDING')
    deadline = datetime.fromisoformat(scope['deadline_utc'])
    reference.require(deadline.tzinfo is not None and deadline > datetime.now(timezone.utc), 'PROVIDER_SCOPE_DEADLINE')
    reference.require(type(scope['external_disclosure_allowed']) is bool, 'PROVIDER_DISCLOSURE_FIELD')
    if require_disclosure:
        reference.require(scope['external_disclosure_allowed'] is True, 'PROVIDER_DISCLOSURE_NOT_DECLARED')
    reference.require(type(scope['maximum_calls']) is int and plan['maximum_calls'] <= scope['maximum_calls'] <= 512,
                      'PROVIDER_SCOPE_CALL_BOUND')
    reference.require(type(workers) is int and type(scope['maximum_concurrent_calls']) is int and
                      1 <= workers <= scope['maximum_concurrent_calls'] <= 8,
                      'PROVIDER_CONCURRENCY_BOUND')
    reference.require(scope['currency'] == currency, 'PROVIDER_SCOPE_CURRENCY')
    try:
        per_call, maximum = Decimal(scope['per_call_reserved']), Decimal(scope['maximum_reserved'])
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('PROVIDER_SCOPE_RESERVATION_BOUND') from exc
    reference.require(per_call.is_finite() and maximum.is_finite() and 0 < per_call <= maximum and
        per_call * plan['maximum_calls'] <= maximum, 'PROVIDER_SCOPE_RESERVATION_BOUND')
    return deadline


def make_scope(plan, *, identifier, deadline_utc, maximum_reserved, per_call_reserved,
               maximum_concurrent_calls=2, external_disclosure_allowed=False):
    if plan.get('family') == 'generation':
        from .generation import validate_plan
        validate_plan(plan)
    else:
        ir.validate_plan(plan)
    value = reference.seal(dict(schema_version='reqlox.local-provider-scope.v1', id=identifier,
        plan_sha256=plan['record_sha256'], deadline_utc=deadline_utc,
        currency='gcp_jpy' if plan.get('family') == 'generation' else 'jev_usd',
        maximum_calls=plan['maximum_calls'], maximum_reserved=str(maximum_reserved),
        per_call_reserved=str(per_call_reserved), maximum_concurrent_calls=maximum_concurrent_calls,
        external_disclosure_allowed=external_disclosure_allowed, reservation_is_invoice=False,
        automatic_retry=False))
    validate_scope(value, plan, workers=1, currency=value['currency'], require_disclosure=False)
    return value


class Ledger:
    def __init__(self, directory, scope):
        self.directory = storage.private_directory(directory)
        self.scope = scope
        self.lock = threading.Lock()

    def update(self, callback):
        with self.lock:
            lock_path = storage.private_path(self.directory, 'ledger.lock')
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                path = self.directory / 'ledger.json'
                value = storage.read(path) if path.exists() else dict(scope_sha256=self.scope['record_sha256'],
                    reserved='0', attempts=[], blocked=False)
                reference.require(value['scope_sha256'] == self.scope['record_sha256'], 'PROVIDER_SCOPE_DRIFT')
                result = callback(value)
                storage.save(path, value, replace=True)
                return result

    def reserve(self, identifier):
        def change(value):
            reference.require(not value['blocked'], 'PROVIDER_PRIOR_FAILURE_STOP')
            reference.require(datetime.fromisoformat(self.scope['deadline_utc']) > datetime.now(timezone.utc), 'PROVIDER_DEADLINE')
            require = reference.require
            require(len(value['attempts']) < self.scope['maximum_calls'], 'PROVIDER_CALL_LIMIT')
            amount = Decimal(value['reserved']) + Decimal(self.scope['per_call_reserved'])
            require(amount <= Decimal(self.scope['maximum_reserved']), 'PROVIDER_RESERVATION_LIMIT')
            require(identifier not in {a['id'] for a in value['attempts']}, 'PROVIDER_DUPLICATE_ATTEMPT')
            value['reserved'] = str(amount)
            value['attempts'].append(dict(id=identifier, status='OUTCOME_UNKNOWN',
                reserved=self.scope['per_call_reserved'], started_at=datetime.now(timezone.utc).isoformat()))
        self.update(change)

    def complete(self, identifier, *, succeeded, usage=None):
        def change(value):
            attempt = next(a for a in value['attempts'] if a['id'] == identifier)
            attempt.update(status='COMPLETE' if succeeded else 'OUTCOME_UNKNOWN', usage=usage,
                completed_at=datetime.now(timezone.utc).isoformat(), reservation_retained=True)
            if not succeeded:
                value['blocked'] = True
        self.update(change)


def execute(plan_path, scope_path, *, state_dir=None, workers=2, execute=False,
            api_key_file=None, client_factory=None):
    plan = storage.checked_record(plan_path)
    ir.validate_plan(plan)
    scope = storage.checked_record(scope_path)
    deadline = validate_scope(scope, plan, workers=workers, require_disclosure=execute)
    if not execute:
        return dict(status='READY_NO_EXECUTION', plan_sha256=plan['record_sha256'],
                    maximum_calls=plan['maximum_calls'], provider_calls=0, automatic_retry=False,
                    external_disclosure_allowed=scope['external_disclosure_allowed'])
    root = storage.private_directory(storage.state_directory(state_dir) / 'provider-scopes')
    directory = storage.private_directory(root / scope['id'])
    # One execution owns this scope; its independent batches still run concurrently.
    descriptor = os.open(storage.private_path(directory, 'execution.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as guard:
        try:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('PROVIDER_SCOPE_ALREADY_RUNNING') from exc
        reference.require(not (directory / 'started.json').exists(), 'PROVIDER_SUCCESSOR_REQUIRED')
        key = judge_client.api_key(key_file=api_key_file)
        def factory():
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            reference.require(remaining > 0, 'PROVIDER_DEADLINE')
            return client_factory() if client_factory else judge_client.JevSystemOneClient(
                key, timeout_seconds=min(45.0, remaining))
        storage.save(directory / 'started.json', dict(plan_sha256=plan['record_sha256'], scope=scope,
            created_at=datetime.now(timezone.utc).isoformat(), automatic_retry=False))
        storage.save(directory / 'review-plan.json', plan)
        ledger, stopped = Ledger(directory, scope), threading.Event()
        observations = {}
        def dispatch(batch):
            results = []
            for repeat in range(3):
                if stopped.is_set():
                    break
                identifier = batch['id'] + '-repeat-' + str(repeat)
                reserved = False
                try:
                    ledger.reserve(identifier)
                    reserved = True
                    request_payload = judge_client.canonical_json_bytes(dict(state=batch['state'],
                        model=judge_client.PINNED_MODEL, questions=batch['questions']))
                    storage.write_bytes(directory / (identifier + '-request.json'), request_payload)
                    response = factory().evaluate(state=batch['state'], questions=batch['questions'])
                    for kind in ('response',):
                        payload = response.get('_provider_' + kind + '_payload')
                        if payload is not None:
                            reference.require(type(payload) is bytes and len(payload) <= 2 * 1024 * 1024,
                                              'PROVIDER_WIRE_BOUND')
                            storage.write_bytes(directory / (identifier + '-' + kind + '.json'), payload)
                    reference.require(response.get('model') == judge_client.PINNED_MODEL, 'PROVIDER_MODEL_DRIFT')
                    # Re-check with the ported client even when an injected transport returns a result.
                    answers = {qid: judge_client.validate_choice_answer(dict(response['answers'][qid],
                        probabilities=response['answers'][qid].get('provider_probabilities', response['answers'][qid]['probabilities'])),
                        criteria=question['criteria'], question_id=qid) for qid, question in batch['questions'].items()}
                    reference.require(set(response['answers']) == set(batch['questions']), 'PROVIDER_ANSWER_COVERAGE')
                    usage = response['usage']
                    reference.require(all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')),
                                      'PROVIDER_USAGE_UNKNOWN')
                    storage.save(directory / (identifier + '.json'), dict(batch_id=batch['id'], repeat=repeat,
                        answers=answers, usage=usage, batch_sha256=reference.digest(batch),
                        model=judge_client.PINNED_MODEL, automatic_retry=False))
                    ledger.complete(identifier, succeeded=True, usage=usage)
                    results.append(answers)
                except Exception as exc:
                    stopped.set()
                    payload = getattr(exc, 'provider_response_payload', None)
                    if type(payload) is bytes:
                        storage.write_bytes(directory / (identifier + '-failed-response.json'), payload[:2 * 1024 * 1024])
                    if reserved:
                        ledger.complete(identifier, succeeded=False)
                    storage.save(directory / (identifier + '-stopped.json'), dict(status='OUTCOME_UNKNOWN',
                        reason='PROVIDER_OR_VALIDATION_FAILURE', error_type=type(exc).__name__,
                        reservation_retained=reserved, automatic_retry=False))
                    break
            return batch, results
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(dispatch, batch) for batch in plan['batches']]
            for future in as_completed(futures):
                batch, results = future.result()
                for qid, identifier in batch['mapping'].items():
                    observations[identifier] = [value[qid] for value in results]
        routed = ir.route(plan, observations)
        storage.save(directory / 'route.json', routed)
        budget = storage.read(directory / 'ledger.json') if (directory / 'ledger.json').exists() else None
        result = reference.seal(dict(status='STOPPED' if stopped.is_set() else 'COMPLETE',
            output=str(directory), plan_sha256=plan['record_sha256'], provider_calls=len(budget['attempts']) if budget else 0,
            provider_call_count_basis='RESERVED_DISPATCH_ATTEMPTS_NOT_PROVIDER_RECEIPTS',
            reserved=budget['reserved'] if budget else '0', currency='jev_usd', invoiced_cost=None,
            attempted_questions=len(plan['requests']), unknown_or_partial_questions=sum(len(v) != 3 for v in observations.values()),
            automatic_retry=False, natural_truth_certified=False, probabilities_calibrated=False,
            execution_authority=False, route_sha256=routed['record_sha256']))
        storage.save(directory / 'terminal.json', result)
        return result
