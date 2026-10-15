"""Reusable threshold policy methods from the development implementation."""
from collections import Counter
from copy import deepcopy
from itertools import groupby
import math
from . import choice_response as response
from . import partial_scores as scores
from . import reference as c
from .repeatability import one_sided_bound

def number(value, reason, *, low=0.0, high=1.0):
    c.require(type(value) in (int, float) and math.isfinite(value) and (low <= value <= high), reason)
    return float(value)

def prepare(thresholds, *, categories, event, method_revision, decision_classes=None, risk_targets=(0.01, 0.05, 0.1), family_alpha=0.05, role='DEVELOPMENT', fixed_trial_ids=None):
    c.require(type(thresholds) in (list, tuple) and 0 < len(thresholds) <= 101, 'THRESHOLD_GRID')
    grid = [number(v, 'THRESHOLD_VALUE') for v in thresholds]
    c.require(grid == sorted(set(grid)), 'THRESHOLD_GRID_ORDER_OR_DUPLICATE')
    response.check(None, categories)
    decisions = list(categories) if decision_classes is None else list(decision_classes)
    c.require(decisions and all((type(v) is str and v in categories for v in decisions)) and (len(set(decisions)) == len(decisions)), 'THRESHOLD_DECISION_CLASSES')
    targets = [number(v, 'THRESHOLD_RISK_TARGET') for v in risk_targets]
    c.require(targets and targets == sorted(set(targets)) and all((0 < v < 1 for v in targets)), 'THRESHOLD_RISK_TARGETS')
    alpha = number(family_alpha, 'THRESHOLD_ALPHA')
    c.require(0 < alpha < 0.5 and role in ('DEVELOPMENT', 'CALIBRATION', 'EVALUATION'), 'THRESHOLD_ROLE_OR_ALPHA')
    c.require(type(event) is str and event and (type(method_revision) is str) and (len(method_revision) == 64) and all((v in '0123456789abcdef' for v in method_revision)), 'THRESHOLD_EVENT_OR_METHOD')
    if role == 'DEVELOPMENT':
        c.require(fixed_trial_ids is None, 'THRESHOLD_DEVELOPMENT_TRIAL_FREEZE')
    else:
        c.require(type(fixed_trial_ids) is list and 0 < len(fixed_trial_ids) <= 10000 and all((type(v) is str and v for v in fixed_trial_ids)) and (len(set(fixed_trial_ids)) == len(fixed_trial_ids)), 'THRESHOLD_FIXED_TRIAL_IDS')
    c.require(role != 'EVALUATION' or len(grid) == 1, 'THRESHOLD_EVALUATION_REQUIRES_FIXED_CHOICE')
    return c.seal(dict(schema_version='reqlox.threshold-policy.v0.1', categories=list(categories), decision_classes=decisions, thresholds=grid, event=event, method_revision=method_revision, risk_targets=targets, family_alpha=alpha, role=role, fixed_trial_ids=deepcopy(fixed_trial_ids), confidence_allocation='BONFERRONI_OVER_THRESHOLDS_AND_OVERALL_PLUS_DECISION_CLASSES', original_operating_floor=c.FLOOR, original_floor_qualified=False, iid_components_and_prospective_timing_required=True, execution_authority=False))

def decision(answer, categories, threshold, decision_classes):
    threshold = number(threshold, 'THRESHOLD_VALUE')
    checked = response.check(answer, categories)
    choice = checked['choice']
    accepted = choice if checked['status'] == 'VALID' and choice in decision_classes and (checked['probabilities'][choice] >= threshold) else None
    return dict(status=checked['status'], choice=choice, accepted=accepted, probabilities=checked['probabilities'], execution_authority=False)

def validate(policy, rows):
    c.check_seal(policy)
    c.require(policy == prepare(policy['thresholds'], categories=policy['categories'], event=policy['event'], method_revision=policy['method_revision'], decision_classes=policy['decision_classes'], risk_targets=policy['risk_targets'], family_alpha=policy['family_alpha'], role=policy['role'], fixed_trial_ids=policy['fixed_trial_ids']), 'THRESHOLD_POLICY_DRIFT')
    c.require(type(rows) is list and 0 < len(rows) <= 10000, 'THRESHOLD_ROWS')
    for row in rows:
        c.require(type(row) is dict and all((type(row.get(k)) is str and row[k] for k in ('id', 'event', 'method_revision', 'dependency_component', 'source_group', 'target_group', 'mechanism_group'))), 'THRESHOLD_ROW_IDENTITY')
        c.require(row['event'] == policy['event'] and row['method_revision'] == policy['method_revision'], 'THRESHOLD_EVENT_OR_METHOD_DRIFT')
        c.require(row.get('label') is None or (type(row['label']) is str and row['label'] in policy['categories']), 'THRESHOLD_LABEL')
        c.require(row.get('label_authority') in ('CONSTRUCTED_FINITE_ORACLE', 'INDEPENDENT_EXECUTABLE_ORACLE', 'HUMAN_ADJUDICATION', 'UNKNOWN'), 'THRESHOLD_LABEL_AUTHORITY')
        c.require(row.get('label') is None or row['label_authority'] != 'UNKNOWN', 'THRESHOLD_UNSUPPORTED_LABEL')
    c.require(len({r['id'] for r in rows}) == len(rows), 'THRESHOLD_DUPLICATE_ROW')
    if policy['fixed_trial_ids'] is not None:
        c.require([r['id'] for r in rows] == policy['fixed_trial_ids'], 'THRESHOLD_FIXED_TRIAL_DRIFT')

