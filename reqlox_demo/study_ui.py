"""Local UI adapters for the existing preparation and evaluation interfaces."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import threading

from reqlox import studies

MAXIMUM_REQUEST_BYTES = 8 * 1024 * 1024
MAXIMUM_WHEEL_BYTES = 4 * 1024 * 1024
OPERATIONS = frozenset(('prepare', 'capsule', 'freeze', 'compare-run', 'score', 'register', 'review'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'INPUT_FIELDS')


def text_map(value, *, maximum_bytes=512 * 1024):
    require(type(value) is dict and len(value) <= 128, 'TEXT_MAP_BOUND')
    require(all(type(k) is str and 0 < len(k) <= 200 and type(v) is str
                and len(v.encode()) <= 262144 for k, v in value.items()), 'TEXT_MEMBER_BOUND')
    require(sum(len(v.encode()) for v in value.values()) <= maximum_bytes, 'TEXT_BYTES_BOUND')
    return value


def dataset(value):
    fields(value, ('event', 'predictor_revision', 'rows'), ('natural_oss',))
    require(type(value['rows']) is list and 1 <= len(value['rows']) <= 256, 'UI_DATASET_ROWS_BOUND')
    return value


def source_map(value):
    text_map(value)
    require(all(not PurePosixPath(k).is_absolute() and '..' not in PurePosixPath(k).parts
                and str(PurePosixPath(k)) == k and '\\' not in k and k.endswith('.py') for k in value),
            'UI_SOURCE_MEMBER_PATH')
    return value


def scores(value):
    """Expose aggregate diagnostics without row identities or group history."""
    keys = ('total_rows', 'valid_forecasts', 'scored_rows', 'unknown_rows', 'truth_counts',
            'scalar_binary_brier', 'binary_log_loss', 'log_loss_infinite', 'empirical_ece',
            'reliability_bins', 'thresholds')
    return {k: value[k] for k in keys}


def public_error(exc):
    text = str(exc)
    return text if re.fullmatch('[A-Z][A-Z0-9_]{1,100}', text) else 'INPUT_OR_EXECUTION_NOT_VERIFIED'


class StudyLab:
    def __init__(self, cache, execution_lock, *, allow_native=False):
        self.cache = Path(cache).absolute() / 'studies'
        self.execution_lock = execution_lock
        self.allow_native = allow_native is True
        self.lock = threading.Lock()
        self.jobs = {}
        self.started = set()
        self.created = 0

    def configuration(self, token):
        example = json.loads((Path(__file__).parent / 'data/study-example.json').read_text())
        return dict(token=token, example=example, settings=studies.settings(),
                    maximum_wheel_bytes=MAXIMUM_WHEEL_BYTES, maximum_dataset_rows=256,
                    provider_calls=0, detailed_records_public=False, native_execution_enabled=self.allow_native)

    def _new(self):
        from reqlox_knowledge import storage
        require(self.created < 64, 'UI_SESSION_ARTIFACT_BOUND')
        storage.private_directory(self.cache)
        directory = self.cache / secrets.token_hex(16)
        directory.mkdir(mode=0o700)
        self.created += 1
        return directory

    def _load(self, identity, kind):
        from reqlox_knowledge import storage
        require(type(identity) is str and re.fullmatch('[a-f0-9]{32}', identity), 'UI_ARTIFACT_ID')
        path = storage.private_path(self.cache, identity + '/artifact.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAXIMUM_REQUEST_BYTES,
                'UI_ARTIFACT_UNAVAILABLE')
        value = storage.read(path, maximum_bytes=MAXIMUM_REQUEST_BYTES)
        require(value['operation'] == kind, 'UI_ARTIFACT_KIND')
        return value['value']

    def _save(self, directory, operation, value, summary):
        from reqlox_knowledge import storage
        storage.save(directory / 'artifact.json', dict(operation=operation, value=value))
        public = dict(schema_version='reqlox.public-study-ui-summary.v1', operation=operation,
                      id=directory.name, provider_calls=0, raw_text_or_code_included=False,
                      independent_generalization_certified=False, natural_source_added_value_certified=False,
                      probability_calibration_certified=False, **summary)
        storage.save(directory / 'summary.json', public)
        return public

    def dispatch(self, operation, request):
        """Dispatch static operations while the server's shared run lock is held."""
        require(operation in OPERATIONS - {'compare-run'}, 'UI_OPERATION')
        if operation == 'prepare':
            fields(request, ('project', 'documents', 'known_projects'), ('sources', 'capsule_id'))
            require(('sources' in request) != ('capsule_id' in request), 'UI_PREPARATION_INPUT')
            require(type(request['project']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', request['project']),
                    'UI_PROJECT_NAME')
            require(type(request['known_projects']) is list and len(request['known_projects']) <= 256
                    and all(type(v) is str and 0 < len(v) <= 100 for v in request['known_projects']), 'UI_HISTORY_BOUND')
            capsule = self._load(request['capsule_id'], 'capsule') if 'capsule_id' in request else None
            sources = capsule['sources'] if capsule else source_map(request['sources'])
            prepared = studies.prepare_context(sources, text_map(request['documents']), project=request['project'],
                known_projects=request['known_projects'], capsule=capsule)
            require(len(prepared['recipes']) <= 128, 'UI_RECIPE_COUNT_BOUND')
            summary = dict(status=prepared['status'], project=prepared['project'], source_files=len(sources),
                recipes=[dict(index=i, module=r['binding']['module'], symbol=r['binding']['symbol'])
                         for i, r in enumerate(prepared['recipes'])],
                reasons=sorted({v['reason'] for v in prepared['holds']})[:12],
                target_code_imported=False, declared_history_only=True, all_chat_unused_verified=False)
            value = prepared
        elif operation == 'capsule':
            fields(request, ('project', 'wheels'))
            require(type(request['wheels']) is list and 1 <= len(request['wheels']) <= 8, 'UI_WHEEL_COUNT')
            decoded = []
            total = 0
            for item in request['wheels']:
                fields(item, ('name', 'sha256', 'base64'))
                require(type(item['name']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.+-]*\\.whl', item['name']),
                        'UI_WHEEL_FILENAME')
                require(type(item['base64']) is str, 'UI_WHEEL_ENCODING')
                raw = base64.b64decode(item['base64'], validate=True)
                total += len(raw)
                require(total <= MAXIMUM_WHEEL_BYTES, 'UI_WHEEL_BYTES_BOUND')
                require(hashlib.sha256(raw).hexdigest() == item['sha256'], 'UI_WHEEL_HASH_DRIFT')
                require(item['name'] not in {n for n, _ in decoded}, 'UI_DUPLICATE_WHEEL')
                decoded.append((item['name'], raw))
            directory = self._new()
            specifications = []
            for name, raw in decoded:
                path = directory / name
                with path.open('xb') as stream:
                    __import__('os').fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                specifications.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
            value = studies.inspect_wheels(specifications, target_project=request['project'])
            return self._save(directory, operation, value, dict(status=value['status'],
                distributions=len(value['distributions']), reasons=sorted({v['reason'] for v in value['holds']})[:12],
                target_code_imported=False, rights_approval_inferred=False))
        elif operation == 'freeze':
            fields(request, ('preparation_id', 'source', 'recipe_index', 'budget'))
            fields(request['source'], ('documents', 'url', 'source_type'))
            require(type(request['source']['url']) is str and len(request['source']['url']) <= 1000, 'UI_SOURCE_URL_BOUND')
            source = studies.supplied_source(text_map(request['source']['documents']),
                url=request['source']['url'], source_type=request['source']['source_type'])
            value = studies.freeze_comparison(self._load(request['preparation_id'], 'prepare'), source,
                recipe_index=request['recipe_index'], budget=request['budget'])
            summary = dict(status='FROZEN', discovery_budget_per_arm=request['budget'],
                common_confirmation_envelope=True, source_blind_baseline=True,
                target_code_executed=False, external_retrieval_verified=False)
        elif operation == 'score':
            fields(request, ('dataset',))
            data = dataset(request['dataset'])
            value = studies.score_forecasts(data['rows'], event=data['event'], predictor_revision=data['predictor_revision'])
            summary = dict(status='DIAGNOSTIC', scores=scores(value), serving=studies.settings()['serving'])
        elif operation == 'register':
            fields(request, ('training', 'forecasts'))
            training, forecasts = dataset(request['training']), dataset(request['forecasts'])
            require((training['event'], training['predictor_revision']) ==
                    (forecasts['event'], forecasts['predictor_revision']), 'UI_CONFIRMATION_EVENT_DRIFT')
            model = studies.fit_calibration(training['rows'], event=training['event'],
                predictor_revision=training['predictor_revision'])
            registration = studies.register_confirmation(model, training['rows'], forecasts['rows'])
            value = dict(training=training, registration=registration)
            summary = dict(status='REGISTERED_DIAGNOSTIC', training_rows=len(training['rows']),
                confirmation_rows=len(forecasts['rows']), candidate_activated=False,
                serving=studies.settings()['serving'], timestamp_authority='LOCAL_CLOCK_NOT_TRUSTED_TIME')
        else:
            fields(request, ('registration_id', 'confirmation'))
            saved = self._load(request['registration_id'], 'register')
            confirmation = dataset(request['confirmation'])
            require((confirmation['event'], confirmation['predictor_revision']) ==
                    (saved['training']['event'], saved['training']['predictor_revision']), 'UI_CONFIRMATION_EVENT_DRIFT')
            value = studies.review_calibration(saved['registration'], saved['training']['rows'], confirmation['rows'])
            summary = dict(status=value['status'], reasons=value['reasons'], engineering_gates=value['engineering_gates'],
                raw=scores(value['raw']), candidate=scores(value['candidate']), serving=value['serving'],
                candidate_activated=False, diagnostic_only=True)
        return self._save(self._new(), operation, value, summary)

    def start(self, request):
        """Acquire the shared lock before creating one immutable bounded job."""
        require(self.allow_native, 'UI_NATIVE_EXECUTION_DISABLED')
        fields(request, ('freeze_id', 'seconds', 'maximum_campaigns', 'execute_isolated_code'))
        require(request['execute_isolated_code'] is True, 'UI_NATIVE_EXECUTION_NOT_SELECTED')
        require(type(request['seconds']) is int and 15 <= request['seconds'] <= 180
                and type(request['maximum_campaigns']) is int and 0 <= request['maximum_campaigns'] <= 32,
                'UI_COMPARISON_LIMITS')
        with self.lock:
            require(request['freeze_id'] not in self.started, 'UI_FROZEN_COMPARISON_ALREADY_STARTED')
            frozen = self._load(request['freeze_id'], 'freeze')
            from reqlox_knowledge import storage
            reservation = storage.private_path(self.cache, request['freeze_id'] + '/ui-started.json')
            require(not reservation.exists(), 'UI_FROZEN_COMPARISON_ALREADY_STARTED')
            require(self.execution_lock.acquire(blocking=False), 'UI_ANOTHER_RUN_ACTIVE')
            try:
                directory = self._new()
                summary = dict(id=directory.name, operation='compare-run', status='RUNNING',
                    native_campaigns=None, provider_calls=0, raw_text_or_code_included=False,
                    independent_generalization_certified=False, natural_source_added_value_certified=False,
                    probability_calibration_certified=False)
                storage.save(reservation, dict(job_id=directory.name, automatic_retry=False))
                storage.save(directory / 'job-started.json', summary)
                self.jobs[directory.name] = summary
                self.started.add(request['freeze_id'])
                threading.Thread(target=self._run, args=(directory, frozen, request), daemon=True).start()
            except BaseException:
                self.execution_lock.release()
                raise
        return deepcopy(summary)

    def _run(self, directory, frozen, request):
        from reqlox_knowledge import storage
        try:
            result = studies.run_comparison(frozen, directory / 'execution', seconds=request['seconds'],
                                            maximum_campaigns=request['maximum_campaigns'])
            summary = dict(status=result.get('status', 'COMPLETE'), native_campaigns=result['native_campaigns'],
                comparison_complete=result.get('comparison_complete', False),
                original_normal_context_verified=result.get('original_normal_context_verified', False),
                source_added_adoptions=result.get('source_added_adoptions'),
                candidate_adopted=result.get('private_candidate_adopted', {}),
                discovered_faults={k: len(v) for k,v in result.get('discovery_faults', {}).items()},
                unknown_conditions={k: len(v) for k,v in result.get('unknown_conditions', {}).items()},
                original_implementation_mutated=result.get('original_implementation_mutated', False))
        except Exception as exc:
            summary = dict(status='STOPPED', reason=public_error(exc),
                native_campaigns=len(list((directory/'execution').glob('*/launch.json'))),
                comparison_complete=False, source_added_adoptions=None, automatic_retry=False)
            try:
                storage.save(directory / 'ui-terminal.json', dict(status='STOPPED', error=str(exc), automatic_retry=False))
            except OSError:
                summary['terminal_persisted'] = False
        finally:
            self.execution_lock.release()
        with self.lock:
            self.jobs[directory.name].update(summary)
            try:
                storage.save(directory / 'summary.json', self.jobs[directory.name])
            except OSError:
                self.jobs[directory.name].update(status='STOPPED', reason='UI_SUMMARY_PERSISTENCE_FAILED')

    def job(self, identity):
        require(type(identity) is str and re.fullmatch('[a-f0-9]{32}', identity), 'UI_JOB_ID')
        with self.lock:
            if identity not in self.jobs:
                from reqlox_knowledge import storage
                path = storage.private_path(self.cache, identity + '/summary.json')
                if path.is_file():
                    self.jobs[identity] = storage.read(path, maximum_bytes=MAXIMUM_REQUEST_BYTES)
                else:
                    started = storage.private_path(self.cache, identity + '/job-started.json')
                    require(started.is_file(), 'UI_JOB_UNAVAILABLE')
                    self.jobs[identity] = dict(storage.read(started), status='OUTCOME_UNKNOWN_SERVER_RESTART',
                                               automatic_retry=False, native_campaigns=None)
            return deepcopy(self.jobs[identity])
