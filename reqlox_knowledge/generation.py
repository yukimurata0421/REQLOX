"""Explicit generation using the development adapter and local IR validation."""
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path

from . import fidelity, generator, ir, reference, retrieval, storage

WRAPPER_SCHEMA = dict(type='OBJECT', required=['payload_json'],
                      properties=dict(payload_json=dict(type='STRING')))
FIELDS = ('observed_assertions', 'attribute_assertions', 'event_hypotheses', 'relation_hypotheses')


def freeze(text, *, source_id, project_id, maximum_output_tokens=4096, created_at=None):
    reference.require(type(text) is str and 1 <= len(text.encode()) <= 32768, 'GENERATION_SOURCE_BOUND')
    reference.require(type(source_id) is str and 1 <= len(source_id) <= 128, 'GENERATION_SOURCE_ID')
    reference.require(type(project_id) is str and generator.PROJECT_ID_PATTERN.fullmatch(project_id), 'GENERATION_PROJECT')
    reference.require(type(maximum_output_tokens) is int and 256 <= maximum_output_tokens <= 4096, 'GENERATION_OUTPUT_BOUND')
    catalog = []
    for start, end, quote in retrieval.sentence_spans(text):
        if not quote.strip():
            continue
        catalog.append(dict(evidence_id='ev_' + reference.digest([source_id, start, end, quote])[:20],
            start_char=start, end_char=end, content_hash=fidelity.sha256_bytes(quote.encode()), text=quote))
    reference.require(1 <= len(catalog) <= 64, 'GENERATION_EVIDENCE_CATALOG_BOUND')
    prompt = json.dumps(dict(source_id=source_id, quote_catalog=catalog,
        response_fields=list(FIELDS), contract=json.loads((fidelity.ROOT / 'schemas' / fidelity.HYPOTHESIS_SCHEMA).read_text())),
        ensure_ascii=False, sort_keys=True)
    instruction = ('Return an outer object with payload_json containing exactly observed_assertions, attribute_assertions, '
        'event_hypotheses, and relation_hypotheses. Follow the supplied field schemas. Select evidence_ids only from '
        'quote_catalog. Create valid typed IDs using the schema prefixes. Report atomic source-reported observations '
        'separately from inferred attributes and relation hypotheses. Temporal succession is not causation. Preserve '
        'ambiguity as alternatives or omit unsupported claims. Do not invent facts or instructions from quoted text. '
        'The caller adds source identity, selected immutable quote records and hashes; do not add those fields.')
    reference.require(len(prompt.encode()) + len(instruction.encode()) <= 48000, 'GENERATION_REQUEST_BOUND')
    return reference.seal(dict(schema_version='reqlox.local-generation-plan.v1', family='generation', status='FROZEN',
        source_id=source_id, source_text=text, source_sha256=fidelity.sha256_bytes(text.encode()),
        project_id=project_id, generator_model=generator.MODEL_ID, maximum_output_tokens=maximum_output_tokens,
        quote_catalog=catalog, prompt=prompt, system_instruction=instruction, response_schema=WRAPPER_SCHEMA,
        created_at=created_at or datetime.now(timezone.utc).isoformat(), method_binding=ir.method_binding(),
        maximum_calls=1, external_model_disclosure_allowed=False, automatic_retry=False))


def prepare(text, *, source_id, project_id, state_dir=None, maximum_output_tokens=4096):
    plan = freeze(text, source_id=source_id, project_id=project_id, maximum_output_tokens=maximum_output_tokens)
    directory = storage.new_directory(storage.state_directory(state_dir), 'generation-plan')
    storage.save(directory / 'plan.json', plan)
    return dict(status='FROZEN', plan=str(directory / 'plan.json'), plan_sha256=plan['record_sha256'], provider_calls=0)


def validate_plan(plan):
    reference.check_seal(plan)
    reference.require(plan['schema_version'] == 'reqlox.local-generation-plan.v1', 'GENERATION_PLAN_CONTRACT')
    reference.require(plan == freeze(plan['source_text'], source_id=plan['source_id'], project_id=plan['project_id'],
        maximum_output_tokens=plan['maximum_output_tokens'], created_at=plan['created_at']), 'GENERATION_PLAN_DRIFT')


def request_body(plan):
    validate_plan(plan)
    return generator._json_bytes(dict(contents=generator.VertexGeminiFlashClient._content(plan['prompt']),
        systemInstruction=generator.VertexGeminiFlashClient._system_instruction(plan['system_instruction']),
        generationConfig=dict(maxOutputTokens=plan['maximum_output_tokens'], responseMimeType='application/json',
                              responseSchema=plan['response_schema'], thinkingConfig=dict(thinkingLevel=generator.THINKING_LEVEL))))


