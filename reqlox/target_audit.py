"""Read-only aggregate audit; archived Python is hashed and never imported."""
import datetime
import os
from pathlib import Path
from . import targets


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    import json
    path = Path(path)
    check(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
          and path.stat().st_size <= 67108864, 'TARGET_AUDIT_ARTIFACT_PATH')
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=nonfinite)


def unique(pairs):
    value = {}
    for k, v in pairs:
        check(k not in value, 'TARGET_AUDIT_DUPLICATE_KEY'); value[k] = v
    return value


def nonfinite(_):
    raise ValueError('TARGET_AUDIT_NONFINITE')


def files(directory):
    import hashlib
    directory = Path(directory)
    if not directory.exists():
        return {}
    check(directory.is_dir() and not any(p.is_symlink() for p in (directory, *directory.parents)), 'TARGET_AUDIT_CHILD_PATH')
    result = {}; size = 0; inspected = 0
    for base, dirs, names in os.walk(directory, followlinks=False):
        inspected += len(dirs) + len(names)
        check(inspected <= 8192, 'TARGET_AUDIT_FILE_LIMIT')
        for name in [*dirs, *names]:
            check(not (Path(base) / name).is_symlink(), 'TARGET_AUDIT_SYMLINK')
        for name in names:
            path = Path(base) / name
            check(path.is_file() and path.stat().st_size <= 67108864, 'TARGET_AUDIT_FILE_BOUND')
            size += path.stat().st_size; check(size <= 268435456, 'TARGET_AUDIT_BYTES_LIMIT')
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def claims(value):
    for key in ('checkout_write_authority', 'independent_generalization_certified', 'natural_source_added_value_certified',
                'probability_calibration_certified', 'automatic_failed_trial_retry'):
        check(value.get(key) is False, 'TARGET_AUDIT_CLAIM_DRIFT')
    check(type(value.get('provider_calls')) is int and value['provider_calls'] == 0, 'TARGET_AUDIT_PROVIDER_DRIFT')


