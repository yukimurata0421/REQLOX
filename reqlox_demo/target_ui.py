"""Explicitly registered local Targets reuse the CLI preparation and run path."""
from pathlib import Path
import uuid
import reqlox
reqlox._runtime()
from reqlox import targets, target_prepare, target_audit, target_snapshot
from reqlox_paths import state_root

OPERATIONS = frozenset(('snapshot', 'plan', 'prepare', 'run', 'audit', 'result'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class TargetLab:
    def __init__(self, manifests=(), allow_native=False, integration_runs=()):
        require(len(manifests) <= 16, 'TARGET_UI_MANIFEST_LIMIT')
        require(len(integration_runs) <= 8, 'TARGET_UI_INTEGRATION_LIMIT')
        self.integration_runs = tuple(integration_runs)
        self.public_integration_results = ()
        self.manifests = {}; self.preparations = {}; self.snapshots = {}; self.allow_native = allow_native
        for manifest in manifests:
            path, value, _ = targets.load(manifest)
            require(value['name'] not in self.manifests, 'TARGET_UI_DUPLICATE_TARGET')
            self.manifests[value['name']] = path

    def configuration(self, token):
        from .integration_ui import summarize
        return dict(token=token, targets=list(self.manifests), native_enabled=self.allow_native,
                    saved_runs=self.saved_runs(),
                    integration_results=[summarize(run) for run in self.integration_runs] + list(self.public_integration_results),
                    provider_calls=0, arbitrary_paths_accepted=False)

    def saved_runs(self):
        """Bounded discovery of completed records for startup-registered Targets."""
        if not self.manifests:
            return []
        import run_reliability_reuse as runner
        root = runner.private(state_root() / 'target-runs')
        if not root.is_dir():
            return []
        paths = list(root.iterdir())
        require(len(paths) <= 256, 'TARGET_UI_HISTORY_LIMIT')
        found = []
        for path in sorted(paths, key=lambda p: p.name):
            if path.is_symlink() or not path.is_dir() or not (path / 'input.json').is_file():
                continue
            try:
                targets.checked_name(path.name)
                inputs = target_audit.read(path / 'input.json')
                name = inputs['plan']['target']
                if name in self.manifests:
                    found.append(dict(run_id=path.name, target=name))
            except (ValueError, KeyError, OSError):
                continue
        return found

    def saved_result(self, request):
        """Audit first, then expose counts and identifiers instead of raw artifacts."""
        require(set(request) == {'run_id'}, 'TARGET_UI_FIELDS')
        identity = targets.checked_name(request['run_id'])
        output = state_root() / 'target-runs' / identity
        audited = target_audit.audit(output)
        inputs = target_audit.read(output / 'input.json')
        require(inputs['plan']['target'] in self.manifests, 'TARGET_UI_UNREGISTERED_TARGET')
        if audited['status'] == 'INCOMPLETE':
            return dict(status='INCOMPLETE', run_id=identity, native_attempts=audited['native_attempts'],
                        repositories=[], audit=audited, provider_calls=0)
        result = target_audit.read(output / 'result.json')
        summaries = []
        for row, planned in zip(result['repositories'], inputs['plan']['repositories']):
            counters = {key: dict(passed=0, failed=0, unconfirmed=0)
                        for key in ('baseline', 'discovery', 'reinjection', 'regression', 'confirmation')}
            detected = set(); candidates = []
            child = output / 'repositories' / row['name']
            observations_verified = row['name'] in audited['verified_repositories'] and not inputs['plan']['paired']
            # Stopped children are reported without promoting partial traces.
            if observations_verified and (child / 'result.json').is_file():
                value = target_audit.read(child / 'result.json')
                candidates = sorted(value.get('adopted_files', {}))
                if planned.get('execution_method') == 'DOCUMENTED_SYNC_PATH_CONTEXT_V1':
                    for record in value.get('rounds', []):
                        observed = target_audit.read(child / record['stage'] / 'observed.json')
                        for observation in observed['rows']:
                            fault = observation['fault']
                            stage = ('confirmation' if record['stage'] == 'confirmation' else
                                     'baseline' if fault == 'NONE' else 'discovery')
                            for passed in (observation['contract_pass'], observation.get('repeat_pass')):
                                counters[stage]['passed' if passed is True else 'failed' if passed is False else 'unconfirmed'] += 1
                            if stage == 'discovery' and observation['contract_pass'] is False:
                                detected.add(fault if fault in ('BODY_EXCEPTION','BODY_BASE_EXCEPTION') else 'OWNER_CONDITION')
                for index, record in enumerate([] if planned.get('execution_method') == 'DOCUMENTED_SYNC_PATH_CONTEXT_V1'
                                               else value.get('rounds', [])):
                    study = target_audit.read(child / record['directory'] / 'result.json')
                    for arm in study['rows']:
                        observed = arm['observed']
                        stages = dict(baseline=[observed['healthy']],
                                      reinjection=observed['reinjection'], regression=observed['regression'])
                        stages['discovery' if index == 0 else 'confirmation'] = observed['probes']
                        for stage, observations in stages.items():
                            for observation in observations:
                                passed = observation['contract_pass']
                                counters[stage]['passed' if passed is True else 'failed' if passed is False else 'unconfirmed'] += 1
                                if index == 0 and stage == 'discovery' and passed is False:
                                    fault = observation['fault']
                                    # Generated conditions can contain private identifiers.
                                    known = {'WRITE','FSYNC','REPLACE','EXCEPTION','TASK_CANCEL','ACQUIRE_CANCEL','BACKWARD','FORWARD','STATIONARY'}
                                    detected.add(fault if fault in known else 'OWNER_CONDITION')
            summaries.append(dict(name=row['name'], status=row['status'], native_attempts=row['native_attempts'],
                observations=counters, detected_faults=sorted(detected), candidate_files=candidates,
                observations_verified=observations_verified,
                held_sites=planned['held_sites'], held_reasons=sorted({h['reason'] for h in planned['held_bindings']}),
                execution_method=planned.get('execution_method','FINITE_REPAIR_LOOP'),
                atomic_held_sites=len(planned.get('atomic_held_bindings', [])),
                atomic_held_reasons=sorted({h['reason'] for h in planned.get('atomic_held_bindings', [])})))
        return dict(status=result['status'], run_id=identity, target=inputs['plan']['target'],
            observed_at_jst=result['observed_at_jst'], native_attempts=result['native_attempts'],
            prior_native_attempts=result.get('prior_native_attempts', 0),
            new_native_attempts=result.get('new_native_attempts', result['native_attempts']),
            repositories=summaries, audit=audited, checkout_unchanged=result['checkout_unchanged'],
            candidate_scope='ISOLATED_SNAPSHOT_ONLY', provider_calls=0,
            independent_generalization_certified=False, natural_source_added_value_certified=False,
            probability_calibration_certified=False)

    def selected_manifest(self, request):
        name = request['target']
        require(type(name) is str and name in self.manifests, 'TARGET_UI_UNREGISTERED_TARGET')
        snapshot = request.get('snapshot_id')
        manifest = self.manifests[name]
        if snapshot is not None:
            require(type(snapshot) is str and snapshot in self.snapshots and self.snapshots[snapshot][0] == name,
                    'TARGET_UI_SNAPSHOT_ID')
            manifest = self.snapshots[snapshot][1]
            target_snapshot.verify(manifest.parent)
        bundle = request.get('preparation_id')
        if bundle is not None:
            require(type(bundle) is str and bundle in self.preparations and self.preparations[bundle][0] == name,
                    'TARGET_UI_PREPARATION_ID')
            require(self.preparations[bundle][2] == snapshot, 'TARGET_UI_PREPARATION_SNAPSHOT')
            return self.preparations[bundle][1]
        return manifest

    def plan(self, request):
        allowed = {'target', 'preparation_id', 'snapshot_id', 'repositories', 'all', 'seconds', 'campaigns', 'rounds', 'plan_sha256'}
        require(type(request) is dict and not set(request) - allowed and 'target' in request, 'TARGET_UI_FIELDS')
        selected = request.get('repositories', [])
        require(type(selected) is list and len(selected) <= 16 and all(type(n) is str for n in selected)
                and type(request.get('all', False)) is bool, 'TARGET_UI_SELECTION')
        return targets.prepare(self.selected_manifest(request), selected, request.get('all', False),
            seconds=request.get('seconds', 120), campaigns=request.get('campaigns', 0), rounds=request.get('rounds', 3))

    def dispatch(self, operation, request):
        require(operation in OPERATIONS and type(request) is dict, 'TARGET_UI_OPERATION')
        if operation == 'result':
            return self.saved_result(request)
        if operation == 'audit':
            require(set(request) == {'run_id'}, 'TARGET_UI_FIELDS')
            run_id = targets.checked_name(request['run_id'])
            return target_audit.audit(state_root() / 'target-runs' / run_id)
        if operation == 'snapshot':
            require(set(request) <= {'target', 'repositories', 'all'} and 'target' in request, 'TARGET_UI_FIELDS')
            require(type(request.get('repositories', [])) is list and len(request.get('repositories', [])) <= 16
                    and all(type(n) is str for n in request.get('repositories', []))
                    and type(request.get('all', False)) is bool, 'TARGET_UI_SELECTION')
            manifest = self.selected_manifest(request)
            target_snapshot.build(manifest, request.get('repositories', []), request.get('all', False))
            root = self.private_parent('target-snapshots')
            identity = 'snapshot-' + uuid.uuid4().hex
            result = target_snapshot.save_bundle(manifest, request.get('repositories', []), root / identity,
                                                request.get('all', False))
            self.snapshots[identity] = (request['target'], Path(result['target']))
            return dict(status=result['status'], snapshot_id=identity,
                repositories=[{k: r[k] for k in ('name', 'copied_python_files')} for r in result['repositories']],
                copied_bytes=result['copied_bytes'], original_selected_inputs_unchanged=True,
                native_attempts=0, provider_calls=0, fault_injection_verified=False, repair_verified=False)
        if operation == 'prepare':
            require(set(request) <= {'target', 'snapshot_id', 'repositories', 'all', 'source_texts'} and 'target' in request, 'TARGET_UI_FIELDS')
            require(type(request.get('repositories', [])) is list and len(request.get('repositories', [])) <= 16
                    and all(type(n) is str for n in request.get('repositories', []))
                    and type(request.get('all', False)) is bool,
                    'TARGET_UI_SELECTION')
            manifest = self.selected_manifest(request)
            # Preparation creates user-owned private output only after static validation.
            options = {} if not request.get('source_texts') else {'natural_source': {'source_texts': request['source_texts']}}
            target_prepare.build(manifest, request.get('repositories', []), request.get('all', False), **options)
            root = self.private_parent('target-preparations')
            identity = 'prepared-' + uuid.uuid4().hex
            result = target_prepare.save_bundle(manifest, request.get('repositories', []), root / identity,
                request.get('all', False), **options)
            self.preparations[identity] = (request['target'], Path(result['target']), request.get('snapshot_id'))
            return dict(status=result['status'], preparation_id=identity, repositories=result['repositories'],
                        provider_calls=0, native_attempts=0, semantic_support_certified=False)
        planned, prepared, roots = self.plan(request)
        if operation == 'plan':
            plan = planned['plan']
            return dict(status='PLANNED', plan_sha256=planned['plan_sha256'],
                repositories=[dict(name=r['name'], accepted_sites=r['accepted_sites'], executable_sites=r['executable_sites'],
                    held_sites=r['held_sites'], held_reasons=sorted({str(h['reason']) for h in r['held_bindings']}))
                    for r in plan['repositories']], provider_calls=0, native_attempts=0)
        require(type(request.get('plan_sha256')) is str and request['plan_sha256'] == planned['plan_sha256'],
                'TARGET_UI_PLAN_CHANGED')
        require(self.allow_native or planned['plan']['maximum_native_campaigns'] == 0, 'TARGET_UI_NATIVE_NOT_ENABLED')
        result = targets.execute(planned, prepared, roots, state_root(), expected=request['plan_sha256'])
        candidates = []
        for row in result['repositories']:
            if row['output'] and (Path(row['output']) / 'result.json').is_file():
                value = target_audit.read(Path(row['output']) / 'result.json')
                candidates.extend(dict(repository=row['name'], path=p) for p in value.get('adopted_files', {}))
        return dict(status=result['status'], run_id=Path(result['output']).name, native_attempts=result['native_attempts'],
            reason=result['reason'], repositories=[{k: r[k] for k in ('name', 'status', 'native_attempts')} for r in result['repositories']],
            candidate_files=candidates, checkout_unchanged=result['checkout_unchanged'], provider_calls=0,
            independent_generalization_certified=False, natural_source_added_value_certified=False,
            probability_calibration_certified=False)

    @staticmethod
    def private_parent(name):
        import os
        import run_reliability_reuse as runner
        state = runner.private(state_root()); state.mkdir(parents=True, mode=0o700, exist_ok=True)
        require(state.stat().st_uid == os.getuid() and state.stat().st_mode & 0o077 == 0, 'TARGET_UI_PRIVATE_STATE')
        root = runner.private(state / name); root.mkdir(mode=0o700, exist_ok=True)
        require(root.stat().st_uid == os.getuid() and root.stat().st_mode & 0o077 == 0, 'TARGET_UI_PRIVATE_STATE')
        return root
