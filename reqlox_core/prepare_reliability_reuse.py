"""Prepare explicitly supplied bounded conditions without a corpus database."""
import reliability_reuse as reuse
import argparse
import json
import run_reliability_reuse as runner
import reliability_specifications as specifications
import reliability_source_conditions as natural


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument('--contracts')
    authority.add_argument('--specification-input')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--condition-input')
    inputs.add_argument('--natural-source-input')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    sources = runner.load_snapshot(args.root)
    output = runner.private(args.output, new=True)
    preparation = None
    if args.specification_input:
        spec = runner.read(args.specification_input)
        preparation = specifications.prepare(sources, spec['specification_texts'], spec['owner_policies'])
        contracts = preparation['contracts']
    else:
        contracts = runner.read(args.contracts)
    path = runner.private(args.natural_source_input or args.condition_input)
    reuse.c.require(path.stat().st_size <= 1048576, 'REUSE_CONDITION_INPUT_BOUND')
    value = runner.read(path)
    if args.natural_source_input:
        if preparation is not None:
            specifications.check_roles(preparation['specification_texts'], value['source_texts'])
        value = natural.prepare(sources, contracts, value['source_texts'])
    else:
        value = prepare_conditions(sources, contracts, value['records'], value['source_texts'])
    if preparation is not None:
        value = reuse.c.seal(dict(value, contract_preparation=preparation))
    runner.save(output, value)
    print(json.dumps(dict(status='PREPARED', hypotheses=len(value['hypotheses']),
                          held=len(value['selection']['held']), new_provider_calls=0, new_native_campaigns=0)))


def prepare_conditions(sources, contracts, records, source_texts):
    "Prepare conditions."
    reuse.c.require(type(records) is list and len(records) <= 20 and type(source_texts) is dict
                    and len(source_texts) <= 20 and all(type(s) is str and len(s.encode()) <= 262144 for s in source_texts.values()),
                    'REUSE_CONDITION_INPUT_BOUND')
    inventory = reuse.inventory(sources);hypotheses = [];held = [];selected_ids = set()
    for record in records:
        try:
            program = reuse.conditions.bind(record,source_texts)
            if not any(reuse.conditions.supported(site,program) for site in inventory['accepted']):
                held.append(dict(condition_id=program['condition_id'],reason='UNSUPPORTED_CONDITION_BINDING'));continue
            if program['condition_id'] in selected_ids:
                held.append(dict(condition_id=program['condition_id'],reason='DUPLICATE_CONDITION_RECORD'));continue
            if len(selected_ids) >= 3:
                held.append(dict(condition_id=program['condition_id'],reason='CONDITION_PROGRAM_CAPACITY'));continue
            statement = f"Check the exception at occurrence {program['occurrence']} in {program['phase']} of {program['operation']}; semantic support is unverified."
            hypotheses.append(reuse.hypothesis(dict(family=program['family'],conditions=[statement],faults=[program['condition_id']],
                source_id=program['source_id'],span=program['span'],condition_programs=[program]),source_texts))
            selected_ids.add(program['condition_id'])
        except ValueError as exc:
            held.append(dict(record_sha256=reuse.c.digest(record),reason=str(exc)))
    reuse.conditions.pool(hypotheses)
    return reuse.c.seal(dict(contracts=contracts,maximum_probes=3,hypotheses=[reuse.hypothesis_input(h) for h in hypotheses],source_texts=source_texts,
        selection=dict(repository_snapshot_sha256=reuse.c.digest(sources),records_sha256=reuse.c.digest(records),candidate_count=len(records),
            selected_count=len(hypotheses),held=held,source_selection='PROVIDED_CONDITION_RECORDS_STATIC_BINDING',
            source_text_to_program_automatic=False,semantic_support_certified=False,execution_authority=False),
        human_time_measured=False,provider_calls=0))


if __name__ == "__main__":
    main()
