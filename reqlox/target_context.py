"""Connect documented path contexts to Target planning, execution and audit."""
import datetime
from pathlib import Path
import re

PROFILE = 'DOCUMENTED_SYNC_PATH_CONTEXT_V1'
CONTRACT = 'documented.path-context-release.v1'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate(value):
    import reliability_path_context as context
    from reliability_specifications import DENIAL
    require(type(value) is dict and set(value) == {'profile', 'documents', 'recipe', 'contract'}
            and value['profile'] == PROFILE, 'TARGET_CONTEXT_CONFIGURATION')
    documents = value['documents']; declaration = value['contract']
    require(type(documents) is dict and 1 <= len(documents) <= 20
            and all(type(k) is str and 0 < len(k) <= 100 and type(v) is str
                    and 0 < len(v.encode()) <= 262144 for k, v in documents.items()), 'TARGET_CONTEXT_DOCUMENTS')
    require(type(declaration) is dict and set(declaration) == {'id', 'scope', 'evidence'}
            and declaration['id'] == CONTRACT and declaration['scope'] == 'DOCUMENTED_WITH_EXIT_ONLY',
            'TARGET_CONTEXT_CONTRACT')
    evidence = declaration['evidence']
    require(type(evidence) is dict and set(evidence) == {'document', 'span'}
            and evidence['document'] in documents, 'TARGET_CONTEXT_RELEASE_EVIDENCE')
    text = documents[evidence['document']]; span = evidence['span']
    require(type(span) is dict and set(span) == {'start', 'end', 'sha256'}
            and type(span['start']) is int and type(span['end']) is int
            and 0 <= span['start'] < span['end'] <= len(text)
            and span['end'] - span['start'] <= 1024
            and context.hashlib.sha256(text[span['start']:span['end']].encode()).hexdigest() == span['sha256'],
            'TARGET_CONTEXT_RELEASE_SPAN')
    quote = text[span['start']:span['end']]
    require(not DENIAL.search(quote) and not re.search(r'\b(?:not|no)\b', quote, re.I) and re.search(
        r'\b(?:file|path|resource)\b.{0,120}\b(?:removed|deleted|released)\b.{0,120}'
        r'\b(?:leave|exit|end)\b.{0,120}\b(?:with|context)\b', quote, re.I | re.S),
        'TARGET_CONTEXT_EXIT_RELEASE_NOT_SUPPORTED')
    require(type(value['recipe']) is dict and value['recipe'].get('document') == evidence['document']
            and value['recipe'].get('recipe_origin') is None, 'TARGET_CONTEXT_AUTHOR_EXAMPLE_REQUIRED')
    return value


def prepare(sources, configuration):
    import reliability_path_context as context
    value = validate(configuration['path_context'])
    require(not configuration['contracts'] and not configuration.get('hypotheses')
            and not configuration.get('source_texts') and not configuration.get('specification_texts'),
            'TARGET_CONTEXT_MIXED_REQUIREMENTS')
    found = context.recipes(sources, value['documents'])
    require(value['recipe'] in found['rows'], 'TARGET_CONTEXT_RECIPE_DRIFT')
    # A supplied document is evidence of a caller, not permission to import code.
    for text in sources.values():
        context.source_guard(text)
    plan = context.plan(sources, value['recipe'], value['documents'], provenance={'role': 'KNOWN_DEVELOPMENT'})
    return plan


def method_identity():
    import reliability_path_context as context
    import reliability_context_evidence as evidence
    return dict(bridge=context.hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                execution=context.methods(), verifier=context.hashlib.sha256(Path(evidence.__file__).read_bytes()).hexdigest())


