"""Reusable reference audit methods from the development implementation."""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from .reference import FLOOR, check_seal, digest, probabilities, require, seal
from .reference_questions import PRESENCE_CRITERIA, SUPPORT_CRITERIA

def checked_answer(answer, categories):
    probabilities(answer['probabilities'], categories)
    require(answer['choice'] in categories, 'REFERENCE_AUDIT_ANSWER_CHOICE')
    return answer

def candidate_ir(packet, draft, source, support, mechanical):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    from .reference import route_reference
    reference = route_reference(packet, draft, source, support, mechanical)
    adopted_events = {e['id'] for e in reference['events']}
    adopted_edges = {e['id'] for e in reference['edges']}
    events, edges = ([], [])
    for event in draft['events']:
        present = checked_answer(source['primitive_' + event['primitive']], PRESENCE_CRITERIA)
        supported = checked_answer(support['event_' + event['id']], SUPPORT_CRITERIA)
        reasons = []
        if supported['choice'] != 'SUPPORTED':
            reasons.append('SUPPORT_' + supported['choice'])
        elif supported['probabilities']['SUPPORTED'] < FLOOR:
            reasons.append('SUPPORT_BELOW_FLOOR')
        if event['origin'] == 'SOURCE_OBSERVED':
            if present['choice'] != 'PRESENT':
                reasons.append('PRESENCE_' + present['choice'])
            elif present['probabilities']['PRESENT'] < FLOOR:
                reasons.append('PRESENCE_BELOW_FLOOR')
        if supported['probabilities'][supported['choice']] < max(supported['probabilities'].values()):
            reasons.append('SUPPORT_CHOICE_DIFFERS_FROM_PROBABILITY_ARGMAX')
        if present['probabilities'][present['choice']] < max(present['probabilities'].values()):
            reasons.append('PRESENCE_CHOICE_DIFFERS_FROM_PROBABILITY_ARGMAX')
        rejected = supported['choice'] == 'NOT_SUPPORTED' or (event['origin'] == 'SOURCE_OBSERVED' and present['choice'] == 'ABSENT')
        state = 'ADMITTED_LLM_CORE' if event['id'] in adopted_events else 'REJECTED_LLM_CANDIDATE' if rejected else 'UNCERTAIN_LLM_CANDIDATE'
        events.append(dict(claim=deepcopy(event), span=mechanical['event_spans'][event['id']], state=state, reasons=reasons, source_presence=deepcopy(present), support=deepcopy(supported)))
    for edge in draft['edges']:
        answer = checked_answer(support['edge_' + edge['id']], SUPPORT_CRITERIA)
        endpoints = edge['from_event'] in adopted_events and edge['to_event'] in adopted_events
        reasons = []
        if not endpoints:
            reasons.append('ENDPOINT_NOT_ADMITTED')
        if answer['choice'] != 'SUPPORTED':
            reasons.append('SUPPORT_' + answer['choice'])
        elif answer['probabilities']['SUPPORTED'] < FLOOR:
            reasons.append('SUPPORT_BELOW_FLOOR')
        state = 'ADMITTED_LLM_CORE' if edge['id'] in adopted_edges else 'REJECTED_LLM_CANDIDATE' if answer['choice'] == 'NOT_SUPPORTED' else 'UNCERTAIN_LLM_CANDIDATE'
        edges.append(dict(claim=deepcopy(edge), span=mechanical['edge_spans'][edge['id']], state=state, reasons=reasons, endpoints_admitted=endpoints, support=deepcopy(answer)))
    return seal(dict(schema_version='reqlox.incident-candidate-ir.v0.1', task_id=packet['task_ref']['id'], source_group=packet['subject']['canonical_group_id'], source_text_sha256=packet['subject']['scope']['text_sha256'], packet_sha256=digest(packet), draft_sha256=digest(draft), reference_sha256=digest(reference), authority='LLM_CANDIDATES_WITH_EXACT_SOURCE_ANCHORS', events=events, edges=edges, reference_complete=reference['reference_complete'], omitted_primitives=reference['omitted_primitives'], boundary_eligible=reference['boundary_eligible'], adopted_floor=FLOOR, probabilities_calibrated=False, natural_truth_certified=False, canonicalization_authority=False, execution_authority=False, reference_threshold_changed=False))

