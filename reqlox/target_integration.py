"""Explicit, non-resettable continuation for the approved copied-module scope.

Preparation imports no Target. Execution requires a separate final grant and
retains all failures. The ordinary twelve-campaign guards remain unchanged.
"""
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

from .native_evidence import retained_workspace, inventory, _save
from .integration_worker import FAULTS, PAYLOADS, digest, require

SCOPE = 'target-snapshot-local-20261012-v01'
CONTRACT = Path('/etc/codex-host-context/host.json')
CONTRACT_SHA = '849771ea24514c882792a83223866509d0013d2595d0801060dcfc5aeac0d67d'
METHOD_NAMES = ('target_integration.py', 'integration_worker.py', 'integration_cli.py',
                'native_evidence.py', 'cli.py', '__init__.py')
LEDGER = 'generalization-preparation-v01/native-test-boundary-incident-v01/cumulative-native-ledger-v02.json'
STOP = 'path-context-cli-v01/authorization-reservations/execution-stop.json'
FENCE = 'path-context-cli-v01/authorization-reservations/integration-extension-v01.claim.json'
PINS = {
    LEDGER: '3cecc8f8e6103cc0a9e6c7282cde998ef14d3f2ece7fcc5ed31c12700f853db4',
    STOP: 'aa9652fa74f6e7373fd504ca8de8cfb5ae6c4cb3455ff084ce381477b52ecea5',
    'path-context-cli-v01/cumulative-native-ledger-v01.json':
        '0ba6aef7416b2ee7d7bcb5289a12ed7c520677612b5eefd31d2c91dfa9702b6d',
    'target/local-system-v02/snapshot.json':
        '39506156cfe81c2723462d1b884c482c5aac52a9b1caa1dc53ca613c4617a81b',
    'target/local-system-v02/target.json':
        'a2049c3b104aaeb1a7f86ef41cea82538fba903a2a0d5b807137aa4ef9d24f28',
    'prepared-system-v02/target.json':
        '085cbd14f469f56cb901e9b8c88b77dd98b21dad6dff7fd8e86fe13ce7004350',
    'path-context-cli-v01/prepared/temppath.configuration.json':
        '3ff1d0270c3fbaa065fe5dda4d412e7549fcd85391abcce6b14c0cd9ac653f10',
    'execution-v01/adopted-snapshots/api/manifest.json':
        '2da37fa722db3a71ed94618b46882ab92eb7984988cd623e49348d1fb6f13997',
    'execution-v01/adopted-snapshots/worker/manifest.json':
        '4fb84ca64bfe4a89768a8b26b049833a10326ea298b563dd9b27843e9b9308d4',
}
LIMITS = dict(cpu_seconds=2, wall_seconds=5, memory_bytes=134217728,
              output_bytes=131072, core_bytes=0)
SCENARIO = dict(faults=list(FAULTS), payloads_sha256=[hashlib.sha256(p).hexdigest() for p in PAYLOADS],
                preexisting_pending=True, following_normal=True,
                requirements=['owned.atomic-bytes.v1', 'owned.async-release.v1',
                              'documented.path-context-release.v1'],
                held_atomic_bindings=4, temppath_repair_performed=False)


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))


def safe_path(path):
    path = Path(os.path.abspath(path))
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'INTEGRATION_PATH_LINK')
    return path


def private_dir(path):
    path = safe_path(path)
    require(path.is_dir() and path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077,
            'INTEGRATION_PRIVATE_DIRECTORY')
    return path


def sha(path):
    path = safe_path(path); metadata = path.stat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 16777216
            and metadata.st_nlink == 1, 'INTEGRATION_FILE_BOUND')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    sha(path)
    return json.loads(Path(path).read_text())


def methods():
    return {name: sha(Path(__file__).parent / name) for name in METHOD_NAMES}


def check_contract():
    metadata = CONTRACT.stat(); value = read(CONTRACT)
    require(metadata.st_uid == 0 and not metadata.st_mode & 0o022
            and value['host_id'] == 'dell-stream-runtime' and digest(value) == CONTRACT_SHA,
            'INTEGRATION_ROOT_CONTRACT')
    text = value['forbidden'][2]
    require(SCOPE in text and '15回' in text and '20秒を全額消費予約' in text,
            'INTEGRATION_EXPLICIT_EXCEPTION_REQUIRED')
    return value


