"Finite reliability controls and verification."
from copy import deepcopy
from decimal import Decimal
import re

import incident_reference as c

ARMS = ('CORRECT_SOURCE', 'NO_SOURCE')
METRICS = ('fault_discovered', 'discriminating_experiment', 'repair_reinjection_pass')
CURRENCIES = ('gcp_jpy', 'jev_usd')


def amounts(value):
    c.require(type(value) is dict and set(value) == set(CURRENCIES), 'DISCOVERY_RESERVATION_CURRENCIES')
    c.require(all(type(v) is str and re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,12})?', v)
                  and Decimal(v) <= Decimal('1000000000') for v in value.values()),
              'DISCOVERY_RESERVATION_AMOUNT')
    return deepcopy(value)


def prepare(groups, *, maximum_experiments, method_revision, provider_reservation_caps=None):
    c.require(type(groups) is list and 0 < len(groups) <= 1000, 'DISCOVERY_GROUPS')
    c.require(type(maximum_experiments) is int and 0 < maximum_experiments <= 100, 'DISCOVERY_EXPERIMENT_BOUND')
    c.require(type(method_revision) is str and len(method_revision) == 64
              and all(v in '0123456789abcdef' for v in method_revision), 'DISCOVERY_METHOD')
    fields = {'id', 'source_group', 'target_group', 'mechanism_group', 'condition_ids',
              'normal_api_sha256', 'owned_purpose_sha256', 'target_snapshot_sha256', 'source_sha256'}
    for g in groups:
        c.require(type(g) is dict and set(g) == fields, 'DISCOVERY_GROUP_SCHEMA')
        c.require(all(type(g[k]) is str and g[k] for k in ('id', 'source_group', 'target_group', 'mechanism_group')),
                  'DISCOVERY_GROUP_IDENTITY')
        c.require(type(g['condition_ids']) is list and 0 < len(g['condition_ids']) <= 1000
                  and all(type(v) is str and v for v in g['condition_ids'])
                  and len(set(g['condition_ids'])) == len(g['condition_ids']), 'DISCOVERY_CONDITIONS')
        c.require(all(type(g[k]) is str and len(g[k]) == 64 and all(v in '0123456789abcdef' for v in g[k])
                      for k in ('normal_api_sha256', 'owned_purpose_sha256', 'target_snapshot_sha256', 'source_sha256')),
                  'DISCOVERY_HASHES')
    c.require(len({g['id'] for g in groups}) == len(groups), 'DISCOVERY_DUPLICATE_GROUP')
    caps = amounts({key:'0' for key in CURRENCIES} if provider_reservation_caps is None else provider_reservation_caps)
    return c.seal(dict(schema_version='reqlox.source-discovery-policy.v0.1', groups=deepcopy(groups),
        arms=list(ARMS), metrics=list(METRICS), maximum_experiments=maximum_experiments,
        provider_reservation_caps_per_group_and_arm=caps, equal_per_arm_reservation_caps=True,
        method_revision=method_revision, equal_per_arm_experiment_limit=True,
        source_is_only_generator_input_difference=True, same_normal_api_and_owned_purpose_required=True,
        fault_condition_catalog_and_gold_hidden_from_generator=True, known_fault_caller_not_supplied=True,
        source_not_allowed_to_redefine_target_truth=True,
        no_automatic_terminal_retry=True, fixed_budget_stopping_rule=True,
        execution_authority=False, external_calls_authorized=False))


def validate(policy, outcomes):
    c.check_seal(policy)
    c.require(policy == prepare(policy['groups'], maximum_experiments=policy['maximum_experiments'],
        method_revision=policy['method_revision'],
        provider_reservation_caps=policy['provider_reservation_caps_per_group_and_arm']), 'DISCOVERY_POLICY_DRIFT')
    c.require(type(outcomes) is list and len(outcomes) <= 2*len(policy['groups']), 'DISCOVERY_OUTCOMES')
    index = {g['id']: g for g in policy['groups']}; pairs = set()
    for row in outcomes:
        c.require(type(row) is dict and row.get('group_id') in index and row.get('arm') in ARMS,
                  'DISCOVERY_OUTCOME_IDENTITY')
        key = (row['group_id'], row['arm']); c.require(key not in pairs, 'DISCOVERY_DUPLICATE_ARM'); pairs.add(key)
        g = index[row['group_id']]
        c.require(row.get('policy_sha256') == c.digest(policy), 'DISCOVERY_OUTCOME_POLICY_DRIFT')
        c.require(row.get('method_revision') == policy['method_revision'], 'DISCOVERY_OUTCOME_METHOD_DRIFT')
        for field in ('normal_api_sha256', 'owned_purpose_sha256', 'target_snapshot_sha256'):
            c.require(row.get(field) == g[field], 'DISCOVERY_TARGET_OR_INPUT_DRIFT')
        c.require(row.get('source_sha256') == (g['source_sha256'] if row['arm'] == 'CORRECT_SOURCE' else None),
                  'DISCOVERY_SOURCE_ARM_DRIFT')
        n = row.get('attempted_experiments')
        c.require(type(n) is int and 0 <= n <= policy['maximum_experiments'], 'DISCOVERY_ATTEMPT_LIMIT')
        c.require(type(row.get('usage_known')) is bool and type(row.get('conditions')) is dict
                  and set(row['conditions']) == set(g['condition_ids']), 'DISCOVERY_CONDITION_DENOMINATOR')
        reserved = amounts(row.get('reserved_amounts'))
        c.require(all(Decimal(reserved[key]) <= Decimal(policy['provider_reservation_caps_per_group_and_arm'][key])
                      for key in CURRENCIES), 'DISCOVERY_PROVIDER_RESERVATION_LIMIT')
        for result in row['conditions'].values():
            c.require(type(result) is dict and set(result) == set(METRICS), 'DISCOVERY_METRICS')
            c.require(all(v is None or type(v) is int and v in (0, 1) for v in result.values()), 'DISCOVERY_LABEL')
            c.require(result['discriminating_experiment'] != 1 or result['fault_discovered'] == 1,
                      'DISCOVERY_IDENTIFICATION_WITHOUT_FAULT')
            c.require(n > 0 or all(v != 1 for v in result.values()), 'DISCOVERY_SUCCESS_WITHOUT_ATTEMPT')
        first = row.get('first_repair_experiment')
        c.require(first is None or type(first) is int and 1 <= first <= n, 'DISCOVERY_FIRST_REPAIR_INDEX')
        if first is not None:
            c.require(any(v['repair_reinjection_pass'] == 1 for v in row['conditions'].values()),
                      'DISCOVERY_REPAIR_INDEX_WITHOUT_SUCCESS')


