"""Reusable probability methods from the development implementation."""
from collections import defaultdict
import hashlib
import json
import math

def require(condition, reason):
    if not condition:
        raise ValueError(reason)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
ROLES = {'DEVELOPMENT', 'CALIBRATION', 'EVALUATION'}
DISPOSITIONS = {'ACCEPT', 'REJECT', 'ABSTAIN', 'UNKNOWN', 'NOT_APPLICABLE'}

def validate_rows(rows):
    require(type(rows) is list and 0 < len(rows) <= 10000, 'PROBABILITY_ROWS_BOUND')
    require(all((type(r) is dict for r in rows)), 'PROBABILITY_ROW_OBJECT')
    for r in rows:
        require(all((type(r.get(k)) is str and r[k] for k in ('id', 'event', 'source_group', 'target_group'))), 'PROBABILITY_IDENTITY')
        require(type(r.get('split')) is str and r['split'] in ROLES and (type(r.get('disposition')) is str) and (r['disposition'] in DISPOSITIONS), 'PROBABILITY_ROLE_OR_DISPOSITION')
        p, y = (r.get('probability'), r.get('label'))
        require(p is None or (type(p) in (int, float) and 0 <= p <= 1 and math.isfinite(p)), 'PROBABILITY_VALUE')
        require(y is None or (type(y) is int and y in (0, 1)), 'PROBABILITY_LABEL')
        require(r.get('label_authority') in ('INDEPENDENT_EXECUTABLE_ORACLE', 'HUMAN_ADJUDICATION', 'UNKNOWN'), 'PROBABILITY_LABEL_AUTHORITY')
        require(y is None or r['label_authority'] != 'UNKNOWN', 'PROBABILITY_UNSUPPORTED_LABEL')
    require(len({r['id'] for r in rows}) == len(rows), 'PROBABILITY_DUPLICATE_ID')
    return rows

def components(rows):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    for r in rows:
        parent[find(('source', r['source_group']))] = find(('target', r['target_group']))
    groups = defaultdict(list)
    for r in rows:
        groups[find(('source', r['source_group']))].append(r)
    return list(groups.values())

def verify_split(rows):
    validate_rows(rows)
    require(len({r['event'] for r in rows}) == 1, 'PROBABILITY_EVENT_MIX')
    for axis in ('source_group', 'target_group'):
        owners = defaultdict(set)
        for r in rows:
            owners[r[axis]].add(r['split'])
        require(all((len(v) == 1 for v in owners.values())), 'PROBABILITY_SPLIT_LEAK:' + axis)
    return dict(rows_sha256=digest(rows), event=rows[0]['event'], counts={role: sum((r['split'] == role for r in rows)) for role in sorted(ROLES)}, source_target_disjoint=True, connected_groups=len(components(rows)))

def binomial_cdf(k, n, p):
    return _binomial_cdf(k, n, p, maximum=10000)

def _binomial_cdf(k, n, p, *, maximum):
    require(type(n) is int and 0 <= n <= maximum and (type(k) is int), 'BINOMIAL_COUNT_BOUND')
    require(type(p) in (int, float) and 0 <= p <= 1 and math.isfinite(p), 'BINOMIAL_PROBABILITY')
    if k < 0:
        return 0.0
    if k >= n or p == 0:
        return 1.0
    if p == 1:
        return 0.0
    return min(1.0, math.fsum((math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)) for i in range(k + 1))))

def _inverse_cdf(k, n, target):
    low, high = (0.0, 1.0)
    for _ in range(64):
        mid = (low + high) / 2
        if binomial_cdf(k, n, mid) > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2

def exact_interval(successes, trials, confidence=0.95):
    require(type(successes) is type(trials) is int and 0 <= successes <= trials <= 10000, 'INTERVAL_COUNTS')
    require(type(confidence) in (int, float) and 0 < confidence < 1, 'INTERVAL_CONFIDENCE')
    if trials == 0:
        return None
    alpha = 1 - confidence
    return [0.0 if successes == 0 else _inverse_cdf(successes - 1, trials, 1 - alpha / 2), 1.0 if successes == trials else _inverse_cdf(successes, trials, alpha / 2)]

