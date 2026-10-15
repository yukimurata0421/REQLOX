"""Finite reliability controls and verification."""
import argparse
import datetime
import json
from pathlib import Path
import signal
import reliability_requirement_experiment as requirements
import reliability_source_conditions as natural
import reliability_specifications as specifications
import reliability_reuse as reuse
import run_reliability_reuse as runner
import run_reliability_improvement_loop as loop
METHODS = (*loop.METHODS, 'reliability_requirement_experiment.py', 'reliability_specifications.py', 'reliability_source_conditions.py', 'run_reliability_paired.py')

def method_identity(path):
    return {name: reuse.sha((Path(path) / name).read_bytes()) for name in METHODS}

def hypotheses_for(sources, contracts, source_texts):
    if not source_texts:
        return ([], [])
    configuration = natural.prepare(sources, contracts, source_texts)
    return ([reuse.hypothesis(h, source_texts) for h in configuration['hypotheses']], configuration['selection']['held'])

def novelty(sources, hypotheses):
    """Novelty."""

    def geometry(program):
        return tuple((program[k] for k in ('family', 'operation', 'phase', 'occurrence')))
    rows = []
    for site in runner.inventory_for(sources)['accepted']:
        own = reuse.propose(site, [], reuse.LIMITS['probes'], include_owned_grid=True)
        source = reuse.propose(site, hypotheses, reuse.LIMITS['probes'], include_owned_grid=True)
        own_geometry = {geometry(p) for p in own.get('condition_programs', {}).values()}
        external = {geometry(p) for p in source.get('condition_programs', {}).values() if p['source_id'] != 'owned-model-qualification-grid-v1'}
        rows.append(dict(site_id=site['id'], source_lifecycle_conditions=len(external), conditions_already_in_owned_grid=len(external & own_geometry), conditions_outside_owned_grid=len(external - own_geometry)))
    return rows

def summarize(inputs, results):
    arms = {}
    for arm in runner.ARMS:
        result = results[arm]
        initial = result['rounds'][0]
        arms[arm] = dict(status=result['status'], api_exposure_accounting=initial['api_exposure_accounting']['arms'][arm], initial_faults=initial['source_faults' if arm == 'SOURCE' else 'no_source_faults'], adopted=bool(result['adopted_files']), adopted_members=sorted(result['adopted_files']), native_campaigns=result['native_campaigns'], reused_arms=result['reused_arms'])
    return reuse.c.seal(dict(status='COMPLETE', input_sha256=reuse.c.digest(inputs), arms=arms, arm_result_sha256={arm: reuse.c.digest(results[arm]) for arm in runner.ARMS}, source_only_initial_fault_difference=arms['SOURCE']['initial_faults'] - arms['NO_SOURCE']['initial_faults'], source_only_initial_repair_unit_fault_difference=arms['SOURCE']['api_exposure_accounting']['faulty_repair_units'] - arms['NO_SOURCE']['api_exposure_accounting']['faulty_repair_units'], source_only_adoption_difference=int(arms['SOURCE']['adopted']) - int(arms['NO_SOURCE']['adopted']), source_condition_novelty=novelty(inputs['sources'], inputs['hypotheses']), comparison_unit='INDEPENDENT_ARM_SNAPSHOT', interpretation='CLIENT_REQUIREMENT_COMPATIBILITY_ONLY', execution_order=inputs['arm_order'], native_campaigns=sum((r['native_campaigns'] for r in results.values())), checkout_mutated=False, target_bug_claim_eligible=False, independent_generalization_certified=False, natural_source_added_value_certified=False, calibration_certified=False, provider_calls=0, human_time_measured=False, automatic_failed_trial_retry=False))

