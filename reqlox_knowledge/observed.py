"""Reusable observed methods from the development implementation."""
import copy
import hashlib
from .reference import digest, require, seal
from . import native as native
from .fidelity import validate_hypothesis_set

def request(assertion, evidence, source_hash, *, hypothesis_id):
    sid = 'atomicity_' + digest([hypothesis_id, assertion, source_hash])[:24]
    return dict(id=sid, purpose='assertion_evidence_fidelity', subject=dict(id=sid, type='observed_event_atomicity'), source_refs=dict(hypothesis_set_id=hypothesis_id, assertion_id=assertion['assertion_id']), input=dict(source_document_sha256=source_hash, claim_atom=dict(statement='The supplied candidate assertion describes exactly one source-reported actual observed event or condition, with one predicate and necessary arguments. It does not combine separate actions or events and does not merely classify a component or state general or hypothetical advice.', predicate='is_one_actual_observed_event_or_condition', arguments=[dict(role='candidate_assertion', value=assertion)]), evidence_spans=evidence), choices=['ENTAILED', 'CONTRADICTED', 'INSUFFICIENT_INFORMATION'])

def requests(candidate):
    validate_hypothesis_set(candidate)
    evidence = {s['evidence_id']: s for s in candidate['evidence_spans']}
    return [request(a, [evidence[k] for k in a['evidence_ids']], candidate['source']['source_document_sha256'], hypothesis_id=candidate['id']) for a in candidate['observed_assertions']]

def controls():
    rows = []
    key = {}
    for index, (quote, statement, predicate, wanted) in enumerate([('During incident A the worker crashed.', 'The worker crashed.', 'crashed', 'ENTAILED'), ('During incident B memory was exhausted.', 'Memory was exhausted.', 'exhausted', 'ENTAILED'), ('During incident C the worker crashed and the cache reset.', 'The worker crashed and the cache reset.', 'crashed_and_reset', 'CONTRADICTED'), ('During incident D the operator drained traffic and then restarted the service.', 'The operator drained traffic and restarted the service.', 'drained_and_restarted', 'CONTRADICTED'), ('A worker may crash when memory is exhausted. This is general advice.', 'A worker may crash when memory is exhausted.', 'may_crash', 'CONTRADICTED'), ('The affected component was a cache. No occurrence is described.', 'The component belongs to caching.', 'classified_as_cache', 'CONTRADICTED')]):
        sha = hashlib.sha256(quote.encode()).hexdigest()
        eid = 'ev_' + sha[:20]
        assertion = dict(assertion_id='owned-atomicity-' + str(index), statement=statement, predicate=predicate, arguments=[], evidence_ids=[eid])
        row = request(assertion, [dict(evidence_id=eid, start_char=0, end_char=len(quote), content_hash=sha, text=quote)], sha, hypothesis_id='owned-atomicity-' + str(index))
        rows.append(row)
        key[row['id']] = dict(wanted=wanted, purpose=row['purpose'])
    return (rows, key)

def project(candidate, fidelity_projection, atomic_requests, judgments, *, controls_pass):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    validate_hypothesis_set(candidate)
    if not controls_pass or fidelity_projection is None:
        return None
    validate_hypothesis_set(fidelity_projection)
    require(fidelity_projection['source'] == candidate['source'] and fidelity_projection['authority'] == candidate['authority'], 'ATOMICITY_FIDELITY_SOURCE_BINDING')
    for field, key in [('observed_assertions', 'assertion_id'), ('attribute_assertions', 'attribute_id'), ('relation_hypotheses', 'relation_hypothesis_id'), ('evidence_spans', 'evidence_id')]:
        original = {r[key]: r for r in candidate[field]}
        require(all((original.get(r[key]) == r for r in fidelity_projection[field])), 'ATOMICITY_FIDELITY_ROW_DRIFT')
    original_events = {e['event_hypothesis_id']: e for e in candidate['event_hypotheses']}
    for event in fidelity_projection['event_hypotheses']:
        original = original_events.get(event['event_hypothesis_id'])
        require(original is not None and set(event['attribute_ids']) <= set(original['attribute_ids']) and (event == dict(original, attribute_ids=event['attribute_ids'])), 'ATOMICITY_FIDELITY_EVENT_DRIFT')
    require(len(atomic_requests) == len(candidate['observed_assertions']) and {r['source_refs']['assertion_id'] for r in atomic_requests} == {a['assertion_id'] for a in candidate['observed_assertions']}, 'ATOMICITY_REQUEST_COVERAGE')
    accepted = set()
    for row in atomic_requests:
        answers = judgments.get(row['id'], [])
        require(len(answers) <= 3, 'ATOMICITY_REPEAT_OVERFLOW')
        if len(answers) == 3 and all((native.positive(a, 'assertion_evidence_fidelity') for a in answers)):
            accepted.add(row['source_refs']['assertion_id'])
    value = copy.deepcopy(fidelity_projection)
    events = [e for e in value['event_hypotheses'] if set(e['assertion_ids']) <= accepted]
    if not events:
        return None
    event_ids = {e['event_hypothesis_id'] for e in events}
    assertion_ids = {a for e in events for a in e['assertion_ids']}
    assertions = [a for a in value['observed_assertions'] if a['assertion_id'] in assertion_ids]
    attributes = [a for a in value['attribute_assertions'] if a['attribute_id'] in {k for e in events for k in e['attribute_ids']}]
    relations = [r for r in value['relation_hypotheses'] if {r['from_event_hypothesis_id'], r['to_event_hypothesis_id']} <= event_ids]
    evidence_ids = {k for a in [*assertions, *attributes, *relations] for k in a['evidence_ids']}
    value.update(id='irhs_' + digest([candidate['id'], 'atomicity-projection', sorted(assertion_ids)])[:20], event_hypotheses=events, observed_assertions=assertions, attribute_assertions=attributes, relation_hypotheses=relations, evidence_spans=[e for e in value['evidence_spans'] if e['evidence_id'] in evidence_ids], limitations=[*candidate['limitations'], 'Assertion fidelity and atomicity are separate three-repeat gates. This projection still requires its own same-incident boundary review; the rejected parent remains unchanged.'])
    value = seal(value)
    validate_hypothesis_set(value)
    return value