def beta_posterior(successes, trials, credible=0.95):
    require(type(successes) is type(trials) is int and 0 <= successes <= trials <= 10000, 'POSTERIOR_COUNTS')
    require(type(credible) in (int, float) and 0 < credible < 1, 'POSTERIOR_CREDIBLE_LEVEL')
    a, b = (successes + 1, trials - successes + 1)

    def quantile(q):
        if b == 1:
            return q ** (1 / a)
        if a == 1:
            return -math.expm1(math.log1p(-q) / b)
        low, high = (0.0, 1.0)
        for _ in range(64):
            mid = (low + high) / 2
            cdf = 1 - _binomial_cdf(a - 1, a + b - 1, mid, maximum=10001)
            if cdf < q:
                low = mid
            else:
                high = mid
        return (low + high) / 2
    tail = (1 - credible) / 2
    return dict(prior='Beta(1,1)', alpha=a, beta=b, mean=a / (a + b), credible_interval=[quantile(tail), quantile(1 - tail)], assumed_exchangeable_bernoulli_groups=True, population_claim_authorized=False)

def report(rows, *, role='EVALUATION'):
    freeze = verify_split(rows)
    require(type(role) is str and role in ROLES, 'PROBABILITY_REPORT_ROLE')
    selected = [r for r in rows if r['split'] == role]
    require(selected, 'PROBABILITY_REPORT_EMPTY')
    groups = components(selected)
    scored = [r for r in selected if r['probability'] is not None and r['label'] is not None]
    group_scores = []
    for group in groups:
        measured = [r for r in group if r['probability'] is not None and r['label'] is not None]
        if measured:
            group_scores.append(sum(((r['probability'] - r['label']) ** 2 for r in measured)) / len(measured))
    observed_groups = [g for g in groups if all((r['label'] is not None for r in g))]
    group_successes = sum((all((r['label'] == 1 for r in g)) for g in observed_groups))
    accepted = [r for r in selected if r['disposition'] == 'ACCEPT']
    observed_accepts = [r for r in accepted if r['label'] is not None]
    false_accepts = sum((r['label'] == 0 for r in observed_accepts))
    positives = [r for r in selected if r['label'] == 1]
    rejected_positive = sum((r['disposition'] in ('REJECT', 'ABSTAIN') for r in positives))
    bins = []
    for i in range(10):
        members = [r for r in scored if min(9, int(r['probability'] * 10)) == i]
        if members:
            bins.append(dict(lower=i / 10, upper=(i + 1) / 10, rows=len(members), mean_probability=sum((r['probability'] for r in members)) / len(members), observed_frequency=sum((r['label'] for r in members)) / len(members), dependency_groups=len(components(members))))
    infinite = sum((r['probability'] == 0 and r['label'] == 1 or (r['probability'] == 1 and r['label'] == 0) for r in scored))
    accepts_by_group = [g for g in groups if any((r['disposition'] == 'ACCEPT' for r in g))]
    observed_accept_groups = [g for g in accepts_by_group if all((r['label'] is not None for r in g if r['disposition'] == 'ACCEPT'))]
    unsafe_groups = sum((any((r['disposition'] == 'ACCEPT' and r['label'] == 0 for r in g)) for g in observed_accept_groups))
    return dict(split_ref=freeze, role=role, attempted_rows=len(selected), scored_rows=len(scored), unknown_labels=sum((r['label'] is None for r in selected)), unknown_probabilities=sum((r['probability'] is None for r in selected)), dispositions={s: sum((r['disposition'] == s for r in selected)) for s in sorted(DISPOSITIONS)}, mean_brier=sum(((r['probability'] - r['label']) ** 2 for r in scored)) / len(scored) if scored else None, group_equal_weight_brier=sum(group_scores) / len(group_scores) if group_scores else None, mean_log_loss=sum((-math.log(r['probability'] if r['label'] else 1 - r['probability']) for r in scored)) / len(scored) if scored and (not infinite) else None, infinite_log_loss_rows=infinite, observed_accepts=len(observed_accepts), unknown_accepts=len(accepted) - len(observed_accepts), false_accepts=false_accepts, false_accept_rate=false_accepts / len(observed_accepts) if observed_accepts else None, observed_positives=len(positives), rejected_positives=rejected_positive, positive_rejection_rate=rejected_positive / len(positives) if positives else None, dependency_groups=len(groups), observed_groups=len(observed_groups), unknown_groups=len(groups) - len(observed_groups), all_member_success_groups=group_successes, exact_group_interval=exact_interval(group_successes, len(observed_groups)), group_posterior=beta_posterior(group_successes, len(observed_groups)), posterior_event='ALL_MEMBER_EVENT_LABELS_TRUE_IN_A_NEW_DEPENDENCY_GROUP', accepted_groups=len(accepts_by_group), observed_accept_groups=len(observed_accept_groups), unsafe_accept_groups=unsafe_groups, unsafe_accept_group_interval=exact_interval(unsafe_groups, len(observed_accept_groups)), reliability_bins=bins, rows_assumed_independent=False, random_population_sample=False, population_accuracy_certified=False)

