"""Reusable partial scores methods from the development implementation."""
from collections import defaultdict
import math
from . import reference as c
PROBABILITY_SUM_TOLERANCE = 1e-06
LABEL_AUTHORITIES = ('CONSTRUCTED_FINITE_ORACLE', 'INDEPENDENT_EXECUTABLE_ORACLE', 'HUMAN_ADJUDICATION', 'UNKNOWN')

def brier(p, label, categories):
    return math.fsum(((p[k] - int(k == label)) ** 2 for k in categories))

def row_bounds(row, categories):
    p = row['probabilities']
    label = row['label']
    if p is None:
        return dict(brier_lower=0.0, brier_upper=2.0 + PROBABILITY_SUM_TOLERANCE, log_loss_lower=0.0, log_loss_upper=None, log_loss_lower_infinite=False, log_loss_upper_infinite=True)
    possible = [label] if label is not None else categories
    scores = [brier(p, y, categories) for y in possible]
    probabilities = [p[y] for y in possible]
    maximum = max(probabilities)
    minimum = min(probabilities)
    return dict(brier_lower=min(scores), brier_upper=max(scores), log_loss_lower=-math.log(maximum) if maximum else None, log_loss_upper=-math.log(minimum) if minimum else None, log_loss_lower_infinite=maximum == 0, log_loss_upper_infinite=minimum == 0)

def aggregate(rows):
    n = len(rows)
    if not n:
        return dict(rows=0, brier_bounds=[None, None], log_loss_bounds=[None, None], log_loss_lower_infinite=False, log_loss_upper_infinite=False)
    low_infinite = any((r['log_loss_lower_infinite'] for r in rows))
    high_infinite = any((r['log_loss_upper_infinite'] for r in rows))
    return dict(rows=n, brier_bounds=[math.fsum((r['brier_lower'] for r in rows)) / n, math.fsum((r['brier_upper'] for r in rows)) / n], log_loss_bounds=[None if low_infinite else math.fsum((r['log_loss_lower'] for r in rows)) / n, None if high_infinite else math.fsum((r['log_loss_upper'] for r in rows)) / n], log_loss_lower_infinite=low_infinite, log_loss_upper_infinite=high_infinite)

def report(rows, categories):
    c.require(type(rows) is list and 0 <= len(rows) <= 10000, 'PARTIAL_SCORE_ROWS_BOUND')
    c.require(type(categories) in (tuple, list) and 2 <= len(categories) <= 64 and all((type(k) is str and k for k in categories)) and (len(set(categories)) == len(categories)), 'PARTIAL_SCORE_CATEGORIES')
    required = {'id', 'probabilities', 'label', 'label_authority', 'dependency_component'}
    for row in rows:
        c.require(type(row) is dict and set(row) >= required, 'PARTIAL_SCORE_ROW_SCHEMA')
        c.require(all((type(row[k]) is str and row[k] for k in ('id', 'dependency_component'))), 'PARTIAL_SCORE_IDENTITY')
        c.require(type(row['label_authority']) is str and row['label_authority'] in LABEL_AUTHORITIES, 'PARTIAL_SCORE_AUTHORITY')
        c.require(row['label'] is None and row['label_authority'] == 'UNKNOWN' or (type(row['label']) is str and row['label'] in categories and (row['label_authority'] != 'UNKNOWN')), 'PARTIAL_SCORE_LABEL_AUTHORITY')
        if row['probabilities'] is not None:
            try:
                c.probabilities(row['probabilities'], categories)
            except (TypeError, OverflowError) as error:
                raise ValueError('PARTIAL_SCORE_PROBABILITY') from error
    c.require(len({r['id'] for r in rows}) == len(rows), 'PARTIAL_SCORE_DUPLICATE_ID')
    bounds = [dict(id=r['id'], dependency_component=r['dependency_component'], label_known=r['label'] is not None, vector_known=r['probabilities'] is not None, **row_bounds(r, categories)) for r in rows]
    full = aggregate(bounds)
    groups = defaultdict(list)
    for r in bounds:
        groups[r['dependency_component']].append(r)
    group_rows = [dict(component=key, **aggregate(value)) for key, value in sorted(groups.items())]
    group_bounds = [dict(brier_lower=g['brier_bounds'][0], brier_upper=g['brier_bounds'][1], log_loss_lower=g['log_loss_bounds'][0], log_loss_upper=g['log_loss_bounds'][1], log_loss_lower_infinite=g['log_loss_lower_infinite'], log_loss_upper_infinite=g['log_loss_upper_infinite']) for g in group_rows]
    measured = [r for r in rows if r['label'] is not None and r['probabilities'] is not None]
    infinite = sum((r['probabilities'][r['label']] == 0 for r in measured))
    uniform = 1 - 1 / len(categories)
    upper = full['brier_bounds'][1]
    return c.seal(dict(schema_version='reqlox.partial-proper-score.v0.1', categories=list(categories), attempted_rows=len(rows), scored_rows=len(measured), unknown_labels=sum((r['label'] is None for r in rows)), unknown_vectors=sum((r['probabilities'] is None for r in rows)), row_bounds=bounds, full_denominator=full, dependency_components=group_rows, group_equal_weight=aggregate(group_bounds), conditional_observed_brier=math.fsum((brier(r['probabilities'], r['label'], categories) for r in measured)) / len(measured) if measured else None, conditional_observed_log_loss=math.fsum((-math.log(r['probabilities'][r['label']]) for r in measured)) / len(measured) if measured and (not infinite) else None, known_infinite_log_loss_rows=infinite, possible_infinite_log_loss_rows=sum((r['log_loss_upper_infinite'] for r in bounds)), uniform_full_denominator_brier=uniform, strictly_better_than_uniform_for_all_completions=upper is not None and upper < uniform, probability_sum_tolerance=PROBABILITY_SUM_TOLERANCE, probabilities_repaired=False, unknown_labels_not_inferred_from_argmax=True, full_denominator_preserved=True, bounds_are_partial_identification_not_confidence_intervals=True, group_ids_and_label_authority_declared_not_verified=True, population_sampling_or_iid_certified=False, natural_truth_certified=False, probabilities_calibrated=False, execution_authority=False))
