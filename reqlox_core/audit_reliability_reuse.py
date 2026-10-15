"""Finite reliability controls and verification."""

if __name__ == '__main__' and not __package__:
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))
    __package__ = 'reqlox_core'

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from .archive_loader import archived_method
from .reqlox_paths import state_root
ROOT = Path(__file__).resolve().parents[1]

def claim_limits(output, kind, seen=None):
    """Current finite reliability method; public state remains outside the package."""
    seen = set() if seen is None else seen
    output = Path(output).absolute()
    if not output.is_relative_to(state_root()) or any((p.is_symlink() for p in (output, *output.parents))):
        raise ValueError('REUSE_AUDIT_SCOPE')
    if output in seen:
        return
    if len(seen) >= 65:
        raise ValueError('REUSE_AUDIT_REFERENCE_LIMIT')
    seen.add(output)

    def checked(value, false_fields, true_fields=()):
        if type(value) is not dict:
            raise ValueError('REUSE_AUDIT_CLAIM_DRIFT')
        if any((k in value and value[k] is not False for k in false_fields)) or any((k in value and value[k] is not True for k in true_fields)) or ('provider_calls' in value and (type(value['provider_calls']) is not int or value['provider_calls'] != 0)):
            raise ValueError('REUSE_AUDIT_CLAIM_DRIFT')
        if 'api_exposure_accounting' in value:
            checked(value['api_exposure_accounting'], ('statistical_independence_certified', 'natural_applicability_denominator_known'))
        if 'arms' in value and type(value['arms']) is dict:
            for arm in value['arms'].values():
                checked(arm, ('statistical_independence_certified', 'natural_applicability_denominator_known'))
    study = json.loads((output / ('input.json' if kind in ('loop', 'paired') else 'study.json')).read_bytes())
    result = json.loads((output / 'result.json').read_bytes())
    if kind == 'paired':
        checked(study, ('checkout_write_authority',))
        checked(result, ('independent_generalization_certified', 'natural_source_added_value_certified', 'calibration_certified', 'human_time_measured', 'automatic_failed_trial_retry', 'target_bug_claim_eligible', 'checkout_mutated'))
        for arm in ('source', 'no_source'):
            claim_limits(output / arm, 'loop', seen)
    elif kind == 'loop':
        checked(study, ('checkout_write_authority', 'human_time_measured'))
        checked(result, ('independent_generalization_certified', 'natural_source_added_value_certified', 'human_time_measured', 'automatic_failed_trial_retry', 'checkout_mutated'), ('confirmation_is_known_successor',))
        for entry in result['rounds']:
            checked(entry, ())
            if not re.fullmatch('round-[0-9]{2}', entry['directory']):
                raise ValueError('REUSE_AUDIT_ROUND_PATH')
            claim_limits(output / entry['directory'], 'run', seen)
    else:
        checked(study, ('source_semantic_support_certified', 'source_selection_automatic', 'human_time_measured', 'automatic_terminal_retry'))
        checked(result, ('natural_source_added_value_certified', 'population_generalization_certified', 'human_time_measured'), ('reused_results_are_historical',))
        for entry in study['entries']:
            if 'reference' in entry:
                claim_limits(entry['reference']['directory'], 'run', seen)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--kind', choices=('run', 'loop', 'paired'), default='run')
    args = parser.parse_args()
    output = Path(args.output).absolute()
    if not output.is_relative_to(state_root()) or any((p.is_symlink() for p in (output, *output.parents))):
        raise ValueError('REUSE_AUDIT_SCOPE')
    claim_limits(output, args.kind)
    study = json.loads((output / ('input.json' if args.kind in ('loop', 'paired') else 'study.json')).read_bytes())
    verifier = {
        'run': 'run_reliability_reuse',
        'loop': 'run_reliability_improvement_loop',
        'paired': 'run_reliability_paired',
    }[args.kind]
    with archived_method(output / 'method', study['method']) as load:
        archived = load('run_reliability_reuse')
        archived.ROOT = ROOT
        _, result = load(verifier).verify(output)
    print(json.dumps(dict(status='VERIFIED', historical_status=result['status'], native_campaigns_in_history=result['native_campaigns'], new_native_campaigns=0, new_provider_calls=0, historical_method_used=True, current_claim_limits_checked=True)))
if __name__ == '__main__':
    main()
