"""Replay a source-to-IR-to-judge path from exact, request-bound saved exchanges."""
import base64
import binascii
from copy import deepcopy
import hashlib
import json

from . import generation, generator, ir, judge_client, reference, storage

SCHEMA = 'reqlox.incident-pipeline-replay-bundle.v1'
MAXIMUM_WIRE_BYTES = 2 * 1024 * 1024


def wire(payload):
    """Retain original bytes; a digest alone does not certify a provider origin."""
    reference.require(type(payload) is bytes and 0 < len(payload) <= MAXIMUM_WIRE_BYTES, 'REPLAY_WIRE_BOUND')
    return dict(body_base64=base64.b64encode(payload).decode(), sha256=hashlib.sha256(payload).hexdigest())


def _body(record):
    reference.require(type(record) is dict and set(record) == {'body_base64', 'sha256'}, 'REPLAY_WIRE_FIELDS')
    reference.require(type(record['body_base64']) is str and len(record['body_base64']) <= (MAXIMUM_WIRE_BYTES + 2) // 3 * 4,
                      'REPLAY_WIRE_BOUND')
    try:
        raw = base64.b64decode(record['body_base64'], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('REPLAY_WIRE_ENCODING') from exc
    reference.require(0 < len(raw) <= MAXIMUM_WIRE_BYTES and hashlib.sha256(raw).hexdigest() == record['sha256'],
                      'REPLAY_WIRE_HASH')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            reference.require(key not in value, 'REPLAY_DUPLICATE_FIELD')
            value[key] = item
        return value
    json.loads(raw, object_pairs_hook=unique,
               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('REPLAY_NONFINITE_JSON')))
    return raw


def generation_request(plan):
    return generation.request_body(plan)


def judge_request(batch):
    return judge_client.canonical_json_bytes(dict(state=batch['state'], model=judge_client.PINNED_MODEL,
                                                questions=batch['questions']))


def _exchange(value, expected_request):
    reference.require(type(value) is dict and set(value) == {'request', 'response', 'http_status'}, 'REPLAY_EXCHANGE_FIELDS')
    reference.require(type(value['http_status']) is int and 100 <= value['http_status'] <= 599, 'REPLAY_HTTP_STATUS')
    request, response = _body(value['request']), _body(value['response'])
    reference.require(request == expected_request, 'REPLAY_REQUEST_BINDING')
    return request, response, value['http_status']


def evaluate(bundle):
    """Use the existing protocol parsers and routing code without network or keys."""
    reference.check_seal(bundle)
    reference.require(set(bundle) == {'schema_version', 'response_provenance', 'generation_plan', 'generation_exchange',
                                     'judge_exchanges', 'record_sha256'} and bundle['schema_version'] == SCHEMA,
                      'REPLAY_BUNDLE_CONTRACT')
    reference.require(bundle['response_provenance'] in ('OWNED_SYNTHETIC_CONTROL', 'SAVED_PROVIDER_EXCHANGES'),
                      'REPLAY_PROVENANCE')
    plan = bundle['generation_plan']
    generation.validate_plan(plan)
    gen_request, gen_response, gen_status = _exchange(bundle['generation_exchange'], generation_request(plan))
    def gen_transport(url, headers, payload, timeout):
        reference.require(payload == gen_request, 'REPLAY_GENERATION_REQUEST')
        return gen_status, gen_response
    client = generator.VertexGeminiFlashClient(project_id=plan['project_id'], total_attempts=1,
                                               token_provider=lambda: 'LOCAL_REPLAY_ONLY', transport=gen_transport)
    response = client.generate_structured(prompt=plan['prompt'], system_instruction=plan['system_instruction'],
        response_schema=deepcopy(plan['response_schema']), max_output_tokens=plan['maximum_output_tokens'])
    candidate = generation.materialize(plan, response['output'])
    review = ir.freeze(candidate, {plan['source_id']: plan['source_text']}, created_at=plan['created_at'])
    batches = {batch['id']: batch for batch in review['batches']}
    exchanges = bundle['judge_exchanges']
    reference.require(type(exchanges) is list and len(exchanges) <= review['maximum_calls'], 'REPLAY_CALL_BOUND')
    observations, seen, failures, raw = {}, set(), [], []
    for item in exchanges:
        reference.require(type(item) is dict and set(item) == {'batch_id', 'repeat', 'exchange'}, 'REPLAY_JUDGE_FIELDS')
        ident, repeat = item['batch_id'], item['repeat']
        reference.require(type(ident) is str and ident in batches and type(repeat) is int and 0 <= repeat <= 2,
                          'REPLAY_JUDGE_ID')
        reference.require((ident, repeat) not in seen, 'REPLAY_DUPLICATE_ATTEMPT')
        seen.add((ident, repeat))
        batch = batches[ident]
        request, payload, status = _exchange(item['exchange'], judge_request(batch))
        raw.append(dict(batch_id=ident, repeat=repeat, request=request, response=payload))
        def transport(url, headers, expected, timeout):
            reference.require(expected == request, 'REPLAY_JUDGE_REQUEST')
            return status, payload, {}
        try:
            value = judge_client.JevSystemOneClient(key='LOCAL_REPLAY_ONLY', transport=transport).evaluate(
                state=batch['state'], questions=batch['questions'])
        except judge_client.JevSystemOneError as exc:
            failures.append(dict(batch_id=ident, repeat=repeat, status='OUTCOME_UNKNOWN',
                                 error_type=type(exc).__name__, http_status=status))
            continue
        for qid, row_id in batch['mapping'].items():
            observations.setdefault(row_id, {})[repeat] = value['answers'][qid]
    judgments = {key:[values[n] for n in sorted(values)] for key, values in observations.items()}
    route = ir.route(review, judgments)
    unknown = sum(len(judgments.get(r['id'], [])) != 3 for r in review['requests'])
    result = reference.seal(dict(schema_version='reqlox.incident-pipeline-replay-result.v1',
        status='REPLAY_COMPLETE' if not unknown and not failures else 'REPLAY_PARTIAL',
        response_provenance=bundle['response_provenance'], bundle_sha256=bundle['record_sha256'],
        source_sha256=plan['source_sha256'], generation_plan_sha256=plan['record_sha256'],
        candidate_sha256=candidate['record_sha256'], review_plan_sha256=review['record_sha256'],
        route_sha256=route['record_sha256'], archived_judge_exchanges=len(exchanges),
        attempted_questions=len(review['requests']), unknown_or_partial_questions=unknown,
        archived_failures=failures, provider_calls=0, target_executions=0, credentials_read=False,
        live_provider_connectivity_verified=False, saved_response_origin_certified=False,
        natural_truth_certified=False, probabilities_calibrated=False, canonicalization_authority=False,
        execution_authority=False))
    return dict(generation_plan=plan, candidate=candidate, review_plan=review, judgments=judgments,
                route=route, result=result, generation_raw=dict(request=gen_request,response=gen_response), judge_raw=raw)


