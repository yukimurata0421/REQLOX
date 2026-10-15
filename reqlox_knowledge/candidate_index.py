"""Reusable candidate index methods from the development implementation."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from .reference import check_seal, digest, require, seal
from .reference_audit import available_claims

def build(entries, database):
    database = Path(database).absolute()
    require('local-private-quarantine' in database.parts and (not database.exists()), 'CANDIDATE_INDEX_SCOPE')
    require(1 <= len(entries) <= 200, 'CANDIDATE_INDEX_BOUND')
    records = []
    seen = set()
    binding = []
    for packet, candidate in entries:
        check_seal(candidate)
        require(candidate['packet_sha256'] == digest(packet), 'CANDIDATE_INDEX_PACKET_BINDING')
        text = packet['review_material']['scope_text']
        scope = packet['subject']['scope']
        require(hashlib.sha256(text.encode()).hexdigest() == candidate['source_text_sha256'] == scope['text_sha256'], 'CANDIDATE_INDEX_SOURCE_HASH')
        claims = available_claims(candidate, include_uncertain=True)
        binding.append(dict(task_id=candidate['task_id'], candidate_sha256=digest(candidate), packet_sha256=digest(packet)))
        for kind in ['events', 'edges']:
            for row in claims[kind]:
                span = row['span']
                a = span['start_char'] - scope['start_char']
                b = span['end_char'] - scope['start_char']
                quote = text[a:b]
                require(0 <= a < b <= len(text) and quote == row['claim']['quote'] and (hashlib.sha256(quote.encode()).hexdigest() == span['content_hash']), 'CANDIDATE_INDEX_SPAN_DRIFT')
                key = digest(dict(task=candidate['task_id'], kind=kind, id=row['claim']['id']))
                require(key not in seen, 'CANDIDATE_INDEX_DUPLICATE')
                seen.add(key)
                claim = row['claim']
                terms = ' '.join([claim.get('primitive', ''), claim.get('description', ''), claim.get('relation', ''), quote])
                records.append((key, candidate['task_id'], kind, row['state'], terms, json.dumps(row, ensure_ascii=False)))
    descriptor = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 384)
    os.close(descriptor)
    connection = sqlite3.connect(database)
    try:
        connection.execute('CREATE VIRTUAL TABLE claims USING fts5(key UNINDEXED,task UNINDEXED,kind UNINDEXED,state UNINDEXED,text,payload UNINDEXED)')
        connection.executemany('INSERT INTO claims VALUES (?,?,?,?,?,?)', records)
        manifest = seal(dict(schema_version='reqlox.incident-candidate-index.v0.1', bindings=binding, claims=len(records), uncertain_claims=sum((r[3] == 'UNCERTAIN_LLM_CANDIDATE' for r in records)), execution_authority=False, canonicalization_authority=False, probabilities_calibrated=False, ranking_score_is_probability=False))
        connection.execute('CREATE TABLE metadata (manifest TEXT NOT NULL)')
        connection.execute('INSERT INTO metadata VALUES (?)', (json.dumps(manifest),))
        connection.commit()
    finally:
        connection.close()
    return manifest

def query(database, text, *, include_uncertain=False, limit=20):
    require(type(text) is str and 1 <= len(text) <= 1000 and (type(limit) is int) and (1 <= limit <= 100), 'CANDIDATE_QUERY_BOUND')
    terms = re.findall('[\\w]+', text, flags=re.UNICODE)
    require(terms, 'CANDIDATE_QUERY_TERMS')
    expression = ' OR '.join(('"' + t + '"' for t in dict.fromkeys(terms)))
    database = Path(database).absolute()
    require('local-private-quarantine' in database.parts, 'CANDIDATE_INDEX_SCOPE')
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        manifest = json.loads(connection.execute('SELECT manifest FROM metadata').fetchone()[0])
        check_seal(manifest)
        require(manifest['execution_authority'] is False and manifest['canonicalization_authority'] is False, 'CANDIDATE_INDEX_AUTHORITY')
        states = ['ADMITTED_LLM_CORE', 'UNCERTAIN_LLM_CANDIDATE'] if include_uncertain else ['ADMITTED_LLM_CORE']
        rows = connection.execute('SELECT key,task,kind,state,bm25(claims),payload FROM claims WHERE claims MATCH ? AND state IN (' + ','.join(('?' for _ in states)) + ') ORDER BY bm25(claims),key LIMIT ?', [expression, *states, limit]).fetchall()
        result = [dict(key=k, task_id=t, kind=kind, state=s, ranking_score=rank, claim=json.loads(payload)) for k, t, kind, s, rank, payload in rows]
        require(all((r['claim']['state'] == r['state'] for r in result)), 'CANDIDATE_INDEX_STATE_DRIFT')
        return seal(dict(results=result, include_uncertain=include_uncertain, ranking_score_is_probability=False, execution_authority=False, canonicalization_authority=False, natural_truth_certified=False))
    finally:
        connection.close()
