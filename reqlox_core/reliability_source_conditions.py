"Finite reliability controls and verification."
import re

from . import reliability_reuse as reuse

c = reuse.c
LIMITS = dict(documents=20, document_bytes=262144, blocks=128, block_characters=4096)
ERROR = re.compile(r'\b(?:OSError|IOError|EIO|ENOSPC|PermissionError|fail(?:ed|s|ure)?|errors?|exceptions?|rais(?:e|es|ed|ing))\b|\u5931\u6557|\u4f8b\u5916|\u30a8\u30e9\u30fc', re.I)
DENIAL = re.compile(r'\b(?:no|without)\s+(?:errors?|exceptions?|failure)|\b(?:does|did|will)\s+not\s+(?:fail|raise)|(?:\u5931\u6557|\u4f8b\u5916|\u30a8\u30e9\u30fc)(?:\u3057\u306a\u3044|\u306f\u306a\u3044|\u304c\u306a\u3044)', re.I)
OPERATIONS = {
    'REPLACE': r'\b(?:os\.)?(?:replace|rename)\s*\(|\b(?:rename|replacement)\b|\u7f6e\u63db|\u30ea\u30cd\u30fc\u30e0',
    'FSYNC': r'\b(?:os\.)?fsync\s*\(|\bfsync\b',
    'WRITE': r'\.write\s*\(|\bfile\s+write\b|\u66f8\u8fbc\u307f|\u66f8\u304d\u8fbc\u307f',
    'STREAM_CLOSE': r'\.close\s*\(|\bclos(?:e|ing|ed)\b|close|\u30af\u30ed\u30fc\u30ba',
    'STREAM_FLUSH': r'\.flush\s*\(|\bflush(?:ing|ed)?\b|flush|\u30d5\u30e9\u30c3\u30b7\u30e5',
    'TASK_CANCEL': r'\btask\s+cancell?ation\b|\btask\s+(?:was\s+)?cancell?ed\b|task\u53d6\u6d88\u3057',
}


def blocks(text):
    
    return [(m.start(),m.end()) for m in re.finditer(r'[^\n]+(?:\n(?![ \t]*\n)[^\n]+)*',text)
            if ERROR.search(m.group())]


def project(source_id, text):
    c.require(type(source_id) is str and 0 < len(source_id) <= 100
              and type(text) is str and 0 < len(text.encode()) <= LIMITS['document_bytes'], 'NATURAL_SOURCE_BOUND')
    rows = []; spans = blocks(text)
    for start,end in spans[:LIMITS['blocks']]:
        quote = text[start:end]; span = dict(start=start,end=end,sha256=reuse.sha(quote))
        row = dict(source_id=source_id,span=span,origin='INFERRED_FROM_REFERENCE',
                   semantic_support_certified=False,target_applicability_certified=False,execution_authority=False)
        reason = None
        operations = [op for op,pattern in OPERATIONS.items() if re.search(pattern,quote,re.I)]
        if len(quote) > LIMITS['block_characters']: reason = 'SOURCE_BLOCK_BOUND'
        elif DENIAL.search(quote): reason = 'NEGATED_OR_MIXED_FAILURE_CLAIM'
        elif len(operations) != 1: reason = 'AMBIGUOUS_OPERATION' if operations else 'UNSUPPORTED_OPERATION'
        operation = operations[0] if len(operations) == 1 else None
        row.update(operation=operation,phase='DURING',occurrence=1,occurrence_basis='TRANSFER_DEFAULT_FIRST_CALL')
        if operation in ('STREAM_FLUSH','STREAM_CLOSE') and reason is None:
            if not re.search(r'\b(?:file|stream)\b|\u30d5\u30a1\u30a4\u30eb|\u30b9\u30c8\u30ea\u30fc\u30e0',quote,re.I):
                reason = 'UNRESOLVED_RESOURCE_KIND'
            verb = r'(?:clos(?:e|ing|ed)|\u30af\u30ed\u30fc\u30ba)' if operation == 'STREAM_CLOSE' else r'(?:flush(?:ing|ed)?|\u30d5\u30e9\u30c3\u30b7\u30e5)'
            modifiers = r'(?:(?:the|a|first|second|third|[0-9]+(?:st|nd|rd|th)?|call|to|stream|file)\s+){0,5}'
            named = r'(?:[a-zA-Z_]\w*\.)?' + verb + r'(?:\(\))?'
            before = bool(re.search(r'\bbefore\s+'+modifiers+named+'|'+named+r'\s*(?:\u306e)?(?:\u76f4\u524d|\u524d\u306b|\u524d\u3067)',quote,re.I))
            after = bool(re.search(r'\bafter\s+'+modifiers+named+'|'+named+r'\s*(?:\u306e)?(?:\u5b8c\u4e86\u5f8c|\u76f4\u5f8c|\u5f8c\u306b|\u5f8c\u3067)',quote,re.I))
            if before != after: row['phase'] = 'BEFORE' if before else 'AFTER'
            elif reason is None: reason = 'UNRESOLVED_LIFECYCLE_PHASE'
            occurrence = re.findall(r'\b(first|second|third|\d+(?:st|nd|rd|th)?)\b(?=\s+(?:(?:file|stream)\s+)?(?:call|flush|close|time))|([0-9]+)\u56de\u76ee',quote,re.I)
            values = []
            for english,japanese in occurrence:
                token = english.lower() or japanese
                values.append({'first':1,'second':2,'third':3}.get(token) or int(re.sub(r'(st|nd|rd|th)$','',token)))
            if values:
                row.update(occurrence=values[0],occurrence_basis='EXPLICIT_SOURCE_ORDINAL')
                if len(set(values)) != 1 or not 1 <= values[0] <= 3: reason = 'UNSUPPORTED_OCCURRENCE'
            if operation == 'STREAM_CLOSE' and row['phase'] != 'AFTER' and reason is None:
                reason = 'UNSUPPORTED_LIFECYCLE_PHASE'
        row.update(status='HELD' if reason else 'CANDIDATE',reason=reason)
        rows.append(row)
    return c.seal(dict(kind='NATURAL_SOURCE_CONDITION_PROJECTION_V1',source_id=source_id,
        source_document_sha256=reuse.sha(text),candidates=rows,candidate_count=len(spans),
        overflow_count=max(0,len(spans)-LIMITS['blocks']),source_text_to_candidate_automatic=True,
        extraction_method='BOUNDED_LEXICAL_OPERATION_AND_FAILURE_CANDIDATES',
        source_selection_automatic=False,semantic_support_certified=False,execution_authority=False))


