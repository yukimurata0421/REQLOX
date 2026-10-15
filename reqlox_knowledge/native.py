"""Reusable native methods from the development implementation."""
from collections import defaultdict
import copy
from .fidelity import validate_hypothesis_set
from .reference import require, seal
EXPECTED = dict(assertion_evidence_fidelity='ENTAILED', attribute_origin_fidelity='SOURCE_ENTAILED', relation_evidence_fidelity='SUPPORTED')

def positive(answer, purpose):
    wanted = EXPECTED[purpose]
    return answer['choice'] == wanted and min(answer['confidence'], answer['probabilities'][wanted]) >= 0.85

def route(candidate, requests, judgments):
    validate_hypothesis_set(candidate)
    accepted = {}
    for request in requests:
        answers = judgments.get(request['id'], [])
        require(len(answers) <= 3, 'NATIVE_REVIEW_REPEAT_OVERFLOW')
        accepted[request['subject']['id']] = len(answers) == 3 and all((positive(a, request['purpose']) for a in answers))
    assertion_ids = {r['assertion_id'] for r in candidate['observed_assertions'] if accepted.get(r['assertion_id'], False)}
    tentative = {e['event_hypothesis_id'] for e in candidate['event_hypotheses'] if set(e['assertion_ids']) <= assertion_ids}
    groups = defaultdict(list)
    for e in candidate['event_hypotheses']:
        groups[e['hypothesis_group_id']].append(e['event_hypothesis_id'])
    selected = {ids[0] for members in groups.values() if len((ids := [x for x in members if x in tentative])) == 1 and len(members) == 1}
    relations = []
    r_groups = defaultdict(list)
    for r in candidate['relation_hypotheses']:
        r_groups[r['hypothesis_group_id']].append(r)
    for members in r_groups.values():
        if len(members) != 1:
            continue
        r = members[0]
        if accepted.get(r['relation_hypothesis_id'], False) and r['declared_origin'] == 'SOURCE_ENTAILED' and ({r['from_event_hypothesis_id'], r['to_event_hypothesis_id']} <= selected):
            relations.append(copy.deepcopy(r))
    if not selected:
        return (None, dict(accepted_event_cores=0, accepted_relations=0, unresolved=True))
    events = []
    attributes = []
    used_assertions = set()
    used_evidence = set()
    attrs = {a['attribute_id']: a for a in candidate['attribute_assertions']}
    for original in candidate['event_hypotheses']:
        if original['event_hypothesis_id'] not in selected:
            continue
        e = copy.deepcopy(original)
        e['attribute_ids'] = [a for a in e['attribute_ids'] if accepted.get(a, False) and attrs[a]['declared_origin'] == 'SOURCE_ENTAILED']
        events.append(e)
        used_assertions.update(e['assertion_ids'])
        attributes.extend((copy.deepcopy(attrs[a]) for a in e['attribute_ids']))
    assertions = [copy.deepcopy(a) for a in candidate['observed_assertions'] if a['assertion_id'] in used_assertions]
    for row in [*assertions, *attributes, *relations]:
        used_evidence.update(row['evidence_ids'])
    value = copy.deepcopy(candidate)
    value.update(observed_assertions=assertions, attribute_assertions=attributes, event_hypotheses=events, relation_hypotheses=relations, evidence_spans=[copy.deepcopy(e) for e in candidate['evidence_spans'] if e['evidence_id'] in used_evidence], limitations=[*candidate['limitations'], 'Three repeat source-fidelity judgments, with endpoint closure and nonblocking enrichment. Original alternatives remain in the frozen generation artifact.'])
    value = seal(value)
    validate_hypothesis_set(value)
    return (value, dict(accepted_event_cores=len(events), accepted_relations=len(relations), unresolved=False))
