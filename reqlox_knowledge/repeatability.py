"""\u56fa\u5b9a\u8a55\u4fa1\u3068\u53cd\u5fa9\u8a55\u4fa1\u3092\u533a\u5225\u3059\u308b\u3001\u6761\u4ef6\u4ed8\u304d\u306e\u4e8c\u9805goal\u8a3a\u65ad\u3002

\u6642\u70b9n\u3068\u65b9\u6cd5i\u3078alpha/(i(i+1)n(n+1))\u3092\u914d\u5206\u3059\u308b\u3002union bound\u306b
\u57fa\u3065\u304f\u4fdd\u5b88\u7684\u306a\u65b9\u5f0f\u3067\u3042\u308a\u3001\u52b9\u7387\u7684\u306amixture\u5883\u754c\u306e\u5b9f\u88c5\u3067\u306f\u306a\u3044\u3002
\u4f9d\u5b58group\u306e\u72ec\u7acb\u6027\u3001\u6bcd\u96c6\u56e3\u62bd\u51fa\u3001\u81ea\u7136Gold\u306f\u3053\u306e\u30b3\u30fc\u30c9\u3067\u8a3c\u660e\u3057\u306a\u3044\u3002
"""
import math
from .probability import exact_interval
from .reference import require, seal

def prepare(method_revisions, *, event, direction, target, family_alpha=0.05, mode='ALL_SAMPLE_TIMES', fixed_groups=None):
    require(type(method_revisions) is list and 0 < len(method_revisions) <= 1000 and all((type(x) is str and len(x) == 64 and all((c in '0123456789abcdef' for c in x)) for x in method_revisions)) and (len(set(method_revisions)) == len(method_revisions)), 'REPEATED_METHOD_REVISIONS')
    require(type(event) is str and event and (direction in ('LOWER_SUCCESS', 'UPPER_ERROR')), 'REPEATED_EVENT')
    require(type(target) in (int, float) and math.isfinite(target) and (0 < target < 1), 'REPEATED_TARGET')
    require(type(family_alpha) in (int, float) and math.isfinite(family_alpha) and (0 < family_alpha < 0.5), 'REPEATED_ALPHA')
    require(mode in ('ALL_SAMPLE_TIMES', 'FIXED_BATCH'), 'REPEATED_MODE')
    require(fixed_groups is None if mode == 'ALL_SAMPLE_TIMES' else type(fixed_groups) is int and 0 < fixed_groups <= 10000, 'REPEATED_FIXED_GROUP_COUNT')
    return seal(dict(schema_version='reqlox.repeated-probability-policy.v0.1', method_revisions=list(method_revisions), event=event, direction=direction, target=float(target), family_alpha=float(family_alpha), mode=mode, fixed_groups=fixed_groups, allocation='alpha/[method_index*(method_index+1)] and optionally /[n*(n+1)]', sampling_unit='PRESEALED_DISJOINT_SOURCE_TARGET_MECHANISM_COMPONENT', iid_bernoulli_groups_required=True, prospective_freeze_required=True, population_generalization_certified=False))

def extend(policy, new_revisions):
    require(seal(policy) == policy, 'REPEATED_POLICY_SEAL')
    require(type(new_revisions) is list and len(new_revisions) > 0, 'REPEATED_EXTENSION')
    successor = prepare(policy['method_revisions'] + new_revisions, event=policy['event'], direction=policy['direction'], target=policy['target'], family_alpha=policy['family_alpha'], mode=policy['mode'], fixed_groups=policy['fixed_groups'])
    successor.pop('record_sha256')
    successor['predecessor_policy_sha256'] = policy['record_sha256']
    successor['old_method_indices_preserved'] = True
    return seal(successor)

def alpha_for(policy, revision, n):
    require(seal(policy) == policy, 'REPEATED_POLICY_SEAL')
    require(revision in policy['method_revisions'], 'REPEATED_UNREGISTERED_METHOD')
    require(type(n) is int and 0 < n <= 10000, 'REPEATED_SAMPLE_COUNT')
    i = policy['method_revisions'].index(revision) + 1
    alpha = policy['family_alpha'] / (i * (i + 1))
    if policy['mode'] == 'ALL_SAMPLE_TIMES':
        alpha /= n * (n + 1)
    return alpha

