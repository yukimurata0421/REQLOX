"Finite reliability controls and verification."
from copy import deepcopy
from decimal import Decimal
import math

from . import incident_reference as c
from . import source_discovery_metrics as discovery
from . import workflow_effort as effort


def report(policy, outcomes, summaries):
    base = discovery.report(policy, outcomes)
    c.require(type(summaries) is list and len(summaries) <= len(policy['groups'])*2, 'EFFORT_DISCOVERY_ROWS')
    groups = {g['id']: g for g in policy['groups']}; index = {}
    for summary in summaries:
        c.check_seal(summary)
        c.require(summary['schema_version'] == effort.SCHEMA and summary['human_scope'] == effort.HUMAN_SCOPE
                  and type(summary['human_tracking_complete']) is bool,
                  'EFFORT_DISCOVERY_SCHEMA')
        for field in ('elapsed_seconds', 'human_active_seconds', 'human_wait_seconds'):
            value = summary[field]
            c.require((value is None and field != 'elapsed_seconds') or type(value) in (int, float)
                      and math.isfinite(value) and value >= 0, 'EFFORT_DISCOVERY_TIME')
        c.require(type(summary['observed_interventions']) is int and summary['observed_interventions'] >= 0
                  and (summary['retry_count'] is None or type(summary['retry_count']) is int and summary['retry_count'] >= 0),
                  'EFFORT_DISCOVERY_COUNT')
        binding = summary['binding']; key = (binding.get('group_id'), binding.get('arm'))
        c.require(key[0] in groups and key[1] in discovery.ARMS and key not in index, 'EFFORT_DISCOVERY_IDENTITY')
        g = groups[key[0]]
        expected = dict(group_id=g['id'], arm=key[1], policy_sha256=c.digest(policy),
            method_revision=policy['method_revision'], normal_api_sha256=g['normal_api_sha256'],
            owned_purpose_sha256=g['owned_purpose_sha256'], target_snapshot_sha256=g['target_snapshot_sha256'],
            source_sha256=g['source_sha256'] if key[1] == 'CORRECT_SOURCE' else None)
        c.require(binding == expected, 'EFFORT_DISCOVERY_BINDING')
        index[key] = summary
    rows = []
    for g in policy['groups']:
        arms = {arm: index.get((g['id'], arm)) for arm in discovery.ARMS}
        a, b = (arms[arm] for arm in discovery.ARMS)
        c.require(a is None or b is None or a['cost_sources'] == b['cost_sources'],
                  'EFFORT_DISCOVERY_MEASUREMENT_SCOPE')
        differences = {}
        for field in ('elapsed_seconds', 'human_active_seconds', 'human_wait_seconds', 'observed_interventions', 'retry_count'):
            known = a is not None and b is not None and a[field] is not None and b[field] is not None
            if field.startswith('human_') or field == 'observed_interventions':
                known = known and a['human_tracking_complete'] and b['human_tracking_complete']
            differences[field] = a[field]-b[field] if known else None
        cost_differences = {}
        for currency in ('JPY', 'USD'):
            cost_differences[currency] = {}
            for kind in effort.AMOUNTS:
                left = a['cost_vectors'].get(currency, {}).get(kind+'_total') if a else None
                right = b['cost_vectors'].get(currency, {}).get(kind+'_total') if b else None
                cost_differences[currency][kind] = str(Decimal(left)-Decimal(right)) if left is not None and right is not None else None
        rows.append(dict(group_id=g['id'], arms=deepcopy(arms),
                         source_minus_no_source_effort=differences, source_minus_no_source_costs=cost_differences))
    return c.seal(dict(schema_version='reqlox.source-discovery-effort.v0.1',
        discovery_report=base, effort_rows=rows, attempted_arms=base['attempted_arms'],
        supplied_effort_arms=len(summaries), missing_effort_arms=base['attempted_arms']-len(summaries),
        missing_human_time_not_set_to_zero=True, waiting_is_not_human_active_time=True,
        human_time_outside_runner_unknown=True, money_currencies_not_combined=True,
        historical_manual_baseline_not_imputed=True, automation_benefit_certified=False,
        source_contribution_certified=False, independent_generalization_certified=False,
        trace_truth_requires_separate_replay=True, execution_authority=False))
