"""Shared offline execution policy, durable private drafts and archived records."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
from reqlox_knowledge import storage
from reqlox_knowledge.reference import canonical, require

OPERATIONS = frozenset(('history', 'open', 'save-draft', 'restore-draft'))
AREAS = frozenset(('knowledge', 'study', 'guided', 'targets', 'records'))
DATA = Path(__file__).resolve().parent / 'data'


def policy():
    from .integration_ui import summarize_public
    saved = summarize_public(storage.read(DATA / 'copied-module-integration-summary.json'))
    return dict(mode='OFFLINE_RECORDS_ONLY', native_execution_enabled=False,
        model_calls_enabled=False, source_fetch_enabled=False, reason='UI_EXECUTION_DISABLED',
        ledger_kind='ARCHIVED_SCOPE_LEDGER', scope='COPIED_TARGET_LOCAL_20261012',
        cumulative_campaigns=saved['cumulative_campaigns'], maximum_campaigns=saved['maximum_campaigns'],
        charged_seconds=saved['cumulative_charged_seconds'], maximum_seconds=saved['maximum_seconds'],
        remaining_campaigns=0, additional_execution_authorized=False)


def check_execution(path):
    require(path not in ('/api/run', '/api/targets/run', '/api/study/compare-run'), 'UI_EXECUTION_DISABLED')


class Workspace:
    def __init__(self, cache):
        self.cache = Path(cache).absolute()
        self.state = self.cache / 'workspace'

    def configuration(self, token):
        return dict(token=token, execution_policy=policy(), provider_calls=0,
                    archive=self.archive(), history=self.history())

    def archive(self):
        value = storage.read(DATA / 'archived-records.json', maximum_bytes=1024*1024)
        require(value['schema'] == 'reqlox.archived-ui-records.v1', 'UI_ARCHIVE_SCHEMA')
        for row in value['records']:
            require(row['record_sha256'] == hashlib.sha256(canonical(
                {k:v for k,v in row.items() if k != 'record_sha256'})).hexdigest(), 'UI_ARCHIVE_HASH')
        return value['records']

    def history(self):
        found = []
        bases = [('knowledge', storage.state_directory(self.cache / 'knowledge-workspace')),
                 ('study', self.cache / 'studies')]
        for area, base in bases:
            if not base.exists():
                continue
            storage.private_directory(base)
            paths = list(base.iterdir());require(len(paths) <= 1024, 'UI_HISTORY_BOUND')
            for directory in sorted(paths, key=lambda p:p.name, reverse=True):
                pattern = 'ui-[a-f0-9]{32}' if area=='knowledge' else '[a-f0-9]{32}'
                if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(pattern, directory.name):
                    continue
                summary = directory / 'summary.json'
                if summary.is_file():
                    value = storage.read(summary, maximum_bytes=1024*1024)
                    found.append(dict(id=directory.name, area=area,
                        operation=value.get('operation', 'compare-run'), status=value.get('status', 'UNKNOWN'),
                        created_at_jst=value.get('created_at_jst'), archived=False))
                elif (directory / 'artifact.json').is_file():
                    value = storage.read(directory / 'artifact.json')
                    found.append(dict(id=directory.name, area=area,
                        operation=value.get('kind', value.get('operation', 'UNKNOWN')),
                        status='LEGACY_PRIVATE_RECORD', archived=False))
                elif area=='study' and (directory / 'job-started.json').is_file():
                    found.append(dict(id=directory.name,area=area,operation='compare-run',
                        status='OUTCOME_UNKNOWN_SERVER_RESTART',archived=False))
        return found

    def dispatch(self, operation, request):
        from .study_ui import fields
        require(operation in OPERATIONS, 'UI_WORKSPACE_OPERATION')
        if operation == 'history':
            fields(request, ())
            return dict(records=self.history(), archive=self.archive(), execution_policy=policy())
        if operation == 'open':
            fields(request, ('id',), ('area',))
            require(type(request['id']) is str, 'UI_RECORD_ID')
            if request.get('area', 'archive') == 'archive':
                row = next((r for r in self.archive() if r['id']==request['id']), None)
                require(row is not None, 'UI_RECORD_UNAVAILABLE')
                return row
            area = request['area'];identity = request['id']
            require(area in ('study', 'knowledge'), 'UI_WORKSPACE_AREA')
            require(re.fullmatch('ui-[a-f0-9]{32}' if area=='knowledge' else '[a-f0-9]{32}', identity), 'UI_RECORD_ID')
            base = storage.state_directory(self.cache / 'knowledge-workspace') if area=='knowledge' else self.cache/'studies'
            path = storage.private_path(base, identity + '/summary.json')
            if path.is_file():
                summary=storage.read(path,maximum_bytes=1024*1024)
            elif area=='study':
                from .study_ui import StudyLab
                import threading
                summary=StudyLab(self.cache,threading.Lock()).job(identity)
            else:
                artifact=storage.read(storage.private_path(base,identity+'/artifact.json'))
                value=artifact.get('value',{})
                summary=dict(id=identity,operation=artifact.get('kind','UNKNOWN'),
                    status='LEGACY_PRIVATE_RECORD',provider_calls=0,
                    detail='Original private artifact retained; only available aggregate fields are restored.',
                    natural_truth_certified=False)
                for key in ('documents','chunks','questions','batches','maximum_calls'):
                    if type(value.get(key)) is int:summary[key]=value[key]
            return dict(id=identity, area=area, summary=summary,
                        provider_calls=0, new_native_campaigns=0)
        fields(request, ('area', 'data') if operation=='save-draft' else ('area',))
        require(request['area'] in AREAS, 'UI_WORKSPACE_AREA')
        path = storage.private_path(storage.private_directory(self.state), request['area'] + '.json')
        if operation == 'save-draft':
            require(type(request['data']) is dict and len(canonical(request['data'])) <= 1024*1024, 'UI_DRAFT_BOUND')
            value = dict(area=request['area'], data=request['data'],
                data_sha256=hashlib.sha256(canonical(request['data'])).hexdigest(),
                saved_at_jst=datetime.now(timezone(timedelta(hours=9))).isoformat())
            storage.save(path, value, replace=True)  # Drafts only; execution evidence is immutable.
            return dict(status='DRAFT_SAVED', saved_at_jst=value['saved_at_jst'], provider_calls=0)
        if not path.is_file():
            return dict(status='NO_DRAFT', data=None, provider_calls=0)
        value = storage.read(path, maximum_bytes=1024*1024+4096)
        require(value['area']==request['area'] and value['data_sha256']==hashlib.sha256(canonical(value['data'])).hexdigest(), 'UI_DRAFT_HASH')
        return dict(status='DRAFT_RESTORED', **value, provider_calls=0)
