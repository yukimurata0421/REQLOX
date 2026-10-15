"""Bounded explicit acquisition through the existing public-document reader."""
from datetime import datetime, timezone
import time
from urllib.parse import urlsplit

from . import corpus, reference, retrieval, storage


def fetch(urls, *, state_dir=None, execute=False, maximum_response_bytes=512*1024,
          timeout_seconds=10, session=None):
    reference.require(type(urls) is list and 1 <= len(urls) <= 3 and len(set(urls)) == len(urls), 'FETCH_URL_COUNT')
    reference.require(all(type(url) is str and 1 <= len(url) <= 2048 for url in urls), 'FETCH_URL_BOUND')
    for url in urls:
        parsed = urlsplit(url)
        reference.require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
                          not parsed.password and parsed.port in (None,443), 'FETCH_PUBLIC_HTTPS_REQUIRED')
    reference.require(type(maximum_response_bytes) is int and 1024 <= maximum_response_bytes <= 512*1024,
                      'FETCH_RESPONSE_BOUND')
    reference.require(type(timeout_seconds) in (int,float) and 1 <= timeout_seconds <= 10, 'FETCH_TIMEOUT_BOUND')
    if not execute:
        return dict(status='READY_NO_EXECUTION', network_calls=0, provider_calls=0,
                    maximum_network_calls=len(urls)*6, source_rights_status='UNKNOWN_NOT_REVIEWED')
    directory = storage.new_directory(storage.state_directory(state_dir),'fetch')
    storage.save(directory/'started.json',dict(urls=urls,maximum_network_calls=len(urls)*6,
        maximum_response_bytes=maximum_response_bytes,created_at=datetime.now(timezone.utc).isoformat(),automatic_retry=False))
    session = session or retrieval.requests.Session()
    session.trust_env = False
    calls = 0
    original_get = session.get
    def counted_get(*args,**kwargs):
        nonlocal calls
        calls += 1
        reference.require(calls <= len(urls)*6, 'FETCH_NETWORK_CALL_BOUND')
        return original_get(*args,**kwargs)
    session.get = counted_get
    documents, records, error_type = [], [], None
    started = time.monotonic()
    try:
        for number,url in enumerate(urls):
            reference.require(time.monotonic()-started <= 60, 'FETCH_WALL_BOUND')
            body, metadata = retrieval.fetch_public_document(session,url,timeout_seconds,maximum_response_bytes)
            storage.write_bytes(directory/('response-%d.bin'%number),body)
            storage.save(directory/('retrieval-%d.json'%number),metadata)
            text, method = retrieval.extract_text(body,metadata.get('content_type'))
            reference.require(1 <= len(text.encode()) <= 512*1024, 'FETCH_EXTRACTED_TEXT_BOUND')
            records.append(dict(input_url=url,metadata=metadata,extraction_method=method))
            documents.append(dict(url=url,text=text,publisher='Fetched source'))
        imported = corpus.import_documents(documents,state_dir=state_dir)
    except Exception as exc:
        error_type = type(exc).__name__
        imported = None
    finally:
        session.get = original_get
        session.close()
    value = reference.seal(dict(status='STOPPED' if error_type else 'COMPLETE',
        output=str(directory),corpus=imported['corpus'] if imported else None,
        documents=len(documents),network_calls=calls,provider_calls=0,error_type=error_type,
        retrieval_records=records,source_rights_status='UNKNOWN_NOT_REVIEWED',
        automatic_retry=False,external_model_disclosure_allowed=False,publication_allowed=False))
    storage.save(directory/'terminal.json',value)
    return {key:value[key] for key in ('status','output','corpus','documents','network_calls','provider_calls',
        'error_type','source_rights_status','automatic_retry')}
