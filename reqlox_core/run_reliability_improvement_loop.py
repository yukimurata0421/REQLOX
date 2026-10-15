"""Finite reliability controls and verification."""

if __name__ == '__main__' and not __package__:
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))
    __package__ = 'reqlox_core'

import argparse
import datetime
import json
from pathlib import Path
import signal
from . import reliability_reuse as reuse
from . import run_reliability_reuse as runner
METHODS = (*runner.METHODS, 'run_reliability_improvement_loop.py')
QUALIFICATION_POLICIES = ('SOURCE_DERIVED_SHARED_ENVELOPE', 'OWNED_MODEL_GRID')

def method_identity(path):
    return {name: reuse.sha((Path(path) / name).read_bytes()) for name in METHODS}

def confirmation_limit(hypotheses, sites=None):
    if sites:
        return max((len(reuse.propose(site, hypotheses, reuse.LIMITS['probes'], qualification_hypotheses=hypotheses)['faults']) for site in sites))
    return max((len(faults) for faults in reuse.OPERATIONS.values())) + len(reuse.conditions.pool(hypotheses))

def repair_decision(result):
    """Repair decision."""
    rows = result['rows']
    if not rows:
        return 'HELD_NO_EXECUTION'
    if any((not r['observed']['healthy']['contract_pass'] for r in rows)):
        return 'REJECTED_BASELINE_INVALID'
    if any((p['contract_pass'] is None for r in rows for p in r['observed']['probes'])):
        return 'HELD_FAULT_NOT_REACHED'
    if any((r['observed']['fault_discovered'] and r['observed']['repair_pass'] is not True for r in rows)):
        return 'REJECTED_REPAIR_UNQUALIFIED'
    if not any((r['observed']['fault_discovered'] for r in rows)):
        return 'NO_COUNTEREXAMPLE'
    return 'CONFIRM_CANDIDATE' if result['composed_candidate_files'] else 'REJECTED_NO_CHANGE'

