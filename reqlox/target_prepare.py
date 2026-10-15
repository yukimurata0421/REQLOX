"""Prepare private Target configurations with existing, read-only Source methods."""
import json
import os
from pathlib import Path
from . import targets


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def build(target, repositories, all_repositories=False, *, natural_source=None,
          condition_input=None, source_index=None, packets=None, specification_input=None):
    import run_reliability_reuse as runner
    import reliability_reuse as reuse
    import reliability_source_conditions as natural
    import reliability_specifications as specifications
    import prepare_reliability_reuse as preparation
    from .target_snapshot import verify_target
    verify_target(target)
    path, manifest, roots = targets.load(target)
    selected = list(roots) if all_repositories else list(repositories)
    check(not (all_repositories and repositories) and bool(selected)
          and len(set(selected)) == len(selected) and not set(selected) - set(roots), 'TARGET_PREPARE_SELECTION')
    check(sum(v is not None for v in (natural_source, condition_input, source_index)) <= 1, 'TARGET_PREPARE_SOURCE_MODE')
    check((source_index is None) == (packets is None), 'TARGET_PREPARE_INDEX_PACKETS')
    for supplied, keys in ((natural_source, {'source_texts'}), (condition_input, {'records', 'source_texts'})):
        if supplied is not None:
            check(type(supplied) is dict and set(supplied) == keys, 'TARGET_PREPARE_INPUT_FIELDS')
    if specification_input is not None:
        check(type(specification_input) is dict and set(specification_input) == {'repositories'}
              and type(specification_input['repositories']) is dict
              and set(specification_input['repositories']) == set(selected), 'TARGET_PREPARE_SPECIFICATION_SELECTION')
    database = None
    if source_index is not None:
        database = runner.private(targets.path_at(str(source_index), Path.cwd()))
        check(database.stat().st_size <= 16777216 and type(packets) is dict and len(packets) <= 20,
              'TARGET_PREPARE_INDEX_BOUND')
    entries = []
    for name in selected:
        row = manifest['repositories'][name]
        configuration = targets.path_at(row['configuration'], path.parent)
        config = targets.validate_configuration(targets.read_json(configuration))
        sources = runner.load_snapshot(roots[name])
        contracts = config['contracts']
        contract_record = None
        if 'path_context' in config:
            from . import target_context
            check(all(v is None for v in (natural_source, condition_input, source_index, specification_input)),
                  'TARGET_CONTEXT_SOURCE_MODE_UNSUPPORTED')
            context_plan = target_context.prepare(sources, config)
            prepared = reuse.c.seal(dict(contracts={}, source_texts={}, hypotheses=[],
                maximum_probes=config.get('maximum_probes', 3), selection=dict(held=[], source_selection='NO_SOURCE'),
                provider_calls=0, context_plan_sha256=targets.digest(context_plan),
                execution_authority=False))
            entries.append(dict(name=name, root=roots[name], original_configuration=configuration,
                original=config, sources=sources, configuration=config, preparation=prepared,
                contract_preparation=None, mode='DOCUMENTED_PATH_CONTEXT', dependency=None))
            check('dependency' not in row, 'TARGET_CONTEXT_DEPENDENCY_UNSUPPORTED')
            continue
        if specification_input is not None:
            item = specification_input['repositories'][name]
            check(type(item) is dict and set(item) == {'specification_texts', 'owner_policies'}, 'TARGET_PREPARE_OWNER_POLICY')
            contract_record = specifications.prepare(sources, item['specification_texts'], item['owner_policies'])
            contracts = contract_record['contracts']
        texts = natural_source['source_texts'] if natural_source is not None else config.get('source_texts', {})
        if condition_input is not None:
            texts = condition_input['source_texts']
        if contract_record is not None:
            specifications.check_roles(contract_record['specification_texts'], texts)
        if database is not None:
            prepared = preparation.prepare(sources, contracts, database, packets)
            if contract_record is not None:
                specifications.check_roles(contract_record['specification_texts'], prepared['source_texts'])
            mode = 'EXISTING_CANDIDATE_INDEX'
        elif condition_input is not None:
            prepared = preparation.prepare_conditions(sources, contracts, condition_input['records'], texts)
            mode = 'PROVIDED_CONDITION_RECORDS'
        elif texts:
            prepared = natural.prepare(sources, contracts, texts)
            mode = 'SUPPLIED_SOURCE_TEXT'
        else:
            prepared = reuse.c.seal(dict(contracts=contracts, source_texts={}, hypotheses=config.get('hypotheses', []),
                maximum_probes=config.get('maximum_probes', 3), selection=dict(held=[], source_selection='NO_SOURCE'), provider_calls=0))
            mode = 'NO_SOURCE'
        generated = {k: prepared[k] for k in ('contracts', 'source_texts', 'hypotheses', 'maximum_probes')}
        generated['maximum_probes'] = config.get('maximum_probes', prepared['maximum_probes'])
        targets.validate_configuration(generated)
        check(len(reuse.c.canonical(generated)) <= 262144, 'TARGET_PREPARE_CONFIGURATION_BOUND')
        entries.append(dict(name=name, root=roots[name], original_configuration=configuration,
            original=config, sources=sources, configuration=generated, preparation=prepared,
            contract_preparation=contract_record, mode=mode,
            dependency=None if 'dependency' not in row else targets.path_at(row['dependency'], path.parent)))
    return path, manifest, roots, entries


