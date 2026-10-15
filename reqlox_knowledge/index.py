"""Reusable index methods from the development implementation."""
from __future__ import annotations
import io
import json
import sqlite3
from pathlib import Path
import numpy as np
from .utils import sha256_bytes
from .facets import apply_facet_rules
from .hybrid import document_semantic_tokens, split_text_windows

class IndexBuildError(RuntimeError):
    pass

def claim_categories_for_window(candidate: dict, start: int, end: int) -> list[str]:
    categories = set()
    for category, claims in candidate['claims'].items():
        for claim in claims:
            location = claim['source_location']
            if location['start_offset'] < end and location['end_offset'] > start:
                categories.add(category)
                break
    return sorted(categories)

def build_chunks(corpus_root: Path, pairs: list[dict], max_characters: int, overlap_characters: int) -> list[dict]:
    chunks = []
    for pair in pairs:
        document = pair['document']
        candidate = pair['candidate']
        text_path = corpus_root / document['storage']['text_path']
        payload = text_path.read_bytes()
        if sha256_bytes(payload) != document['integrity']['text_sha256']:
            raise IndexBuildError(f'document text hash mismatch: {text_path}')
        text = payload.decode('utf-8')
        document_facets = {key: sorted(set(values)) for key, values in candidate['facets'].items()}
        for start, end, chunk_text in split_text_windows(text, max_characters, overlap_characters):
            if text[start:end] != chunk_text:
                raise IndexBuildError(f"chunk offset mismatch: {document['id']}:{start}:{end}")
            categories = claim_categories_for_window(candidate, start, end)
            chunk_facets, _facet_evidence = apply_facet_rules(chunk_text)
            chunks.append({'source_ref': document['source_ref'], 'document_ref': {'id': document['id'], 'revision_id': document['revision_id'], 'text_sha256': document['integrity']['text_sha256']}, 'title': candidate['incident']['title'], 'publisher': candidate['incident']['publisher'], 'source_type': candidate['incident']['source_type'], 'quality': document['extraction']['quality'], 'document_facets': document_facets, 'chunk_facets': chunk_facets, 'claim_categories': categories, 'start_offset': start, 'end_offset': end, 'text': chunk_text, 'chunk_sha256': sha256_bytes(chunk_text.encode('utf-8'))})
    return chunks

def numpy_payload(value: np.ndarray) -> bytes:
    output = io.BytesIO()
    np.save(output, value, allow_pickle=False)
    return output.getvalue()

def create_database(path: Path, chunks: list[dict], records: list[dict]) -> None:
    if path.exists():
        raise IndexBuildError(f'index database already exists: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("\n            PRAGMA journal_mode=DELETE;\n            PRAGMA synchronous=FULL;\n            CREATE TABLE chunks (\n                rowid INTEGER PRIMARY KEY,\n                embedding_id TEXT NOT NULL UNIQUE,\n                source_id TEXT NOT NULL,\n                source_revision_id TEXT NOT NULL,\n                canonical_url TEXT NOT NULL,\n                document_id TEXT NOT NULL,\n                document_revision_id TEXT NOT NULL,\n                title TEXT NOT NULL,\n                publisher TEXT NOT NULL,\n                source_type TEXT NOT NULL,\n                quality TEXT NOT NULL,\n                start_offset INTEGER NOT NULL,\n                end_offset INTEGER NOT NULL,\n                chunk_sha256 TEXT NOT NULL,\n                facets_json TEXT NOT NULL,\n                chunk_facets_json TEXT NOT NULL,\n                claim_categories_json TEXT NOT NULL,\n                text TEXT NOT NULL,\n                semantic_text TEXT NOT NULL\n            );\n            CREATE INDEX chunks_source_id ON chunks(source_id);\n            CREATE INDEX chunks_publisher ON chunks(publisher);\n            CREATE INDEX chunks_source_type ON chunks(source_type);\n            CREATE INDEX chunks_quality ON chunks(quality);\n            CREATE VIRTUAL TABLE chunks_fts USING fts5(\n                title, publisher, text, semantic_text,\n                content='chunks', content_rowid='rowid',\n                tokenize='unicode61 remove_diacritics 2'\n            );\n            ")
        rows = []
        for index, (chunk, record) in enumerate(zip(chunks, records), 1):
            semantic = document_semantic_tokens(chunk['chunk_facets'], chunk['claim_categories'])
            semantic.extend(('document' + value for value in document_semantic_tokens(chunk['document_facets'], [])))
            rows.append((index, record['id'], chunk['source_ref']['id'], chunk['source_ref']['revision_id'], chunk['source_ref']['canonical_url'], chunk['document_ref']['id'], chunk['document_ref']['revision_id'], chunk['title'], chunk['publisher'], chunk['source_type'], chunk['quality'], chunk['start_offset'], chunk['end_offset'], chunk['chunk_sha256'], json.dumps(chunk['document_facets'], ensure_ascii=False, sort_keys=True), json.dumps(chunk['chunk_facets'], ensure_ascii=False, sort_keys=True), json.dumps(chunk['claim_categories'], ensure_ascii=False), chunk['text'], ' '.join(semantic)))
        connection.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        connection.execute('INSERT INTO chunks_fts(rowid,title,publisher,text,semantic_text) SELECT rowid,title,publisher,text,semantic_text FROM chunks')
        connection.commit()
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        connection.close()
    temporary.replace(path)