def run(sources, contracts, hypotheses, output, *, deadline, maximum_rounds=3, maximum_native_campaigns=24, maximum_probes=3, dependency=None, source_texts=None, supplied_candidates=None, evaluation_kind='DEVELOPMENT_CONTROL', site_cache=None, incident_sets=None, discovery_policy='ISOLATED_SOURCE_KNOWLEDGE', qualification_policy='OWNED_MODEL_GRID', enabled_arms=runner.ARMS, before_native=None):
    enabled_arms = runner.checked_arms(enabled_arms)
    arm_fields = {} if enabled_arms == runner.ARMS else dict(enabled_arms=list(enabled_arms))
    reuse.c.require(type(maximum_rounds) is int and 2 <= maximum_rounds <= 4, 'LOOP_ROUND_LIMIT')
    reuse.c.require(type(maximum_native_campaigns) is int and 0 <= maximum_native_campaigns <= 128, 'LOOP_NATIVE_LIMIT')
    reuse.c.require(discovery_policy in runner.DISCOVERY_POLICIES, 'REUSE_DISCOVERY_POLICY')
    reuse.c.require(qualification_policy in QUALIFICATION_POLICIES, 'LOOP_QUALIFICATION_POLICY')
    end = datetime.datetime.fromisoformat(deadline)
    reuse.c.require(end.tzinfo is not None and 0 < (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds() <= 7200, 'LOOP_DEADLINE')
    reuse.validate_sources(sources)
    source_texts = source_texts or {}
    projections = [reuse.project_incident_set(ir, source_texts[ir['source']['source_record_id']]) for ir in incident_sets or []]
    hypotheses = list(hypotheses) + [h for p in projections for h in p['hypotheses']]
    qualification_hypotheses = hypotheses
    if qualification_policy == 'OWNED_MODEL_GRID':
        qualification_hypotheses, owned_texts = reuse.conditions.owned_qualification()
        reuse.c.require(not set(owned_texts) & set(source_texts), 'LOOP_QUALIFICATION_SOURCE_COLLISION')
        source_texts = dict(source_texts, **owned_texts)
    output = runner.private(output, new=True)
    output.mkdir(mode=448)
    method = method_identity(runner.ROOT / 'reqlox_core')
    archive = output / 'method'
    archive.mkdir(mode=448)
    for name in METHODS:
        with (archive / name).open('xb') as stream:
            stream.write((runner.ROOT / 'reqlox_core' / name).read_bytes())
    inputs = reuse.c.seal(dict(sources=sources, contracts=contracts, hypotheses=hypotheses, source_texts=source_texts, source_projections=projections, incident_sets=incident_sets or [], supplied_candidates=supplied_candidates or {}, evaluation_kind=evaluation_kind, maximum_rounds=maximum_rounds, maximum_native_campaigns=maximum_native_campaigns, maximum_probes=maximum_probes, discovery_policy=discovery_policy, **arm_fields, qualification_policy=qualification_policy, qualification_hypotheses=qualification_hypotheses, confirmation_budget_policy='SUPPORTED_SITE_FAULTS', deadline=deadline, dependency_sha256=None if dependency is None else reuse.sha(Path(dependency).read_bytes()), method=method, site_cache=None if site_cache is None else str(runner.private(site_cache)), acceptance='COUNTEREXAMPLE_THEN_ALL_REPAIRS_THEN_FRESH_FULL_CATALOG_CONFIRMATION', checkout_write_authority=False, provider_calls=0, human_time_measured=False))
    runner.save(output / 'input.json', inputs)
    current = dict(sources)
    history = []
    native = 0
    reused = 0
    pending = False
    status = 'ROUND_LIMIT'
    try:
        for index in range(maximum_rounds):
            reuse.c.require(method_identity(runner.ROOT / 'reqlox_core') == method, 'LOOP_METHOD_CHANGED')
            directory = output / f'round-{index:02d}'
            round_hypotheses = hypotheses if index == 0 else qualification_hypotheses
            result = runner.run(current, contracts, round_hypotheses, directory, maximum_probes=maximum_probes if index == 0 else confirmation_limit(qualification_hypotheses, runner.inventory_for(current)['accepted']), dependency=dependency, source_texts=source_texts, supplied_candidates=supplied_candidates if index == 0 else None, evaluation_kind=evaluation_kind, site_cache=site_cache if index == 0 else output / f'round-{index - 1:02d}', maximum_native_campaigns=maximum_native_campaigns - native, deadline=deadline, discovery_policy=discovery_policy if index == 0 else 'LEGACY_SHARED_POOL', enabled_arms=enabled_arms, before_native=before_native)
            native += result['native_campaigns']
            reused += result['reused_arms']
            decision = repair_decision(result)
            history.append(dict(directory=directory.name, result_sha256=reuse.c.digest(result), decision=decision, snapshot_sha256=reuse.c.digest(current), native_campaigns=result['native_campaigns'], reused_arms=result['reused_arms'], source_faults=result['source_faults'], no_source_faults=result['no_source_faults'], api_exposure_accounting=result['api_exposure_accounting']))
            runner.save(output / f'round-{index:02d}-decision.json', reuse.c.seal(history[-1]))
            if decision == 'NO_COUNTEREXAMPLE':
                status = 'ADOPTED_IN_SNAPSHOT' if pending else 'NO_COUNTEREXAMPLE'
                break
            if decision != 'CONFIRM_CANDIDATE':
                status = decision
                break
            current.update(result['composed_candidate_files'])
            pending = True
        adopted = {p: text for p, text in current.items() if text != sources[p]} if status == 'ADOPTED_IN_SNAPSHOT' else {}
        manifest = reuse.c.seal(dict(status=status, input_sha256=reuse.c.digest(inputs), rounds=history, native_campaigns=native, reused_arms=reused, adopted_files=adopted, adopted_snapshot_sha256=reuse.c.digest(current) if adopted else None, initial_source_comparison=history[0] if history else None, confirmation_is_known_successor=True, checkout_mutated=False, provider_calls=0, human_time_measured=False, independent_generalization_certified=False, natural_source_added_value_certified=False, unsupported_source_conditions=sum((len(p['held']) for p in projections)), automatic_failed_trial_retry=False))
        runner.save(output / 'result.json', manifest)
        verify(output)
        return manifest
    except BaseException as exc:
        if not (output / 'result.json').exists():
            runner.save(output / 'result.json', reuse.c.seal(dict(status='STOPPED', reason=str(exc)[:300], error=type(exc).__name__, rounds=history, completed_native_campaigns=native, input_sha256=reuse.c.digest(inputs), adopted_files={}, checkout_mutated=False, provider_calls=0, automatic_retry=False)))
        raise

def verify(output):
    output = runner.private(output)
    inputs = runner.read(output / 'input.json')
    result = runner.read(output / 'result.json')
    reuse.c.check_seal(inputs)
    reuse.c.check_seal(result)
    enabled_arms = runner.checked_arms(inputs.get('enabled_arms', runner.ARMS))
    policy = inputs.get('qualification_policy', 'SOURCE_DERIVED_SHARED_ENVELOPE')
    reuse.c.require(policy in QUALIFICATION_POLICIES, 'LOOP_QUALIFICATION_POLICY')
    budget_policy = inputs.get('confirmation_budget_policy', 'GLOBAL_PROGRAM_POOL')
    reuse.c.require(budget_policy in ('SUPPORTED_SITE_FAULTS', 'GLOBAL_PROGRAM_POOL'), 'LOOP_CONFIRMATION_BUDGET_POLICY')
    qualification_hypotheses = inputs['hypotheses']
    if policy == 'OWNED_MODEL_GRID':
        qualification_hypotheses, texts = reuse.conditions.owned_qualification()
        reuse.c.require(all((inputs['source_texts'].get(k) == v for k, v in texts.items())), 'LOOP_QUALIFICATION_GRID_DRIFT')
    reuse.c.require(inputs.get('qualification_hypotheses', inputs['hypotheses']) == qualification_hypotheses, 'LOOP_QUALIFICATION_GRID_DRIFT')
    reuse.c.require(inputs['checkout_write_authority'] is False and inputs['human_time_measured'] is False and (type(inputs['provider_calls']) is int) and (inputs['provider_calls'] == 0), 'LOOP_INPUT_CLAIM_DRIFT')
    projections = [reuse.project_incident_set(ir, inputs['source_texts'][ir['source']['source_record_id']]) for ir in inputs['incident_sets']]
    reuse.c.require(projections == inputs['source_projections'], 'LOOP_SOURCE_PROJECTION_DRIFT')
    reuse.c.require(all((result[k] is False for k in ('independent_generalization_certified', 'natural_source_added_value_certified', 'human_time_measured', 'automatic_failed_trial_retry'))) and result['confirmation_is_known_successor'] is True and (type(result['provider_calls']) is int) and (result['provider_calls'] == 0) and (type(result['unsupported_source_conditions']) is int) and (result['unsupported_source_conditions'] == sum((len(p['held']) for p in projections))), 'LOOP_RESULT_CLAIM_DRIFT')
    reuse.c.require(method_identity(output / 'method') == inputs['method'], 'LOOP_ARCHIVED_METHOD_DRIFT')
    reuse.c.require(result['input_sha256'] == reuse.c.digest(inputs) and result['status'] != 'STOPPED', 'LOOP_RESULT_DRIFT')
    current = dict(inputs['sources'])
    native = 0
    reused = 0
    pending = False
    expected_status = 'ROUND_LIMIT'
    reuse.c.require(0 < len(result['rounds']) <= inputs['maximum_rounds'], 'LOOP_ROUND_DENOMINATOR')
    reuse.c.require(result['initial_source_comparison'] == result['rounds'][0], 'LOOP_INITIAL_COMPARISON_DRIFT')
    for index, entry in enumerate(result['rounds']):
        reuse.c.require(entry['directory'] == f'round-{index:02d}', 'LOOP_ROUND_DIRECTORY')
        study, observed = runner.verify(output / entry['directory'])
        decision = repair_decision(observed)
        reuse.c.require(study['sources'] == current and study['contracts'] == inputs['contracts'] and (study['hypotheses'] == (inputs['hypotheses'] if index == 0 else qualification_hypotheses)) and (study['source_texts'] == inputs['source_texts']) and (study['evaluation_kind'] == inputs['evaluation_kind']) and (runner.checked_arms(study.get('enabled_arms', runner.ARMS)) == enabled_arms) and (study.get('discovery_policy', 'LEGACY_SHARED_POOL') == (inputs.get('discovery_policy', 'LEGACY_SHARED_POOL') if index == 0 else 'LEGACY_SHARED_POOL')) and (study['method'] == {k: inputs['method'][k] for k in runner.METHODS}) and (study['maximum_probes'] == (inputs['maximum_probes'] if index == 0 else confirmation_limit(qualification_hypotheses, runner.inventory_for(current)['accepted']) if budget_policy == 'SUPPORTED_SITE_FAULTS' else confirmation_limit(qualification_hypotheses))) and (study['supplied_candidates'] == (inputs['supplied_candidates'] if index == 0 else {})) and (study['dependency_sha256'] == inputs['dependency_sha256']), 'LOOP_INPUT_DRIFT')
        expected = dict(directory=entry['directory'], result_sha256=reuse.c.digest(observed), decision=decision, snapshot_sha256=reuse.c.digest(current), native_campaigns=observed['native_campaigns'], reused_arms=observed['reused_arms'], source_faults=observed['source_faults'], no_source_faults=observed['no_source_faults'], api_exposure_accounting=observed['api_exposure_accounting'])
        reuse.c.require(entry == expected and runner.read(output / f'round-{index:02d}-decision.json') == reuse.c.seal(expected), 'LOOP_DECISION_DRIFT')
        native += observed['native_campaigns']
        reused += observed['reused_arms']
        if decision == 'CONFIRM_CANDIDATE':
            current.update(observed['composed_candidate_files'])
            pending = True
        else:
            reuse.c.require(index == len(result['rounds']) - 1, 'LOOP_TERMINAL_REPLAY')
            expected_status = 'ADOPTED_IN_SNAPSHOT' if decision == 'NO_COUNTEREXAMPLE' and pending else decision
    adopted = {p: text for p, text in current.items() if text != inputs['sources'][p]} if expected_status == 'ADOPTED_IN_SNAPSHOT' else {}
    reuse.c.require(result['status'] == expected_status and result['adopted_files'] == adopted and (result['native_campaigns'] == native <= inputs['maximum_native_campaigns']) and (result['reused_arms'] == reused) and (result['adopted_snapshot_sha256'] == (reuse.c.digest(current) if adopted else None)) and (result['checkout_mutated'] is False), 'LOOP_ADOPTION_DRIFT')
    return (inputs, result)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', required=True, choices=('run', 'verify'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--root')
    parser.add_argument('--configuration')
    parser.add_argument('--deadline')
    parser.add_argument('--maximum-rounds', type=int, default=3)
    parser.add_argument('--maximum-native-campaigns', type=int, default=24)
    parser.add_argument('--dependency')
    parser.add_argument('--site-cache')
    args = parser.parse_args()

    def stopped(*_):
        raise KeyboardInterrupt('LOOP_REQUESTED_STOP')
    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    if args.action == 'verify':
        _, result = verify(args.output)
        print(json.dumps(dict(status='VERIFIED', historical_status=result['status'], new_native_campaigns=0)))
        return
    if not all((args.root, args.configuration, args.deadline)):
        parser.error('run requires --root, --configuration, and --deadline')
    configuration = runner.read(args.configuration)
    sources = runner.load_snapshot(args.root)
    hypotheses = [reuse.hypothesis(h, configuration.get('source_texts', {})) for h in configuration.get('hypotheses', [])]
    result = run(sources, configuration['contracts'], hypotheses, args.output, deadline=args.deadline, maximum_rounds=args.maximum_rounds, maximum_native_campaigns=args.maximum_native_campaigns, maximum_probes=configuration.get('maximum_probes', 3), dependency=args.dependency, source_texts=configuration.get('source_texts'), supplied_candidates=configuration.get('candidates'), site_cache=args.site_cache, discovery_policy=configuration.get('discovery_policy', 'ISOLATED_SOURCE_KNOWLEDGE'), qualification_policy=configuration.get('qualification_policy', 'OWNED_MODEL_GRID'), incident_sets=configuration.get('incident_hypothesis_sets'))
    reuse.c.require(runner.load_snapshot(args.root) == sources, 'LOOP_CHECKOUT_DRIFT')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rounds', 'adopted_files')}, ensure_ascii=False))
if __name__ == '__main__':
    main()
