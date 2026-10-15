"""Public preparation, equal-budget comparison, and calibration interfaces.

These functions create local artifacts. They do not call a model, acquire a
repository, activate a probability transform, or certify generalization.
"""
from copy import deepcopy
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

from . import _runtime
from .capsule import inspect_wheels


def _modules():
    _runtime()
    import incident_reference as c
    import reliability_path_context as context
    import reliability_incident_conditions as conditions
    import reliability_probability_evaluation as probability
    import reliability_calibration_setup as calibration
    return c, context, conditions, probability, calibration


def settings():
    """Return the shipped public settings; serving remains RAW."""
    return json.loads((Path(__file__).parent / 'data' / 'evaluation-settings.json').read_text())


def prepare_context(sources, documents, *, project, known_projects=(), capsule=None):
    """Discover bounded documented callers without importing target code."""
    c, context, _, _, _ = _modules()
    from packaging.utils import canonicalize_name
    c.require(type(project) is str and project, 'PREPARATION_PROJECT')
    project = canonicalize_name(project)
    known = {canonicalize_name(p) for p in known_projects}
    holds = []
    if project in known:
        holds.append(dict(reason='DECLARED_LOCAL_HISTORY_EXPOSURE'))
    if capsule is not None:
        from packaging.markers import default_environment
        c.check_seal(capsule)
        c.require(capsule['kind'] == 'LOCAL_PURE_PYTHON_WHEEL_CAPSULE_V1'
                  and capsule['sources'] == sources and capsule['target_project'] == project,
                  'PREPARATION_CAPSULE_BINDING')
        marker_environment = default_environment()
        marker_environment['extra'] = ''
        c.require(capsule['runtime_marker_environment'] == marker_environment
                  and capsule['runtime_executable_sha256'] == hashlib.sha256(
                      Path(sys.executable).resolve().read_bytes()).hexdigest(),
                  'PREPARATION_CAPSULE_RUNTIME_DRIFT')
        for member, text in sources.items():
            distribution = capsule['distributions'][capsule['member_distribution'][member]]
            c.require(hashlib.sha256(text.encode()).hexdigest() == distribution['files_sha256'][member],
                      'PREPARATION_CAPSULE_SOURCE_DRIFT')
        holds.extend(capsule['holds'])
    roots = {Path(n).parts[0].removesuffix('.py') for n in sources}
    import ast
    for member, text in sources.items():
        try:
            context.source_guard(text, capability=context.native_import_capability())
            tree = ast.parse(text)
        except (ValueError, SyntaxError) as exc:
            holds.append(dict(member=member, reason=str(exc)[:160]))
            continue
        for node in ast.walk(tree):
            imported = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
            for module in imported:
                if module.split('.')[0] not in roots | set(sys.stdlib_module_names):
                    holds.append(dict(member=member, module=module, reason='MISSING_PINNED_DEPENDENCY'))
    discovered = context.recipes(sources, documents)
    holds.extend(discovered['held'])
    if not discovered['rows']:
        holds.append(dict(reason='NO_DOCUMENTED_SUPPORTED_CONTEXT'))
    target_rows = discovered['rows']
    if capsule is not None:
        target_rows = [r for r in target_rows if any(
            r['binding']['module'] in context.module_names({member: text})
            and capsule['member_distribution'][member] == project
            for member, text in sources.items())]
        if not target_rows:
            holds.append(dict(reason='NO_TARGET_PROJECT_CONTEXT'))
    return c.seal(dict(kind='PUBLIC_CONTEXT_PREPARATION_V1', project=project,
        status='HELD' if holds else 'READY_STATICALLY', sources=sources, documents=documents,
        recipes=target_rows, holds=holds, method=context.methods(),
        capsule_sha256=None if capsule is None else c.digest(capsule),
        dependency_capsule=capsule, local_history_scope='CALLER_DECLARED_PROJECTS_ONLY',
        all_chat_unused_verified=False, unused_holdout_certified=False,
        implementation_behavior_used_as_specification=False, target_code_imported=False,
        provider_calls=0, execution_authority=False))


def supplied_source(documents, *, url, source_type='OWNED_SYNTHETIC_REPORT'):
    """Bind supplied text; this function performs no external retrieval."""
    c, _, _, _, _ = _modules()
    c.require(source_type in ('OWNED_SYNTHETIC_REPORT', 'ISSUE_REPORT', 'POSTMORTEM'), 'SOURCE_TYPE')
    return c.seal(dict(kind='PUBLIC_OBSERVED_FAILURE_SOURCE_V1', documents=documents, url=url,
        source_type=source_type, raw_sha256=c.digest(documents), retrieval_complete=True,
        retrieval_scope='CALLER_SUPPLIED_DOCUMENT_SET', external_retrieval_verified=False,
        execution_authority=False))