def audit(output):
    import reliability_reuse as reuse
    import run_reliability_reuse as runner
    import run_reliability_improvement_loop as loop
    output = runner.private(Path(output).absolute())
    check(output.is_dir() and output.stat().st_uid == os.getuid() and not output.stat().st_mode & 0o077,
          'TARGET_AUDIT_PRIVATE_DIRECTORY')
    inputs = read(output / 'input.json'); reuse.c.check_seal(inputs)
    plan = inputs['plan']; check(inputs['plan_sha256'] == targets.digest(plan), 'TARGET_AUDIT_PLAN_DRIFT')
    check(plan['schema'] == 'reqlox.target-plan.v1' and inputs['status'] == 'PLANNED', 'TARGET_AUDIT_SCHEMA')
    selected = plan['selected_repositories']
    check(type(selected) is list and 0 < len(selected) <= targets.MAX_REPOSITORIES
          and len(set(selected)) == len(selected), 'TARGET_AUDIT_SELECTION')
    for name in selected: targets.checked_name(name)
    check([r['name'] for r in plan['repositories']] == selected, 'TARGET_AUDIT_PLAN_SELECTION')
    check(plan['checkout_write_authority'] is False and plan['statistical_independence_certified'] is False
          and type(plan['provider_calls']) is int and plan['provider_calls'] == 0, 'TARGET_AUDIT_PLAN_CLAIMS')
    check(type(plan['maximum_native_campaigns']) is int and 0 <= plan['maximum_native_campaigns'] <= 64
          and type(plan['seconds']) is int and 1 <= plan['seconds'] <= 7200, 'TARGET_AUDIT_BUDGET')
    check(inputs['run_name'] == output.name, 'TARGET_AUDIT_RUN_NAME')
    start = datetime.datetime.fromisoformat(inputs['started_at']); end = datetime.datetime.fromisoformat(inputs['deadline'])
    check(start.tzinfo is not None and end.tzinfo is not None and (end-start).total_seconds() == plan['seconds'], 'TARGET_AUDIT_DEADLINE')
    method = loop.method_identity(Path(runner.__file__).parent)
    if plan['paired']:
        import run_reliability_paired as pair
        method = pair.method_identity(Path(runner.__file__).parent)
    check(plan['method']['target_workspace'] == reuse.sha(Path(targets.__file__).read_bytes())
          and plan['method']['core'] == method, 'TARGET_AUDIT_METHOD_UNSUPPORTED')
    has_context = any(r.get('execution_method') == 'DOCUMENTED_SYNC_PATH_CONTEXT_V1' for r in plan['repositories'])
    if has_context:
        from . import target_context
        check(not plan['paired'] and plan['method'].get('path_context') == target_context.method_identity(),
              'TARGET_AUDIT_CONTEXT_METHOD_UNSUPPORTED')
    else:
        check('path_context' not in plan['method'], 'TARGET_AUDIT_UNEXPECTED_CONTEXT_METHOD')
    prior_attempts = 0
    if 'authorization' in plan:
        from . import target_authorization
        check(plan['method'].get('authorization') == reuse.sha(Path(target_authorization.__file__).read_bytes()),
              'TARGET_AUDIT_AUTHORIZATION_METHOD')
        authorization, view = target_authorization.inspect(inputs['authorization']['path'])
        target_authorization.check_plan(authorization, plan)
        check(view == inputs['authorization'] and view['status'] == 'APPROVED'
              and plan['authorization']['reviewed_binding_sha256'] == view['reviewed_binding_sha256']
              and plan['authorization']['prior_native_attempts'] == view['prior_native_attempts'],
              'TARGET_AUDIT_AUTHORIZATION_DRIFT')
        check(end <= datetime.datetime.fromisoformat(authorization['deadline']), 'TARGET_AUDIT_AUTHORIZATION_DEADLINE')
        prior_attempts = view['prior_native_attempts']
        claim = read(Path(authorization['reservation_directory']) / 'claim.json')
        check(claim['plan_sha256'] == inputs['plan_sha256'] and claim['prior_native_attempts'] == prior_attempts
              and claim['charged_window_seconds'] == authorization['maximum_window_seconds']
              and claim['deadline'] == inputs['deadline'], 'TARGET_AUDIT_AUTHORIZATION_CLAIM')
    else:
        check('authorization' not in inputs and 'authorization' not in plan['method'], 'TARGET_AUDIT_UNEXPECTED_AUTHORIZATION')
    for summary in plan['repositories']:
        preparation = read(output / 'preparations' / (summary['name'] + '.json')); reuse.c.check_seal(preparation)
        check(preparation['name'] == summary['name'] and targets.digest(preparation['sources']) == summary['sources_sha256']
              and targets.digest(preparation['configuration']) == summary['configuration_sha256'], 'TARGET_AUDIT_PREPARATION_DRIFT')
        targets.validate_configuration(preparation['configuration'])
        check(targets.digest(runner.inventory_for(preparation['sources'])) == summary['inventory_sha256'], 'TARGET_AUDIT_INVENTORY_DRIFT')
        eligible, held = runner.eligible_sites(runner.inventory_for(preparation['sources']), preparation['sources'],
            preparation['configuration']['contracts'], {}, summary['dependency_sha256'] is not None)
        if 'path_context' in preparation['configuration']:
            from . import target_context
            context_plan = target_context.prepare(preparation['sources'], preparation['configuration'])
            check(summary.get('execution_method') == target_context.PROFILE and summary['dependency_sha256'] is None
                  and summary.get('context_plan_sha256') == targets.digest(context_plan)
                  and summary.get('context_contract_sha256') == targets.digest(preparation['configuration']['path_context']['contract'])
                  and summary.get('atomic_held_bindings') == held and summary['accepted_sites'] == 1
                  and summary['executable_sites'] == 1 and summary['held_sites'] == 0 and summary['held_bindings'] == [],
                  'TARGET_AUDIT_CONTEXT_PREPARATION_DRIFT')
            continue
        check('execution_method' not in summary, 'TARGET_AUDIT_UNEXPECTED_EXECUTION_METHOD')
        check(len(runner.inventory_for(preparation['sources'])['accepted']) == summary['accepted_sites']
              and len(eligible) == summary['executable_sites'] and held == summary['held_bindings']
              and len(held) == summary['held_sites'], 'TARGET_AUDIT_BINDING_DRIFT')
    reservations = sorted(output.glob('native-reservation-*.json'))
    check(prior_attempts + len(reservations) <= plan['maximum_native_campaigns'], 'TARGET_AUDIT_RESERVATION_LIMIT')
    if prior_attempts:
        check(len(reservations) <= authorization['maximum_new_native_campaigns'], 'TARGET_AUDIT_AUTHORIZATION_LIMIT')
    reserved = {name: 0 for name in selected}; order = []
    for number, path in enumerate(reservations, prior_attempts + 1):
        record = read(path)
        check(path.name == f'native-reservation-{number:03d}.json' and record['attempt'] == number
              and record['maximum'] == plan['maximum_native_campaigns'] and record['deadline'] == inputs['deadline']
              and record['plan_sha256'] == inputs['plan_sha256'] and record['repository'] in reserved
              and record['status'] == 'RESERVED_BEFORE_DISPATCH'
              and record['outcome'] == 'UNKNOWN_UNTIL_CHILD_RECEIPT', 'TARGET_AUDIT_RESERVATION_DRIFT')
        reserved[record['repository']] += 1; order.append(selected.index(record['repository']))
        if prior_attempts:
            check(read(Path(authorization['reservation_directory']) / path.name) == record,
                  'TARGET_AUDIT_AUTHORIZATION_RESERVATION')
    check(order == sorted(order), 'TARGET_AUDIT_RESERVATION_ORDER')
    if not (output / 'result.json').exists():
        return dict(status='INCOMPLETE', historical_status='UNKNOWN_TERMINAL', native_attempts=prior_attempts + len(reservations),
            unverified_repositories=selected, aggregate_consistency_verified=False, child_semantics_verified=False,
            new_native_campaigns=0, new_provider_calls=0, archived_code_executed=False)
    result = read(output / 'result.json'); reuse.c.check_seal(result); claims(result)
    check(result['schema'] == 'reqlox.target-run.v1' and result['output'] == str(output)
          and result['plan_sha256'] == inputs['plan_sha256'] and result['deadline'] == inputs['deadline']
          and result['maximum_native_campaigns'] == plan['maximum_native_campaigns']
          and type(result['native_attempts']) is int and result['native_attempts'] == prior_attempts + len(reservations), 'TARGET_AUDIT_AGGREGATE_DRIFT')
    if 'authorization' in plan:
        check(result.get('prior_native_attempts') == prior_attempts
              and result.get('new_native_attempts') == len(reservations)
              and result.get('prior_charged_seconds') == authorization['prior_charged_seconds']
              and result.get('charged_window_seconds') == authorization['maximum_window_seconds']
              and result.get('authorization_record_sha256') == view['record_sha256'], 'TARGET_AUDIT_AUTHORIZATION_TOTAL')
    check(result['checkout_unchanged_scope'] == 'SELECTED_PYTHON_SOURCE_SNAPSHOTS'
          and type(result['checkout_unchanged']) is bool, 'TARGET_AUDIT_CHECKOUT_CLAIM')
    rows = result['repositories']; check([r['name'] for r in rows] == selected, 'TARGET_AUDIT_RESULT_SELECTION')
    verified = []; stopped = False
    for summary, row in zip(plan['repositories'], rows):
        name = row['name']; child = output / 'repositories' / name
        check(row['native_attempts'] == reserved[name], 'TARGET_AUDIT_REPOSITORY_BUDGET')
        check(row['evidence_files'] == files(child), 'TARGET_AUDIT_CHILD_FILE_DRIFT')
        if stopped:
            check(row['status'] == 'NOT_RUN_AFTER_STOP' and row['output'] is None and not reserved[name]
                  and not row['evidence_files'], 'TARGET_AUDIT_UNEXECUTED_DRIFT')
            continue
        if row['status'] == 'STOPPED':
            stopped = True
        if row['output'] is None:
            check(row['status'] == 'STOPPED' and not row['evidence_files'] and not reserved[name], 'TARGET_AUDIT_CHILD_MISSING')
            continue
        check(row['output'] == str(child), 'TARGET_AUDIT_CHILD_ESCAPE')
        if (child / 'result.json').exists():
            observed = read(child / 'result.json'); reuse.c.check_seal(observed)
            check(row['result_sha256'] == targets.digest(observed), 'TARGET_AUDIT_CHILD_RESULT_DRIFT')
        else:
            check(row['status'] == 'STOPPED', 'TARGET_AUDIT_CHILD_RESULT_MISSING'); continue
        child_inputs = read(child / 'input.json'); reuse.c.check_seal(child_inputs)
        if summary.get('execution_method') == 'DOCUMENTED_SYNC_PATH_CONTEXT_V1':
            preparation = read(output / 'preparations' / (name + '.json'))
            context_plan = target_context.prepare(preparation['sources'], preparation['configuration'])
            remaining = plan['maximum_native_campaigns'] - prior_attempts - sum(reserved[n] for n in selected[:selected.index(name)])
            check(child_inputs['deadline'] == inputs['deadline']
                  and child_inputs['maximum_native_campaigns'] == remaining, 'TARGET_AUDIT_CONTEXT_BUDGET')
            if row['status'] == 'STOPPED':
                check(row.get('finite_contract_completed') is False, 'TARGET_AUDIT_STOP_SUCCESS'); continue
            _, observed = target_context.verify(child, context_plan, preparation['configuration']['path_context']['contract'])
            check(row['status'] == observed['status'] and row['finite_contract_completed'] == (observed['status'] == 'NO_COUNTEREXAMPLE')
                  and row['completed_native_campaigns'] == observed['native_campaigns'] <= reserved[name],
                  'TARGET_AUDIT_CONTEXT_COMPLETION')
            verified.append(name)
            continue
        check(child_inputs['method'] == method and child_inputs['deadline'] == inputs['deadline']
              and targets.digest(child_inputs['sources']) == summary['sources_sha256'], 'TARGET_AUDIT_CHILD_INPUT_DRIFT')
        for filename, sha256 in method.items():
            check(reuse.sha((child / 'method' / filename).read_bytes()) == sha256, 'TARGET_AUDIT_ARCHIVE_DRIFT')
        preparation = read(output / 'preparations' / (name + '.json'))['configuration']
        check(child_inputs['maximum_rounds'] == plan['maximum_rounds']
              and child_inputs['maximum_probes'] == preparation.get('maximum_probes', 3), 'TARGET_AUDIT_CHILD_BUDGET_DRIFT')
        remaining = plan['maximum_native_campaigns'] - prior_attempts - sum(reserved[n] for n in selected[:selected.index(name)])
        if plan['paired']:
            import reliability_requirement_experiment as requirements
            policies = {family: {k: value[k] for k in ('basis', 'scope')} for family, value in preparation['contracts'].items()}
            expected_experiment = requirements.prepare(child_inputs['sources'], preparation.get('specification_texts', {}), policies)
            check(child_inputs['experiment'] == expected_experiment
                  and child_inputs['source_texts'] == preparation.get('source_texts', {})
                  and child_inputs['maximum_native_campaigns_per_arm'] == remaining, 'TARGET_AUDIT_CHILD_CONTRACT_DRIFT')
        else:
            hypotheses = [reuse.hypothesis(h, preparation.get('source_texts', {})) for h in preparation.get('hypotheses', [])]
            _, owned = reuse.conditions.owned_qualification()
            expected_texts = dict(preparation.get('source_texts', {}), **owned)
            check(child_inputs['contracts'] == preparation['contracts'] and child_inputs['hypotheses'] == hypotheses
                  and child_inputs['source_texts'] == expected_texts
                  and child_inputs['maximum_native_campaigns'] == remaining
                  and child_inputs['dependency_sha256'] == summary['dependency_sha256'], 'TARGET_AUDIT_CHILD_CONTRACT_DRIFT')
        if row['status'] == 'STOPPED':
            check(row.get('finite_contract_completed') is False, 'TARGET_AUDIT_STOP_SUCCESS'); continue
        check(row['status'] == observed['status'], 'TARGET_AUDIT_CHILD_STATUS_DRIFT')
        # Use only the currently installed verifier, after exact method matching.
        if plan['paired']:
            _, observed = pair.verify(child)
            qualified = all(arm['status'] in ('ADOPTED_IN_SNAPSHOT', 'NO_COUNTEREXAMPLE') for arm in observed['arms'].values())
        else:
            _, observed = loop.verify(child)
            qualified = observed['status'] in ('ADOPTED_IN_SNAPSHOT', 'NO_COUNTEREXAMPLE')
        check(row['finite_contract_completed'] == (qualified and summary['held_sites'] == 0)
              and row['completed_native_campaigns'] == observed['native_campaigns'] <= reserved[name], 'TARGET_AUDIT_FINITE_COMPLETION')
        verified.append(name)
    expected_status = 'STOPPED' if stopped or not result['checkout_unchanged'] else 'COMPLETE' if all(r.get('finite_contract_completed') for r in rows) else 'PARTIAL'
    check(result['status'] == expected_status and ((result['reason'] is not None) == (expected_status == 'STOPPED')), 'TARGET_AUDIT_STATUS_DRIFT')
    return dict(status='VERIFIED', historical_status=result['status'], native_attempts=prior_attempts + len(reservations),
        aggregate_consistency_verified=True, child_semantics_verified=len(verified) == len(selected),
        verified_repositories=verified, unverified_repositories=[n for n in selected if n not in verified],
        new_native_campaigns=0, new_provider_calls=0, archived_code_executed=False,
        independent_generalization_certified=False, natural_source_added_value_certified=False, probability_calibration_certified=False)