def source_bindings(scope):
    """Verify the eight-file receipt and existing adopted snapshots without import."""
    scope = private_dir(scope)
    require(scope.name == SCOPE, 'INTEGRATION_SCOPE_ID')
    check_contract()
    refs = {}
    for name, expected in PINS.items():
        require(sha(scope / name) == expected, 'INTEGRATION_HISTORICAL_BINDING_DRIFT')
        refs[name] = expected
    ledger, stop = read(scope / LEDGER), read(scope / STOP)
    require(ledger['status'] == 'TERMINAL' and ledger['cumulative_native_campaigns'] == 12
            and ledger['cumulative_charged_seconds'] == 42 and stop['native_execution_disabled'] is True,
            'INTEGRATION_PRIOR_SCOPE_NOT_CLOSED')
    target = scope / 'target/local-system-v02'
    receipt = read(target / 'snapshot.json')
    require(len(receipt['files']) == 8 and receipt['selected_repositories'] == ['api', 'worker', 'temppath'],
            'INTEGRATION_RECEIPT_SCOPE')
    require(receipt['output'] == str(target), 'INTEGRATION_RECEIPT_ROOT_REDIRECT')
    original = {}; candidate = {}
    for name, expected in receipt['files'].items():
        require(sha(target / name) == expected, 'INTEGRATION_RECEIPT_DRIFT')
        refs['target/local-system-v02/' + name] = expected
        if name.startswith('repositories/'):
            key = name.removeprefix('repositories/')
            ast.parse((target / name).read_text())
            original[key] = expected
            candidate[key] = expected
    for repository, member in (('api', 'storage.py'), ('worker', 'resource.py')):
        base = scope / 'execution-v01/adopted-snapshots' / repository
        manifest = read(base / 'manifest.json')
        require(manifest['schema'] == 'reqlox.adopted-copy.v1'
                and manifest['candidate_scope'] == 'ISOLATED_SNAPSHOT_ONLY'
                and manifest['repository'] == repository and set(manifest['files']) == {member},
                'INTEGRATION_CANDIDATE_SCOPE')
        expected = manifest['files'][member]
        require(sha(base / member) == expected, 'INTEGRATION_CANDIDATE_DRIFT')
        ast.parse((base / member).read_text())
        refs[str((base / member).relative_to(scope))] = expected
        candidate[repository + '/' + member] = expected
    require(set(original) == {'api/storage.py', 'worker/resource.py',
                              'temppath/temppath/__init__.py', 'temppath/temppath/temppath.py'},
            'INTEGRATION_MODULE_SET')
    config = read(scope / 'path-context-cli-v01/prepared/temppath.configuration.json')['path_context']
    require(config['contract']['scope'] == 'DOCUMENTED_WITH_EXIT_ONLY'
            and config['recipe']['binding']['module'] == 'temppath'
            and config['recipe']['binding']['symbol'] == 'TemporaryPathContext'
            and config['recipe']['binding']['args'] == [] and config['recipe']['binding']['kwargs'] == {},
            'INTEGRATION_README_BINDING')
    evidence = config['contract']['evidence']; span = evidence['span']
    document = config['documents'][evidence['document']]
    require(hashlib.sha256(document[span['start']:span['end']].encode()).hexdigest() == span['sha256'],
            'INTEGRATION_README_EVIDENCE')
    return dict(refs=refs, original=original, candidate=candidate)