def checked(projection, text):
    c.check_seal(projection)
    c.require(projection == project(projection['source_id'],text),'NATURAL_SOURCE_PROJECTION_DRIFT')
    return projection


def prepare(sources, contracts, source_texts):
    c.require(type(source_texts) is dict and 0 < len(source_texts) <= LIMITS['documents'], 'NATURAL_SOURCE_DOCUMENT_LIMIT')
    inventory = reuse.inventory(sources); hypotheses = []; held = []; programs = set(); projections = []
    for source_id,text in source_texts.items():
        projection = project(source_id,text); projections.append(projection)
        if projection['overflow_count']:
            held.append(dict(source_id=source_id,reason='SOURCE_CANDIDATE_CAPACITY',count=projection['overflow_count']))
        for row in projection['candidates']:
            if row['status'] == 'HELD': held.append(row); continue
            operation = row['operation']; matching = []
            program = None
            if operation in ('STREAM_FLUSH','STREAM_CLOSE'):
                record = dict(kind='LIFECYCLE_CONDITION_V1',family='atomic_context',
                    **{k:row[k] for k in ('operation','phase','occurrence','source_id','span','origin')})
                program = reuse.conditions.bind(record,source_texts)
                if len(programs) >= 3 and program['condition_id'] not in programs:
                    held.append(dict(row,status='HELD',reason='CONDITION_PROGRAM_CAPACITY')); continue
                matching = ['atomic_context'] if any(reuse.conditions.supported(s,program) for s in inventory['accepted']) else []
            else:
                matching = sorted({s['family'] for s in inventory['accepted'] if operation in reuse.OPERATIONS[s['family']]})
            if not matching:
                held.append(dict(row,status='HELD',reason='NO_SUPPORTED_TARGET_BINDING')); continue
            for family in matching:
                statement = f"Candidate failure in {operation}: a finite projection of Source evidence; semantic support is unverified."
                record = dict(family=family,conditions=[statement],faults=[operation if program is None else program['condition_id']],
                              source_id=source_id,span=row['span'])
                if program is not None:
                    record['condition_programs'] = [program]; programs.add(program['condition_id'])
                hypotheses.append(reuse.hypothesis_input(reuse.hypothesis(record,source_texts)))
    return c.seal(dict(contracts=contracts,maximum_probes=3,hypotheses=hypotheses,source_texts=source_texts,
        discovery_policy='ISOLATED_SOURCE_KNOWLEDGE',qualification_policy='OWNED_MODEL_GRID',
        selection=dict(repository_snapshot_sha256=c.digest(sources),projections=projections,
            candidate_count=sum(p['candidate_count'] for p in projections),selected_count=len(hypotheses),held=held,
            source_text_to_candidate_automatic=True,source_text_to_program_automatic=True,
            source_selection_automatic=False,semantic_support_certified=False,execution_authority=False),
        human_time_measured=False,provider_calls=0))


def verify_prepared(configuration, sources):
    c.check_seal(configuration)
    expected = prepare(sources,configuration['contracts'],configuration['source_texts'])
    if 'contract_preparation' in configuration:
        from . import reliability_specifications as specifications
        value = specifications.verify(configuration['contract_preparation'],sources)
        specifications.check_roles(value['specification_texts'],configuration['source_texts'])
        c.require(value['contracts']==configuration['contracts'],'NATURAL_SOURCE_CONTRACT_DRIFT')
        expected = c.seal(dict(expected,contract_preparation=value))
    c.require(configuration == expected,'NATURAL_SOURCE_CONFIGURATION_DRIFT')
    return configuration
