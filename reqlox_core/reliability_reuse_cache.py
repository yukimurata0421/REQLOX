"Finite reliability controls and verification."
from . import reliability_reuse as reuse

COMPILED_FAMILIES = ('atomic_file', 'async_resource', 'elapsed_ttl')
MAXIMUM_REFERENCE_DEPTH = 4
MAXIMUM_REFERENCE_DIRECTORIES = 16


def key(plan, arm, method, runtime, evaluation_kind, snapshot_sha256):
    reuse.c.require(arm in ('SOURCE', 'NO_SOURCE'), 'REUSE_CACHE_ARM')
    reuse.c.require(set(plan) == {'site', 'sources', 'contract', 'proposal',
                                 'candidate_code', 'dependency_sha256'}, 'REUSE_CACHE_PLAN_FIELDS')
    site = plan['site']
    graph=site['binding'].get('module_graph')
    members={site['member']} if graph is None else set(graph['modules'])
    reuse.c.require(site['family'] in reuse.FAMILIES and set(plan['sources']) == members
                    and reuse.sha(plan['sources'][site['member']]) == site['member_sha256'],
                    'REUSE_CACHE_MEMBER_CLOSURE')
    if graph is not None:
        reuse.c.require(site['family']=='atomic_context' and site['binding']['kind']==reuse.serialized.KIND,
                        'REUSE_CACHE_MODULE_BACKEND')
        reuse.c.require(all(reuse.sha(plan['sources'][n])==h for n,h in graph['source_sha256'].items()),
                        'REUSE_CACHE_MODULE_DEPENDENCY_DRIFT')
    
    
    compiled = site['family'] in COMPILED_FAMILIES
    closure = dict(kind='FULL_MEMBER_AND_FIXED_COMPILER' if compiled else 'WHOLE_REPOSITORY',
                   member_sha256=site['member_sha256'],
                   repository_sha256=None if compiled else snapshot_sha256)
    return reuse.c.digest(dict(plan=plan, arm=arm, closure=closure, method=method,
                               runtime=runtime, evaluation_kind=evaluation_kind))


def reference(directory, study, result, entry, plan, value):
    return reuse.c.seal(dict(directory=str(directory), study_sha256=reuse.c.digest(study),
        result_sha256=reuse.c.digest(result), entry_directory=entry['directory'],
        key=key(plan, entry['arm'], study['method'], study['runtime'],
                study['evaluation_kind'], reuse.c.digest(study['sources'])),
        observation_sha256=reuse.c.digest(value), counts_as_new_native_execution=False,
        counts_as_new_discovery=False))