def prepare(scope, output, *, runtime_baseline):
    bindings = source_bindings(scope); scope = private_dir(scope)
    runtime = read(runtime_baseline)
    runtime_identity = validate_runtime(runtime)
    require(not (scope / FENCE).exists() and not any((scope / FENCE).parent.glob('integration-native-*.json')),
            'INTEGRATION_CONTINUATION_ALREADY_CLAIMED')
    output = safe_path(output)
    require(output.is_relative_to(scope) and not output.exists(), 'INTEGRATION_NEW_PREPARATION_REQUIRED')
    private_dir(output.parent); output.mkdir(mode=0o700)
    for variant in ('original', 'candidate'):
        root = output / variant; root.mkdir(mode=0o700)
        for member in bindings[variant]:
            origin = scope / 'target/local-system-v02/repositories' / member
            if variant == 'candidate' and member in ('api/storage.py', 'worker/resource.py'):
                origin = scope / 'execution-v01/adopted-snapshots' / member
            destination = root / member; destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(origin.read_bytes()); destination.chmod(0o400)
    method = methods()
    plans = []
    for number, variant in ((13, 'original'), (14, 'candidate'), (15, 'candidate')):
        plan = dict(schema='reqlox.module-integration-plan.v1', attempt=number, variant=variant,
                    sources=bindings[variant], method=method, scenario=SCENARIO,
                    scenario_sha256=digest(SCENARIO), limits=LIMITS,
                    parent_namespaces={k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net')})
        _save(output / f'plan-{number}.json', plan)
        plans.append(sha(output / f'plan-{number}.json'))
    observer = scope / 'execution-v01/observe_stream.py'
    expected = read(scope / 'execution-v01/evidence-manifest.json')['files']['observe_stream.py']['sha256']
    require(sha(observer) == expected, 'INTEGRATION_OBSERVER_DRIFT')
    bundle = dict(schema='reqlox.module-integration-bundle.v1', scope=str(scope), output=str(output),
                  contract_sha256=CONTRACT_SHA, source_bindings=bindings, method=method,
                  plans_sha256=plans, observer_sha256=expected,
                  launcher_sha256={name: sha('/usr/bin/' + name) for name in ('bwrap', 'prlimit')},
                  python_sha256=sha(Path('/usr/bin/python3').resolve()),
                  runtime_identity=runtime_identity, runtime_baseline_sha256=sha(runtime_baseline),
                  old_execution_stop_preserved=True, prior_campaigns=12, prior_seconds=42,
                  maximum_campaigns=15, maximum_new_campaigns=3, reserved_window_seconds=20,
                  maximum_experiment_seconds=120, approval_to_finish_seconds=300,
                  native_execution_authorized=False)
    _save(output / 'bundle.json', bundle)
    _save(output / 'pending-grant.json', dict(schema='reqlox.module-integration-final-grant.v1',
          status='PENDING_FINAL_APPROVAL', bundle_sha256=sha(output / 'bundle.json'),
          received_at_jst=None, user_approval_reference=None, maximum_new_campaigns=3,
          window_seconds=20, approval_to_finish_seconds=300))
    return dict(status='PREPARED_NOT_EXECUTED', bundle_sha256=sha(output / 'bundle.json'),
                plans_sha256=plans, cumulative_native_campaigns=12, cumulative_charged_seconds=42,
                new_native_campaigns=0, final_execution_approval_required=True)


def check_bundle(output):
    output = private_dir(output); bundle = read(output / 'bundle.json')
    scope = private_dir(bundle['scope'])
    require(bundle['output'] == str(output) and output.is_relative_to(scope), 'INTEGRATION_OUTPUT_DRIFT')
    require(bundle['source_bindings'] == source_bindings(scope) and bundle['method'] == methods(),
            'INTEGRATION_INPUT_OR_METHOD_DRIFT')
    for key, expected in dict(contract_sha256=CONTRACT_SHA, prior_campaigns=12, prior_seconds=42,
                              maximum_campaigns=15, maximum_new_campaigns=3,
                              reserved_window_seconds=20, maximum_experiment_seconds=120,
                              approval_to_finish_seconds=300, native_execution_authorized=False).items():
        require(bundle[key] == expected, 'INTEGRATION_BUDGET_RESET')
    for index, number in enumerate((13, 14, 15)):
        plan = read(output / f'plan-{number}.json')
        variant = 'original' if number == 13 else 'candidate'
        expected = dict(schema='reqlox.module-integration-plan.v1', attempt=number, variant=variant,
                        sources=bundle['source_bindings'][variant], method=bundle['method'],
                        scenario=SCENARIO, scenario_sha256=digest(SCENARIO), limits=LIMITS,
                        parent_namespaces={k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net')})
        require(plan == expected and sha(output / f'plan-{number}.json') == bundle['plans_sha256'][index],
                'INTEGRATION_PLAN_DRIFT')
        root = output / variant
        actual = {}; entries = 0
        for directory, folders, files in os.walk(root, followlinks=False):
            for name in folders + files:
                entries += 1; path = Path(directory) / name
                require(entries <= 32 and not path.is_symlink(), 'INTEGRATION_STAGED_ENTRY_BOUND_OR_LINK')
                if name in files: actual[str(path.relative_to(root))] = sha(path)
        require(actual == plan['sources'], 'INTEGRATION_STAGED_SOURCE_DRIFT')
    require(set(bundle['launcher_sha256']) == {'bwrap', 'prlimit'}, 'INTEGRATION_LAUNCHER_SET')
    for name, expected in bundle['launcher_sha256'].items():
        require(sha('/usr/bin/' + name) == expected, 'INTEGRATION_LAUNCHER_DRIFT')
    require(sha(Path('/usr/bin/python3').resolve()) == bundle['python_sha256'], 'INTEGRATION_PYTHON_DRIFT')
    require(sha(scope / 'execution-v01/observe_stream.py') == bundle['observer_sha256'],
            'INTEGRATION_OBSERVER_DRIFT')
    return bundle


def check_grant(output, grant, current=None):
    current = current or now(); value = read(grant)
    require(set(value) == {'schema', 'status', 'bundle_sha256', 'received_at_jst',
                          'user_approval_reference', 'maximum_new_campaigns', 'window_seconds',
                          'approval_to_finish_seconds'} and value['schema'] == 'reqlox.module-integration-final-grant.v1'
            and value['status'] == 'APPROVED_FINAL_EXECUTION' and type(value['user_approval_reference']) is str
            and bool(value['user_approval_reference'].strip()), 'INTEGRATION_FINAL_APPROVAL_REQUIRED')
    require(value['bundle_sha256'] == sha(Path(output) / 'bundle.json')
            and value['maximum_new_campaigns'] == 3 and value['window_seconds'] == 20
            and value['approval_to_finish_seconds'] == 300, 'INTEGRATION_GRANT_BINDING')
    received = dt.datetime.fromisoformat(value['received_at_jst'])
    require(received.tzinfo is not None and 0 <= (current - received).total_seconds() <= 291,
            'INTEGRATION_FINAL_APPROVAL_EXPIRED')
    return received + dt.timedelta(seconds=300)


def capacity(bundle):
    """Read the shared fence; a prepared view must not report reset counters."""
    fence = Path(bundle['scope']) / FENCE
    events = sorted(fence.parent.glob('integration-native-*.json'))
    claimed = fence.exists()
    require(not events or claimed, 'INTEGRATION_ORPHAN_RESERVATIONS')
    if claimed:
        claim = read(fence)
        require(claim['prior_native_campaigns'] == 12 and claim['cumulative_charged_seconds'] == 62,
                'INTEGRATION_CLAIM_CHARGE_DRIFT')
    attempts = max([13 if claimed else 12, *[read(p)['attempt'] for p in events]])
    require(attempts <= 15, 'INTEGRATION_CAP_EXCEEDED')
    return dict(status='CLOSED_CONTINUATION' if claimed else 'PREPARED_INPUTS_VERIFIED_NOT_EXECUTED',
                cumulative_native_campaigns=attempts, cumulative_charged_seconds=62 if claimed else 42,
                currently_executable_native_campaigns=0, conditional_unclaimed_campaigns=0 if claimed else 3,
                final_execution_approval_required=not claimed, automatic_retry=False)


def validate_runtime(value, previous=None, current=None):
    current = current or now()
    require(0 <= (current - dt.datetime.fromisoformat(value['observed_at_jst'])).total_seconds() < 10,
            'INTEGRATION_RUNTIME_STALE')
    require(value['host_id'] == 'dell-stream-runtime' and value['hardware_model'] == 'Precision Tower 5810'
            and value['target_host_id'] == value['configured_target_host_id']
            and value['release_id'] == value['configured_release_id']
            and value['source_commit'] == value['configured_source_commit']
            and 0 <= value['evidence_age_seconds'] < 30 and 0 <= value['transport_age_seconds'] < 30
            and value['lifecycle_state'] == 'RUNNING' and len(value['containers']) == 4
            and all(c['ready'] for c in value['containers'])
            and value['transport_ffmpeg_pid'] == value['ffmpeg_pid'] == value['recovery']['last_pid'],
            'INTEGRATION_RUNTIME_IDENTITY')
    metrics, recovery = value['transport_metrics'], value['recovery']
    require(metrics['bytes_sent_delta'] > 0 and not any(metrics[k] for k in
            ('network_down', 'remote_warning', 'low_upload_pressure')) and recovery['last_reason'] == 'healthy'
            and all(recovery[k] == 0 for k in ('net_fail_streak', 'stall_streak', 'remote_warning_streak',
                                             'restart_failure_count'))
            and recovery['pending_recovery_actions'] == [], 'INTEGRATION_NEW_DELIVERY_ANOMALY')
    units = value['units']; service = units['stream-v3-fast-recovery-controller.service']
    timer = units['stream-v3-fast-recovery-controller.timer']
    require(service['Type'] == 'oneshot' and service['ExecMainStatus'] == '0' and service['Result'] == 'success'
            and (service['ActiveState'], service['SubState']) in
            (('inactive', 'dead'), ('activating', 'start'), ('active', 'running'))
            and timer['Unit'] == 'stream-v3-fast-recovery-controller.service' and timer['Result'] == 'success'
            and timer['ActiveState'] == 'active' and timer['SubState'] in ('waiting', 'running')
            and units['k3s.service'] == dict(ActiveState='active', SubState='running', Result='success'),
            'INTEGRATION_RUNTIME_UNIT')
    stable = {k: value[k] for k in ('hostname', 'hardware_model', 'boot_id', 'host_id', 'target_host_id',
              'release_id', 'source_commit', 'pod_uid', 'containers', 'ffmpeg_pid', 'ffmpeg_generation')}
    stable['postboot'] = units['stream-v3-postboot-verification.service']
    stable['config_sha256'] = value['raw_sha256']['config']
    if previous is not None:
        require(stable == previous, 'INTEGRATION_RUNTIME_DRIFT')
    return stable


def observe(bundle, timeout=3):
    """Separate read-only operational audit; these are not Target campaigns."""
    scope = Path(bundle['scope'])
    require(sha(scope / 'execution-v01/observe_stream.py') == bundle['observer_sha256'],
            'INTEGRATION_OBSERVER_DRIFT')
    value = json.loads(subprocess.check_output(['sudo', '-n', '/usr/bin/python3', '-B',
                   str(scope / 'execution-v01/observe_stream.py')], timeout=timeout))
    for unit, properties in [('stream-v3-fast-recovery-controller.service', ('Type', 'ExecMainStatus')),
                             ('stream-v3-fast-recovery-controller.timer', ('Unit',))]:
        rows = subprocess.check_output(['systemctl', 'show', unit, *['--property=' + p for p in properties]],
                                       text=True, timeout=1)
        value['units'][unit].update(dict(line.split('=', 1) for line in rows.splitlines()))
    return value


class Continuation:
    """The fixed old reservation directory owns the one-shot extension fence."""
    def __init__(self, bundle, output, deadline):
        self.bundle, self.output, self.deadline = bundle, Path(output), deadline
        self.scope = Path(bundle['scope']); self.fence = self.scope / FENCE
        self.attempts = 12; self.started = None; self.started_wall = None
        self.claim_sha256 = None
        self.event_hashes = {}
        require(not self.fence.exists() and not any(self.fence.parent.glob('integration-native-*.json')),
                'INTEGRATION_CONTINUATION_ALREADY_CLAIMED')
        private_dir(self.fence.parent)

    def remaining(self):
        approval_left = (self.deadline - now()).total_seconds()
        window_left = 20 if self.started is None else 20 - (time.monotonic() - self.started)
        return min(approval_left, window_left)

    def reserve(self, number, plan_sha256):
        require(number == self.attempts + 1 and 13 <= number <= 15 and self.remaining() >= 8.5,
                'INTEGRATION_CONTINUATION_LIMIT_OR_DEADLINE')
        if number == 13:
            self.started = time.monotonic(); self.started_wall = now()
            _save(self.fence, dict(schema='reqlox.integration-continuation-claim.v1',
                  bundle_sha256=sha(self.output.parent / 'bundle.json'), output=str(self.output),
                  first_reserved_attempt=13, cumulative_campaigns_at_claim=13,
                  prior_native_campaigns=12, prior_charged_seconds=42, charged_window_seconds=20,
                  cumulative_charged_seconds=62, started_at_jst=self.started_wall.isoformat(),
                  deadline_jst=self.deadline.isoformat(), automatic_retry=False, reservation_release=False,
                  historical_bindings=self.bundle['source_bindings']['refs']))
            self.attempts = 13
            self.claim_sha256 = sha(self.fence)
        else:
            require(sha(self.fence) == self.claim_sha256, 'INTEGRATION_FENCE_DRIFT')
            events = sorted(self.fence.parent.glob('integration-native-*.json'))
            require([p.name for p in events] == [f'integration-native-{n:03d}.json' for n in range(13, number)]
                    and all(read(p)['output'] == str(self.output) and sha(p) == self.event_hashes[p.name]
                            for p in events), 'INTEGRATION_RESERVATION_DRIFT')
        event = dict(attempt=number, plan_sha256=plan_sha256, output=str(self.output),
                     status='RESERVED_BEFORE_DISPATCH', recorded_at_jst=now().isoformat(),
                     failed_launch_consumes=True, automatic_retry=False)
        _save(self.fence.parent / f'integration-native-{number:03d}.json', event)
        self.event_hashes[f'integration-native-{number:03d}.json'] = sha(self.fence.parent / f'integration-native-{number:03d}.json')
        self.attempts = number
        return event


def child_command(prepared, phase, plan):
    cmd = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
           '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib',
           '--symlink', 'usr/lib64', '/lib64', '--tmpfs', '/tmp', '--proc', '/proc', '--dev', '/dev',
           '--chdir', '/tmp', '--ro-bind', str(phase / 'plan.json'), '/run/plan.json',
           '--ro-bind', str(phase / 'method'), '/app', '--ro-bind', str(prepared / plan['variant']), '/target',
           '/usr/bin/python3', '-I', '-S', '-B', '-c',
           'import sys;sys.path.insert(0,"/app");from integration_worker import run;run(sys.argv[1],sys.argv[2])',
           '/run/plan.json', digest(plan)]
    return ['/usr/bin/prlimit', '--cpu=2:2', '--as=134217728:134217728',
            '--fsize=131072:131072', '--core=0:0', '--', *cmd]


def validate_observation(observed, plan, parent):
    require(parent == plan['parent_namespaces'], 'INTEGRATION_PARENT_NAMESPACE_DRIFT')
    require(observed['schema'] == 'reqlox.module-integration-observation.v1'
            and observed['plan_sha256'] == digest(plan) and observed['sources'] == plan['sources']
            and observed['method'] == plan['method'] and observed['scenario_sha256'] == digest(SCENARIO)
            and observed['module_imported'] is True and observed['external_action_attempts'] == []
            and observed['held_atomic_bindings'] == 4 and observed['temppath_repair_performed'] is False
            and observed['origins'] == dict(api='/target/api/storage.py', worker='/target/worker/resource.py',
                                           temppath='/target/temppath/temppath/temppath.py'),
            'INTEGRATION_OBSERVATION_BINDING')
    boundary = observed['execution_boundary']
    require(type(boundary['uid']) is int and boundary['uid'] > 0
            and boundary['effective_capabilities'] == 0 and boundary['home_visible'] is False
            and boundary['cpu'] == [2, 2] and boundary['memory'] == [134217728, 134217728]
            and boundary['output'] == [131072, 131072] and boundary['core'] == [0, 0],
            'INTEGRATION_CHILD_LIMITS')
    require(set(observed['namespaces']) == set(parent) and all(observed['namespaces'][k] != parent[k]
            for k in parent), 'INTEGRATION_NAMESPACE')
    rows = observed['rows']
    require(len(rows) == 10 and [row['case'] for row in rows] == [*FAULTS, *['NORMAL'] * 4, 'PREEXISTING_PENDING']
            and [row['payload_sha256'] for row in rows] == [hashlib.sha256(PAYLOADS[0]).hexdigest()] * 5
                + SCENARIO['payloads_sha256'] + [hashlib.sha256(PAYLOADS[0]).hexdigest()],
            'INTEGRATION_CASE_COVERAGE')
    keys = ('injection_reached', 'acquired', 'exception_preserved', 'destination_preserved',
            'lock_released', 'scratch_removed', 'owned_pending_removed', 'unrelated_preserved',
            'following_normal_pass')
    for row in rows:
        require(all(type(row[k]) is bool for k in (*keys, 'passed'))
                and row['passed'] == all(row[k] for k in keys), 'INTEGRATION_ROW_VERDICT')
    require(all(row['injection_reached'] and row['acquired'] and row['exception_preserved'] for row in rows),
            'INTEGRATION_FAULT_NOT_REACHED')
    expected_errors = ['InjectedError'] * 4 + ['CancelledError'] + [None] * 4 + ['FileExistsError']
    require([row['exception_type'] for row in rows] == expected_errors
            and all((row['following_normal_error'] is None) == row['following_normal_pass'] for row in rows),
            'INTEGRATION_EXCEPTION_OBSERVATION')
    return dict(counterexample=any(not row['passed'] for row in rows[:5]),
                all_pass=all(row['passed'] for row in rows), normal_pass=all(row['passed'] for row in rows[5:9]),
                failed_cases=[row['case'] for row in rows if not row['passed']])


def launch(prepared, phase, plan, guard):
    phase.mkdir(mode=0o700); _save(phase / 'plan.json', plan)
    method = phase / 'method'; method.mkdir(mode=0o700)
    data = (Path(__file__).parent / 'integration_worker.py').read_bytes()
    require(hashlib.sha256(data).hexdigest() == plan['method']['integration_worker.py'], 'INTEGRATION_WORKER_DRIFT')
    (method / 'integration_worker.py').write_bytes(data); (method / 'integration_worker.py').chmod(0o400)
    parent = {k: os.readlink('/proc/self/ns/' + k) for k in ('user', 'mnt', 'pid', 'net')}
    require(parent == plan['parent_namespaces'], 'INTEGRATION_PARENT_NAMESPACE_DRIFT')
    _save(phase / 'launch.json', dict(plan_sha256=digest(plan), parent_namespaces=parent,
          child_limits=LIMITS, network_isolated=True, home_mounted=False, original_mounted=False,
          serial=True, automatic_retry=False, limits_before_bwrap=True))
    child = None; error = None; code = None
    try:
        with (phase / 'observed.json').open('xb') as out, (phase / 'stderr.log').open('xb') as err:
            os.fchmod(out.fileno(), 0o600); os.fchmod(err.fileno(), 0o600)
            guard.reserve(plan['attempt'], digest(plan))
            child = subprocess.Popen(child_command(prepared, phase, plan), stdout=out, stderr=err,
                                     env={}, start_new_session=True)
            code = child.wait(timeout=min(5, guard.remaining()))
    except BaseException as exc:
        error = type(exc).__name__
        _save(phase / 'error.json', dict(error_type=error, reserved_attempts=guard.attempts,
              reservation_not_released=True, automatic_retry=False))
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=1)
    summary = None
    if code == 0 and error is None:
        try:
            observed = read(phase / 'observed.json')
            require((phase / 'observed.json').stat().st_size <= 131072, 'INTEGRATION_OUTPUT_BOUND')
            summary = validate_observation(observed, plan, parent)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            error = type(exc).__name__ + ':' + str(exc)[:120]
    _save(phase / 'receipt.json', dict(status='VERIFIED' if summary is not None else 'UNKNOWN',
          plan_sha256=sha(phase / 'plan.json'), observed_sha256=sha(phase / 'observed.json'),
          launch_sha256=sha(phase / 'launch.json'), code=code, error=error, summary=summary,
          attempt=plan['attempt'], automatic_retry=False, reserved_attempts=guard.attempts))
    require(summary is not None, 'INTEGRATION_NATIVE_RESULT_UNKNOWN')
    return summary


def execute(output, grant):
    output = private_dir(output)
    require(os.getuid() > 0, 'INTEGRATION_NON_ROOT_REQUIRED')
    deadline = check_grant(output, grant)  # Deny before *any* process or new workspace.
    bundle = check_bundle(output)
    original = None; decision = 'NOT_PERFORMED'; reason = None
    with retained_workspace(output, 'execution') as run:
        guard = Continuation(bundle, run, deadline)
        _save(run / 'grant.json', read(grant))
        _save(run / 'bundle.json', bundle)
        try:
            baseline = bundle['runtime_identity']
            for number in (13, 14, 15):
                check_bundle(output)
                runtime = observe(bundle, timeout=min(3, guard.remaining() - 5))
                baseline = validate_runtime(runtime, baseline)
                _save(run / f'runtime-before-{number}.json', runtime)
                plan = read(output / f'plan-{number}.json')
                summary = launch(output, run / f'phase-{number}', plan, guard)
                runtime = observe(bundle, timeout=min(3, guard.remaining()))
                validate_runtime(runtime, baseline)
                _save(run / f'runtime-after-{number}.json', runtime)
                require(guard.remaining() > 0, 'INTEGRATION_WINDOW_EXPIRED')
                if number == 13:
                    original = summary
                    if not summary['counterexample'] or not summary['normal_pass']:
                        reason = 'NO_SUPPORTED_COUNTEREXAMPLE_OR_NORMAL_BASELINE_FAILED'; break
                elif number == 14:
                    if not summary['all_pass']:
                        reason = 'CANDIDATE_NOT_IMPROVED_OR_REGRESSION'; break
                    decision = 'CANDIDATE_IMPROVED_AWAITING_FRESH_CONFIRMATION'
                else:
                    decision = 'ADOPT_EXISTING_CANDIDATE_FOR_ISOLATED_COMPOSED_CALLER' if summary['all_pass'] else 'NOT_ADOPTED'
                    reason = 'FRESH_CONFIRMATION_PASS' if summary['all_pass'] else 'FRESH_CONFIRMATION_FAILED'
        except BaseException as exc:
            decision = 'UNKNOWN_NOT_ADOPTED'; reason = type(exc).__name__ + ':' + str(exc)[:160]
            _save(run / 'supervisor-error.json', dict(error_type=type(exc).__name__, reason=reason,
                  automatic_retry=False, reservation_release=False))
        finally:
            # Claim is never rewritten. Its full charge survives a missing terminal.
            events = list(guard.fence.parent.glob('integration-native-*.json'))
            attempts = max([12, guard.attempts, *[read(p)['attempt'] for p in events]])
            charged = 62 if guard.fence.exists() else 42
            _save(run / 'terminal.json', dict(schema='reqlox.module-integration-terminal.v1',
                  cumulative_native_campaigns=attempts, cumulative_charged_seconds=charged,
                  new_native_campaigns=attempts - 12, maximum_native_campaigns=15,
                  maximum_experiment_seconds=120, completed_at_jst=now().isoformat(),
                  elapsed_window_seconds=None if guard.started is None else time.monotonic() - guard.started,
                  adoption=decision, stop_reason=reason, original_summary=original,
                  held_atomic_bindings=4, temppath_repair_performed=False,
                  original_preserved=True, old_execution_stop_preserved=True,
                  historical_raw_evidence_gap='RAW_EVIDENCE_UNRECOVERED_NOT_REAUDITABLE',
                  global_claim_sha256=sha(guard.fence) if guard.fence.exists() else None,
                  reservation_hashes={p.name: sha(p) for p in events},
                  independent_generalization=False, probability_calibration=False, source_added_value=False,
                  automatic_retry=False, reservation_release=False))
    return dict(output=str(run), **read(run / 'terminal.json'))


def audit(run):
    """Hash and re-evaluate observations; never import archived Target or worker."""
    run = private_dir(run); bundle = read(run / 'bundle.json'); scope = Path(bundle['scope'])
    retained = read(run / 'retention-terminal.json')
    files = inventory(run); files.pop('retention-terminal.json')
    require(retained['inventory_status'] == 'VERIFIED' and retained['files'] == files,
            'INTEGRATION_RETAINED_EVIDENCE_DRIFT')
    for name, expected in bundle['source_bindings']['refs'].items():
        require(sha(scope / name) == expected, 'INTEGRATION_HISTORICAL_BINDING_DRIFT')
    terminal = read(run / 'terminal.json'); phases = []
    fence = scope / FENCE
    if terminal['global_claim_sha256'] is not None:
        require(sha(fence) == terminal['global_claim_sha256'], 'INTEGRATION_AUDIT_FENCE_DRIFT')
        claim = read(fence)
        require(claim['output'] == str(run) and claim['cumulative_charged_seconds'] == 62,
                'INTEGRATION_AUDIT_CHARGE')
    events = sorted(fence.parent.glob('integration-native-*.json'))
    require({p.name: sha(p) for p in events} == terminal['reservation_hashes'], 'INTEGRATION_AUDIT_RESERVATIONS')
    count = max([12, 13 if terminal['global_claim_sha256'] is not None else 12,
                 *[read(p)['attempt'] for p in events]])
    require(terminal['cumulative_native_campaigns'] == count and count <= 15
            and terminal['cumulative_charged_seconds'] == (62 if terminal['global_claim_sha256'] else 42),
            'INTEGRATION_AUDIT_LEDGER')
    for number in (13, 14, 15):
        phase = run / f'phase-{number}'
        if not phase.exists():
            phases.append(dict(attempt=number, status='UNKNOWN_MISSING_PHASE'
                               if number <= count else 'NOT_PERFORMED')); continue
        if not (phase / 'receipt.json').exists():
            phases.append(dict(attempt=number, status='UNKNOWN_MISSING_RECEIPT')); continue
        receipt = read(phase / 'receipt.json')
        for name in ('plan', 'launch', 'observed'):
            require(sha(phase / (name + '.json')) == receipt[name + '_sha256'], 'INTEGRATION_RECEIPT_DRIFT')
        require(sha(phase / 'plan.json') == bundle['plans_sha256'][number - 13]
                and sha(phase / 'method/integration_worker.py') == bundle['method']['integration_worker.py'],
                'INTEGRATION_AUDIT_PLAN_OR_METHOD_DRIFT')
        if receipt['status'] == 'VERIFIED':
            summary = validate_observation(read(phase / 'observed.json'), read(phase / 'plan.json'),
                                           read(phase / 'launch.json')['parent_namespaces'])
            require(summary == receipt['summary'], 'INTEGRATION_AUDIT_SUMMARY_DRIFT')
        phases.append(dict(attempt=number, status=receipt['status'], summary=receipt['summary']))
    if terminal['adoption'] == 'ADOPT_EXISTING_CANDIDATE_FOR_ISOLATED_COMPOSED_CALLER':
        require(all(row['status'] == 'VERIFIED' for row in phases)
                and phases[0]['summary']['counterexample'] and phases[0]['summary']['normal_pass']
                and phases[1]['summary']['all_pass'] and phases[2]['summary']['all_pass']
                and terminal['original_summary'] == phases[0]['summary'], 'INTEGRATION_AUDIT_ADOPTION')
        baseline = None
        for number in (13, 14, 15):
            for stage in ('before', 'after'):
                value = read(run / f'runtime-{stage}-{number}.json')
                baseline = validate_runtime(value, baseline,
                    current=dt.datetime.fromisoformat(value['observed_at_jst']))
        ended = dt.datetime.fromisoformat(terminal['completed_at_jst'])
        started = dt.datetime.fromisoformat(claim['started_at_jst'])
        require(ended <= dt.datetime.fromisoformat(claim['deadline_jst'])
                and 0 <= (ended - started).total_seconds() <= 20
                and terminal['elapsed_window_seconds'] <= 20, 'INTEGRATION_AUDIT_DEADLINE')
    return dict(status='LOCAL_HASH_AUDIT', phases=phases, terminal=terminal,
                native_executed_by_audit=False, trusted_timestamp=False)