def error_summary(selected, alpha, iid):
    total = len(selected)
    errors = sum((r['label'] is not None and r['label'] != r['accepted'] for r in selected))
    unknown = sum((r['label'] is None for r in selected))
    upper = one_sided_bound(errors + unknown, total, alpha, 'UPPER_ERROR') if iid and total else None
    return dict(accepted=total, known_correct=total - errors - unknown, known_errors=errors, unknown_labels=unknown, selective_error_bounds=[errors / total, (errors + unknown) / total] if total else None, conditional_iid_error_upper=upper, one_sided_alpha=alpha if iid else None, no_acceptance_is_not_zero_risk=not total)

def component_assignments(rows):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    parents = list(range(len(rows)))
    seen = {}

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, row in enumerate(rows):
        for axis in ('source_group', 'target_group', 'mechanism_group', 'dependency_component'):
            key = (axis, row[axis])
            if key in seen:
                parents[find(i)] = find(seen[key])
            else:
                seen[key] = i
    names = {}
    for i, row in enumerate(rows):
        key = find(i)
        names[key] = min(names.get(key, row['dependency_component']), row['dependency_component'])
    return {row['id']: names[find(i)] for i, row in enumerate(rows)}

def binary_diagnostics(rows, categories):
    if len(categories) != 2:
        return dict(status='NOT_BINARY', auroc=None, probability_calibration_certified=False)
    unknown = sum((r['label'] is None or r['probabilities'] is None for r in rows))
    if unknown:
        return dict(status='INCOMPLETE_TRUTH_OR_VECTORS', attempted=len(rows), incomplete_rows=unknown, auroc=None, incomplete_rows_not_removed=True, probability_calibration_certified=False)
    pairs = [(r['probabilities'][categories[0]], int(r['label'] == categories[0])) for r in rows]
    positives = sum((y for _, y in pairs))
    negatives = len(pairs) - positives
    wins = 0.0
    earlier_negatives = 0
    for _, group in groupby(sorted(pairs), key=lambda r: r[0]):
        tied = list(group)
        pos = sum((y for _, y in tied))
        neg = len(tied) - pos
        wins += pos * (earlier_negatives + 0.5 * neg)
        earlier_negatives += neg
    auc = wins / (positives * negatives) if positives and negatives else None
    bins = [[] for _ in range(5)]
    for p, y in pairs:
        bins[min(4, int(p * 5))].append((p, y))
    calibration = []
    for index, bucket in enumerate(bins):
        n = len(bucket)
        mean = math.fsum((p for p, _ in bucket)) / n if n else None
        observed = sum((y for _, y in bucket)) / n if n else None
        calibration.append(dict(bin_lower=index / 5, bin_upper=(index + 1) / 5, count=n, mean_probability=mean, empirical_success_fraction=observed, finite_absolute_gap=abs(mean - observed) if n else None))
    return dict(status='COMPLETE_FINITE_COHORT', attempted=len(rows), positive_class=categories[0], positives=positives, negatives=negatives, auroc=auc, tied_pairs_receive_half_credit=True, scalar_brier=math.fsum(((p - y) ** 2 for p, y in pairs)) / len(pairs), retrospective_scalar_prevalence_brier=positives / len(pairs) * (negatives / len(pairs)), fixed_bin_calibration=calibration, finite_fixed_bin_ece=math.fsum((r['count'] * (r['finite_absolute_gap'] or 0.0) for r in calibration)) / len(rows), ranking_and_probability_quality_separate=True, pair_count_is_not_independent_sample_count=True, bins_are_descriptive_not_calibration_certificate=True, probability_calibration_certified=False)