def available_claims(value, *, include_uncertain=False):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    check_seal(value)
    require(value['execution_authority'] is False and value['canonicalization_authority'] is False, 'REFERENCE_AUDIT_AUTHORITY')
    states = {'ADMITTED_LLM_CORE'}
    if include_uncertain:
        states.add('UNCERTAIN_LLM_CANDIDATE')
    events = [deepcopy(e) for e in value['events'] if e['state'] in states]
    ids = {e['claim']['id'] for e in events}
    edges = [deepcopy(e) for e in value['edges'] if e['state'] in states and e['claim']['from_event'] in ids and (e['claim']['to_event'] in ids)]
    return dict(events=events, edges=edges, execution_authority=False, natural_truth_certified=False)

def dependency_ids(rows):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]
    for row in rows:
        require(all((type(row.get(k)) is str and row[k] for k in ['task_id', 'source_group', 'source_text_sha256'])), 'REFERENCE_AUDIT_GROUP_IDENTITY')
        parent[find(('group', row['source_group']))] = find(('text', row['source_text_sha256']))
    return {r['task_id']: digest(find(('group', r['source_group']))) for r in rows}

def presence_comparison(rows, predictions):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    from .reference_evaluation import compare_primitive_presence
    ids = dependency_ids(rows)
    grouped = [{**r, 'source_group': ids[r['task_id']]} for r in rows]
    for row in rows:
        for answer in row['answers'].values():
            if set(answer['probabilities']) == set(PRESENCE_CRITERIA):
                checked_answer(answer, PRESENCE_CRITERIA)
    result = compare_primitive_presence(grouped, predictions)
    return seal({**result, 'canonical_or_text_hash_groups': True, 'measurement_unit': 'DOCUMENT_PRIMITIVE_PRESENCE', 'event_identity_or_causal_truth': False})

def admission_audit(values):
    counts = Counter()
    for value in values:
        check_seal(value)
        for kind in ['events', 'edges']:
            counts[kind + '_candidates'] += len(value[kind])
            for row in value[kind]:
                counts[kind + '_' + row['state']] += 1
                for reason in row['reasons']:
                    counts[kind + '_' + reason] += 1
        counts['omitted_primitive_presences'] += len(value['omitted_primitives'])
    return seal(dict(schema_version='reqlox.incident-admission-audit.v0.1', documents=len(values), counts=dict(counts), reasons_can_overlap=True, threshold_changed=False, truth_certified=False, execution_authority=False))

def paired_recall(rows, before, after):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    import random
    old = presence_comparison(rows, before)
    new = presence_comparison(rows, after)
    old_rows = {r['task_id']: r for r in old['rows']}
    groups = defaultdict(list)
    for r in new['rows']:
        groups[r['source_group']].append((old_rows[r['task_id']], r))
    differences = []
    for members in groups.values():
        tp0 = sum((a.get('true_positive', 0) for a, b in members))
        tp1 = sum((b.get('true_positive', 0) for a, b in members))
        positive = sum((a.get('true_positive', 0) + a.get('false_negative', 0) for a, b in members))
        if positive:
            differences.append((tp1 - tp0) / positive)
    interval = None
    if len(differences) > 1:
        rng = random.Random(20261008)
        samples = sorted((sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(2000)))
        interval = [samples[49], samples[1949]]
    return seal(dict(schema_version='reqlox.paired-reference-recall.v0.1', group_equal_weight_difference=sum(differences) / len(differences) if differences else None, groups_with_positive_reference=len(differences), paired_group_bootstrap_interval=interval, bootstrap_samples=2000, conditional_on_saved_llm_reference=True, random_population_sample=False, natural_truth_certified=False, independent_target_success=False, selection_may_be_retrospective=True))