def run(plan, contract, output, *, before_native, deadline, maximum_native_campaigns):
    import reliability_path_context as context
    import run_reliability_path_context as native
    import run_reliability_reuse as storage
    output = storage.private(output, new=True); output.mkdir(mode=0o700)
    storage.save(output / 'input.json', context.c.seal(dict(context_plan=plan, contract=contract,
        deadline=deadline, maximum_native_campaigns=maximum_native_campaigns)))
    rounds = []; attempts = 0; status = 'UNCONFIRMED'; reason = None
    def reserve():
        nonlocal attempts
        require(attempts < maximum_native_campaigns, 'TARGET_CONTEXT_NATIVE_CAMPAIGN_LIMIT')
        require((datetime.datetime.fromisoformat(deadline) - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                >= plan['limits']['wall_seconds'], 'TARGET_DEADLINE')
        before_native(); attempts += 1
    for stage in ('initial', 'confirmation'):
        receipt, observation = native.execute(plan, output / stage, before_native=reserve)
        rounds.append(dict(stage=stage, receipt_sha256=context.c.digest(receipt), label=receipt['label']))
        if receipt['status'] != 'COMPLETE' or observation is None or receipt['label'] is None:
            status = 'STOPPED'; reason = receipt.get('error') or 'PATH_CONTEXT_UNCONFIRMED'; break
        if receipt['label'] == 'FAIL':
            status = 'COUNTEREXAMPLE_NO_SUPPORTED_REPAIR' if stage == 'initial' else 'CONFIRMATION_FAILED'
            break
        if stage == 'confirmation':
            status = 'NO_COUNTEREXAMPLE'
    result = context.c.seal(dict(schema='reqlox.target-context-run.v1', status=status, reason=reason,
        context_plan_sha256=context.c.digest(plan), contract_sha256=context.c.digest(contract),
        rounds=rounds, native_campaigns=attempts, adopted_files={}, repair_attempted=False,
        repair_verified=False, automatic_retry=False, provider_calls=0,
        independent_generalization_certified=False, natural_source_added_value_certified=False,
        probability_calibration_certified=False))
    storage.save(output / 'result.json', result)
    return result


def verify(output, plan, contract):
    import reliability_path_context as context
    import reliability_context_evidence as evidence
    import run_reliability_reuse as storage
    from .target_audit import read
    output = storage.private(output)
    inputs = read(output / 'input.json'); result = read(output / 'result.json')
    context.c.check_seal(inputs); context.c.check_seal(result)
    require(inputs['context_plan'] == plan and inputs['contract'] == contract
            and result['schema'] == 'reqlox.target-context-run.v1'
            and result['context_plan_sha256'] == context.c.digest(plan)
            and result['contract_sha256'] == context.c.digest(contract), 'TARGET_CONTEXT_RESULT_BINDING')
    require(result['adopted_files'] == {} and result['repair_attempted'] is False and result['repair_verified'] is False
            and result['automatic_retry'] is False and result['provider_calls'] == 0
            and all(result[k] is False for k in ('independent_generalization_certified',
                'natural_source_added_value_certified', 'probability_calibration_certified')),
            'TARGET_CONTEXT_RESULT_CLAIMS')
    rows = result['rounds']; require(1 <= len(rows) <= 2, 'TARGET_CONTEXT_ROUNDS')
    require(result['native_campaigns'] == len(rows) <= inputs['maximum_native_campaigns'], 'TARGET_CONTEXT_BUDGET')
    labels = []
    for row, stage in zip(rows, ('initial', 'confirmation')):
        require(row['stage'] == stage, 'TARGET_CONTEXT_STAGE')
        child = output / stage
        saved = read(child / 'plan.json'); receipt = read(child / 'receipt.json')
        require(saved == plan and context.c.digest(receipt) == row['receipt_sha256']
                and row['label'] == receipt['label'], 'TARGET_CONTEXT_CHILD_BINDING')
        checked = evidence.verify_execution(child)
        require(checked['label'] == row['label'], 'TARGET_CONTEXT_LABEL')
        launch = read(child / 'launch.json')
        require(launch.get('launcher_limits') == 'PRLIMIT_BEFORE_BWRAP', 'TARGET_CONTEXT_STARTUP_LIMITS')
        if receipt['status'] == 'COMPLETE':
            observed = read(child / 'observed.json')
            context.check_execution_boundary(observed.get('execution_boundary'))
        labels.append(row['label'])
    expected = ('NO_COUNTEREXAMPLE' if labels == ['PASS', 'PASS'] else
                'COUNTEREXAMPLE_NO_SUPPORTED_REPAIR' if labels == ['FAIL'] else
                'CONFIRMATION_FAILED' if labels == ['PASS', 'FAIL'] else 'STOPPED')
    require(result['status'] == expected, 'TARGET_CONTEXT_STATUS')
    return inputs, result
