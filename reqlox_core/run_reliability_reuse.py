"""Finite reliability controls and verification."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import shutil
from reqlox_paths import state_root
import reliability_reuse as reuse
import reliability_reuse_cache as site_cache_support
ROOT = Path(__file__).resolve().parents[1]
METHODS = ('reqlox_paths.py', 'reliability_reuse.py', 'reliability_reuse_worker.py', 'run_reliability_reuse.py', 'repository_atomic_write.py', 'repository_atomic_worker.py', 'incident_reference.py', 'reliability_reuse_cache.py', 'reliability_context.py', 'reliability_instance.py', 'reliability_conditions.py', 'reliability_delegated_context.py', 'reliability_serialized_flow.py', 'reliability_module_graph.py')
_INVENTORY_MEMO = None
DISCOVERY_POLICIES = ('LEGACY_SHARED_POOL', 'ISOLATED_SOURCE_KNOWLEDGE')
ARMS = ('SOURCE', 'NO_SOURCE')

def checked_arms(arms):
    reuse.c.require(type(arms) in (list, tuple) and 0 < len(arms) <= 2 and (len(set(arms)) == len(arms)) and (set(arms) <= set(ARMS)), 'REUSE_ARM_SELECTION')
    return tuple((arm for arm in ARMS if arm in arms))

def inventory_for(sources):
    """Current finite reliability method; public state remains outside the package."""
    global _INVENTORY_MEMO
    functions = (reuse.inventory, reuse.module_bindings, reuse.imports, reuse.canonical_function, reuse.async_binding, reuse.clock_binding, reuse.context_binding, reuse.atomic.binding, reuse.local_names, reuse.signature, reuse.dotted, reuse.AliasNormalizer, reuse.AliasNormalizer.visit_Name, reuse.ast.parse, reuse.ast.unparse, reuse.ast.walk, reuse.atomic.checked_path, reuse.contexts.bind_generator, reuse.instances.bind, reuse.instances.imported_helper, reuse.instances.arguments, reuse.instances.closed_namespace, reuse.instances.literal, reuse.instances.body, reuse.delegated.looking, reuse.delegated.bind, reuse.delegated.lifecycle, reuse.delegated.creator_binding, reuse.delegated.constructor_binding, reuse.serialized.looking, reuse.serialized.bind, reuse.serialized.bind_backend, reuse.serialized.module_guard, reuse.serialized.expand_creator, reuse.module_graph.build, reuse.module_graph.bind, reuse.module_graph.relative_names, reuse.module_graph.package_exports, reuse.contexts.bind_fd_generator, reuse.contexts.bind, reuse.contexts.fd_module)
    configuration = reuse.c.digest(dict(limits=reuse.LIMITS, atomic_limits=reuse.atomic.LIMITS, families=reuse.FAMILIES, contracts=reuse.CONTRACTS, operations=reuse.OPERATIONS, maximum_modules=reuse.module_graph.MAXIMUM_MODULES, maximum_reexport_edges=reuse.module_graph.MAXIMUM_REEXPORT_EDGES, maximum_public_exports=reuse.module_graph.MAXIMUM_PUBLIC_EXPORTS))
    key = (reuse.c.digest(sources), functions, configuration)
    memo = _INVENTORY_MEMO or []
    for index, (saved_key, raw) in enumerate(memo):
        if saved_key == key:
            memo.append(memo.pop(index))
            return json.loads(raw)
    value = reuse.inventory(sources)
    raw = reuse.c.canonical(value)
    reuse.c.require(reuse.c.digest(sources) == key[0], 'REUSE_INVENTORY_SOURCE_CHANGED')
    if len(raw) <= 8388608:
        memo.append((key, raw))
        while len(memo) > 2 or sum((len(data) for _, data in memo)) > 8388608:
            memo.pop(0)
    _INVENTORY_MEMO = memo
    return value

def save(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), 384)
        stream.write(reuse.c.canonical(value))

def read(path):
    return json.loads(Path(path).read_bytes())

def load_snapshot(root):
    root = Path(root).absolute()
    reuse.c.require(root.is_dir() and (not any((p.is_symlink() for p in (root, *root.parents)))), 'REUSE_REPOSITORY_PATH')
    excluded = {'targets', 'corpus', 'post-mortems', 'vendor', 'third_party', 'node_modules', '.venv', 'venv', '.git', '__pycache__'}
    tracked = None
    if shutil.which('git'):
        identity = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root, capture_output=True, timeout=5)
        if identity.returncode == 0 and Path(identity.stdout.decode().strip()).resolve() == root:
            process = subprocess.run(['git', 'ls-files', '-z', '--', '*.py'], cwd=root, capture_output=True, check=True, timeout=5)
            tracked = [s.decode() for s in process.stdout.split(b'\x00') if s]
    if tracked is None:
        tracked = []
        inspected = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in excluded and (not d.startswith('test'))]
            reuse.c.require(not any(((Path(directory) / d).is_symlink() for d in dirs)), 'REUSE_DIRECTORY_LINK')
            inspected += len(dirs) + len(names)
            reuse.c.require(inspected <= 8192, 'REUSE_DIRECTORY_BOUND')
            tracked.extend((str((Path(directory) / n).relative_to(root)) for n in names if n.endswith('.py')))
            reuse.c.require(len(tracked) <= reuse.LIMITS['files'], 'REUSE_REPO_FILES')
    sources = {}
    for name in sorted(tracked):
        if any((p.startswith('test') or p in excluded for p in Path(name).parts)):
            continue
        reuse.atomic.checked_path(name)
        path = root / name
        reuse.c.require(not any((p.is_symlink() for p in (path, *path.parents))) and path.is_file() and (path.stat().st_size <= reuse.LIMITS['file_bytes']), 'REUSE_SOURCE_PATH')
        sources[name] = path.read_text()
    reuse.validate_sources(sources)
    return sources

def private(path, *, new=False):
    path = Path(path).absolute()
    c = reuse.c
    c.require(path.is_relative_to(state_root()) and (not any((p.is_symlink() for p in (path, *path.parents)))), 'REUSE_PRIVATE_PATH')
    c.require(not new or not path.exists(), 'REUSE_IMMUTABLE_OUTPUT')
    return path

def method_identity(path):
    return {name: reuse.sha((Path(path) / name).read_bytes()) for name in METHODS}

def runtime_identity():
    import asyncio, contextlib, io, tempfile, unittest.mock, _asyncio, select
    fixed = [asyncio, contextlib, io, tempfile, unittest.mock, _asyncio, select, os, json]
    modules = {m.__name__: m for m in fixed}
    modules.update({name: m for name, m in sys.modules.copy().items() if name.startswith(('asyncio.', 'unittest.', 'json.')) and getattr(m, '__file__', None)})
    return dict(executable_sha256=reuse.sha(Path(sys.executable).resolve().read_bytes()), python=sys.version, kernel=platform.release(), boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(), machine_id_sha256=reuse.sha(Path('/etc/machine-id').read_bytes()), stdlib={name: reuse.sha(Path(m.__file__).read_bytes()) for name, m in sorted(modules.items()) if getattr(m, '__file__', None)})

def study_identity(value):
    inputs = {k: value[k] for k in ('sources', 'contracts', 'hypotheses', 'source_texts', 'incident_sets', 'method', 'runtime', 'dependency_sha256', 'maximum_probes', 'supplied_candidates', 'evaluation_kind')}
    if 'discovery_policy' in value:
        inputs['discovery_policy'] = value['discovery_policy']
    if 'enabled_arms' in value:
        inputs['enabled_arms'] = value['enabled_arms']
    return reuse.c.digest(inputs)

def check_observation(obs, plan, parent):
    c = reuse.c
    c.require(obs['plan_sha256'] == c.digest(plan) and obs['family'] == plan['site']['family'], 'REUSE_OBSERVATION_BINDING')
    c.require(set(obs['namespaces']) == set(parent) and all(obs['namespaces'][k] != v for k, v in parent.items()), 'REUSE_NAMESPACE')
    c.require(obs['external_action_attempts'] == 0 and type(obs['maximum_rss_kib']) is int
              and 0 < obs['maximum_rss_kib'] <= 131072, 'REUSE_NATIVE_RESOURCES')
    if 'execution_boundary' in obs:
        boundary = obs['execution_boundary']
        c.require(boundary['uid'] != 0 and boundary['effective_capabilities'] == 0
                  and boundary['home_visible'] is False
                  and boundary['cpu_seconds'] == [2, 2]
                  and boundary['memory_bytes'] == [134217728, 134217728]
                  and boundary['file_bytes'] == [131072, 131072]
                  and boundary['core_bytes'] == [0, 0], 'REUSE_EXECUTION_BOUNDARY')
    c.require(obs['model_calls'] == 0 and obs['forecasts'] is None and type(obs['healthy']['contract_pass']) is bool, 'REUSE_NATIVE_SCOPE')
    c.require([r['fault'] for r in obs['probes']] == plan['proposal']['faults'], 'REUSE_PROBE_DENOMINATOR')
    family = plan['site']['family']
    for row in [obs['healthy'], *obs['probes'], *obs['reinjection'], *obs['regression']]:
        passed = None
        if family == 'atomic_file':
            if plan['site']['binding'].get('instance'):
                c.require(row.get('actual_instance_invocation') is True, 'REUSE_INSTANCE_INVOCATION')
            passed = (row['error_class'] == row['expected_error_class'] and row['destination_preserved']
                      and row['residual_temporary_files'] == 0 and row['preexisting_file_preserved']
                      and row['unrelated_file_preserved'] and row['retry_pass'] is not False)
        elif family == 'async_resource':
            passed = (row['work_held_resource'] and row['resource_released'] and row['different_task_reacquired']
                      and row['error_class'] == row['expected_error_class'] and row['prior_owner_lock_preserved']
                      and row['work_result_preserved'] and row['returns_work_result']==plan['site']['binding']['returns_result']
                      and (row['fault']!='ACQUIRE_CANCEL' or row['acquisition_wait_observed']))
        elif family == 'elapsed_ttl': passed = row['observed'] == row['expected']
        else:
            c.require(row['expected_error_class'] == (None if row['fault'] == 'NORMAL' else 'OSError'),
                      'REUSE_EXPECTED_EXCEPTION_DRIFT')
            passed = (row['error_class'] == row['expected_error_class'] and row['destination_preserved']
                      and row['unrelated_file_preserved'] and row['residual_temporary_files'] == 0)
            c.require(type(row['fault_injected']) is bool and type(row['fault_injection_count']) is int
                      and row['fault_injection_count'] >= 0
                      and row['fault_injected'] == (row['fault_injection_count'] > 0)
                      and (row['fault'] != 'NORMAL' or not row['fault_injected']), 'REUSE_FAULT_INJECTION_DRIFT')
            reached = row['fault'] == 'NORMAL' or row['fault_injected']
            c.require(row['applicability'] == ('OBSERVED' if reached else 'FAULT_NOT_REACHED'), 'REUSE_FAULT_APPLICABILITY')
            if not reached: passed = None
            c.require(type(row['default_mode_used']) is bool,'REUSE_CONTEXT_INVOCATION')
            binding = plan['site']['binding']; generator = binding.get('kind') in reuse.contexts.GENERATOR_KINDS
            options = ({binding['mode_parameter']:'wb'} if generator and binding['mode_parameter'] and not row['default_mode_used'] else {})
            if not generator: options = dict(overwrite=True,mode='wb')
            text_mode = generator and binding['default_mode']=='w' and (row['default_mode_used'] or not binding['mode_parameter'])
            if binding.get('kind')==reuse.delegated.KIND:
                options=dict(overwrite=True) if row['default_mode_used'] else dict(overwrite=True,mode='wb')
                text_mode=row['default_mode_used'] and binding['default_mode']=='w'
                c.require(row.get('public_entry_symbol')==binding['entry_symbol']
                          and row.get('repair_symbol')==binding['repair_symbol'],'REUSE_DELEGATED_INVOCATION')
            if binding.get('kind')==reuse.serialized.KIND:
                options={};text_mode=True
                payload, content=reuse.serialized.sample(binding['caller_profile'],row['input_case'])
                expected_content=content if row['fault']=='NORMAL' else b'prior'
                c.require(row['input_profile']==binding['caller_profile'] and row['input_payload_sha256']==c.digest(payload)
                          and row['expected_content_sha256']==reuse.sha(expected_content)
                          and row['destination_preserved']==(row['destination_sha256']==reuse.sha(expected_content))
                          and type(row['returned_none']) is bool and row['input_domain_qualified'] is False
                          and row['public_entry_symbol']==binding['entry_symbol']
                          and row['repair_symbol']==binding['repair_symbol'], 'REUSE_SERIALIZED_INVOCATION')
                passed = passed and row['returned_none'] if reached else None
            c.require(row['invocation_kwargs']==options and row['write_input_kind']==('TEXT' if text_mode else 'BYTES'),
                      'REUSE_CONTEXT_INVOCATION')
            if reuse.conditions.is_condition(row['fault']):
                program = plan['proposal']['condition_programs'][row['fault']]
                expected_hits = [dict(operation=program['operation'],phase=program['phase'],occurrence=program['occurrence'])] if row['fault_injected'] else []
                c.require(row['condition_id'] == row['fault'] and row['condition_hits'] == expected_hits
                          and type(row['condition_seen']) is int and 0 <= row['condition_seen'] <= 20,
                          'REUSE_CONDITION_TRACE_DRIFT')
                c.require(not row['fault_injected'] or (row['fault_injection_count'] == 1
                          and row['condition_seen'] >= program['occurrence']), 'REUSE_CONDITION_TRACE_DRIFT')
        if family=='atomic_context' and row['applicability']=='FAULT_NOT_REACHED':
            c.require(row['contract_pass'] is None,'REUSE_ORACLE_DRIFT')
        else:
            c.require(type(row['contract_pass']) is bool and row['contract_pass']==passed,'REUSE_ORACLE_DRIFT')
    found = obs['healthy']['contract_pass'] and any(r['contract_pass'] is False for r in obs['probes'])
    executable_candidate = plan['candidate_code'] if plan['candidate_code'] is not None else reuse.candidate(plan['site'])
    executed = found and executable_candidate is not None
    c.require(obs['fault_discovered'] == found and obs['actual_candidate_code_executed'] is executed, 'REUSE_DISCOVERY_DRIFT')
    c.require([r['fault'] for r in obs['reinjection']] == (reuse.qualification_faults(plan['site'],plan['proposal']) if executed else []), 'REUSE_REINJECTION_DENOMINATOR')
    expected_regression = {'atomic_file': 5, 'async_resource': 1, 'elapsed_ttl': 3, 'atomic_context': 2}[family] if executed else 0
    serialized=family=='atomic_context' and plan['site']['binding'].get('kind')==reuse.serialized.KIND
    if serialized and executed:expected_regression=3
    c.require(len(obs['regression']) == expected_regression, 'REUSE_REGRESSION_DENOMINATOR')
    if serialized:
        c.require(all(r['default_mode_used'] is False and r['input_case']=='BASE' for r in [obs['healthy'],*obs['probes'],*obs['reinjection']])
                  and [r['input_case'] for r in obs['regression']]==(['BASE','EMPTY','UNICODE'] if executed else [])
                  and all(r['default_mode_used'] is False for r in obs['regression']), 'REUSE_SERIALIZED_INVOCATION_DENOMINATOR')
    elif family=='atomic_context':
        c.require(all(r['default_mode_used'] is False for r in [obs['healthy'],*obs['probes'],*obs['reinjection']])
                  and [r['default_mode_used'] for r in obs['regression']] == ([False,True] if executed else []),
                  'REUSE_CONTEXT_INVOCATION_DENOMINATOR')
    expected = None if not executed else all(r['contract_pass'] is True for r in obs['reinjection']+obs['regression'])
    c.require(obs['candidate_code'] == (executable_candidate if executed else None)
              and obs['repair_pass'] == expected and obs['candidate_sha256'] == (reuse.sha(executable_candidate) if executed else None), 'REUSE_REPAIR_DRIFT')
    if 'module_graph' in plan['site']['binding']:
        graph = plan['site']['binding']['module_graph']
        groups = [([obs['healthy'],*obs['probes']],plan['sources'])]
        if executed:
            groups.append(([*obs['reinjection'],*obs['regression']],
                           reuse.apply_candidate(plan['sources'],plan['site'],executable_candidate)))
        for rows,sources in groups:
            c.require(all(row['public_entry_member']==graph['entry_member']
                          and row['repair_member']==graph['repair_member']
                          and row['executed_module_members']==sorted(sources)
                          and row['executed_source_sha256']==c.digest(sources) for row in rows),
                      'REUSE_MODULE_GRAPH_INVOCATION')
            if 'public_entry_resolution' in graph:
                resolution = graph['public_entry_resolution']
                c.require(all(row.get('public_function_module')==graph['modules'][resolution['function_member']]
                              and row.get('public_function_symbol')==resolution['function_symbol'] for row in rows),
                          'REUSE_PACKAGE_PUBLIC_FUNCTION_INVOCATION')
    status = ('BASELINE_INVALID' if not obs['healthy']['contract_pass'] else
              'FAULT_NOT_REACHED' if any(r['contract_pass'] is None for r in obs['probes']) else 'REPAIRED' if expected is True else
              'REPAIR_FAILED' if executed else 'REPAIR_UNSUPPORTED' if found else 'NO_COUNTEREXAMPLE')
    c.require(obs['status'] == status, 'REUSE_STATUS_DRIFT')

def execute(directory, plan, archive, dependency=None):
    directory.mkdir(mode=0o700)
    save(directory/'plan.json', plan)
    parent = {k: os.readlink('/proc/self/ns/'+k) for k in ('user', 'mnt', 'pid', 'net')}
    launch = reuse.c.seal(dict(plan_sha256=reuse.c.digest(plan), method=method_identity(archive),
        runtime=runtime_identity(), limits=reuse.LIMITS, parent_namespaces=parent,
        launcher_limits='PRLIMIT_BEFORE_BWRAP',
        prlimit_sha256=reuse.sha(Path('/usr/bin/prlimit').read_bytes()),
        credential_or_home_mounted=False, automatic_retry=False))
    save(directory/'launch.json', launch)
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv', '--cap-drop', 'ALL',
        '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib']
    if Path('/lib64').exists(): command.extend(['--ro-bind', '/lib64', '/lib64'])
    command.extend(['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/run',
        '--ro-bind', str(directory/'plan.json'), '/run/plan.json', '--ro-bind', str(archive), '/run/modules'])
    if dependency is not None:
        reuse.c.require(reuse.sha(Path(dependency).read_bytes()) == plan['dependency_sha256'], 'REUSE_DEPENDENCY_DRIFT')
        command.extend(['--ro-bind', str(Path(dependency).absolute()), '/run/dependency.whl'])
    command.extend(['--chdir', '/run/modules', str(Path(sys.executable).resolve()), '-S', '-B',
                    '/run/modules/reliability_reuse_worker.py', reuse.c.digest(plan)])
    command = ['/usr/bin/prlimit', '--cpu=2:2', '--as=134217728:134217728',
               '--fsize=131072:131072', '--core=0:0', '--', *command]
    process = None; value = None; error = None; code = None
    with (directory/'observed.json').open('xb') as out, (directory/'stderr.log').open('xb') as err:
        os.fchmod(out.fileno(), 0o600); os.fchmod(err.fileno(), 0o600)
        try:
            process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
            try: code = process.wait(timeout=reuse.LIMITS['wall_seconds'])
            except subprocess.TimeoutExpired:
                raise ValueError('REUSE_WALL_LIMIT')
            reuse.c.require(code == 0 and (directory/'observed.json').stat().st_size <= reuse.LIMITS['output_bytes'], 'REUSE_CHILD_FAILED')
            value = read(directory/'observed.json')
            reuse.c.require('execution_boundary' in value, 'REUSE_EXECUTION_BOUNDARY_MISSING')
            check_observation(value, plan, parent)
        except BaseException as exc:
            error = type(exc).__name__; raise
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
            save(directory/'receipt.json', reuse.c.seal(dict(status='COMPLETE' if value is not None and error is None else 'STOPPED',
                returncode=code, error=error, plan_sha256=reuse.c.digest(plan), launch_sha256=reuse.c.digest(launch),
                observed_sha256=reuse.sha((directory/'observed.json').read_bytes()), automatic_retry=False)))
    return value

def eligible_sites(inventory, sources, contracts, candidates, dependency_available):
    eligible = []
    held = list(inventory['held'])
    for site in inventory['accepted']:
        try:
            contract = reuse.bind_contract(site, contracts)
            code = candidates.get(site['id'])
            if code is not None:
                reuse.apply_candidate(sources, site, code)
            reuse.c.require(site['family'] != 'elapsed_ttl' or dependency_available, 'REUSE_TTL_DEPENDENCY_REQUIRED')
            eligible.append((site, contract, code))
        except ValueError as exc:
            held.append(dict(member=site['member'], symbol=site['symbol'], reason=str(exc)))
    return (eligible, held)

def entries_for(eligible, enabled_arms=ARMS):
    enabled_arms = checked_arms(enabled_arms)
    return [dict(site_id=site['id'], arm=arm, directory=site['id'] + '-' + arm.lower()) for i, (site, _, _) in enumerate(eligible) for arm in (('SOURCE', 'NO_SOURCE') if i % 2 == 0 else ('NO_SOURCE', 'SOURCE')) if arm in enabled_arms]

def build_plan(site, contract, code, sources, hypotheses, arm, maximum_probes, dependency_sha256, discovery_policy='ISOLATED_SOURCE_KNOWLEDGE'):
    reuse.c.require(discovery_policy in DISCOVERY_POLICIES and arm in ('SOURCE', 'NO_SOURCE'), 'REUSE_DISCOVERY_POLICY')
    visible = hypotheses if arm == 'SOURCE' else []
    envelope = visible if discovery_policy == 'ISOLATED_SOURCE_KNOWLEDGE' else hypotheses
    members = site['binding'].get('module_graph', {}).get('modules', {site['member']: None})
    return dict(site=site, sources={n: sources[n] for n in members}, contract=contract, proposal=reuse.propose(site, visible, maximum_probes, qualification_hypotheses=envelope, include_owned_grid=discovery_policy == 'ISOLATED_SOURCE_KNOWLEDGE'), candidate_code=code, dependency_sha256=dependency_sha256 if site['family'] == 'elapsed_ttl' else None)

def verify(output, *, _context=None):
    output = private(output)
    context = _context if _context is not None else dict(active=set(), done={}, visits=0)
    if output in context['done']:
        return context['done'][output]
    reuse.c.require(output not in context['active'], 'REUSE_REFERENCE_CYCLE')
    reuse.c.require(len(context['active']) < site_cache_support.MAXIMUM_REFERENCE_DEPTH and context['visits'] < site_cache_support.MAXIMUM_REFERENCE_DIRECTORIES, 'REUSE_REFERENCE_LIMIT')
    context['active'].add(output)
    context['visits'] += 1
    study = read(output / 'study.json')
    reuse.c.check_seal(study)
    discovery_policy = study.get('discovery_policy', 'LEGACY_SHARED_POOL')
    reuse.c.require(discovery_policy in DISCOVERY_POLICIES, 'REUSE_DISCOVERY_POLICY')
    reuse.c.require(all((study[k] is False for k in ('source_semantic_support_certified', 'source_selection_automatic', 'human_time_measured', 'automatic_terminal_retry'))) and type(study['provider_calls']) is int and (study['provider_calls'] == 0), 'REUSE_STUDY_CLAIM_DRIFT')
    reuse.c.require(study_identity(study) == study['identity'], 'REUSE_STUDY_IDENTITY_DRIFT')
    reuse.c.require(method_identity(output / 'method') == study['method'], 'REUSE_ARCHIVED_METHOD_DRIFT')
    inventory = inventory_for(study['sources'])
    reuse.c.require(inventory == study['inventory'], 'REUSE_INVENTORY_DRIFT')
    for h in study['hypotheses']:
        original = reuse.hypothesis_input(h)
        reuse.c.require(reuse.hypothesis(original, study['source_texts']) == h, 'REUSE_HYPOTHESIS_DRIFT')
    projections = [reuse.project_incident_set(ir, study['source_texts'][ir['source']['source_record_id']]) for ir in study['incident_sets']]
    reuse.c.require(projections == study['source_projections'], 'REUSE_INCIDENT_PROJECTION_DRIFT')
    eligible, held = eligible_sites(inventory, study['sources'], study['contracts'], study['supplied_candidates'], study['dependency_sha256'] is not None)
    basics = entries_for(eligible, study.get('enabled_arms', ARMS))
    reuse.c.require(len(study['entries']) == len(basics) and study['held'] == held, 'REUSE_ENTRY_DENOMINATOR')
    for entry, basic in zip(study['entries'], basics):
        reuse.c.require({k: entry[k] for k in basic} == basic and set(entry) <= set(basic) | {'reference'}, 'REUSE_ENTRY_BINDING')
    rows = []
    for entry in study['entries']:
        p = read(output / entry['directory'] / 'plan.json')
        site, contract, candidate = next((r for r in eligible if r[0]['id'] == entry['site_id']))
        expected = build_plan(site, contract, candidate, study['sources'], study['hypotheses'], entry['arm'], study['maximum_probes'], study['dependency_sha256'], discovery_policy)
        reuse.c.require(p == expected, 'REUSE_PLAN_INPUT_DRIFT')
        if 'reference' in entry:
            ref = entry['reference']
            reuse.c.check_seal(ref)
            old_directory = private(ref['directory'])
            old_study, old_result = verify(old_directory, _context=context)
            old_entry = next((e for e in old_study['entries'] if e['directory'] == ref['entry_directory']), None)
            reuse.c.require(old_entry is not None, 'REUSE_REFERENCE_ENTRY_MISSING')
            old_plan = read(old_directory / old_entry['directory'] / 'plan.json')
            value = next((r['observed'] for r in old_result['rows'] if r['site_id'] == old_entry['site_id'] and r['arm'] == old_entry['arm']))
            reuse.c.require(site_cache_support.reference(old_directory, old_study, old_result, old_entry, old_plan, value) == ref, 'REUSE_REFERENCE_DRIFT')
            current_key = site_cache_support.key(p, entry['arm'], study['method'], study['runtime'], study['evaluation_kind'], reuse.c.digest(study['sources']))
            reuse.c.require(current_key == ref['key'], 'REUSE_REFERENCE_DEPENDENCY_DRIFT')
            reuse.c.require(read(output / entry['directory'] / 'reuse.json') == ref, 'REUSE_REFERENCE_RECEIPT_DRIFT')
            rows.append(dict(site_id=site['id'], arm=entry['arm'], observed=value))
            continue
        launch = read(output / entry['directory'] / 'launch.json')
        reuse.c.check_seal(launch)
        receipt = read(output / entry['directory'] / 'receipt.json')
        reuse.c.check_seal(receipt)
        reuse.c.require(receipt['status'] == 'COMPLETE' and receipt['returncode'] == 0 and (receipt['error'] is None) and (receipt['launch_sha256'] == reuse.c.digest(launch)) and (launch['method'] == study['method']) and (launch['runtime'] == study['runtime']) and (launch['limits'] == reuse.LIMITS) and (launch['plan_sha256'] == receipt['plan_sha256'] == reuse.c.digest(p)), 'REUSE_RECEIPT_DRIFT')
        raw = (output / entry['directory'] / 'observed.json').read_bytes()
        reuse.c.require(reuse.sha(raw) == receipt['observed_sha256'], 'REUSE_OBSERVATION_DRIFT')
        value = json.loads(raw)
        check_observation(value, p, launch['parent_namespaces'])
        rows.append(dict(site_id=site['id'], arm=entry['arm'], observed=value))
    result = read(output / 'result.json')
    reuse.c.check_seal(result)
    reuse.c.require(all((result[k] is False for k in ('natural_source_added_value_certified', 'population_generalization_certified', 'human_time_measured'))) and result['reused_results_are_historical'] is True and (type(result['provider_calls']) is int) and (result['provider_calls'] == 0) and (type(result['target_specific_adapter_count']) is int) and (result['target_specific_adapter_count'] == 0), 'REUSE_RESULT_CLAIM_DRIFT')
    reuse.c.require(type(result['evaluated_arms']) is int and result['evaluated_arms'] == len(study['entries']) and (type(result['unsupported_source_conditions']) is int) and (result['unsupported_source_conditions'] == sum((len(p['held']) for p in projections))), 'REUSE_RESULT_DENOMINATOR_DRIFT')
    native = sum(('reference' not in e for e in study['entries']))
    reuse.c.require(result['status'] == 'COMPLETE' and result['study_sha256'] == reuse.c.digest(study) and (result['rows'] == rows) and (result['native_campaigns'] == native) and (result.get('reused_arms', 0) == len(rows) - native) and (result['accepted_sites'] == len(inventory['accepted'])) and (result['executed_sites'] == len(eligible)) and (result['held_sites'] == len(held)) and (result['source_faults'] == sum((r['observed']['fault_discovered'] for r in rows if r['arm'] == 'SOURCE'))) and (result['no_source_faults'] == sum((r['observed']['fault_discovered'] for r in rows if r['arm'] == 'NO_SOURCE'))) and (result['repaired_arms'] == sum((r['observed']['repair_pass'] is True for r in rows))), 'REUSE_RESULT_DRIFT')
    reuse.c.require(result['composed_candidate_files'] == reuse.compose_patches(study['sources'], rows), 'REUSE_COMPOSED_PATCH_DRIFT')
    reuse.c.require(result['api_exposure_accounting'] == exposure_accounting(inventory, rows), 'REUSE_EXPOSURE_ACCOUNTING_DRIFT')
    patches = {}
    for row in rows:
        if row['observed']['repair_pass'] is True:
            site = next((s for s in inventory['accepted'] if s['id'] == row['site_id']))
            patches[site['id']] = reuse.apply_candidate(study['sources'], site, row['observed']['candidate_code'])[site.get('repair_member', site['member'])]
    reuse.c.require(result['candidate_repository_files'] == patches, 'REUSE_CANDIDATE_PATCH_DRIFT')
    context['active'].remove(output)
    context['done'][output] = (study, result)
    return (study, result)

def run(sources, contracts, hypotheses, output, *, maximum_probes=3, dependency=None, cache=None, site_cache=None, supplied_candidates=None, evaluation_kind='DEVELOPMENT_CONTROL', source_texts=None, incident_sets=None, maximum_native_campaigns=None, deadline=None, discovery_policy='ISOLATED_SOURCE_KNOWLEDGE', enabled_arms=ARMS, before_native=None):
    reuse.validate_sources(sources)
    enabled_arms = checked_arms(enabled_arms)
    arm_fields = {} if enabled_arms == ARMS else dict(enabled_arms=list(enabled_arms))
    reuse.c.require(discovery_policy in DISCOVERY_POLICIES, 'REUSE_DISCOVERY_POLICY')
    reuse.c.require(type(maximum_probes) is int and 1 <= maximum_probes <= reuse.LIMITS['probes'], 'REUSE_PROBE_LIMIT')
    source_texts = source_texts or {}
    incident_sets = incident_sets or []
    projections = [reuse.project_incident_set(ir, source_texts[ir['source']['source_record_id']]) for ir in incident_sets]
    hypotheses = list(hypotheses) + [h for p in projections for h in p['hypotheses']]
    for h in hypotheses:
        original = reuse.hypothesis_input(h)
        reuse.c.require(reuse.hypothesis(original, source_texts) == h, 'REUSE_HYPOTHESIS_DRIFT')
    inventory = inventory_for(sources)
    supplied_candidates = supplied_candidates or {}
    reuse.c.require(type(supplied_candidates) is dict and set(supplied_candidates) <= {s['id'] for s in inventory['accepted']}, 'REUSE_CANDIDATE_IDS')
    eligible, held = eligible_sites(inventory, sources, contracts, supplied_candidates, dependency is not None)
    reuse.c.require(cache is None or site_cache is None, 'REUSE_CACHE_MODE_CONFLICT')
    output = private(output, new=True)
    method = method_identity(ROOT / 'reqlox_core')
    runtime = runtime_identity()
    dep_hash = None if dependency is None else reuse.sha(Path(dependency).read_bytes())
    identity = study_identity(dict(sources=sources, contracts=contracts, hypotheses=hypotheses, source_texts=source_texts, incident_sets=incident_sets, method=method, runtime=runtime, dependency_sha256=dep_hash, maximum_probes=maximum_probes, supplied_candidates=supplied_candidates, evaluation_kind=evaluation_kind, discovery_policy=discovery_policy, **arm_fields))
    if cache is not None:
        old_study, old_result = verify(cache)
        reuse.c.require(old_study['identity'] == identity, 'REUSE_CACHE_INPUT_CHANGED')
        output.mkdir(mode=448)
        receipt = reuse.c.seal(dict(status='VERIFIED_REUSE', source_run=str(private(cache)), identity=identity, source_result_sha256=reuse.c.digest(old_result), new_native_campaigns=0, new_provider_calls=0, historical_result_not_new_success=True, human_time_measured=False))
        save(output / 'reuse.json', receipt)
        return receipt
    pool = {}
    if site_cache is not None:
        old_directory = private(site_cache)
        old_study, old_result = verify(old_directory)
        for entry in old_study['entries']:
            old_plan = read(old_directory / entry['directory'] / 'plan.json')
            value = next((r['observed'] for r in old_result['rows'] if r['site_id'] == entry['site_id'] and r['arm'] == entry['arm']))
            ref = entry.get('reference') or site_cache_support.reference(old_directory, old_study, old_result, entry, old_plan, value)
            pool[ref['key']] = (ref, value)
    entries = entries_for(eligible, enabled_arms)
    for entry in entries:
        site, contract, code = next((r for r in eligible if r[0]['id'] == entry['site_id']))
        plan = build_plan(site, contract, code, sources, hypotheses, entry['arm'], maximum_probes, dep_hash, discovery_policy)
        key = site_cache_support.key(plan, entry['arm'], method, runtime, evaluation_kind, reuse.c.digest(sources))
        if key in pool:
            entry['reference'] = pool[key][0]
    native_count = sum(('reference' not in e for e in entries))
    reuse.c.require(maximum_native_campaigns is None or (type(maximum_native_campaigns) is int and 0 <= maximum_native_campaigns <= 128 and (native_count <= maximum_native_campaigns)), 'REUSE_NATIVE_CAMPAIGN_LIMIT')
    end = None if deadline is None else datetime.datetime.fromisoformat(deadline)
    reuse.c.require(end is None or end.tzinfo is not None, 'REUSE_DEADLINE_TIMEZONE')
    if end is not None:
        remaining = (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        reuse.c.require(0 < remaining <= 7200 and remaining >= native_count * reuse.LIMITS['wall_seconds'], 'REUSE_DEADLINE')
    output.mkdir(mode=448)
    archive = output / 'method'
    archive.mkdir(mode=448)
    for name in METHODS:
        with (archive / name).open('xb') as stream:
            os.fchmod(stream.fileno(), 384)
            stream.write((ROOT / 'reqlox_core' / name).read_bytes())
    study = reuse.c.seal(dict(schema_version='reqlox.reliability-reuse-study.v2', identity=identity, observed_at_jst=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(), sources=sources, inventory=inventory, contracts=contracts, hypotheses=hypotheses, source_texts=source_texts, incident_sets=incident_sets, source_projections=projections, maximum_probes=maximum_probes, dependency_sha256=dep_hash, method=method, runtime=runtime, discovery_policy=discovery_policy, **arm_fields, supplied_candidates=supplied_candidates, entries=entries, held=held, evaluation_kind=evaluation_kind, source_semantic_support_certified=False, source_selection_automatic=False, human_time_measured=False, provider_calls=0, automatic_terminal_retry=False))
    save(output / 'study.json', study)
    rows = []
    patches = {}
    try:
        for entry in entries:
            site, contract, code = next((r for r in eligible if r[0]['id'] == entry['site_id']))
            plan = build_plan(site, contract, code, sources, hypotheses, entry['arm'], maximum_probes, dep_hash, discovery_policy)
            if 'reference' in entry:
                directory = output / entry['directory']
                directory.mkdir(mode=448)
                save(directory / 'plan.json', plan)
                save(directory / 'reuse.json', entry['reference'])
                value = pool[entry['reference']['key']][1]
            else:
                if end is not None:
                    reuse.c.require((end - datetime.datetime.now(datetime.timezone.utc)).total_seconds() >= reuse.LIMITS['wall_seconds'], 'REUSE_DEADLINE')
                if before_native is not None:
                    before_native()
                value = execute(output / entry['directory'], plan, archive, dependency if site['family'] == 'elapsed_ttl' else None)
            rows.append(dict(site_id=site['id'], arm=entry['arm'], observed=value))
            if value['repair_pass']:
                patches[site['id']] = reuse.apply_candidate(sources, site, value['candidate_code'])[site.get('repair_member', site['member'])]
        reuse.c.require(method_identity(ROOT / 'reqlox_core') == method, 'REUSE_METHOD_CHANGED_DURING_RUN')
    except BaseException as exc:
        save(output / 'result.json', reuse.c.seal(dict(status='STOPPED', error=type(exc).__name__, rows=rows, study_sha256=reuse.c.digest(study), attempted_arms=len(entries), completed_arms=len(rows), automatic_retry=False)))
        raise
    result = reuse.c.seal(dict(status='COMPLETE', study_sha256=reuse.c.digest(study), rows=rows, api_exposure_accounting=exposure_accounting(inventory, rows), candidate_repository_files=patches, composed_candidate_files=reuse.compose_patches(sources, rows), target_specific_adapter_count=0, accepted_sites=len(inventory['accepted']), executed_sites=len(eligible), held_sites=len(held), unsupported_source_conditions=sum((len(p['held']) for p in projections)), native_campaigns=sum(('reference' not in e for e in entries)), reused_arms=sum(('reference' in e for e in entries)), evaluated_arms=len(entries), reused_results_are_historical=True, provider_calls=0, human_time_measured=False, natural_source_added_value_certified=False, population_generalization_certified=False, no_source_faults=sum((r['observed']['fault_discovered'] for r in rows if r['arm'] == 'NO_SOURCE')), source_faults=sum((r['observed']['fault_discovered'] for r in rows if r['arm'] == 'SOURCE')), repaired_arms=sum((r['observed']['repair_pass'] is True for r in rows))))
    save(output / 'result.json', result)
    verify(output)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=('run', 'verify'), required=True)
    parser.add_argument('--root')
    parser.add_argument('--configuration')
    parser.add_argument('--output', required=True)
    parser.add_argument('--cache')
    parser.add_argument('--site-cache')
    parser.add_argument('--dependency')
    parser.add_argument('--maximum-native-campaigns', type=int)
    parser.add_argument('--deadline')
    args = parser.parse_args()

    def interrupted(*_):
        raise KeyboardInterrupt('REUSE_REQUESTED_STOP')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.action == 'verify':
        _, result = verify(args.output)
        print(json.dumps(dict(status='VERIFIED', historical_status=result['status'], new_native_campaigns=0)))
    else:
        config = read(args.configuration)
        sources = load_snapshot(args.root)
        hs = [reuse.hypothesis(r, config.get('source_texts', {})) for r in config.get('hypotheses', [])]
        result = run(sources, config['contracts'], hs, args.output, dependency=args.dependency, cache=args.cache, site_cache=args.site_cache, supplied_candidates=config.get('candidates'), maximum_probes=config.get('maximum_probes', 3), source_texts=config.get('source_texts'), incident_sets=config.get('incident_hypothesis_sets'), maximum_native_campaigns=args.maximum_native_campaigns, deadline=args.deadline, discovery_policy=config.get('discovery_policy', 'ISOLATED_SOURCE_KNOWLEDGE'))
        reuse.c.require(load_snapshot(args.root) == sources, 'REUSE_SOURCE_CHANGED_DURING_RUN')
        print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'candidate_repository_files', 'composed_candidate_files')}, ensure_ascii=False))
if __name__ == '__main__':
    main()

def exposure_accounting(inventory, rows):
    """Current finite reliability method; public state remains outside the package."""
    reuse.c.check_seal(inventory)
    reuse.c.require(all((r['arm'] in ARMS for r in rows)), 'REUSE_EXPOSURE_ACCOUNTING_ARM')
    units = {}
    for site in inventory['accepted']:
        binding = site['binding']
        graph = binding.get('module_graph', {})
        resolution = graph.get('public_entry_resolution', {})
        function_member = resolution.get('function_member', site['member'])
        function_symbol = resolution.get('function_symbol', binding.get('entry_symbol', site['symbol']))
        function_hash = graph.get('source_sha256', {}).get(function_member, site['member_sha256'])
        entry = dict(family=site['family'], member=function_member, symbol=function_symbol, source_sha256=function_hash, input_profile=binding.get('caller_profile'))
        repair = dict(family=site['family'], member=site.get('repair_member', site['member']), symbol=binding.get('repair_symbol', site['symbol']), code_sha256=site['code_sha256'])
        units[site['id']] = dict(entry_function_id=reuse.c.digest(entry), repair_unit_id=reuse.c.digest(repair))
    arms = {}
    for arm in ARMS:
        observed = [r for r in rows if r['arm'] == arm]
        reuse.c.require(len(observed) == len({r['site_id'] for r in observed}) and all((r['site_id'] in units for r in observed)), 'REUSE_EXPOSURE_ACCOUNTING_ROWS')
        grouped = {}
        for row in observed:
            grouped.setdefault(units[row['site_id']]['repair_unit_id'], []).append(row['observed'])
        arms[arm] = dict(api_entries=len(observed), entry_functions=len({units[r['site_id']]['entry_function_id'] for r in observed}), repair_units=len(grouped), faulty_api_entries=sum((r['observed']['fault_discovered'] for r in observed)), faulty_repair_units=sum((any((r['fault_discovered'] for r in group)) for group in grouped.values())), candidate_passed_api_entries=sum((r['observed']['repair_pass'] is True for r in observed)), candidate_passed_repair_units=sum((all((r['repair_pass'] is True for r in group)) for group in grouped.values())))
    return dict(kind='API_EXPOSURE_AND_REPAIR_UNIT_ACCOUNTING_V1', site_units=units, arms=arms, scope='OBSERVED_RUN_CANDIDATE_REINJECTION_ONLY', statistical_independence_certified=False, natural_applicability_denominator_known=False)
