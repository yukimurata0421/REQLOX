"Finite reliability controls and verification."
import re

import reliability_reuse as reuse

c = reuse.c
PREDICATES = {
    'destination_preserved': r'preserv(?:e|es|ed).*?(?:existing|original|prior).*?(?:destination|target)|(?:destination|target).*?(?:unchanged|preserved)|(?:\u65e2\u5b58|\u5143)\u306e(?:\u4fdd\u5b58\u5148|\u30d5\u30a1\u30a4\u30eb).*?(?:\u4fdd\u6301|\u5909\u66f4\u3057\u306a\u3044)',
    'exception_propagated': r'propagat(?:e|es|ed).*?(?:exception|error)|re-rais(?:e|es|ed).*?(?:exception|error)|(?:\u4f8b\u5916|\u30a8\u30e9\u30fc).*?(?:\u4f1d\u64ad|\u518d\u9001\u51fa)',
    'owned_temporary_removed': r'(?:remove|removes|unlink|clean).*?only.*?(?:temporary|temp).*?owned|(?:remove|removes|unlink|clean).*?owned.*?(?:temporary|temp)|\u6240\u6709.*?\u4e00\u6642.*?(?:\u524a\u9664|\u56de\u53ce)',
}
DENIAL = re.compile(r'\b(?:does|do|will|can)\s+not\b|\b(?:never|cannot|might|may|should|could|would|if)\b|(?:\u4fdd\u8a3c\u3057\u306a\u3044|\u672a\u4fdd\u8a3c|\u3079\u304d|\u304b\u3082\u3057\u308c\u306a\u3044)|(?:\u4f1d\u64ad|\u518d\u9001\u51fa|\u524a\u9664|\u56de\u53ce)(?:\u3057\u306a\u3044|\u3055\u308c\u306a\u3044|\u3055\u308c\u307e\u305b\u3093)',re.I)


def check_roles(specification_texts, source_texts):
    c.require(type(specification_texts) is dict and type(source_texts) is dict
              and all(type(text) is str for text in (*specification_texts.values(),*source_texts.values())), 'SPECIFICATION_ROLE_TEXTS')
    c.require(not any(spec.strip() and spec.strip() in text for spec in specification_texts.values()
                      for text in source_texts.values()), 'REUSE_SOURCE_SPECIFICATION_ROLE_COLLISION')


def evidence(specification_texts):
    "Evidence."
    c.require(type(specification_texts) is dict and 0 < len(specification_texts) <= 20,
              'SPECIFICATION_DOCUMENT_BOUND')
    spans = {predicate:[] for predicate in PREDICATES};held = []
    for source_id,text in specification_texts.items():
        c.require(type(source_id) is str and 0 < len(source_id) <= 100 and type(text) is str
                  and 0 < len(text.encode()) <= 262144,'SPECIFICATION_TEXT_BOUND')
        for match in re.finditer(r'[^\n]+(?:\n(?![ \t]*\n)[^\n]+)*',text):
            quote = match.group()
            found = [name for name,pattern in PREDICATES.items() if re.search(pattern,quote,re.I|re.S)]
            if not found:continue
            span = dict(start=match.start(),end=match.end(),sha256=reuse.sha(quote))
            if len(quote)>4096 or DENIAL.search(quote):
                held.append(dict(source_id=source_id,span=span,predicates=found,reason='SPECIFICATION_AMBIGUOUS_OR_NEGATED'));continue
            for name in found:
                spans[name].append(dict(source_id=source_id,span=span,source_document_sha256=reuse.sha(text)))
    return spans, held


def prepare(sources, specification_texts, owner_policies=None):
    owner_policies = {} if owner_policies is None else owner_policies
    c.require(type(owner_policies) is dict and set(owner_policies) <= set(reuse.CONTRACTS), 'SPECIFICATION_OWNER_POLICIES')
    for family,policy in owner_policies.items():
        c.require(type(policy) is dict and set(policy)=={'basis','scope'}
                  and all(type(v) is str and 0 < len(v) <= 1000 for v in policy.values()), 'SPECIFICATION_OWNER_POLICY_FIELDS')
    spans, held = evidence(specification_texts)
    inventory = reuse.inventory(sources); candidates=[];contracts={}
    for family in sorted({s['family'] for s in inventory['accepted']}):
        missing = [name for name,rows in spans.items() if not rows]
        reasons = []
        if held:reasons.append('SPECIFICATION_CONFLICT_OR_AMBIGUITY')
        if family not in ('atomic_file','atomic_context'):reasons.append('SPECIFICATION_FAMILY_UNSUPPORTED')
        if missing:reasons.append('SPECIFICATION_PREDICATES_MISSING')
        if family not in owner_policies:reasons.append('OWNER_POLICY_REQUIRED')
        declaration = None
        if not reasons:
            declaration = dict(id=reuse.CONTRACTS[family],**owner_policies[family]);contracts[family]=declaration
        candidates.append(dict(family=family,contract_id=reuse.CONTRACTS[family],declaration=declaration,
            missing_predicates=missing,reasons=reasons,status='CANDIDATE' if not reasons else 'HELD',
            specification_semantics_certified=False,execution_authority=False))
    return c.seal(dict(kind='SPECIFICATION_CONTRACT_CANDIDATES_V1',repository_snapshot_sha256=c.digest(sources),
        specification_texts=specification_texts,owner_policies=owner_policies,evidence=spans,held=held,
        candidates=candidates,contracts=contracts,contract_ids_from_catalog=True,
        ownership_derived_from_source=False,specification_semantics_certified=False,execution_authority=False))


def verify(value,sources):
    c.check_seal(value)
    c.require(value==prepare(sources,value['specification_texts'],value['owner_policies']), 'SPECIFICATION_CANDIDATE_DRIFT')
    return value