def sweep(policy, rows, *, iid_components_attested=False):
    validate(policy, rows)
    c.require(type(iid_components_attested) is bool, 'THRESHOLD_IID_ATTESTATION')
    assignments = component_assignments(rows)
    components = Counter((assignments[r['id']] for r in rows))
    iid = iid_components_attested and policy['role'] != 'DEVELOPMENT'
    c.require(not iid or len(components) == len(rows), 'THRESHOLD_DEPENDENT_ROWS')
    alpha = policy['family_alpha'] / (len(policy['thresholds']) * (1 + len(policy['decision_classes'])))
    score_rows = []
    for row in rows:
        checked = response.check(row.get('answer'), policy['categories'])
        score_rows.append(dict(id=row['id'], probabilities=checked['probabilities'], label=row['label'], label_authority=row['label_authority'], dependency_component=assignments[row['id']]))
    curve = []
    for threshold in policy['thresholds']:
        checked = [dict(**{k: r[k] for k in ('id', 'label')}, **decision(r.get('answer'), policy['categories'], threshold, policy['decision_classes'])) for r in rows]
        accepted = [r for r in checked if r['accepted'] is not None]
        summary = error_summary(accepted, alpha, iid)
        per_class = {key: error_summary([r for r in accepted if r['accepted'] == key], alpha, iid) for key in policy['decision_classes']}
        goals = {}
        for risk in policy['risk_targets']:
            goals[str(risk)] = dict(empirical_upper_within_goal=summary['selective_error_bounds'] is not None and summary['selective_error_bounds'][1] <= risk, conditional_iid_upper_within_goal=summary['conditional_iid_error_upper'] is not None and summary['conditional_iid_error_upper'] <= risk)
        curve.append(dict(threshold=threshold, attempted=len(rows), coverage=len(accepted) / len(rows), abstained=len(rows) - len(accepted), invalid_answers=sum((r['status'] != 'VALID' for r in checked)), overall=summary, per_decision_class=per_class, risk_goal_diagnostics=goals))
    return c.seal(dict(schema_version='reqlox.threshold-sweep.v0.1', policy_sha256=c.digest(policy), rows_sha256=c.digest([dict(**{k: r[k] for k in ('id', 'event', 'method_revision', 'label', 'label_authority', 'dependency_component', 'source_group', 'target_group', 'mechanism_group')}, raw_answer_sha256=response.fingerprint(r.get('answer'))) for r in rows]), role=policy['role'], attempted=len(rows), dependency_components=len(components), maximum_rows_per_component=max(components.values()), curve=curve, known_label_counts=dict(Counter((r['label'] for r in rows if r['label'] is not None))), proper_score=scores.report(score_rows, tuple(policy['categories'])), binary_diagnostics=binary_diagnostics(score_rows, policy['categories']), conditional_iid_bounds_computed=iid, simultaneous_thresholds_and_classes_accounted_for=iid, iid_sampling_and_freeze_timing_not_proved_by_this_report=True, source_target_mechanism_dependency_checked=True, group_ids_declared_not_independently_verified=True, observed_labels_not_repaired=True, unknowns_preserved=True, zero_coverage_not_optimal=True, adopted_threshold=None, probability_calibration_certified=False, population_generalization_certified=False, execution_authority=False))

def development_proposals(policy, result):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    c.check_seal(policy)
    c.check_seal(result)
    c.require(result['policy_sha256'] == c.digest(policy), 'THRESHOLD_PROPOSAL_POLICY_BINDING')
    c.require(policy['role'] == result['role'] == 'DEVELOPMENT', 'THRESHOLD_PROPOSAL_DEVELOPMENT_ONLY')
    supported = all((result['known_label_counts'].get(key, 0) > 0 for key in policy['categories']))
    proposals = {}
    for risk in policy['risk_targets']:
        per_class = {}
        for key in policy['decision_classes']:
            candidates = [r for r in result['curve'] if supported and r['per_decision_class'][key]['selective_error_bounds'] is not None and (r['per_decision_class'][key]['selective_error_bounds'][1] <= risk)]
            candidates.sort(key=lambda r: (-r['per_decision_class'][key]['accepted'], r['threshold']))
            selected = candidates[0] if candidates else None
            per_class[key] = dict(threshold=selected['threshold'], accepted=selected['per_decision_class'][key]['accepted'], empirical_error_bounds=selected['per_decision_class'][key]['selective_error_bounds']) if selected else None
        proposals[str(risk)] = per_class
    return c.seal(dict(schema_version='reqlox.threshold-development-proposals.v0.1', policy_sha256=c.digest(policy), sweep_sha256=c.digest(result), proposals=proposals, both_success_and_failure_labels_required=True, all_truth_categories_observed=supported, rule='MAX_CLASS_ACCEPTED_THEN_LOWEST_GRID_THRESHOLD_EMPIRICAL_WORST_UNKNOWN_ERROR', posthoc_development_candidates_only=True, independent_fixed_validation_required=True, adopted_threshold=None, threshold_qualified=False, execution_authority=False))

def zero_error_sample_requirement(risk, *, family_alpha=0.05, simultaneous_tests=1):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    risk = number(risk, 'THRESHOLD_RISK_TARGET')
    alpha = number(family_alpha, 'THRESHOLD_ALPHA')
    c.require(0 < risk < 1 and 0 < alpha < 0.5 and (type(simultaneous_tests) is int) and (1 <= simultaneous_tests <= 10000), 'THRESHOLD_SAMPLE_PLAN')
    return math.ceil(math.log(alpha / simultaneous_tests) / math.log1p(-risk))