def fit_isotonic(rows):
    """Ported current method; source identity is recorded in publication/knowledge-port.json."""
    verify_split(rows)
    require(all((r['split'] == 'CALIBRATION' for r in rows)), 'CALIBRATION_ROLE_REQUIRED')
    groups = components(rows)
    points = defaultdict(lambda: [0.0, 0.0])
    for group in groups:
        known = [r for r in group if r['probability'] is not None and r['label'] is not None]
        for r in known:
            points[r['probability']][0] += r['label'] / len(known)
            points[r['probability']][1] += 1 / len(known)
    require(points, 'CALIBRATION_NO_OBSERVATIONS')
    blocks = []
    for x, (positive, weight) in sorted(points.items()):
        blocks.append(dict(lower=x, upper=x, positive=positive, weight=weight))
        while len(blocks) >= 2 and blocks[-2]['positive'] / blocks[-2]['weight'] > blocks[-1]['positive'] / blocks[-1]['weight']:
            right, left = (blocks.pop(), blocks.pop())
            blocks.append(dict(lower=left['lower'], upper=right['upper'], positive=left['positive'] + right['positive'], weight=left['weight'] + right['weight']))
    model = dict(schema_version='reqlox.isotonic-calibration.v0.1', event=rows[0]['event'], training_rows_sha256=digest(rows), source_groups=sorted({r['source_group'] for r in rows}), training_rows=rows, target_groups=sorted({r['target_group'] for r in rows}), dependency_groups=len(groups), blocks=[dict(lower=b['lower'], upper=b['upper'], probability=min(0.99, max(0.01, b['positive'] / b['weight']))) for b in blocks], extrapolation='CLAMP_NEAREST_BLOCK', population_calibration_certified=False)
    model['model_sha256'] = digest(model)
    return model

def calibrated_probability(model, row):
    require(model.get('model_sha256') == digest({k: v for k, v in model.items() if k != 'model_sha256'}), 'CALIBRATION_MODEL_DRIFT')
    require(model == fit_isotonic(model['training_rows']), 'CALIBRATION_DERIVATION_DRIFT')
    require(row['split'] == 'EVALUATION' and row['event'] == model['event'], 'CALIBRATION_EVALUATION_ROLE')
    require(row['source_group'] not in model['source_groups'] and row['target_group'] not in model['target_groups'], 'CALIBRATION_EVALUATION_LEAK')
    p = row['probability']
    if p is None:
        return None
    require(type(p) in (int, float) and math.isfinite(p) and (0 <= p <= 1), 'PROBABILITY_VALUE')
    for block in model['blocks']:
        if p <= block['upper']:
            return block['probability']
    return model['blocks'][-1]['probability']