def freeze_comparison(preparation, source, *, recipe_index=0, budget=4):
    """Use the same caller, oracle, repairer, and confirmation envelope."""
    c, context, conditions, _, _ = _modules()
    c.check_seal(preparation)
    c.require(preparation == prepare_context(preparation['sources'], preparation['documents'],
        project=preparation['project'], capsule=preparation['dependency_capsule']), 'PREPARATION_DRIFT')
    c.require(preparation['status'] == 'READY_STATICALLY', 'PREPARATION_HELD')
    c.require(type(recipe_index) is int and 0 <= recipe_index < len(preparation['recipes']), 'RECIPE_INDEX')
    base = context.plan(preparation['sources'], preparation['recipes'][recipe_index], preparation['documents'],
        provenance=dict(role='KNOWN_DEVELOPMENT', project=preparation['project'],
                        preparation_sha256=c.digest(preparation)))
    return conditions.freeze(base, source, budget=budget, baseline_policy='TARGET_GUIDED_SOURCE_BLIND_V1')


def run_comparison(frozen, output, *, seconds=180, maximum_campaigns=32):
    """Execute a frozen comparison in new private directories with hard bounds."""
    c, _, conditions, _, _ = _modules()
    import run_reliability_incident_conditions as runner
    c.require(type(seconds) is int and 1 <= seconds <= 600 and type(maximum_campaigns) is int
              and 0 <= maximum_campaigns <= 32, 'PUBLIC_COMPARISON_LIMITS')
    deadline = time.monotonic() + seconds
    attempts = 0
    def guard():
        c.require(time.monotonic() < deadline, 'PUBLIC_COMPARISON_DEADLINE')
        c.require(conditions.methods() == frozen['method'], 'PUBLIC_COMPARISON_METHOD_DRIFT')
    def before_native():
        nonlocal attempts
        guard()
        c.require(attempts < maximum_campaigns, 'PUBLIC_COMPARISON_CAMPAIGN_BOUND')
        attempts += 1
    guard.before_native = before_native
    return runner.run(frozen, Path(output).absolute(), guard=guard)


def score_forecasts(rows, *, event, predictor_revision):
    """Keep missing forecasts and unknown labels in the declared denominator."""
    c, _, _, probability, _ = _modules()
    c.require(type(rows) is list and len(rows) <= 4096, 'PUBLIC_FORECAST_ROWS_BOUND')
    return probability.evaluate(rows, event=event, predictor_revision=predictor_revision)


def fit_calibration(rows, *, event, predictor_revision):
    """Fit a monotone diagnostic candidate using training rows only."""
    c, _, _, _, calibration = _modules()
    return calibration.fit(rows, event=event, predictor_revision=predictor_revision,
                           training_ref=dict(kind='LOCAL_SUPPLIED_TRAINING_ROWS_V1', sha256=c.digest(rows)))


def register_confirmation(model, training_rows, forecast_rows):
    """Freeze one candidate and unlabeled forecasts before confirmation."""
    c, _, _, probability, _ = _modules()
    c.check_seal(model)
    c.require(type(forecast_rows) is list and 1 <= len(forecast_rows) <= 4096, 'CONFIRMATION_ROWS_BOUND')
    c.require(all(r['label'] is None and r['label_authority'] == 'UNKNOWN' for r in forecast_rows),
              'CONFIRMATION_ALREADY_LABELED')
    probability.evaluate(forecast_rows, event=model['event'], predictor_revision=model['original_method_revision'])
    c.require(model['training_rows_sha256'] == c.digest(training_rows), 'CONFIRMATION_TRAINING_DRIFT')
    overlaps = _overlaps(training_rows, forecast_rows)
    c.require(not any(overlaps.values()), 'CONFIRMATION_DEPENDENCY_OR_GROUP_OVERLAP')
    return c.seal(dict(kind='PUBLIC_PRELABEL_CALIBRATION_REGISTRATION_V1', model_sha256=c.digest(model),
        model=model, training_rows_sha256=c.digest(training_rows), forecast_rows=deepcopy(forecast_rows),
        forecast_rows_sha256=c.digest(forecast_rows), settings_sha256=c.digest(settings()),
        registered_at_jst=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),
        timestamp_authority='LOCAL_CLOCK_NOT_TRUSTED_TIME', source_provenance_verified=False,
        probability_calibration_certified=False, automatic_activation=False, execution_authority=False))


