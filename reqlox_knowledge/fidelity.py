"""Reusable fidelity methods from the development implementation."""
from __future__ import annotations
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from jsonschema import Draft202012Validator, FormatChecker
from .identity import stable_id
from .utils import canonical_json_bytes, sha256_bytes
from .validator import schema_registry
ROOT = Path(__file__).resolve().parent / 'data'
HYPOTHESIS_SCHEMA = 'incident-hypothesis-set.v0.1.schema.json'
REQUEST_SCHEMA = 'provisional-judge-request.v0.2.schema.json'
DEFAULT_POLICY = ROOT / 'policies' / 'jev' / 'incident-ir-element-fidelity.v0.1.json'
PURPOSES = ('assertion_evidence_fidelity', 'attribute_origin_fidelity', 'relation_evidence_fidelity')

class ElementFidelityError(RuntimeError):
    pass

def self_hash(value: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes({key: item for key, item in value.items() if key != 'record_sha256'}))

@lru_cache(maxsize=None)
def _validator(schema_dir: Path, schema_name: str) -> Draft202012Validator:
    schema = json.loads((schema_dir / schema_name).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    registry, _ = schema_registry(schema_dir)
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())

def validate_schema(value: dict[str, Any], schema_dir: Path, schema_name: str, label: str) -> None:
    errors = sorted(_validator(schema_dir, schema_name).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        detail = '; '.join((f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors))
        raise ElementFidelityError(f'{label}: {detail}')

def _unique_index(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ElementFidelityError(f'duplicate {label} ids')
    return result

def _check_refs(owner: str, values: Iterable[str], available: dict[str, Any], label: str) -> None:
    missing = sorted(set(values) - set(available))
    if missing:
        raise ElementFidelityError(f'{owner}: unknown {label}: {missing}')

def validate_hypothesis_set(value: dict[str, Any], *, schema_dir: Path=ROOT / 'schemas', maximum_alternatives: int=3) -> None:
    validate_schema(value, schema_dir, HYPOTHESIS_SCHEMA, 'incident hypothesis set')
    if value['record_sha256'] != self_hash(value):
        raise ElementFidelityError('incident hypothesis set self-hash mismatch')
    evidence = _unique_index(value['evidence_spans'], 'evidence_id', 'evidence')
    assertions = _unique_index(value['observed_assertions'], 'assertion_id', 'assertion')
    attributes = _unique_index(value['attribute_assertions'], 'attribute_id', 'attribute')
    events = _unique_index(value['event_hypotheses'], 'event_hypothesis_id', 'event hypothesis')
    relations = _unique_index(value['relation_hypotheses'], 'relation_hypothesis_id', 'relation hypothesis')
    for span in evidence.values():
        if span['start_char'] >= span['end_char']:
            raise ElementFidelityError(f"{span['evidence_id']}: invalid evidence offsets")
        if span['content_hash'] != sha256_bytes(span['text'].encode('utf-8')):
            raise ElementFidelityError(f"{span['evidence_id']}: evidence content hash mismatch")
    for assertion in assertions.values():
        _check_refs(assertion['assertion_id'], assertion['evidence_ids'], evidence, 'evidence ids')
    for attribute in attributes.values():
        _check_refs(attribute['attribute_id'], attribute['base_assertion_ids'], assertions, 'base assertion ids')
        _check_refs(attribute['attribute_id'], attribute['evidence_ids'], evidence, 'evidence ids')
    for event in events.values():
        _check_refs(event['event_hypothesis_id'], event['assertion_ids'], assertions, 'assertion ids')
        _check_refs(event['event_hypothesis_id'], event['attribute_ids'], attributes, 'attribute ids')
        for attribute_id in event['attribute_ids']:
            if not set(attributes[attribute_id]['base_assertion_ids']).issubset(event['assertion_ids']):
                raise ElementFidelityError(f"{event['event_hypothesis_id']}: attribute {attribute_id} base assertion is outside event")
    attribute_owners: dict[str, list[str]] = defaultdict(list)
    for event in events.values():
        for attribute_id in event['attribute_ids']:
            attribute_owners[attribute_id].append(event['event_hypothesis_id'])
    for attribute_id in attributes:
        owners = attribute_owners.get(attribute_id, [])
        if len(owners) != 1:
            raise ElementFidelityError(f'{attribute_id}: attribute must belong to exactly one event hypothesis, got {owners}')
    for relation in relations.values():
        relation_id = relation['relation_hypothesis_id']
        _check_refs(relation_id, [relation['from_event_hypothesis_id'], relation['to_event_hypothesis_id']], events, 'event hypothesis ids')
        _check_refs(relation_id, [relation['from_assertion_id'], relation['to_assertion_id']], assertions, 'endpoint assertion ids')
        _check_refs(relation_id, relation['evidence_ids'], evidence, 'evidence ids')
        from_event = events[relation['from_event_hypothesis_id']]
        to_event = events[relation['to_event_hypothesis_id']]
        if relation['from_assertion_id'] not in from_event['assertion_ids']:
            raise ElementFidelityError(f'{relation_id}: from assertion is outside from event')
        if relation['to_assertion_id'] not in to_event['assertion_ids']:
            raise ElementFidelityError(f'{relation_id}: to assertion is outside to event')
        if relation['from_event_hypothesis_id'] == relation['to_event_hypothesis_id']:
            raise ElementFidelityError(f'{relation_id}: self relation is not allowed')
    for label, rows in (('event', value['event_hypotheses']), ('relation', value['relation_hypotheses'])):
        groups: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            groups[row['hypothesis_group_id']].append(row['alternative_index'])
        for group_id, indices in groups.items():
            if len(indices) > maximum_alternatives:
                raise ElementFidelityError(f'{group_id}: {label} alternatives exceed bounded maximum {maximum_alternatives}')
            if len(indices) != len(set(indices)):
                raise ElementFidelityError(f'{group_id}: duplicate alternative index')

def load_policy(path: Path=DEFAULT_POLICY) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('record_sha256') != self_hash(value):
        raise ElementFidelityError('element-fidelity policy self-hash mismatch')
    if tuple(value['scope']['purposes']) != PURPOSES:
        raise ElementFidelityError('element-fidelity policy purpose order drifted')
    if set(value['purposes']) != set(PURPOSES):
        raise ElementFidelityError('element-fidelity policy purpose definitions drifted')
    deterministic = value['deterministic_policy']
    if deterministic['threshold_calibrated'] is not False:
        raise ElementFidelityError('element-fidelity threshold must remain marked uncalibrated')
    return value

def _evidence_rows(evidence_by_id: dict[str, dict[str, Any]], evidence_ids: list[str]) -> list[dict[str, Any]]:
    return [{'evidence_id': evidence_by_id[evidence_id]['evidence_id'], 'start_char': evidence_by_id[evidence_id]['start_char'], 'end_char': evidence_by_id[evidence_id]['end_char'], 'content_hash': evidence_by_id[evidence_id]['content_hash'], 'text': evidence_by_id[evidence_id]['text']} for evidence_id in evidence_ids]

def _assertion_value(assertion: dict[str, Any]) -> dict[str, Any]:
    return {'assertion_id': assertion['assertion_id'], 'statement': assertion['statement'], 'predicate': assertion['predicate'], 'arguments': assertion['arguments']}

def _source_refs(candidate: dict[str, Any], *, assertion_id: str | None=None, attribute_id: str | None=None, event_hypothesis_id: str | None=None, relation_hypothesis_id: str | None=None) -> dict[str, Any]:
    source = candidate['source']
    return {'source_kind': 'INCIDENT_HYPOTHESIS_SET', 'source_manifest_id': source['source_manifest_id'], 'source_record_id': source['source_record_id'], 'task_id': source['task_id'], 'incident_key': source['incident_key'], 'hypothesis_set_id': candidate['id'], 'assertion_id': assertion_id, 'attribute_id': attribute_id, 'event_hypothesis_id': event_hypothesis_id, 'relation_hypothesis_id': relation_hypothesis_id}

def _make_request(*, candidate: dict[str, Any], policy: dict[str, Any], purpose: str, subject_id: str, input_value: dict[str, Any], source_refs: dict[str, Any], created_at: str) -> dict[str, Any]:
    purpose_policy = policy['purposes'][purpose]
    input_sha = sha256_bytes(canonical_json_bytes(input_value))
    return {'id': stable_id('pjr_', purpose, subject_id, input_sha), 'contract_type': 'ProvisionalJudgeRequest', 'contract_version': '0.2.0', 'created_at': created_at, 'purpose': purpose, 'subject': {'type': purpose_policy['subject_type'], 'id': subject_id}, 'choices': purpose_policy['choices'], 'insufficient_choice': 'INSUFFICIENT_INFORMATION', 'input': input_value, 'input_sha256': input_sha, 'source_refs': source_refs, 'disclosure': {'status': 'BLOCKED_PENDING_SCOPED_AUTHORIZATION', 'external_api_used': False, 'authorized': False}, 'authority': {'dataset_tier': 'SILVER_CANDIDATE', 'gold_truth': False, 'canonicalization_authorized': False, 'mutation_authority': 'NONE'}, 'limitations': ['Only the named atomic subject and cited evidence spans are in scope.', 'Prior Jev scores, target thresholds, and unrelated document text are absent from input.', 'A judgment is silver evaluation evidence and cannot authorize canonicalization or execution.']}

def build_requests(candidate: dict[str, Any], policy: dict[str, Any], *, created_at: str, schema_dir: Path=ROOT / 'schemas') -> list[dict[str, Any]]:
    evidence = {row['evidence_id']: row for row in candidate['evidence_spans']}
    assertions = {row['assertion_id']: row for row in candidate['observed_assertions']}
    attribute_owner = {attribute_id: event['event_hypothesis_id'] for event in candidate['event_hypotheses'] for attribute_id in event['attribute_ids']}
    requests: list[dict[str, Any]] = []
    for assertion in candidate['observed_assertions']:
        input_value = {'source_document_sha256': candidate['source']['source_document_sha256'], 'claim_atom': _assertion_value(assertion), 'evidence_spans': _evidence_rows(evidence, assertion['evidence_ids'])}
        requests.append(_make_request(candidate=candidate, policy=policy, purpose='assertion_evidence_fidelity', subject_id=assertion['assertion_id'], input_value=input_value, source_refs=_source_refs(candidate, assertion_id=assertion['assertion_id']), created_at=created_at))
    for attribute in candidate['attribute_assertions']:
        input_value = {'source_document_sha256': candidate['source']['source_document_sha256'], 'base_assertions': [_assertion_value(assertions[assertion_id]) for assertion_id in attribute['base_assertion_ids']], 'attribute': {'attribute_id': attribute['attribute_id'], 'field': attribute['field'], 'value': attribute['value'], 'declared_origin': attribute['declared_origin']}, 'evidence_spans': _evidence_rows(evidence, attribute['evidence_ids'])}
        requests.append(_make_request(candidate=candidate, policy=policy, purpose='attribute_origin_fidelity', subject_id=attribute['attribute_id'], input_value=input_value, source_refs=_source_refs(candidate, attribute_id=attribute['attribute_id'], event_hypothesis_id=attribute_owner[attribute['attribute_id']]), created_at=created_at))
    for relation in candidate['relation_hypotheses']:
        input_value = {'source_document_sha256': candidate['source']['source_document_sha256'], 'from_assertion': _assertion_value(assertions[relation['from_assertion_id']]), 'to_assertion': _assertion_value(assertions[relation['to_assertion_id']]), 'relation': {'relation_hypothesis_id': relation['relation_hypothesis_id'], 'type': relation['relation'], 'declared_origin': relation['declared_origin']}, 'evidence_spans': _evidence_rows(evidence, relation['evidence_ids'])}
        requests.append(_make_request(candidate=candidate, policy=policy, purpose='relation_evidence_fidelity', subject_id=relation['relation_hypothesis_id'], input_value=input_value, source_refs=_source_refs(candidate, relation_hypothesis_id=relation['relation_hypothesis_id']), created_at=created_at))
    if len({row['id'] for row in requests}) != len(requests):
        raise ElementFidelityError('duplicate element-fidelity request ids')
    for request in requests:
        validate_schema(request, schema_dir, REQUEST_SCHEMA, request['id'])
        if request['input_sha256'] != sha256_bytes(canonical_json_bytes(request['input'])):
            raise ElementFidelityError(f"{request['id']}: request input hash mismatch")
    return requests