def one_sided_bound(successes, n, alpha, direction):
    require(type(successes) is type(n) is int and 0 <= successes <= n <= 10000 and (n > 0), 'REPEATED_BOUND_COUNTS')
    require(type(alpha) in (int, float) and math.isfinite(alpha) and (0 < alpha < 0.5), 'REPEATED_BOUND_ALPHA')
    require(direction in ('LOWER_SUCCESS', 'UPPER_ERROR'), 'REPEATED_BOUND_DIRECTION')
    if direction == 'LOWER_SUCCESS' and successes == n:
        return math.exp(math.log(alpha) / n)
    if direction == 'UPPER_ERROR' and successes == 0:
        return -math.expm1(math.log(alpha) / n)
    bounds = exact_interval(successes, n, confidence=1 - 2 * alpha)
    return bounds[0 if direction == 'LOWER_SUCCESS' else 1]

def report(policy, revision, groups):
    require(seal(policy) == policy, 'REPEATED_POLICY_SEAL')
    require(type(groups) is list and 0 < len(groups) <= 10000, 'REPEATED_GROUP_ROWS')
    fields = {'id', 'source_group', 'target_group', 'mechanism_group', 'event', 'method_revision', 'label'}
    require(all((type(g) is dict and set(g) >= fields and (type(g['id']) is str) and bool(g['id']) for g in groups)), 'REPEATED_GROUP_SCHEMA')
    require(len({g['id'] for g in groups}) == len(groups), 'REPEATED_DUPLICATE_GROUP')
    for axis in ('source_group', 'target_group', 'mechanism_group'):
        require(all((type(g.get(axis)) is str and g[axis] for g in groups)), 'REPEATED_GROUP_IDENTITY')
        require(len({g[axis] for g in groups}) == len(groups), 'REPEATED_DEPENDENT_GROUPS:' + axis)
    require(all((g['event'] == policy['event'] and g['method_revision'] == revision for g in groups)), 'REPEATED_EVENT_REVISION_DRIFT')
    require(all((g['label'] is None or (type(g['label']) is int and g['label'] in (0, 1)) for g in groups)), 'REPEATED_LABEL')
    n = len(groups)
    alpha = alpha_for(policy, revision, n)
    known = sum((g['label'] is not None for g in groups))
    unknown = n - known
    observed_ones = sum((g['label'] == 1 for g in groups))
    worst = observed_ones if policy['direction'] == 'LOWER_SUCCESS' else observed_ones + unknown
    bound = one_sided_bound(worst, n, alpha, policy['direction'])
    eligible = policy['mode'] == 'ALL_SAMPLE_TIMES' or n == policy['fixed_groups']
    reached = eligible and (bound >= policy['target'] if policy['direction'] == 'LOWER_SUCCESS' else bound <= policy['target'])
    return seal(dict(schema_version='reqlox.repeated-probability-diagnostic.v0.1', method_index=policy['method_revisions'].index(revision) + 1, event=policy['event'], direction=policy['direction'], attempted_groups=n, observed_groups=known, unknown_groups=unknown, observed_ones=observed_ones, empirical_fraction_bounds=[observed_ones / n, (observed_ones + unknown) / n], current_one_sided_alpha=alpha, conditional_iid_one_sided_bound=bound, target=policy['target'], prescribed_evaluation_time=eligible, conditional_numeric_goal_reached=reached, unknowns_not_relabelled=True, unknowns_not_removed_from_denominator=True, repeated_looks_accounted_for=policy['mode'] == 'ALL_SAMPLE_TIMES', multiple_methods_accounted_for=True, iid_and_sampling_not_established=True, original_freeze_timing_not_proved_by_this_report=True, labels_not_verified_by_this_report=True, population_generalization_certified=False))

def all_success_minimum(policy, revision, *, maximum=10000):
    require(type(maximum) is int and 0 < maximum <= 10000, 'REPEATED_PLANNING_BOUND')
    if policy['mode'] == 'FIXED_BATCH':
        ns = [policy['fixed_groups']] if policy['fixed_groups'] <= maximum else []
    else:
        ns = range(1, maximum + 1)
    for n in ns:
        ones = n if policy['direction'] == 'LOWER_SUCCESS' else 0
        value = one_sided_bound(ones, n, alpha_for(policy, revision, n), policy['direction'])
        if value >= policy['target'] if policy['direction'] == 'LOWER_SUCCESS' else value <= policy['target']:
            return n
    return None