def _overlaps(training, confirmation):
    axes = ('id', 'source_group', 'target_group', 'mechanism_group', 'dependency_component')
    result = {a: sorted({r[a] for r in training} & {r[a] for r in confirmation}) for a in axes}
    for axis in ('source_content_sha256', 'reachable_module_sha256', 'external_distribution_sha256'):
        left = {v for r in training for v in r.get(axis, [])}
        right = {v for r in confirmation for v in r.get(axis, [])}
        result[axis] = sorted(left & right)
    return result


def review_calibration(registration, training_rows, confirmation_rows):
    """Report diagnostic scores without turning supplied rows into certification."""
    c, _, _, probability, calibration = _modules()
    c.check_seal(registration)
    c.require(type(confirmation_rows) is list and 1 <= len(confirmation_rows) <= 4096, 'CONFIRMATION_ROWS_BOUND')
    c.require(registration['kind'] == 'PUBLIC_PRELABEL_CALIBRATION_REGISTRATION_V1'
              and registration['settings_sha256'] == c.digest(settings())
              and registration['training_rows_sha256'] == c.digest(training_rows), 'CONFIRMATION_REGISTRATION_DRIFT')
    model = registration['model']
    c.require(c.digest(model) == registration['model_sha256'], 'CONFIRMATION_MODEL_DRIFT')
    expected = fit_calibration(training_rows, event=model['event'], predictor_revision=model['original_method_revision'])
    c.require(model == expected, 'CONFIRMATION_TRAINED_MODEL_DRIFT')
    unlabelled = deepcopy(confirmation_rows)
    for row in unlabelled:
        row['label'] = None
        row['label_authority'] = 'UNKNOWN'
    c.require(unlabelled == registration['forecast_rows']
              and c.digest(unlabelled) == registration['forecast_rows_sha256'], 'CONFIRMATION_FORECAST_DRIFT')
    c.require(not any(_overlaps(training_rows, confirmation_rows).values()), 'CONFIRMATION_GROUP_OVERLAP')
    raw = probability.evaluate(confirmation_rows, event=model['event'], predictor_revision=model['original_method_revision'])
    derived = probability.apply_postprocessor(model, confirmation_rows)
    corrected = probability.evaluate(derived, event=model['event'], predictor_revision=model['record_sha256'])
    policy = settings()['calibration']
    threshold = settings()['serving']['threshold']
    decisions = next(r for r in corrected['thresholds'] if r['threshold'] == threshold)
    gates = {
        'minimum_scored_rows': raw['scored_rows'] >= policy['minimum_natural_scored_rows'],
        'minimum_projects': raw['project_groups'] >= policy['minimum_natural_projects'],
        'minimum_declared_dependency_components': raw['dependency_components'] >= policy['minimum_dependency_components'],
        'minimum_pass_labels': raw['truth_counts'].get('PASS', 0) >= policy['minimum_pass_labels'],
        'minimum_fail_labels': raw['truth_counts'].get('FAIL', 0) >= policy['minimum_fail_labels'],
        'minimum_label_coverage': raw['scored_rows'] / raw['total_rows'] >= policy['minimum_label_coverage'],
        'minimum_selection_coverage': decisions['scored_selection_coverage'] >= policy['minimum_selection_coverage'],
        'minimum_brier_improvement': raw['scalar_binary_brier'] is not None and corrected['scalar_binary_brier'] is not None
            and raw['scalar_binary_brier'] - corrected['scalar_binary_brier'] >= policy['minimum_brier_improvement'],
        'maximum_empirical_ece': corrected['empirical_ece'] is not None
            and corrected['empirical_ece'] <= policy['maximum_empirical_ece'],
        'log_loss_nonregression': corrected['binary_log_loss'] is not None and not corrected['log_loss_infinite']
            and (raw['log_loss_infinite'] or raw['binary_log_loss'] is not None
                 and corrected['binary_log_loss'] <= raw['binary_log_loss']),
        'natural_forecast_and_native_label_provenance_verified': False,
    }
    reasons = ['NATURAL_FORECAST_AND_NATIVE_LABEL_PROVENANCE_NOT_VERIFIED_BY_PUBLIC_ROW_INPUT']
    reasons.extend('GATE_' + name.upper() for name, passed in gates.items() if not passed)
    return c.seal(dict(kind='PUBLIC_CALIBRATION_DIAGNOSTIC_REVIEW_V1', status='HELD',
        reasons=reasons, engineering_gates=gates,
        registration_sha256=c.digest(registration), raw=raw, candidate=corrected,
        serving=settings()['serving'], diagnostic_only=True, probability_calibration_certified=False,
        independent_generalization_certified=False, automatic_activation=False, execution_authority=False))