def save_bundle(target, repositories, output, all_repositories=False, **options):
    import run_reliability_reuse as runner
    import reliability_reuse as reuse
    path, original_manifest, roots, entries = build(target, repositories, all_repositories, **options)
    output = runner.private(Path(os.path.abspath(output)), new=True)
    check(not any(output.is_relative_to(r) or r.is_relative_to(output) for r in roots.values()),
          'TARGET_PREPARE_OUTPUT_OVERLAP')
    check(output.parent.is_dir(), 'TARGET_PREPARE_OUTPUT_PARENT')
    # Complete preparation and check drift before the first output write.
    check(targets.read_json(path) == original_manifest, 'TARGET_PREPARE_MANIFEST_CHANGED')
    for entry in entries:
        check(runner.load_snapshot(entry['root']) == entry['sources']
              and targets.read_json(entry['original_configuration']) == entry['original'], 'TARGET_PREPARE_INPUT_CHANGED')
    output.mkdir(mode=0o700)
    manifest = dict(schema=targets.SCHEMA, name=original_manifest['name'], repositories={})
    if 'snapshot_receipt' in original_manifest:
        receipt = targets.path_at(original_manifest['snapshot_receipt'], path.parent)
        manifest['snapshot_receipt'] = os.path.relpath(receipt, output)
    if 'authorization' in original_manifest:
        authorization = targets.path_at(original_manifest['authorization'], path.parent)
        manifest['authorization'] = os.path.relpath(authorization, output)
    summaries = []
    for entry in entries:
        name = entry['name']; configuration = output / (name + '.configuration.json')
        runner.save(configuration, entry['configuration'])
        record = reuse.c.seal(dict(name=name, mode=entry['mode'], sources_sha256=targets.digest(entry['sources']),
            original_configuration_sha256=targets.digest(entry['original']),
            configuration_sha256=targets.digest(entry['configuration']), preparation=entry['preparation'],
            contract_preparation=entry['contract_preparation'], execution_authority=False, provider_calls=0))
        runner.save(output / (name + '.preparation.json'), record)
        row = dict(path=os.path.relpath(entry['root'], output), configuration=configuration.name)
        if entry['dependency'] is not None:
            row['dependency'] = os.path.relpath(entry['dependency'], output)
        manifest['repositories'][name] = row
        summaries.append(dict(name=name, mode=entry['mode'], hypotheses=len(entry['configuration'].get('hypotheses', [])),
            held_conditions=len(entry['preparation']['selection']['held']), contracts=list(entry['configuration']['contracts']),
            configuration_sha256=record['configuration_sha256']))
    with (output / 'target.json').open('x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(targets.validate_manifest(manifest), ensure_ascii=False, indent=2) + '\n')
    summary = reuse.c.seal(dict(schema='reqlox.target-preparation.v1', status='PREPARED', output=str(output),
        target=str(output / 'target.json'), manifest_sha256=targets.digest(manifest),
        original_manifest_sha256=targets.digest(original_manifest), repositories=summaries,
        target_imports=0, native_attempts=0, provider_calls=0, checkout_write_authority=False,
        semantic_support_certified=False, independent_generalization_certified=False))
    runner.save(output / 'preparation.json', summary)
    return summary
