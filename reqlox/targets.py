"""Named repositories, static input identities, and one shared finite run budget."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA = 'reqlox.target.v1'
MAX_REPOSITORIES = 16
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')


def checked_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError('Names require 1..64 letters, digits, dots, underscores or hyphens')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def path_at(value, base, *, directory=False, new=False):
    if not isinstance(value, str) or not value or '\0' in value:
        raise ValueError('Expected a nonempty filesystem path')
    path = Path(os.path.abspath(base / value))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink paths are not supported')
    if new:
        if path.exists() or not path.parent.is_dir():
            raise ValueError('Output must be new and its parent directory must exist')
    elif not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f'Missing path: {path}')
    return path


def read_json(path):
    if path.stat().st_size > 262144:
        raise ValueError('JSON input exceeds 256 KiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON number')
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def validate_manifest(value):
    if (not isinstance(value, dict) or not {'schema', 'name', 'repositories'} <= set(value)
            or set(value) - {'schema', 'name', 'repositories', 'snapshot_receipt', 'authorization'} or value['schema'] != SCHEMA):
        raise ValueError('Expected a reqlox.target.v1 manifest')
    if 'snapshot_receipt' in value:
        receipt = value['snapshot_receipt']
        if not isinstance(receipt, str) or '\0' in receipt or Path(receipt).name != 'snapshot.json':
            raise ValueError('Expected a snapshot.json receipt path')
    if 'authorization' in value and (type(value['authorization']) is not str or not value['authorization']
                                     or '\0' in value['authorization']):
        raise ValueError('Expected an authorization record path')
    checked_name(value['name'])
    rows = value['repositories']
    if not isinstance(rows, dict) or len(rows) > MAX_REPOSITORIES:
        raise ValueError('A Target supports at most 16 named repositories')
    for name, row in rows.items():
        checked_name(name)
        if not isinstance(row, dict) or not {'path', 'configuration'} <= set(row) <= {'path', 'configuration', 'dependency'}:
            raise ValueError(f'Invalid repository entry: {name}')
        if any(not isinstance(v, str) or not v for v in row.values()):
            raise ValueError(f'Invalid repository paths: {name}')
    return value


def load(target):
    path = path_at(str(target), Path.cwd())
    value = validate_manifest(read_json(path))
    roots = {name: path_at(row['path'], path.parent, directory=True) for name, row in value['repositories'].items()}
    for name, root in roots.items():
        if any(root.is_relative_to(other) or other.is_relative_to(root) for key, other in roots.items() if key != name):
            raise ValueError('Repository roots must be distinct and must not overlap')
    return path, value, roots


def init(target, name):
    path = path_at(str(target), Path.cwd(), new=True)
    value = validate_manifest(dict(schema=SCHEMA, name=checked_name(name), repositories={}))
    with path.open('x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(value, indent=2) + '\n')
    return dict(status='TARGET_CREATED', target=str(path), name=name, provider_calls=0, native_attempts=0)


def add(target, name, root, configuration, dependency=None):
    path, value, roots = load(target)
    if 'snapshot_receipt' in value:
        raise ValueError('Copied Target membership is frozen; register a new original manifest')
    original = path.read_bytes()
    name = checked_name(name)
    if name in roots or len(roots) >= MAX_REPOSITORIES:
        raise ValueError('Repository name already exists or Target capacity was reached')
    root = path_at(str(root), Path.cwd(), directory=True)
    if any(root.is_relative_to(other) or other.is_relative_to(root) for other in roots.values()):
        raise ValueError('Repository roots must be distinct and must not overlap')
    configuration = path_at(str(configuration), Path.cwd())
    validate_configuration(read_json(configuration))
    row = dict(path=os.path.relpath(root, path.parent), configuration=os.path.relpath(configuration, path.parent))
    if dependency is not None:
        row['dependency'] = os.path.relpath(path_at(str(dependency), Path.cwd()), path.parent)
    value['repositories'][name] = row
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.reqlox-target-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.write('\n')
    try:
        if path.read_bytes() != original:
            raise ValueError('Target manifest changed during registration')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(status='REPOSITORY_REGISTERED', target=str(path), repository=name, provider_calls=0, native_attempts=0)


def listing(target):
    path, value, roots = load(target)
    return dict(status='TARGET_LISTED', name=value['name'], target=str(path),
                repositories=[dict(name=name, path=str(root), configuration=value['repositories'][name]['configuration'])
                              for name, root in roots.items()], provider_calls=0, native_attempts=0)


def validate_configuration(config):
    import reliability_reuse as reuse
    allowed = {'contracts', 'source_texts', 'hypotheses', 'maximum_probes', 'specification_texts', 'path_context'}
    if not isinstance(config, dict) or 'contracts' not in config or set(config) - allowed:
        raise ValueError('Configuration requires contracts; unknown fields are rejected')
    if not isinstance(config['contracts'], dict) or set(config['contracts']) - set(reuse.FAMILIES):
        raise ValueError('Unknown contract family')
    for family, row in config['contracts'].items():
        if (not isinstance(row, dict) or set(row) != {'id', 'basis', 'scope'} or row['id'] != reuse.CONTRACTS[family]
                or any(not isinstance(v, str) or not v.strip() for v in row.values())):
            raise ValueError(f'Invalid owned contract: {family}')
    probes = config.get('maximum_probes', 3)
    if type(probes) is not int or not 1 <= probes <= reuse.LIMITS['probes']:
        raise ValueError('Invalid maximum_probes')
    for key in ('source_texts', 'specification_texts'):
        if not isinstance(config.get(key, {}), dict) or any(not isinstance(v, str) for v in config.get(key, {}).values()):
            raise ValueError(f'{key} must map identifiers to supplied text')
    if not isinstance(config.get('hypotheses', []), list):
        raise ValueError('hypotheses must be a list')
    if 'path_context' in config:
        from .target_context import validate
        validate(config['path_context'])
        if config['contracts'] or config.get('hypotheses') or config.get('source_texts') or config.get('specification_texts'):
            raise ValueError('TARGET_CONTEXT_MIXED_REQUIREMENTS')
    return config


def prepare(target, repositories, all_repositories=False, *, paired=False, seconds=120, campaigns=12, rounds=3,
            authorization=None):
    import reliability_reuse as reuse
    import run_reliability_reuse as runner
    import run_reliability_improvement_loop as loop
    from .target_snapshot import verify_target
    verify_target(target)
    if type(seconds) is not int or not 1 <= seconds <= 7200 or type(campaigns) is not int or not 0 <= campaigns <= 64:
        raise ValueError('seconds must be 1..7200 and campaign limit must be 0..64')
    if type(rounds) is not int or not 2 <= rounds <= 4:
        raise ValueError('maximum-rounds must be 2..4')
    path, manifest, roots = load(target)
    if 'authorization' in manifest:
        registered_authorization = path_at(manifest['authorization'], path.parent)
        if authorization is not None and path_at(str(authorization), Path.cwd()) != registered_authorization:
            raise ValueError('TARGET_AUTHORIZATION_MANIFEST_OVERRIDE')
        authorization = registered_authorization
    selected = list(roots) if all_repositories else list(repositories)
    if (all_repositories and repositories) or not selected or len(set(selected)) != len(selected) or set(selected) - set(roots):
        raise ValueError('Select registered repositories with repeated --repo, or explicitly use --all')
    prepared, summaries = [], []
    for name in selected:
        row = manifest['repositories'][name]
        configuration = path_at(row['configuration'], path.parent)
        config = validate_configuration(read_json(configuration))
        dependency = path_at(row['dependency'], path.parent) if 'dependency' in row else None
        if dependency is not None and (dependency.suffix != '.whl' or dependency.stat().st_size > 16777216):
            raise ValueError('Dependency must be a local wheel of at most 16 MiB')
        if paired and (dependency is not None or config.get('hypotheses')):
            raise ValueError('Paired mode prepares source_texts and does not support dependency wheels or explicit hypotheses')
        if not paired and config.get('specification_texts'):
            raise ValueError('specification_texts require paired mode')
        sources = runner.load_snapshot(roots[name])
        inventory = runner.inventory_for(sources)
        hypotheses = [reuse.hypothesis(h, config.get('source_texts', {})) for h in config.get('hypotheses', [])]
        experiment = None; context_plan = None
        if 'path_context' in config:
            from . import target_context
            if paired or dependency is not None:
                raise ValueError('TARGET_CONTEXT_PAIRED_OR_DEPENDENCY_UNSUPPORTED')
            context_plan = target_context.prepare(sources, config)
        if paired:
            import reliability_requirement_experiment as requirements
            import run_reliability_paired as pair
            policies = {family: {key: record[key] for key in ('basis', 'scope')} for family, record in config['contracts'].items()}
            experiment = requirements.prepare(sources, config.get('specification_texts', {}), policies)
            pair.hypotheses_for(sources, experiment['contracts'], config.get('source_texts', {}))
        eligible, held = runner.eligible_sites(inventory, sources, config['contracts'], {}, dependency is not None)
        atomic_held = held
        if context_plan is not None:
            eligible, held = [context_plan], []
        summary = dict(name=name, path=str(roots[name]), configuration=str(configuration), sources_sha256=digest(sources),
                       configuration_sha256=digest(config), inventory_sha256=digest(inventory),
                       dependency_sha256=None if dependency is None else hashlib.sha256(dependency.read_bytes()).hexdigest(),
                       accepted_sites=len(inventory['accepted']), executable_sites=len(eligible), held_sites=len(held), held_bindings=held)
        if context_plan is not None:
            summary.update(execution_method=target_context.PROFILE, accepted_sites=1,
                context_plan_sha256=digest(context_plan),
                context_contract_sha256=digest(config['path_context']['contract']),
                atomic_held_bindings=atomic_held, binding_scope='DOCUMENTED_CONTEXT_INVOCATIONS')
        prepared.append(dict(summary=summary, root=roots[name], configuration=configuration, config=config,
                             sources=sources, hypotheses=hypotheses, experiment=experiment, dependency=dependency,
                             context_plan=context_plan))
        summaries.append(summary)
    method = dict(target_workspace=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  core=loop.method_identity(Path(runner.__file__).parent))
    if paired:
        method['core'] = pair.method_identity(Path(runner.__file__).parent)
    if any(entry['context_plan'] is not None for entry in prepared):
        method['path_context'] = target_context.method_identity()
    authorization_view = None
    if authorization is not None:
        from . import target_authorization
        authorization_value, authorization_view = target_authorization.inspect(authorization)
        method['authorization'] = hashlib.sha256(Path(target_authorization.__file__).read_bytes()).hexdigest()
    plan = dict(schema='reqlox.target-plan.v1', target=manifest['name'], manifest_sha256=digest(manifest),
                repositories=summaries, selected_repositories=selected, paired=paired, seconds=seconds,
                maximum_native_campaigns=campaigns, maximum_rounds=rounds, method=method,
                checkout_write_authority=False, provider_calls=0, statistical_independence_certified=False)
    if authorization_view is not None:
        target_authorization.check_plan(authorization_value, plan)
        plan['authorization'] = {k: authorization_view[k] for k in ('reviewed_binding_sha256', 'prior_native_attempts',
            'prior_charged_seconds', 'remaining_native_campaigns', 'remaining_seconds',
            'maximum_new_native_campaigns', 'maximum_window_seconds')}
    planned = dict(status='PLANNED', plan=plan, plan_sha256=digest(plan), native_attempts=0, provider_calls=0)
    if authorization_view is not None:
        planned['authorization'] = authorization_view
    return planned, prepared, roots


class Budget:
    def __init__(self, maximum, deadline, output=None, plan_sha256=None):
        self.maximum, self.deadline, self.attempts = maximum, deadline, 0
        self.output = output
        self.plan_sha256 = plan_sha256
        self.repository = None

    def reserve(self):
        import reliability_reuse as reuse
        if (self.deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() < reuse.LIMITS['wall_seconds']:
            raise ValueError('TARGET_DEADLINE')
        if self.attempts >= self.maximum:
            raise ValueError('TARGET_NATIVE_CAMPAIGN_LIMIT')
        self.attempts += 1  # Failed or unknown launches retain their reservation.
        if self.output is not None:
            import run_reliability_reuse as runner
            runner.save(self.output / f'native-reservation-{self.attempts:03d}.json',
                        dict(attempt=self.attempts, maximum=self.maximum, deadline=self.deadline.isoformat(),
                             repository=self.repository, plan_sha256=self.plan_sha256,
                             status='RESERVED_BEFORE_DISPATCH', outcome='UNKNOWN_UNTIL_CHILD_RECEIPT'))


def execute(planned, prepared, roots, state, *, name=None, expected=None):
    import run_reliability_reuse as runner
    import run_reliability_improvement_loop as loop
    plan = planned['plan']
    if expected is not None and expected != planned['plan_sha256']:
        raise ValueError('Target plan changed since the reviewed dry run')
    authorization_value = None
    started = datetime.datetime.now(datetime.timezone.utc)
    deadline = started + datetime.timedelta(seconds=plan['seconds'])
    if 'authorization' in planned:
        from . import target_authorization
        authorization_value, current = target_authorization.inspect(planned['authorization']['path'], for_execution=True)
        if current != planned['authorization']:
            raise ValueError('TARGET_AUTHORIZATION_RECORD_DRIFT')
        target_authorization.check_plan(authorization_value, plan)
        if deadline > datetime.datetime.fromisoformat(authorization_value['deadline']):
            raise ValueError('TARGET_AUTHORIZATION_WINDOW_UNAVAILABLE')
    state = Path(os.path.abspath(state))
    execution_root = state / 'target-runs'
    if authorization_value is not None:
        reservations = Path(authorization_value['reservation_directory'])
        if any(reservations.is_relative_to(root) or root.is_relative_to(reservations) for root in roots.values()):
            raise ValueError('TARGET_AUTHORIZATION_RESERVATION_OVERLAP')
    if any(state.is_relative_to(root) or execution_root.is_relative_to(root) or root.is_relative_to(execution_root)
           for root in roots.values()):
        raise ValueError('Run output must be separate from every registered repository')
    state = runner.private(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
        raise ValueError('Runtime state must be owned by this user with mode 0700')
    run_name = checked_name(name or datetime.datetime.now(datetime.timezone.utc).strftime('target-%Y%m%dT%H%M%S%fZ'))
    output = runner.private(state / 'target-runs' / run_name, new=True)
    output.parent.mkdir(mode=0o700, exist_ok=True)
    output.mkdir(mode=0o700)
    import reliability_reuse as reuse
    from .target_audit import files
    if authorization_value is None:
        budget = Budget(plan['maximum_native_campaigns'], deadline, output, planned['plan_sha256'])
    else:
        budget = target_authorization.Budget(authorization_value, deadline, output, planned['plan_sha256'])
    prior_attempts = budget.attempts
    runner.save(output / 'input.json', reuse.c.seal(dict(**planned, started_at=started.isoformat(),
        deadline=deadline.isoformat(), run_name=run_name)))
    (output / 'preparations').mkdir(mode=0o700)
    for entry in prepared:
        runner.save(output / 'preparations' / (entry['summary']['name'] + '.json'), reuse.c.seal(dict(
            name=entry['summary']['name'], sources=entry['sources'], configuration=entry['config'])))
    (output / 'repositories').mkdir(mode=0o700)
    results, stop_reason = [], None
    for entry in prepared:
        row = dict(name=entry['summary']['name'], status='NOT_RUN', native_attempts=0, output=None, evidence_files={})
        if stop_reason:
            row.update(status='NOT_RUN_AFTER_STOP', reason=stop_reason)
            results.append(row)
            continue
        before = budget.attempts
        budget.repository = row['name']
        try:
            if (runner.load_snapshot(entry['root']) != entry['sources'] or read_json(entry['configuration']) != entry['config']
                    or (entry['dependency'] is not None and hashlib.sha256(entry['dependency'].read_bytes()).hexdigest()
                        != entry['summary']['dependency_sha256'])):
                raise ValueError('TARGET_INPUT_CHANGED')
            if datetime.datetime.now(datetime.timezone.utc) >= deadline:
                raise ValueError('TARGET_DEADLINE')
            child = output / 'repositories' / row['name']
            row['output'] = str(child)
            common = dict(deadline=deadline.isoformat(), maximum_rounds=plan['maximum_rounds'],
                          maximum_probes=entry['config'].get('maximum_probes', 3), before_native=budget.reserve)
            remaining = budget.maximum - budget.attempts
            if entry.get('context_plan') is not None:
                from . import target_context
                result = target_context.run(entry['context_plan'], entry['config']['path_context']['contract'], child,
                    deadline=deadline.isoformat(), maximum_native_campaigns=remaining, before_native=budget.reserve)
                qualified = result['status'] == 'NO_COUNTEREXAMPLE'
                if result['status'] == 'STOPPED':
                    raise ValueError(result['reason'])
            elif plan['paired']:
                import run_reliability_paired as pair
                result = pair.run(entry['sources'], entry['experiment'], entry['config'].get('source_texts', {}), child,
                                  maximum_native_campaigns_per_arm=remaining, **common)
                qualified = all(arm['status'] in ('ADOPTED_IN_SNAPSHOT', 'NO_COUNTEREXAMPLE') for arm in result['arms'].values())
            else:
                result = loop.run(entry['sources'], entry['config']['contracts'], entry['hypotheses'], child,
                                  source_texts=entry['config'].get('source_texts', {}), dependency=entry['dependency'],
                                  maximum_native_campaigns=remaining, **common)
                qualified = result['status'] in ('ADOPTED_IN_SNAPSHOT', 'NO_COUNTEREXAMPLE')
            row.update(status=result['status'], finite_contract_completed=qualified and entry['summary']['held_sites'] == 0,
                       result_sha256=digest(result), completed_native_campaigns=result['native_campaigns'])
        except (Exception, KeyboardInterrupt) as exc:
            stop_reason = str(exc)[:300] or type(exc).__name__
            row.update(status='STOPPED', reason=stop_reason, finite_contract_completed=False)
        if row['output'] is not None:
            child = Path(row['output'])
            row['evidence_files'] = files(child)
            if (child / 'result.json').is_file():
                row['result_sha256'] = digest(runner.read(child / 'result.json'))
        row['native_attempts'] = budget.attempts - before
        results.append(row)
    unchanged = True
    for entry in prepared:
        try:
            if runner.load_snapshot(entry['root']) != entry['sources']:
                unchanged = False
        except (ValueError, OSError):
            unchanged = False
    if not unchanged:
        stop_reason = 'TARGET_SOURCE_CHANGED_DURING_RUN'
    status = 'STOPPED' if stop_reason else 'COMPLETE' if all(row.get('finite_contract_completed') for row in results) else 'PARTIAL'
    result = dict(schema='reqlox.target-run.v1', status=status, reason=stop_reason, output=str(output),
                  plan_sha256=planned['plan_sha256'], repositories=results, native_attempts=budget.attempts,
                  maximum_native_campaigns=budget.maximum, deadline=deadline.isoformat(),
                  observed_at_jst=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
                  checkout_unchanged=unchanged, checkout_unchanged_scope="SELECTED_PYTHON_SOURCE_SNAPSHOTS",
                  checkout_write_authority=False, provider_calls=0,
                  automatic_failed_trial_retry=False, independent_generalization_certified=False,
                  natural_source_added_value_certified=False, probability_calibration_certified=False)
    if authorization_value is not None:
        result.update(prior_native_attempts=prior_attempts, new_native_attempts=budget.attempts - prior_attempts,
            prior_charged_seconds=authorization_value['prior_charged_seconds'],
            charged_window_seconds=authorization_value['maximum_window_seconds'],
            authorization_record_sha256=planned['authorization']['record_sha256'])
    result = reuse.c.seal(result)
    runner.save(output / 'result.json', result)
    return result