def run(sources, experiment, source_texts, output, *, deadline, maximum_probes=3, maximum_rounds=3, maximum_native_campaigns_per_arm=12, arm_order=runner.ARMS, supplied_candidates_by_arm=None, before_native=None):
    requirements.verify(experiment, sources)
    specifications.check_roles(experiment['specification_texts'], source_texts)
    reuse.c.require(type(maximum_native_campaigns_per_arm) is int and 0 <= maximum_native_campaigns_per_arm <= 64, 'PAIRED_NATIVE_LIMIT')
    reuse.c.require(type(maximum_rounds) is int and 2 <= maximum_rounds <= 4, 'LOOP_ROUND_LIMIT')
    reuse.c.require(type(maximum_probes) is int and 1 <= maximum_probes <= reuse.LIMITS['probes'], 'REUSE_PROBE_LIMIT')
    reuse.c.require(type(arm_order) in (tuple, list) and len(arm_order) == 2 and (set(arm_order) == set(runner.ARMS)), 'PAIRED_ARM_ORDER')
    end = datetime.datetime.fromisoformat(deadline)
    reuse.c.require(end.tzinfo is not None and 0 < (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds() <= 7200, 'LOOP_DEADLINE')
    candidates = supplied_candidates_by_arm or {}
    reuse.c.require(type(candidates) is dict and set(candidates) <= set(runner.ARMS) and all((type(v) is dict for v in candidates.values())), 'PAIRED_CANDIDATES')
    hypotheses, held = hypotheses_for(sources, experiment['contracts'], source_texts)
    output = runner.private(output, new=True)
    output.mkdir(mode=448)
    method = method_identity(runner.ROOT / 'reqlox_core')
    archive = output / 'method'
    archive.mkdir(mode=448)
    for name in METHODS:
        with (archive / name).open('xb') as stream:
            stream.write((runner.ROOT / 'reqlox_core' / name).read_bytes())
    inputs = reuse.c.seal(dict(kind='PAIRED_REQUIREMENT_STUDY_V1', sources=sources, experiment=experiment, source_texts=source_texts, hypotheses=hypotheses, held_source_conditions=held, maximum_probes=maximum_probes, maximum_rounds=maximum_rounds, maximum_native_campaigns_per_arm=maximum_native_campaigns_per_arm, arm_order=list(arm_order), deadline=deadline, method=method, supplied_candidates_by_arm=candidates, checkout_write_authority=False, provider_calls=0))
    runner.save(output / 'input.json', inputs)
    results = {}
    try:
        for arm in arm_order:
            reuse.c.require(method_identity(runner.ROOT / 'reqlox_core') == method, 'PAIRED_METHOD_CHANGED')
            results[arm] = loop.run(dict(sources), experiment['contracts'], hypotheses if arm == 'SOURCE' else [], output / arm.lower(), deadline=deadline, maximum_rounds=maximum_rounds, maximum_native_campaigns=maximum_native_campaigns_per_arm, maximum_probes=maximum_probes, source_texts=source_texts if arm == 'SOURCE' else {}, enabled_arms=(arm,), supplied_candidates=candidates.get(arm), evaluation_kind='OWNED_REQUIREMENT_CONTROL', discovery_policy='ISOLATED_SOURCE_KNOWLEDGE', qualification_policy='OWNED_MODEL_GRID', before_native=before_native)
        result = summarize(inputs, results)
        runner.save(output / 'result.json', result)
        verify(output)
        return result
    except BaseException as exc:
        if not (output / 'result.json').exists():
            runner.save(output / 'result.json', reuse.c.seal(dict(status='STOPPED', error=type(exc).__name__, reason=str(exc)[:300], input_sha256=reuse.c.digest(inputs), completed_arms=list(results), adopted_files={}, checkout_mutated=False, automatic_retry=False, provider_calls=0)))
        raise

def verify(output):
    output = runner.private(output)
    inputs = runner.read(output / 'input.json')
    result = runner.read(output / 'result.json')
    reuse.c.check_seal(inputs)
    reuse.c.check_seal(result)
    requirements.verify(inputs['experiment'], inputs['sources'])
    specifications.check_roles(inputs['experiment']['specification_texts'], inputs['source_texts'])
    hypotheses, held = hypotheses_for(inputs['sources'], inputs['experiment']['contracts'], inputs['source_texts'])
    reuse.c.require(hypotheses == inputs['hypotheses'] and held == inputs['held_source_conditions'], 'PAIRED_SOURCE_DRIFT')
    reuse.c.require(method_identity(output / 'method') == inputs['method'], 'PAIRED_ARCHIVED_METHOD_DRIFT')
    reuse.c.require(inputs['checkout_write_authority'] is False and inputs['provider_calls'] == 0 and (inputs['arm_order'] in (list(runner.ARMS), list(reversed(runner.ARMS)))), 'PAIRED_INPUT_DRIFT')
    results = {}
    for arm in runner.ARMS:
        child, results[arm] = loop.verify(output / arm.lower())
        owned_hypotheses, owned_texts = reuse.conditions.owned_qualification()
        expected_texts = dict(inputs['source_texts'] if arm == 'SOURCE' else {}, **owned_texts)
        reuse.c.require(child['sources'] == inputs['sources'] and child['contracts'] == inputs['experiment']['contracts'] and (child['hypotheses'] == (hypotheses if arm == 'SOURCE' else [])) and (child['source_texts'] == expected_texts) and (child['enabled_arms'] == [arm]) and (child['incident_sets'] == []) and (child['source_projections'] == []) and (child['supplied_candidates'] == inputs['supplied_candidates_by_arm'].get(arm, {})) and (child['site_cache'] is None) and (child['dependency_sha256'] is None) and (child['maximum_rounds'] == inputs['maximum_rounds']) and (child['maximum_probes'] == inputs['maximum_probes']) and (child['maximum_native_campaigns'] == inputs['maximum_native_campaigns_per_arm']) and (child['deadline'] == inputs['deadline']) and (child['evaluation_kind'] == 'OWNED_REQUIREMENT_CONTROL') and (child['discovery_policy'] == 'ISOLATED_SOURCE_KNOWLEDGE') and (child['qualification_policy'] == 'OWNED_MODEL_GRID') and (child['method'] == {k: inputs['method'][k] for k in loop.METHODS}), 'PAIRED_ARM_INPUT_DRIFT')
    reuse.c.require(result == summarize(inputs, results), 'PAIRED_RESULT_DRIFT')
    return (inputs, result)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', required=True, choices=('run', 'verify'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--root')
    parser.add_argument('--configuration')
    parser.add_argument('--deadline')
    parser.add_argument('--maximum-native-campaigns-per-arm', type=int, default=12)
    args = parser.parse_args()

    def stopped(*_):
        raise KeyboardInterrupt('PAIRED_REQUESTED_STOP')
    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    if args.action == 'verify':
        _, result = verify(args.output)
        print(json.dumps(dict(status='VERIFIED', historical_status=result['status'], new_native_campaigns=0)))
        return
    if not all((args.root, args.configuration, args.deadline)):
        parser.error('run requires root, configuration and deadline')
    configuration = runner.read(args.configuration)
    sources = runner.load_snapshot(args.root)
    experiment = requirements.prepare(sources, configuration.get('specification_texts', {}), configuration['owner_policies'])
    result = run(sources, experiment, configuration.get('source_texts', {}), args.output, deadline=args.deadline, maximum_probes=configuration.get('maximum_probes', 3), maximum_rounds=configuration.get('maximum_rounds', 3), maximum_native_campaigns_per_arm=args.maximum_native_campaigns_per_arm)
    reuse.c.require(runner.load_snapshot(args.root) == sources, 'LOOP_CHECKOUT_DRIFT')
    print(json.dumps(result, ensure_ascii=False))
if __name__ == '__main__':
    main()
