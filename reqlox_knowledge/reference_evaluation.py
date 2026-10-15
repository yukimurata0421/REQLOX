"""Reusable reference evaluation methods from the development implementation."""
from __future__ import annotations
from collections import Counter, defaultdict
from .reference import FLOOR, require, seal

def compare_primitive_presence(reference_rows, baseline_rows):
    require(len({r['task_id'] for r in reference_rows}) == len(reference_rows) > 0, 'PRESENCE_REFERENCE_DUPLICATE')
    require(set(baseline_rows) == {r['task_id'] for r in reference_rows}, 'PRESENCE_BASELINE_COVERAGE')
    confusion = Counter()
    by_group = defaultdict(Counter)
    unobserved = 0
    task_rows = []
    for row in reference_rows:
        proposal = baseline_rows[row['task_id']]
        if proposal is None:
            unobserved += 1
        observed = {e['primitive'] for i in (proposal or {}).get('incidents', []) for e in i['events'] if e['observation_origin'] == 'SOURCE_OBSERVED'}
        counts = Counter()
        for ident, answer in row['answers'].items():
            if not ident.startswith('primitive_'):
                continue
            primitive = ident[len('primitive_'):]
            choice = answer['choice']
            confident = answer['probabilities'][choice] >= FLOOR
            if choice == 'INSUFFICIENT_INFORMATION' or not confident:
                counts['unknown_reference'] += 1
                continue
            positive = choice == 'PRESENT'
            predicted = primitive in observed
            key = 'true_positive' if positive and predicted else 'false_negative' if positive else 'false_positive' if predicted else 'true_negative'
            counts[key] += 1
        confusion.update(counts)
        by_group[row['source_group']].update(counts)
        task_rows.append(dict(task_id=row['task_id'], source_group=row['source_group'], prediction_observed=proposal is not None, **dict(counts)))

    def ratio(positive, denominator):
        return positive / denominator if denominator else None
    group_precision = [ratio(v['true_positive'], v['true_positive'] + v['false_positive']) for v in by_group.values()]
    group_recall = [ratio(v['true_positive'], v['true_positive'] + v['false_negative']) for v in by_group.values()]
    return seal(dict(schema_version='reqlox.primitive-presence-reference-evaluation.v0.1', attempted_tasks=len(reference_rows), missing_predictions=unobserved, observations=dict(confusion), source_groups=len(by_group), precision_against_llm_presence_reference=ratio(confusion['true_positive'], confusion['true_positive'] + confusion['false_positive']), recall_against_llm_presence_reference=ratio(confusion['true_positive'], confusion['true_positive'] + confusion['false_negative']), group_equal_weight_precision=sum((x for x in group_precision if x is not None)) / sum((x is not None for x in group_precision)) if any((x is not None for x in group_precision)) else None, group_equal_weight_recall=sum((x for x in group_recall if x is not None)) / sum((x is not None for x in group_recall)) if any((x is not None for x in group_recall)) else None, observation_event='SOURCE_REPORTED_PRIMITIVE_PRESENCE_NOT_EVENT_IDENTITY_OR_CAUSAL_EDGE_TRUTH', reference_authority='LLM_ADJUDICATED_REFERENCE', model_inference_events_scored=False, unknown_reference_is_not_negative=True, missing_prediction_treated_as_empty=True, true_precision=None, true_recall=None, event_or_edge_semantics_certified=False, population_generalization_certified=False, rows=task_rows))

def evaluate_saved(base):
    from pathlib import Path
    import run_incident_reference_campaign as campaign
    from evaluate_gemini_against_frozen_gold import load_baseline_rows
    from run_peer_isolation import save, ref
    base = Path(base).absolute()
    campaign.verify_freeze(base)
    plan = campaign.load(base / 'plan.json')
    _, rows = load_baseline_rows(campaign.BASELINE, campaign.ROOT / 'corpus')
    reference_rows = [dict(task_id=job['task_id'], source_group=campaign.load(base / 'tasks' / job['id'] / 'packet.json')['subject']['canonical_group_id'], answers=campaign.load(base / 'tasks' / job['id'] / 'source-judgment.json')['answers']) for job in plan['jobs']]
    baseline = {r['task_id']: r['proposal'] if r['status'] == 'VALID_MODEL_PROPOSAL_REVIEW_REQUIRED' else None for r in rows}
    result = compare_primitive_presence(reference_rows, baseline)
    result = seal({**result, 'reference_freeze_ref': ref(base / 'reference-freeze.json'), 'baseline_ref': ref(campaign.BASELINE)})
    save(base / 'primitive-presence-comparison.json', result)
    return {k: result[k] for k in ['attempted_tasks', 'missing_predictions', 'observations', 'precision_against_llm_presence_reference', 'recall_against_llm_presence_reference']}
