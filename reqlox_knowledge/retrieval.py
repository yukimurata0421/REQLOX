"""Reusable retrieval methods from the development implementation."""
from __future__ import annotations
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
import requests
from bs4 import BeautifulSoup
from .facets import apply_facet_rules, content_quality
from .utils import canonical_json_bytes, iso_utc, sha256_bytes
CONTRACT_VERSION = '1.0.0'
TOOL_VERSION = 'incident-candidate.rules.v1'
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
BLOCKED_TAGS = ('script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'svg', 'noscript')
CLAIM_RULES = {'symptoms': re.compile('\\b(unavailable|outage|degrad(?:ed|ation)|errors?|latency|timed? out|fail(?:ed|ure))\\b', re.I), 'impact': re.compile('\\b(customers?|users?|impact(?:ed)?|requests?|traffic|availability|data loss)\\b', re.I), 'timeline': re.compile('\\b(20\\d{2}[-/]\\d{1,2}[-/]\\d{1,2}|\\d{1,2}:\\d{2}\\s*(?:UTC|GMT|PST|PDT|EST|EDT)?|January|February|March|April|May|June|July|August|September|October|November|December)\\b', re.I), 'reported_causes': re.compile('\\b(root cause|caused by|due to|triggered by|resulted from|originated from)\\b', re.I), 'contributing_factors': re.compile('\\b(contribut(?:ed|ing|ory)|exacerbat(?:ed|ing)|amplif(?:ied|ication)|because|compounded)\\b', re.I), 'mitigations': re.compile('\\b(mitigat(?:ed|ion)|roll(?:ed)? back|restart(?:ed)?|failover|restore(?:d)?|resolved|recovered|disabled|drain(?:ed)?)\\b', re.I), 'follow_ups': re.compile('\\b(action items?|follow[- ]?ups?|we will|prevent recurrence|remediat(?:e|ion)|improv(?:e|ement)|corrective actions?)\\b', re.I)}

class RetrievalError(RuntimeError):
    pass

def validate_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise RetrievalError(f'refusing non-public HTTPS URL: {url}')
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as error:
        raise RetrievalError(f'DNS resolution failed for {parsed.hostname}: {error}') from error
    if not addresses:
        raise RetrievalError(f'DNS resolution returned no address for {parsed.hostname}')
    for address in addresses:
        parsed_address = ipaddress.ip_address(address)
        if not parsed_address.is_global:
            raise RetrievalError(f'refusing non-global address for {parsed.hostname}')

def read_bounded_response(response: requests.Response, max_response_bytes: int) -> bytes:
    declared = response.headers.get('Content-Length')
    if declared:
        try:
            if int(declared) > max_response_bytes:
                raise RetrievalError(f'response exceeds limit: {declared} > {max_response_bytes}')
        except ValueError:
            pass
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_response_bytes:
            raise RetrievalError(f'response exceeded limit while reading: {size} > {max_response_bytes}')
        chunks.append(chunk)
    return b''.join(chunks)

def fetch_public_document(session: requests.Session, url: str, timeout: float, max_response_bytes: int) -> tuple[bytes, dict]:
    current = url
    for _ in range(6):
        validate_public_https(current)
        retrieved_at = iso_utc(datetime.now(timezone.utc))
        with session.get(current, timeout=(5, timeout), allow_redirects=False, stream=True) as response:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get('Location')
                if not location:
                    raise RetrievalError(f'redirect without Location: HTTP {response.status_code}')
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            body = read_bounded_response(response, max_response_bytes)
            return (body, {'status': 'SUCCESS', 'method': 'HTTP_GET', 'retrieved_at': retrieved_at, 'final_url': response.url, 'http_status': response.status_code, 'content_type': response.headers.get('Content-Type'), 'response_bytes': len(body), 'response_sha256': sha256_bytes(body)})
    raise RetrievalError('redirect limit exceeded')

def decode_bytes(body: bytes, content_type: str | None) -> str:
    match = re.search('charset=([^;\\s]+)', content_type or '', re.I)
    encoding = match.group(1).strip('"\'') if match else 'utf-8'
    return body.decode(encoding, errors='replace')

def extract_text(body: bytes, content_type: str | None) -> tuple[str, str]:
    lowered = (content_type or '').lower()
    if 'pdf' in lowered or body.startswith(b'%PDF-'):
        raise RetrievalError('PDF_TEXT_EXTRACTOR_UNAVAILABLE')
    decoded = decode_bytes(body, content_type)
    if 'json' in lowered or decoded.lstrip().startswith(('{', '[')):
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise RetrievalError(f'invalid JSON document: {error}') from error
        lines = []

        def collect_strings(value: object, path: str='root') -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    collect_strings(child, f'{path}.{key}')
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    collect_strings(child, f'{path}[{index}]')
            elif isinstance(value, str) and value.strip():
                cleaned_value = BeautifulSoup(value, 'html.parser').get_text(' ') if '<' in value and '>' in value else value
                cleaned = ' '.join(cleaned_value.split())
                if cleaned:
                    lines.append(f'{path}: {cleaned}')
        collect_strings(payload)
        text = '\n'.join(lines)
        if not text:
            raise RetrievalError('empty structured JSON text representation')
        return (text, 'structured-json-text.v1')
    if 'html' not in lowered and (not re.search('<html\\b|<!doctype\\s+html', decoded[:1000], re.I)):
        text = '\n'.join((line.strip() for line in decoded.splitlines() if line.strip()))
        if not text:
            raise RetrievalError('empty text representation')
        return (text, 'plain-text.v1')
    soup = BeautifulSoup(decoded, 'html.parser')
    for tag in soup.find_all(BLOCKED_TAGS):
        tag.decompose()
    content_candidates = soup.select("article, main, [role='main']")
    target = max(content_candidates, key=lambda node: len(node.get_text(' ', strip=True)), default=soup.body or soup)
    lines = []
    for raw_line in target.get_text('\n').splitlines():
        line = ' '.join(raw_line.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    text = '\n'.join(lines)
    if not text:
        raise RetrievalError('empty visible-text representation')
    return (text, 'html-visible-text.v1')

def quality_for(text: str, local_kind: str | None) -> tuple[str, list[str]]:
    quality, flags = content_quality(text, local_kind or 'scraped_text')
    mapping = {'usable': 'USABLE', 'short': 'SHORT', 'blocked_or_noise': 'BLOCKED_OR_NOISE'}
    if quality not in mapping:
        raise RetrievalError(f'unsupported extracted text quality: {quality}')
    return (mapping[quality], flags)

def sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for match in re.finditer('[^.!?\\n]+(?:[.!?]+|$)', text):
        raw = match.group(0)
        stripped = raw.strip()
        if len(stripped) < 30 or len(stripped) > 800:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        end = start + len(stripped)
        spans.append((start, end, stripped))
    return spans

def extract_claims(text: str, text_sha256: str) -> dict[str, list[dict]]:
    spans = sentence_spans(text)
    claims = {category: [] for category in CLAIM_RULES}
    for category, pattern in CLAIM_RULES.items():
        seen = set()
        for start, end, sentence in spans:
            match = pattern.search(sentence)
            if not match or sentence in seen:
                continue
            seen.add(sentence)
            claim_hash = sha256_bytes(f'{category}\n{start}\n{end}\n{sentence}'.encode('utf-8'))[:20]
            claims[category].append({'id': f'claim_{claim_hash}', 'text': sentence, 'provenance_kind': 'SOURCE_REPORTED_UNVERIFIED', 'source_location': {'kind': 'TEXT_OFFSET', 'text_sha256': text_sha256, 'start_offset': start, 'end_offset': end}, 'extraction_rule': f'{TOOL_VERSION}:{category}:{match.group(0).lower()}'})
            if len(claims[category]) == 5:
                break
    return claims

def make_document(source_record: dict, result: dict, created_at: str, stamp: str) -> dict:
    text = result['text']
    text_bytes = text.encode('utf-8')
    text_sha = sha256_bytes(text_bytes)
    document_id = 'doc_' + sha256_bytes(source_record['id'].encode('utf-8'))[:20]
    text_path = f'quarantine/documents/{document_id}/text.{text_sha}.txt'
    quality, quality_flags = quality_for(text, result.get('local_kind'))
    limitations = ['Source rights are unresolved; this local copy is quarantined from model disclosure and publication.']
    limitations.extend(quality_flags)
    base = {'id': document_id, 'contract_type': 'RetrievedDocument', 'contract_version': CONTRACT_VERSION, 'created_at': created_at, 'source_ref': {'id': source_record['id'], 'revision_id': source_record['revision_id'], 'canonical_url': source_record['source']['canonical_url']}, 'acquisition': result['acquisition'], 'extraction': {'method': result['extraction_method'], 'quality': quality, 'text_characters': len(text), 'text_bytes': len(text_bytes), 'text_lines': len(text.splitlines())}, 'storage': {'classification': 'LOCAL_PRIVATE_QUARANTINE', 'text_path': text_path, 'raw_response_retained': False, 'rights_status': 'UNKNOWN_NOT_REVIEWED', 'external_model_disclosure_allowed': False, 'publication_allowed': False, 'human_review_required': True}, 'integrity': {'text_sha256': text_sha}, 'limitations': sorted(set(limitations))}
    if result.get('source_text_ref'):
        base['input_text_ref'] = result['source_text_ref']
    revision_hash = sha256_bytes(canonical_json_bytes(base))[:12]
    return {**base, 'revision_id': f'rev_{stamp}_{revision_hash}'}

def make_candidate(source_record: dict, document: dict, text: str, created_at: str, stamp: str) -> dict:
    source = source_record['source']
    claims = extract_claims(text, document['integrity']['text_sha256'])
    facets, _evidence = apply_facet_rules(text)
    limitations = ['All extracted claims are unreviewed pattern matches, not verified facts.', 'One source-level candidate may contain multiple incidents and requires human splitting.', 'No FailureModel, target mapping, or experiment authorization is produced.', 'Source rights remain unresolved; external model disclosure and publication are blocked.']
    if document['extraction']['quality'] != 'USABLE':
        limitations.append('Extracted document quality is not USABLE and requires retrieval review.')
    candidate_id = 'inc_candidate_' + sha256_bytes(source_record['id'].encode('utf-8'))[:20]
    base = {'id': candidate_id, 'contract_type': 'IncidentModelCandidate', 'contract_version': CONTRACT_VERSION, 'created_at': created_at, 'lifecycle_status': 'REVIEW_REQUIRED', 'source_ref': document['source_ref'], 'document_ref': {'id': document['id'], 'revision_id': document['revision_id'], 'text_sha256': document['integrity']['text_sha256']}, 'incident': {'title': source['title'], 'publisher': source['publisher'], 'source_type': source['source_type'], 'incident_start': source['incident_start'], 'incident_end': source['incident_end'], 'affected_products': source['affected_products'], 'regions': source['regions']}, 'claims': claims, 'facets': facets, 'extraction': {'method': 'DETERMINISTIC_RULES', 'tool_version': TOOL_VERSION, 'human_review_state': 'NOT_REVIEWED', 'claim_count': sum((len(values) for values in claims.values()))}, 'processing_boundary': {'scope': 'LOCAL_PRIVATE_QUARANTINE_ONLY', 'source_rights_status': 'UNKNOWN_NOT_REVIEWED', 'external_model_disclosure_allowed': False, 'publication_allowed': False}, 'limitations': limitations}
    revision_hash = sha256_bytes(canonical_json_bytes(base))[:12]
    return {**base, 'revision_id': f'rev_{stamp}_{revision_hash}'}

def local_result(source_record: dict, variant: dict) -> dict:
    text = variant['text']
    result = {'source_record': source_record, 'text': text, 'local_kind': variant['kind'], 'extraction_method': 'existing-text.v1', 'acquisition': {'status': 'SUCCESS', 'method': 'LOCAL_EXISTING_COPY', 'retrieved_at': None, 'final_url': source_record['source']['canonical_url'], 'http_status': None, 'content_type': 'text/markdown' if variant['format'] == 'markdown' else 'text/plain', 'response_bytes': None, 'response_sha256': None}}
    if variant.get('source_text_ref'):
        result['source_text_ref'] = variant['source_text_ref']
    return result
