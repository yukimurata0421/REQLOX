"Finite reliability controls and verification."
import errno
import hashlib
import re

from . import incident_reference as c

FIELDS = {'kind','family','operation','phase','occurrence','source_id','span','origin'}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def bind(record, sources):
    c.require(type(record) is dict and set(record) == FIELDS, 'CONDITION_FIELDS')
    c.require(record['kind'] == 'LIFECYCLE_CONDITION_V1' and record['family'] == 'atomic_context', 'CONDITION_FAMILY')
    c.require(record['operation'] in ('STREAM_FLUSH','STREAM_CLOSE')
              and record['phase'] in ('BEFORE','AFTER')
              and (record['operation'] != 'STREAM_CLOSE' or record['phase'] == 'AFTER'), 'CONDITION_OPERATION')
    c.require(type(record['occurrence']) is int and 1 <= record['occurrence'] <= 3, 'CONDITION_OCCURRENCE')
    c.require(record['origin'] in ('SOURCE_OBSERVED','INFERRED_FROM_REFERENCE'), 'CONDITION_ORIGIN')
    c.require(type(record['source_id']) is str and 0 < len(record['source_id']) <= 100
              and record['source_id'] in sources, 'CONDITION_SOURCE_MISSING')
    text = sources[record['source_id']]; span = record['span']
    c.require(type(text) is str and 0 < len(text.encode()) <= 262144 and type(span) is dict
              and set(span) == {'start','end','sha256'} and type(span['start']) is int and type(span['end']) is int
              and 0 <= span['start'] < span['end'] <= len(text)
              and sha(text[span['start']:span['end']]) == span['sha256'], 'CONDITION_EVIDENCE_SPAN')
    identity = c.digest(dict(record=record,source_document_sha256=sha(text)))
    return c.seal(dict(**record,condition_id='CONDITION_'+identity,source_document_sha256=sha(text),
                       outcome='RAISE_OSERROR_EIO',semantic_support_certified=False,
                       target_applicability_certified=False,execution_authority=False))


def checked(program, sources):
    c.check_seal(program)
    expected = bind({k:program[k] for k in FIELDS},sources)
    c.require(program == expected, 'CONDITION_BINDING_DRIFT')
    return program


def supported(site, program):
    return site['family'] == 'atomic_context' and site['binding'].get('kind') in ('GENERATOR_CONTEXT','FD_GENERATOR_CONTEXT','DELEGATED_GENERATOR_CONTEXT','SERIALIZED_ATOMIC_CONTEXT')


def is_condition(fault):
    return type(fault) is str and re.fullmatch(r'CONDITION_[0-9a-f]{64}',fault) is not None


def pool(hypotheses):
    programs = {}
    for h in hypotheses:
        for p in h.get('condition_programs',[]):
            c.require(p['condition_id'] not in programs or programs[p['condition_id']] == p, 'CONDITION_ID_COLLISION')
            programs[p['condition_id']] = p
    c.require(len(programs) <= 3, 'CONDITION_PROGRAM_LIMIT')
    return programs


def owned_qualification():
    "Owned qualification."
    from . import reliability_reuse as reuse
    source_id = 'owned-model-qualification-grid-v1'
    text = 'Owned finite file lifecycle model: first explicit flush before/after and first stream context exit after. Not an external incident or physical fault oracle.'
    texts = {source_id:text};span = dict(start=0,end=len(text),sha256=sha(text));hypotheses=[]
    for operation,phase in (('STREAM_FLUSH','BEFORE'),('STREAM_FLUSH','AFTER'),('STREAM_CLOSE','AFTER')):
        program = bind(dict(kind='LIFECYCLE_CONDITION_V1',family='atomic_context',operation=operation,
            phase=phase,occurrence=1,source_id=source_id,span=span,origin='INFERRED_FROM_REFERENCE'),texts)
        hypotheses.append(reuse.hypothesis(dict(family='atomic_context',conditions=['\u4e8b\u524d\u56fa\u5b9a\u3057\u305f\u6240\u6709\u30e2\u30c7\u30eb\u306e\u8cc7\u683c\u78ba\u8a8d\u6761\u4ef6'],
            faults=[program['condition_id']],source_id=source_id,span=span,condition_programs=[program]),texts))
    return hypotheses,texts


class Injector:
    def __init__(self, program):
        self.program = program; self.seen = 0; self.hits = []

    def call(self, operation, function):
        if operation != self.program['operation']:
            return function()
        self.seen += 1
        selected = self.seen == self.program['occurrence']
        if selected and self.program['phase'] == 'BEFORE':
            self.fail(operation)
        result = function()
        if selected and self.program['phase'] == 'AFTER':
            self.fail(operation)
        return result

    def fail(self, operation):
        self.hits.append(dict(operation=operation,phase=self.program['phase'],occurrence=self.seen))
        raise OSError(errno.EIO,'OWNED_LIFECYCLE_CONDITION')