def replay(bundle_path, *, state_dir=None):
    bundle = storage.checked_record(bundle_path)
    values = evaluate(bundle)
    directory = storage.new_directory(storage.state_directory(state_dir), 'incident-replay')
    storage.save(directory / 'bundle.json', bundle)
    for key, filename in [('generation_plan','generation-plan.json'),('candidate','candidate.json'),
                          ('review_plan','review-plan.json'),('judgments','judgments.json'),
                          ('route','route.json'),('result','result.json')]:
        storage.save(directory / filename, values[key])
    rawdir = storage.private_directory(directory / 'original-exchanges')
    for kind, payload in values['generation_raw'].items():
        storage.write_bytes(rawdir / ('generation-' + kind + '.json'), payload)
    for row in values['judge_raw']:
        for kind in ('request','response'):
            storage.write_bytes(rawdir / f'{row["batch_id"]}-{row["repeat"]}-{kind}.json', row[kind])
    return dict(status=values['result']['status'], output=str(directory),
                result_sha256=values['result']['record_sha256'], response_provenance=bundle['response_provenance'],
                unknown_or_partial_questions=values['result']['unknown_or_partial_questions'],
                provider_calls=0, target_executions=0, credentials_read=False)


def export_archive(generation_directory, judge_directory, *, state_dir=None):
    """Collect existing stage archives; missing wire evidence cannot be fabricated."""
    from pathlib import Path
    gen = Path(generation_directory).absolute()
    judge = Path(judge_directory).absolute()
    plan = storage.checked_record(gen / 'generation-plan.json')
    generation.validate_plan(plan)
    review = storage.checked_record(judge / 'review-plan.json')
    ir.validate_plan(review)
    reference.require(storage.checked_record(gen / 'review-plan.json') == review, 'REPLAY_REVIEW_PLAN_BINDING')
    def saved(path):
        # read() rejects linked and oversized inputs and duplicate JSON fields.
        storage.read(path, maximum_bytes=MAXIMUM_WIRE_BYTES)
        return path.read_bytes()
    exchange = dict(request=wire(saved(gen / 'request-body.json')),
                    response=wire(saved(gen / 'response-body.json')), http_status=200)
    rows=[]
    for batch in review['batches']:
        for repeat in range(3):
            ident = batch['id'] + '-repeat-' + str(repeat)
            response = judge / (ident + '-response.json')
            if not response.exists():
                continue
            rows.append(dict(batch_id=batch['id'], repeat=repeat, exchange=dict(
                request=wire(saved(judge / (ident + '-request.json'))), response=wire(saved(response)),http_status=200)))
    bundle = reference.seal(dict(schema_version=SCHEMA, response_provenance='SAVED_PROVIDER_EXCHANGES',
        generation_plan=plan, generation_exchange=exchange, judge_exchanges=rows))
    values = evaluate(bundle)
    reference.require(values['review_plan'] == review, 'REPLAY_GENERATION_REVIEW_BINDING')
    directory = storage.new_directory(storage.state_directory(state_dir), 'incident-archive')
    storage.save(directory / 'bundle.json', bundle)
    return dict(status='ARCHIVE_EXPORTED', bundle=str(directory / 'bundle.json'),
                bundle_sha256=bundle['record_sha256'], replay_status=values['result']['status'],
                provider_calls=0, target_executions=0, saved_response_origin_certified=False)
