"""Import supplied documents and build the existing local hybrid search index."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from . import facets, fidelity, hybrid, index, retrieval, search, storage
from .reference import digest, require, seal


def import_documents(documents, *, state_dir=None):
    require(type(documents) is list and 1 <= len(documents) <= 200, 'CORPUS_DOCUMENT_COUNT')
    require(all(type(row) is dict and type(row.get('text')) is str and
                1 <= len(row['text'].encode()) <= 512 * 1024 for row in documents), 'CORPUS_TEXT_BOUND')
    require(sum(len(row['text'].encode()) for row in documents) <= 16 * 1024 * 1024, 'CORPUS_TOTAL_BYTES')
    urls = [row.get('url') for row in documents]
    require(all(type(url) is str and 1 <= len(url) <= 2048 for url in urls), 'CORPUS_URL')
    require(len(set(urls)) == len(urls), 'CORPUS_DUPLICATE_URL')
    canonical_urls = [facets.canonicalize_url(url) for url in urls]
    require(len(set(canonical_urls)) == len(canonical_urls), 'CORPUS_DUPLICATE_CANONICAL_URL')
    now = datetime.now(timezone.utc)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    created_at = now.isoformat()
    directory = storage.new_directory(storage.state_directory(state_dir), 'corpus')
    pairs = []
    for row in documents:
        url = facets.canonicalize_url(row['url'])
        require(url.startswith('https://') and '@' not in url.split('/')[2], 'CORPUS_SOURCE_URL')
        source = dict(id='src_' + hashlib.sha256(url.encode()).hexdigest()[:20], revision_id='rev_' + stamp,
            source=dict(canonical_url=url, title=row.get('title', url), publisher=row.get('publisher', 'Supplied'),
                source_type=row.get('source_type', 'INCIDENT_REPORT'), incident_start=None, incident_end=None,
                affected_products=[], regions=[]))
        result = retrieval.local_result(source, dict(text=row['text'], kind='supplied', format='text'))
        document = retrieval.make_document(source, result, created_at, stamp)
        candidate = retrieval.make_candidate(source, document, row['text'], created_at, stamp)
        for value, name in [(document, 'retrieved-document.v1.schema.json'),
                            (candidate, 'incident-model-candidate.v1.schema.json')]:
            fidelity.validate_schema(value, Path(__file__).parent / 'data/schemas', name, name)
        storage.write_bytes(storage.private_path(directory, document['storage']['text_path']), row['text'].encode())
        pairs.append(dict(document=document, candidate=candidate))
    manifest = seal(dict(schema_version='reqlox.local-corpus.v1', status='COMPLETE', pairs=pairs,
        input_documents_sha256=digest(documents), source_documents=len(pairs), network_calls=0,
        external_model_disclosure_allowed=False, publication_allowed=False,
        natural_truth_certified=False, execution_authority=False))
    storage.save(directory / 'corpus.json', manifest)
    return dict(status='COMPLETE', corpus=str(directory / 'corpus.json'), documents=len(pairs),
                provider_calls=0, network_calls=0, source_rights_status='UNKNOWN_NOT_REVIEWED')


def build_index(corpus_path, *, dimension=768, chunk_characters=1400, chunk_overlap=200):
    require(type(dimension) is int and 64 <= dimension <= 2048, 'CORPUS_VECTOR_DIMENSION')
    require(type(chunk_characters) is int and 200 <= chunk_characters <= 4000 and
            type(chunk_overlap) is int and 0 <= chunk_overlap < chunk_characters, 'CORPUS_CHUNK_BOUND')
    corpus_path = Path(corpus_path).absolute()
    root = storage.private_directory(corpus_path.parent)
    corpus = storage.checked_record(corpus_path)
    require(corpus['schema_version'] == 'reqlox.local-corpus.v1' and corpus['status'] == 'COMPLETE', 'CORPUS_MANIFEST')
    # Validate every referenced text path before the imported chunk builder reads it.
    for pair in corpus['pairs']:
        storage.private_path(root, pair['document']['storage']['text_path'])
    chunks = index.build_chunks(root, corpus['pairs'], chunk_characters, chunk_overlap)
    require(1 <= len(chunks) <= 5000, 'CORPUS_CHUNK_COUNT')
    import numpy as np
    frequencies = np.zeros(dimension, dtype=np.float64)
    features = []
    for chunk in chunks:
        semantic = hybrid.document_semantic_tokens(chunk['chunk_facets'], chunk['claim_categories'])
        semantic.extend('document' + value for value in hybrid.document_semantic_tokens(chunk['document_facets'], []))
        current = hybrid.weighted_features(chunk['text'], chunk['title'], semantic)
        features.append(current)
        for bucket in hybrid.bucket_counts(current, dimension):
            frequencies[bucket] += 1
    idf = hybrid.idf_from_document_frequencies(frequencies, len(chunks))
    vectors = np.asarray([hybrid.vector_from_features(current, dimension, idf) for current in features], dtype=np.float32)
    config = dict(model_id=hybrid.MODEL_ID, model_version=hybrid.MODEL_VERSION,
        dimension=dimension, tokenizer_version=hybrid.TOKENIZER_VERSION, hash_algorithm=hybrid.HASH_ALGORITHM,
        semantic_aliases=hybrid.SEMANTIC_ALIASES, semantic_aliases_sha256=hybrid.aliases_sha256(),
        chunk_characters=chunk_characters, chunk_overlap=chunk_overlap,
        limitations=['Local hashing TF-IDF is a retrieval baseline, not a calibrated probability or semantic verifier.'])
    records = []
    for number, chunk in enumerate(chunks):
        records.append(dict(id='emb_' + digest([chunk['document_ref'], chunk['start_offset'], chunk['end_offset']])[:20],
                            revision_id='rev_' + digest(chunk)[:20]))
    output = storage.new_directory(root, 'index')
    for name, payload in [('model-config.json', json.dumps(config, ensure_ascii=False).encode()),
                          ('vectors.npy', index.numpy_payload(vectors)), ('idf.npy', index.numpy_payload(idf))]:
        storage.write_bytes(output / name, payload)
    index.create_database(output / 'hybrid-search.sqlite3', chunks, records)
    (output / 'hybrid-search.sqlite3').chmod(0o600)
    components = {}
    for name, filename in [('model_config', 'model-config.json'), ('vectors', 'vectors.npy'),
                            ('idf', 'idf.npy'), ('hybrid_database', 'hybrid-search.sqlite3')]:
        payload = (output / filename).read_bytes()
        components[name] = dict(path=filename, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
    components['vectors']['shape'] = list(vectors.shape)
    components['idf']['shape'] = list(idf.shape)
    manifest = seal(dict(schema_version='reqlox.local-hybrid-index.v1', id=output.name, status='COMPLETE',
        corpus_sha256=corpus['record_sha256'], components=components, chunks=len(chunks),
        documents=corpus['source_documents'], dimension=dimension, provider_calls=0,
        ranking_score_is_probability=False, external_model_disclosure_allowed=False))
    storage.save(output / 'index.json', manifest)
    return dict(status='COMPLETE', index=str(output / 'index.json'), chunks=len(chunks),
                documents=corpus['source_documents'], provider_calls=0)


def search_index(index_path, query, *, mode='hybrid', limit=10, publisher=(), source_type=(), quality=(), facet=()):
    require(type(query) is str and 1 <= len(query) <= 1000, 'CORPUS_QUERY_BOUND')
    require(mode in ('hybrid', 'vector', 'fts') and type(limit) is int and 1 <= limit <= 100, 'CORPUS_QUERY_OPTIONS')
    index_path = Path(index_path).absolute()
    storage.private_directory(index_path.parent)
    manifest = storage.checked_record(index_path)
    require(manifest['schema_version'] == 'reqlox.local-hybrid-index.v1', 'CORPUS_INDEX_CONTRACT')
    for component in manifest['components'].values():
        path = storage.private_path(index_path.parent, component['path'])
        require(path.stat().st_size <= 64 * 1024 * 1024, 'CORPUS_INDEX_COMPONENT_BOUND')
    loaded = search.load_index(index_path.parent, index_path)
    args = SimpleNamespace(mode=mode, publisher=list(publisher), source_type=list(source_type),
                           quality=list(quality), facet=list(facet))
    rows = search.rank_results(loaded, query, args)[:limit]
    return seal(dict(results=[search.result_json(row, manifest['id']) for row in rows], mode=mode,
        ranking_score_is_probability=False, probabilities_calibrated=False, provider_calls=0,
        natural_truth_certified=False, execution_authority=False))
