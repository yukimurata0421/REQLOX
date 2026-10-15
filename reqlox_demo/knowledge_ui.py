"""Local browser adapters for supplied documents and native IR preparation."""
import json
from pathlib import Path
import re

from .study_ui import fields

OPERATIONS = frozenset(('import', 'index', 'search', 'excerpt', 'get-excerpt', 'ir-prepare', 'ir-route', 'score'))


class KnowledgeLab:
    def __init__(self, cache):
        self.state = Path(cache).absolute() / 'knowledge-workspace'
        self.created = 0

    def configuration(self, token):
        import importlib.util
        path = Path(__file__).parent / 'data/knowledge-example.json'
        return dict(token=token, example=json.loads(path.read_text()), provider_calls=0,
                    dependencies_available=all(importlib.util.find_spec(name) for name in ('numpy','requests','bs4')),
                    maximum_documents=32, external_disclosure_allowed=False,
                    runtime_paths_returned=False, probabilities_calibrated=False)

    def _save(self, kind, value, **summary):
        from reqlox_knowledge import storage, reference
        reference.require(self.created < 64, 'UI_SESSION_ARTIFACT_BOUND')
        directory = storage.new_directory(storage.state_directory(self.state), 'ui')
        storage.save(directory / 'artifact.json', dict(kind=kind, value=value))
        self.created += 1
        from datetime import datetime, timezone, timedelta
        public = dict(id=directory.name, operation=kind, provider_calls=0,
                    created_at_jst=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                    natural_truth_certified=False, probabilities_calibrated=False, **summary)
        storage.save(directory / 'summary.json', public)
        return public

    def _load(self, identity, kind):
        from reqlox_knowledge import storage, reference
        reference.require(type(identity) is str and re.fullmatch('ui-[a-f0-9]{32}', identity), 'UI_ARTIFACT_ID')
        record = storage.read(storage.state_directory(self.state) / identity / 'artifact.json')
        reference.require(record['kind'] == kind, 'UI_ARTIFACT_KIND')
        return record['value']

    def dispatch(self, operation, request):
        from reqlox import knowledge
        from reqlox_knowledge import storage, reference
        reference.require(operation in OPERATIONS, 'UI_OPERATION')
        if operation == 'import':
            fields(request, ('documents',))
            reference.require(type(request['documents']) is list and 1 <= len(request['documents']) <= 32,
                              'UI_DOCUMENT_COUNT')
            value = knowledge.import_documents(request['documents'], state_dir=self.state)
            return self._save('import', value, status=value['status'], documents=value['documents'])
        if operation == 'index':
            fields(request, ('corpus_id',))
            value = knowledge.build_index(self._load(request['corpus_id'], 'import')['corpus'])
            value['corpus_id'] = request['corpus_id']
            return self._save('index', value, status=value['status'], chunks=value['chunks'], documents=value['documents'])
        if operation == 'excerpt':
            fields(request, ('index_id', 'source_ref', 'document_ref', 'source_location'))
            return self.excerpt(request)
        if operation == 'get-excerpt':
            fields(request, ('id',))
            value = self._load(request['id'], 'excerpt')
            verified = self.excerpt({key:value[key] for key in ('index_id','source_ref','document_ref','source_location')}, save=False)
            return dict(id=request['id'], operation='excerpt', provider_calls=0, natural_truth_certified=False, **verified)
        if operation == 'search':
            fields(request, ('index_id', 'query'), ('mode', 'limit'))
            value = knowledge.search(self._load(request['index_id'], 'index')['index'], request['query'],
                mode=request.get('mode', 'hybrid'), limit=request.get('limit', 10))
            return dict(operation=operation, results=value['results'], provider_calls=0,
                        local_quotations_included=True, ranking_score_is_probability=False)
        if operation == 'ir-prepare':
            fields(request, ('candidate', 'source_texts'))
            value = knowledge.prepare_ir(request['candidate'], request['source_texts'], state_dir=self.state)
            return self._save(operation, value, status=value['status'], batches=value['batches'],
                              questions=value['questions'], maximum_calls=value['maximum_calls'])
        if operation == 'ir-route':
            fields(request, ('plan_id', 'judgments'))
            plan = storage.checked_record(self._load(request['plan_id'], 'ir-prepare')['plan'])
            value = knowledge.route_ir(plan, request['judgments'])
            return self._save(operation, value, status='COMPLETE',
                fidelity_summary=value['fidelity_summary'],
                atomic_projection_present=value['atomic_projection'] is not None,
                structural_comparator_assessment=value['structural_comparator_assessment'],
                all_original_candidates_preserved=True, same_incident_boundary_review_required=True)
        fields(request, ('rows', 'categories'))
        value = knowledge.partial_scores(request['rows'], request['categories'])
        return self._save(operation, value, status='COMPLETE',
            **{key:value[key] for key in ('attempted_rows','scored_rows','unknown_labels','unknown_vectors',
                'full_denominator','group_equal_weight','conditional_observed_brier','known_infinite_log_loss_rows')})

    def excerpt(self, request, *, save=True):
        """Bind an exact indexed source span; browser-supplied quote text is rejected."""
        import hashlib
        import sqlite3
        from reqlox_knowledge import storage, reference, search
        indexed = self._load(request['index_id'], 'index')
        reference.require('corpus_id' in indexed, 'UI_LEGACY_SOURCE_BINDING_UNAVAILABLE')
        corpus_path = self._load(indexed['corpus_id'], 'import')['corpus']
        corpus = storage.checked_record(corpus_path)
        manifest = storage.checked_record(indexed['index'])
        reference.require(manifest['corpus_sha256']==corpus['record_sha256'], 'UI_SOURCE_INDEX_DRIFT')
        source=request['source_ref'];document=request['document_ref'];location=request['source_location']
        reference.require(type(source) is dict and type(document) is dict and type(location) is dict, 'UI_SOURCE_REFERENCE')
        pair = next((p for p in corpus['pairs'] if p['document']['source_ref']==source and
            p['document']['id']==document.get('id') and p['document']['revision_id']==document.get('revision_id')), None)
        reference.require(pair is not None, 'UI_SOURCE_REFERENCE')
        doc=pair['document'];original=storage.private_path(Path(corpus_path).parent,doc['storage']['text_path']).read_bytes().decode('utf-8')
        digest=lambda text:hashlib.sha256(text.encode()).hexdigest()
        reference.require(digest(original)==doc['integrity']['text_sha256'], 'UI_SOURCE_TEXT_DRIFT')
        start,end=location.get('start_offset'),location.get('end_offset')
        reference.require(location.get('kind')=='TEXT_OFFSET' and type(start) is int and type(end) is int
                          and 0<=start<end<=len(original) and end-start<=4000, 'UI_SOURCE_SPAN')
        text=original[start:end]
        reference.require(digest(text)==location.get('chunk_sha256'), 'UI_SOURCE_QUOTE_DRIFT')
        loaded=search.load_index(Path(indexed['index']).parent,Path(indexed['index']))
        with sqlite3.connect(loaded['database_path'].as_uri()+'?mode=ro',uri=True) as connection:
            found=connection.execute('SELECT 1 FROM chunks WHERE source_id=? AND document_id=? AND start_offset=? AND end_offset=? AND chunk_sha256=?',
                (source['id'],document['id'],start,end,digest(text))).fetchone()
        reference.require(found is not None, 'UI_SOURCE_SPAN_NOT_INDEXED')
        value=dict(title=pair['candidate']['incident']['title'],text=text,source_ref=source,
            document_ref=dict(document,text_sha256=digest(original)),source_location=location,
            index_id=request['index_id'],source_binding_verified=True)
        return self._save('excerpt',value,status='SOURCE_BOUND',**value) if save else value