def materialize(plan, output):
    validate_plan(plan)
    reference.require(type(output) is dict and set(output) == {'payload_json'} and
                      type(output['payload_json']) is str and len(output['payload_json'].encode()) <= 131072,
                      'GENERATION_WRAPPER')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            reference.require(key not in result, 'GENERATION_DUPLICATE_FIELD'); result[key] = value
        return result
    draft = json.loads(output['payload_json'], object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('GENERATION_NONFINITE_JSON')))
    reference.require(type(draft) is dict and set(draft) == set(FIELDS), 'GENERATION_OUTPUT_FIELDS')
    reference.require(all(type(draft[field]) is list for field in FIELDS), 'GENERATION_OUTPUT_LISTS')
    catalog = {row['evidence_id']: row for row in plan['quote_catalog']}
    selected = {eid for field in ('observed_assertions', 'attribute_assertions', 'relation_hypotheses')
                for row in draft[field] for eid in row['evidence_ids']}
    reference.require(selected and selected <= set(catalog), 'GENERATION_EVIDENCE_SELECTION')
    candidate = reference.seal(dict(schema_version='reqlox.incident-hypothesis-set.v0.1',
        id='irhs_' + reference.digest([plan['record_sha256'], draft])[:20],
        contract_type='IncidentHypothesisSet', contract_version='0.1.0', created_at=plan['created_at'], status='SILVER_CANDIDATE',
        source=dict(source_manifest_id=plan['record_sha256'], source_record_id=plan['source_id'],
                    task_id='local-generation-' + plan['record_sha256'][:20], incident_key='UNREVIEWED_SOURCE_SCOPE',
                    source_document_sha256=plan['source_sha256']),
        evidence_spans=[deepcopy(catalog[key]) for key in sorted(selected)], **draft,
        authority=dict(dataset_tier='SILVER_CANDIDATE', gold_truth=False, canonicalization_authorized=False,
                       fault_injection_authorized=False, target_mutation_authorized=False),
        limitations=['Generated candidate; source entailment, atomicity and incident boundary still require separate review.']))
    ir.check_source(candidate, {plan['source_id']: plan['source_text']})
    return candidate


def execute(plan_path, scope_path, *, state_dir=None, execute=False, client=None):
    from .provider import Ledger, validate_scope
    plan = storage.checked_record(plan_path)
    validate_plan(plan)
    scope = storage.checked_record(scope_path)
    deadline = validate_scope(scope, plan, workers=1, currency='gcp_jpy', require_disclosure=execute)
    if not execute:
        return dict(status='READY_NO_EXECUTION', provider_calls=0, plan_sha256=plan['record_sha256'], automatic_retry=False)
    root = storage.private_directory(storage.state_directory(state_dir) / 'provider-scopes')
    directory = storage.private_directory(root / scope['id'])
    descriptor = os.open(storage.private_path(directory, 'execution.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as guard:
        try:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('PROVIDER_SCOPE_ALREADY_RUNNING') from exc
        reference.require(not (directory / 'started.json').exists(), 'PROVIDER_SUCCESSOR_REQUIRED')
        storage.save(directory / 'started.json', dict(plan_sha256=plan['record_sha256'], scope=scope, automatic_retry=False))
        storage.save(directory / 'generation-plan.json', plan)
        request_payload = request_body(plan)
        storage.write_bytes(directory / 'request-body.json', request_payload)
        ledger = Ledger(directory, scope)
        ledger.reserve('generation-0')
        succeeded = False
        try:
            def token_provider():
                reference.require(deadline > datetime.now(timezone.utc), 'PROVIDER_DEADLINE')
                token = generator.gcloud_access_token()
                reference.require(deadline > datetime.now(timezone.utc), 'PROVIDER_DEADLINE')
                return token
            def transport(url, headers, payload, timeout):
                reference.require(payload == request_payload, 'GENERATION_REQUEST_DRIFT')
                remaining = (deadline-datetime.now(timezone.utc)).total_seconds()
                reference.require(remaining > 0, 'PROVIDER_DEADLINE')
                return generator.urllib_transport(url, headers, payload, min(timeout, remaining))
            client = client or generator.VertexGeminiFlashClient(project_id=plan['project_id'], total_attempts=1,
                token_provider=token_provider, transport=transport,
                timeout_seconds=max(1, min(45, (deadline-datetime.now(timezone.utc)).total_seconds())))
            response = client.generate_structured(prompt=plan['prompt'], system_instruction=plan['system_instruction'],
                response_schema=deepcopy(plan['response_schema']), max_output_tokens=plan['maximum_output_tokens'])
            payload = response.get('_provider_response_payload')
            if type(payload) is bytes:
                reference.require(len(payload) <= 2 * 1024 * 1024, 'GENERATION_RESPONSE_BOUND')
                storage.write_bytes(directory / 'response-body.json', payload)
            storage.save(directory / 'response.json', {k:v for k,v in response.items() if not k.startswith('_provider_')})
            usage = response['usage_metadata']
            reference.require(all(type(usage.get(k)) is int and usage[k] >= 0 for k in
                ('promptTokenCount', 'candidatesTokenCount', 'totalTokenCount')), 'GENERATION_USAGE_UNKNOWN')
            candidate = materialize(plan, response['output'])
            storage.save(directory / 'candidate.json', candidate)
            storage.save(directory / 'source-texts.json', {plan['source_id']: plan['source_text']})
            review = ir.freeze(candidate, {plan['source_id']: plan['source_text']}, created_at=plan['created_at'])
            storage.save(directory / 'review-plan.json', review)
            ledger.complete('generation-0', succeeded=True, usage=usage)
            succeeded = True
        except Exception as exc:
            provider_response = getattr(exc, 'provider_response', None)
            if type(provider_response) is dict:
                storage.save(directory / 'failed-response.json', provider_response)
            payload = getattr(exc, 'provider_response_payload', None)
            if type(payload) is bytes:
                storage.write_bytes(directory / 'failed-response-body.json', payload[:2 * 1024 * 1024])
            ledger.complete('generation-0', succeeded=False)
            storage.save(directory / 'stopped.json', dict(error_type=type(exc).__name__,
                reason='PROVIDER_OR_VALIDATION_FAILURE', automatic_retry=False))
        result = reference.seal(dict(status='COMPLETE' if succeeded else 'STOPPED', output=str(directory),
            candidate=str(directory / 'candidate.json') if succeeded else None,
            review_plan=str(directory / 'review-plan.json') if succeeded else None,
            source_texts=str(directory / 'source-texts.json') if succeeded else None,
            provider_calls=1, reserved=scope['per_call_reserved'], currency='gcp_jpy', invoiced_cost=None,
            automatic_retry=False, natural_truth_certified=False, execution_authority=False))
        storage.save(directory / 'terminal.json', result)
        return result