def report(policy, outcomes):
    validate(policy, outcomes)
    index = {(r['group_id'], r['arm']): r for r in outcomes}
    totals = {arm: {metric: [0, 0, 0] for metric in METRICS} for arm in ARMS}
    group_rows = []; paired_deltas = {metric: [] for metric in METRICS}
    for g in policy['groups']:
        arm_rows = {}
        for arm in ARMS:
            supplied = index.get((g['id'], arm)); metrics = {}
            for metric in METRICS:
                labels = [supplied['conditions'][key][metric] if supplied else None for key in g['condition_ids']]
                ones = sum(v == 1 for v in labels); unknown = sum(v is None for v in labels); n = len(labels)
                metrics[metric] = dict(attempted_conditions=n, known_positive=ones, unknown=unknown,
                                       finite_fraction_bounds=[ones/n, (ones+unknown)/n])
                counts = totals[arm][metric]; counts[0] += ones; counts[1] += unknown; counts[2] += n
            arm_rows[arm] = dict(metrics=metrics, missing_outcome=supplied is None,
                attempted_experiments=supplied['attempted_experiments'] if supplied else None,
                usage_known=supplied['usage_known'] if supplied else False,
                first_repair_experiment=supplied['first_repair_experiment'] if supplied else None)
        differences = {}
        for metric in METRICS:
            a = arm_rows[ARMS[0]]['metrics'][metric]['finite_fraction_bounds']
            b = arm_rows[ARMS[1]]['metrics'][metric]['finite_fraction_bounds']
            differences[metric] = [a[0]-b[1], a[1]-b[0]]
            paired_deltas[metric].append(differences[metric])
        group_rows.append(dict(id=g['id'], arms=arm_rows, source_minus_no_source_bounds=differences))
    metrics = {arm: {metric: dict(attempted_conditions=n, known_positive=ones, unknown=unknown,
                    finite_fraction_bounds=[ones/n, (ones+unknown)/n])
                    for metric, (ones, unknown, n) in totals[arm].items()} for arm in ARMS}
    paired = {metric: [sum(v[k] for v in bounds)/len(bounds) for k in (0, 1)]
              for metric, bounds in paired_deltas.items()}
    disjoint = all(len({g[axis] for g in policy['groups']}) == len(policy['groups'])
                   for axis in ('source_group', 'target_group', 'mechanism_group'))
    return c.seal(dict(schema_version='reqlox.source-discovery-metrics.v0.1', policy_sha256=c.digest(policy),
        attempted_groups=len(policy['groups']), attempted_arms=2*len(policy['groups']),
        supplied_arms=len(outcomes), missing_arms=2*len(policy['groups'])-len(outcomes),
        per_arm_condition_metrics=metrics, group_rows=group_rows,
        equally_weighted_paired_group_difference_bounds=paired,
        equal_experiment_limits=True, all_usage_known=len(outcomes) == 2*len(policy['groups'])
            and all(r['usage_known'] for r in outcomes),
        equal_per_arm_reservation_caps=True, known_reserved_totals_per_arm={arm:
            {key:str(sum((Decimal(r['reserved_amounts'][key]) for r in outcomes if r['arm'] == arm), Decimal('0')))
             for key in CURRENCIES} for arm in ARMS},
        reservations_are_not_invoice_charges=True, missing_arm_reservations_not_set_to_zero=True,
        reservation_totals_cover_supplied_arms_only=True,
        source_target_mechanism_ids_disjoint=disjoint,
        repair_attempt_indices_are_descriptive_not_unbiased_time_estimates=True,
        bounds_are_unknown_label_ranges_not_confidence_intervals=True,
        actual_oracle_labels_and_input_disclosure_not_verified_by_this_report=True,
        iid_sampling_and_unused_status_not_established=True,
        independent_generalization_certified=False, execution_authority=False))
