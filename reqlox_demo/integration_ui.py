"""Read-only, allowlisted view of retained module-integration observations."""
from pathlib import Path
from reqlox import target_integration as integration


def summarize(run):
    run = Path(run)
    audited = integration.audit(run)
    terminal = audited['terminal']
    phases = []
    for phase in audited['phases']:
        rows = []
        if phase['status'] == 'VERIFIED':
            rows = integration.read(run / f"phase-{phase['attempt']}" / 'observed.json')['rows']
        count = lambda values: dict(passed=sum(row['passed'] for row in values), total=len(values))
        phases.append(dict(attempt=phase['attempt'], status=phase['status'],
                           faults=count(rows[:5]), normal=count(rows[5:9]), boundary=count(rows[9:]),
                           scratch_removed=sum(row['scratch_removed'] for row in rows),
                           lock_released=sum(row['lock_released'] for row in rows),
                           failed_api_cleanup=sum(not row['owned_pending_removed'] for row in rows[:3])))
    adopted = terminal['adoption'] == 'ADOPT_EXISTING_CANDIDATE_FOR_ISOLATED_COMPOSED_CALLER'
    return dict(audit='VERIFIED_LOCAL_HASH_AUDIT', cumulative_campaigns=terminal['cumulative_native_campaigns'],
                cumulative_charged_seconds=terminal['cumulative_charged_seconds'],
                maximum_campaigns=15, maximum_seconds=120, new_campaigns=terminal['new_native_campaigns'],
                phases=phases, adoption='ADOPTED_ISOLATED_COPY' if adopted else 'NOT_ADOPTED_OR_UNKNOWN',
                candidate_scope='ISOLATED_COMPOSED_CALLER_ONLY', held_atomic_bindings=4,
                temppath_repair_performed=False, historical_raw_evidence_gap=True,
                originals_preserved=terminal['original_preserved'], additional_execution_enabled=False,
                independent_generalization=False, probability_calibration=False, source_added_value=False)


def summarize_public(record):
    """Validate an archived aggregate without accepting paths or raw evidence."""
    def check(condition):
        if not condition:
            raise ValueError('PUBLIC_INTEGRATION_SUMMARY_INVALID')
    check(type(record) is dict and set(record) == {'schema', 'summary'}
          and record['schema'] == 'REQLOX_PUBLIC_INTEGRATION_SUMMARY_V1')
    value = record['summary']
    fields = {'audit', 'cumulative_campaigns', 'cumulative_charged_seconds', 'maximum_campaigns',
              'maximum_seconds', 'new_campaigns', 'phases', 'adoption', 'candidate_scope',
              'held_atomic_bindings', 'temppath_repair_performed', 'historical_raw_evidence_gap',
              'originals_preserved', 'additional_execution_enabled', 'independent_generalization',
              'probability_calibration', 'source_added_value'}
    check(type(value) is dict and set(value) == fields)
    for name, expected in {'cumulative_campaigns': 15, 'cumulative_charged_seconds': 62,
                           'maximum_campaigns': 15, 'maximum_seconds': 120, 'new_campaigns': 3,
                           'held_atomic_bindings': 4}.items():
        check(type(value[name]) is int and value[name] == expected)
    for name in ('temppath_repair_performed', 'additional_execution_enabled', 'independent_generalization',
                 'probability_calibration', 'source_added_value'):
        check(value[name] is False)
    check(value['originals_preserved'] is True and value['historical_raw_evidence_gap'] is True
          and value['audit'] == 'VERIFIED_LOCAL_HASH_AUDIT'
          and value['adoption'] in ('ADOPTED_ISOLATED_COPY', 'NOT_ADOPTED_OR_UNKNOWN')
          and value['candidate_scope'] == 'ISOLATED_COMPOSED_CALLER_ONLY')
    check(type(value['phases']) is list and len(value['phases']) == 3)
    for number, phase in zip((13, 14, 15), value['phases']):
        check(type(phase) is dict and set(phase) == {'attempt', 'status', 'faults', 'normal', 'boundary',
                                                  'scratch_removed', 'lock_released', 'failed_api_cleanup'}
              and type(phase['attempt']) is int and phase['attempt'] == number and phase['status'] == 'VERIFIED')
        for stage, total in (('faults', 5), ('normal', 4), ('boundary', 1)):
            count = phase[stage]
            check(type(count) is dict and set(count) == {'passed', 'total'}
                  and type(count['passed']) is int and 0 <= count['passed'] <= total
                  and type(count['total']) is int and count['total'] == total)
        for name, maximum in (('scratch_removed', 10), ('lock_released', 10), ('failed_api_cleanup', 3)):
            check(type(phase[name]) is int and 0 <= phase[name] <= maximum)
    import copy
    output = copy.deepcopy(value)
    output['audit'] = 'ARCHIVED_LOCAL_HASH_AUDIT'
    return output
