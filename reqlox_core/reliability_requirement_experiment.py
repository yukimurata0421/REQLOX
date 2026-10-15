"Finite reliability controls and verification."
from . import reliability_reuse as reuse
from . import reliability_specifications as specifications

c = reuse.c


def prepare(sources, specification_texts, owner_policies):
    reuse.validate_sources(sources)
    c.require(type(specification_texts) is dict, 'REQUIREMENT_SPECIFICATION_TEXTS')
    
    spans, ambiguous = specifications.evidence(specification_texts) if specification_texts else (
        {name: [] for name in specifications.PREDICATES}, [])
    c.require(type(owner_policies) is dict and set(owner_policies) <= set(reuse.CONTRACTS),
              'REQUIREMENT_OWNER_POLICIES')
    for policy in owner_policies.values():
        c.require(type(policy) is dict and set(policy) == {'basis', 'scope'}
                  and all(type(v) is str and 0 < len(v) <= 1000 for v in policy.values()),
                  'REQUIREMENT_OWNER_POLICY_FIELDS')
    properties = {name: dict(status='AMBIGUOUS' if any(name in r['predicates'] for r in ambiguous)
                            else 'LEXICAL_EVIDENCE' if spans[name] else 'UNKNOWN',
                            evidence=spans[name], ambiguous=[r for r in ambiguous if name in r['predicates']])
                  for name in specifications.PREDICATES}
    inventory = reuse.inventory(sources); contracts = {}; sites = []
    for site in inventory['accepted']:
        family = site['family']; reasons = []
        if family not in ('atomic_file', 'atomic_context'):
            reasons.append('REQUIREMENT_PROPERTY_MODEL_UNSUPPORTED')
        if family not in owner_policies: reasons.append('OWNER_REQUIREMENT_REQUIRED')
        if not reasons: contracts[family] = dict(id=reuse.CONTRACTS[family], **owner_policies[family])
        sites.append(dict(site_id=site['id'], family=family, status='PREPARED' if not reasons else 'HELD',
                          reasons=reasons, target_bug_claim_eligible=False))
    return c.seal(dict(kind='OWNED_REQUIREMENT_EXPERIMENT_V1',
        repository_snapshot_sha256=c.digest(sources), specification_texts=specification_texts,
        owner_policies=owner_policies, property_evidence=properties, contracts=contracts, sites=sites,
        interpretation='CLIENT_REQUIREMENT_COMPATIBILITY_ONLY',
        specification_semantics_certified=False, target_bug_claim_eligible=False,
        ownership_derived_from_source=False, execution_authority=False,
        independent_generalization_certified=False))


def verify(value, sources):
    c.check_seal(value)
    c.require(value == prepare(sources, value['specification_texts'], value['owner_policies']),
              'REQUIREMENT_EXPERIMENT_DRIFT')
    return value
