"""Reusable search methods from the development implementation."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import numpy as np
from .hybrid import lexical_tokens, query_semantic_tokens, query_vector

class SearchError(RuntimeError):
    pass

def latest_index_manifest(corpus_root: Path) -> Path:
    paths = sorted((corpus_root / 'manifests').glob('hybrid-index-*.json'))
    if not paths:
        raise SearchError('no hybrid search index manifest found')
    return paths[-1]

def checked_component(corpus_root: Path, component: dict) -> Path:
    path = corpus_root / component['path']
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != component['sha256']:
        raise SearchError(f'component hash mismatch: {path}')
    return path

def load_index(corpus_root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['status'] != 'COMPLETE':
        raise SearchError(f'index is not COMPLETE: {manifest_path}')
    paths = {name: checked_component(corpus_root, component) for name, component in manifest['components'].items()}
    config = json.loads(paths['model_config'].read_text(encoding='utf-8'))
    vectors = np.load(paths['vectors'], mmap_mode='r', allow_pickle=False)
    idf = np.load(paths['idf'], mmap_mode='r', allow_pickle=False)
    if list(vectors.shape) != manifest['components']['vectors']['shape']:
        raise SearchError('vector shape does not match manifest')
    if list(idf.shape) != manifest['components']['idf']['shape']:
        raise SearchError('IDF shape does not match manifest')
    if vectors.shape[1] != config['dimension'] or idf.shape[0] != config['dimension']:
        raise SearchError('model dimension mismatch')
    return {'manifest': manifest, 'config': config, 'vectors': vectors, 'idf': idf, 'database_path': paths['hybrid_database']}

def parse_facet(value: str) -> tuple[str, str]:
    if '=' not in value:
        raise argparse.ArgumentTypeError('facet must be FIELD=VALUE')
    field, item = value.split('=', 1)
    if not re.fullmatch('[a-z_]+', field) or not re.fullmatch('[a-z0-9_]+', item):
        raise argparse.ArgumentTypeError('facet field/value must use lowercase identifiers')
    return (field, item)

def row_matches(row: dict, args: argparse.Namespace) -> bool:
    if args.publisher and row['publisher'].casefold() not in {value.casefold() for value in args.publisher}:
        return False
    if args.source_type and row['source_type'] not in args.source_type:
        return False
    if args.quality and row['quality'] not in args.quality:
        return False
    for field, value in args.facet:
        if value not in row['facets'].get(field, []):
            return False
    return True

def fts_expression(query: str, config: dict) -> str:
    semantic = query_semantic_tokens(query, config['semantic_aliases'])
    terms = lexical_tokens(query) + semantic + ['document' + value for value in semantic]
    safe = []
    for term in sorted(set(terms)):
        cleaned = term.replace('"', '""').strip()
        if cleaned:
            safe.append(f'"{cleaned}"')
    return ' OR '.join(safe)

def read_rows(connection: sqlite3.Connection) -> list[dict]:
    columns = ['rowid', 'embedding_id', 'source_id', 'source_revision_id', 'canonical_url', 'document_id', 'document_revision_id', 'title', 'publisher', 'source_type', 'quality', 'start_offset', 'end_offset', 'chunk_sha256', 'facets_json', 'chunk_facets_json', 'claim_categories_json', 'text']
    values = connection.execute('SELECT rowid,embedding_id,source_id,source_revision_id,canonical_url,document_id,document_revision_id,title,publisher,source_type,quality,start_offset,end_offset,chunk_sha256,facets_json,chunk_facets_json,claim_categories_json,text FROM chunks ORDER BY rowid').fetchall()
    rows = []
    for value in values:
        row = dict(zip(columns, value))
        row['facets'] = json.loads(row.pop('facets_json'))
        row['chunk_facets'] = json.loads(row.pop('chunk_facets_json'))
        row['claim_categories'] = json.loads(row.pop('claim_categories_json'))
        rows.append(row)
    return rows

def rank_results(index: dict, query: str, args: argparse.Namespace) -> list[dict]:
    connection = sqlite3.connect(f"file:{index['database_path']}?mode=ro", uri=True)
    try:
        rows = read_rows(connection)
        eligible = {row['rowid'] for row in rows if row_matches(row, args)}
        if not eligible:
            return []
        query_embedding = query_vector(query, index['config'], index['idf'])
        vector_scores = np.asarray(index['vectors'] @ query_embedding, dtype=np.float32)
        vector_order = sorted(eligible, key=lambda rowid: (-float(vector_scores[rowid - 1]), rowid))
        vector_rank = {rowid: rank for rank, rowid in enumerate(vector_order, 1)}
        lexical_rank = {}
        lexical_score = {}
        expression = fts_expression(query, index['config'])
        if expression:
            try:
                matches = connection.execute('SELECT rowid,bm25(chunks_fts,3.0,1.5,1.0,4.0) FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY 2 LIMIT 5000', (expression,)).fetchall()
            except sqlite3.OperationalError as error:
                raise SearchError(f'FTS query failed: {error}') from error
            filtered = [(rowid, score) for rowid, score in matches if rowid in eligible]
            lexical_rank = {rowid: rank for rank, (rowid, _score) in enumerate(filtered, 1)}
            lexical_score = {rowid: float(score) for rowid, score in filtered}
        rows_by_id = {row['rowid']: row for row in rows}
        best_by_source = {}
        for rowid in eligible:
            vrank = vector_rank[rowid]
            lrank = lexical_rank.get(rowid)
            if args.mode == 'vector':
                score = float(vector_scores[rowid - 1])
            elif args.mode == 'fts':
                if lrank is None:
                    continue
                score = 1.0 / (60 + lrank)
            else:
                score = 1.0 / (60 + vrank)
                if lrank is not None:
                    score += 1.0 / (60 + lrank)
            row = rows_by_id[rowid]
            result = {**row, 'score': score, 'vector_score': float(vector_scores[rowid - 1]), 'vector_rank': vrank, 'fts_rank': lrank, 'fts_bm25': lexical_score.get(rowid)}
            current = best_by_source.get(row['source_id'])
            ordering = (score, result['vector_score'], -rowid)
            if current is None or ordering > current[0]:
                best_by_source[row['source_id']] = (ordering, result)
        return [value[1] for value in sorted(best_by_source.values(), key=lambda value: value[0], reverse=True)]
    finally:
        connection.close()

def result_json(result: dict, index_id: str) -> dict:
    return {'score': round(result['score'], 8), 'vector_score': round(result['vector_score'], 8), 'vector_rank': result['vector_rank'], 'fts_rank': result['fts_rank'], 'source_ref': {'id': result['source_id'], 'revision_id': result['source_revision_id'], 'canonical_url': result['canonical_url']}, 'document_ref': {'id': result['document_id'], 'revision_id': result['document_revision_id']}, 'title': result['title'], 'publisher': result['publisher'], 'source_type': result['source_type'], 'quality': result['quality'], 'facets': result['facets'], 'chunk_facets': result['chunk_facets'], 'claim_categories': result['claim_categories'], 'source_location': {'kind': 'TEXT_OFFSET', 'start_offset': result['start_offset'], 'end_offset': result['end_offset'], 'chunk_sha256': result['chunk_sha256']}, 'excerpt': ' '.join(result['text'].split())[:500], 'index_id': index_id}
