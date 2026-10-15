"Fit diagnostic calibration candidates using training data only."
from collections import Counter
from copy import deepcopy
import math

import incident_choice_response as responses
import incident_reference as c
import reliability_probability_evaluation as probability

GROUP_AXES = ('source_group', 'target_group', 'mechanism_group', 'dependency_component')
EPSILON = 1e-6
REGULARIZATION = .05
MAXIMUM_ROWS = 4096


def validate_settings(settings):
    c.check_seal(settings)
    c.require(set(settings) == {'schema_version', 'profile', 'event', 'predictor_revision', 'preparation',
        'calibration', 'stage_order', 'human_time_measured', 'automatic_retry',
        'execution_authority', 'probability_calibration_certified', 'record_sha256'}, 'CALIBRATION_SETTINGS_FIELDS')
    c.require(settings['schema_version'] == 'reqlox.generalization-calibration-settings.v0.1'
              and settings['profile'] == 'DOCUMENTED_SYNC_PATH_CONTEXT_V1'
              and settings['event'] == 'FINITE_PATH_CONTEXT_RESOURCE_RELEASE_V1'
              and settings['execution_authority'] is False
              and settings['probability_calibration_certified'] is False,
              'CALIBRATION_SETTINGS_BOUNDARY')
    c.require(type(settings['predictor_revision']) is str and len(settings['predictor_revision']) == 64
        and settings['stage_order'] == ['LOCAL_HISTORY', 'FREEZE', 'ACQUIRE', 'STATIC_PREPARE',
            'DEPENDENCY_AND_INPUT_PREFLIGHT', 'PREPARE_FORECAST', 'AUTHORIZED_FORECAST',
            'FREEZE_BEFORE_LABELS', 'NATIVE_GOLD', 'TRAIN_OR_CONFIRM', 'ADOPTION_REVIEW']
        and settings['human_time_measured'] is settings['automatic_retry'] is False, 'CALIBRATION_SETTINGS_STAGES')
    policy = settings['calibration']
    c.require(set(policy) == {'feature_clipping_epsilon', 'slope_l2_regularization',
        'training_weighting', 'split_axes', 'decision_threshold', 'minimum_natural_scored_rows',
        'minimum_natural_projects', 'minimum_dependency_components', 'minimum_pass_labels',
        'minimum_fail_labels', 'minimum_label_coverage', 'minimum_selection_coverage',
        'maximum_empirical_ece', 'minimum_brier_improvement', 'require_group_nonregression'},
        'CALIBRATION_POLICY_FIELDS')
    c.require(policy['feature_clipping_epsilon'] == EPSILON
        and policy['slope_l2_regularization'] == REGULARIZATION
        and policy['training_weighting'] == 'EQUAL_DEPENDENCY_COMPONENT'
        and policy['split_axes'] == list(GROUP_AXES)
        and policy['decision_threshold'] == .85
        and policy['require_group_nonregression'] is True,
        'CALIBRATION_POLICY_FIXED_METHOD')
    for key in ('minimum_natural_scored_rows', 'minimum_natural_projects',
                'minimum_dependency_components', 'minimum_pass_labels', 'minimum_fail_labels'):
        c.require(type(policy[key]) is int and 2 <= policy[key] <= MAXIMUM_ROWS,
                  'CALIBRATION_POLICY_SAMPLE_BOUND')
    for key in ('minimum_label_coverage', 'minimum_selection_coverage', 'maximum_empirical_ece',
                'minimum_brier_improvement'):
        value = policy[key]
        c.require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1,
                  'CALIBRATION_POLICY_SCORE_BOUND')
    limits = settings['preparation']
    c.require(set(limits) == {'maximum_projects', 'maximum_archives', 'maximum_requests',
                            'maximum_request_bytes', 'source_selection', 'missing_dependency'},
              'CALIBRATION_PREPARATION_FIELDS')
    c.require(type(limits['maximum_projects']) is int and 1 <= limits['maximum_projects'] <= 12
        and type(limits['maximum_archives']) is int and 1 <= limits['maximum_archives'] <= 8
        and limits['maximum_requests'] == limits['maximum_projects'] + limits['maximum_archives']
        and limits['maximum_request_bytes'] == 24576
        and limits['source_selection'] == 'ORIGINAL_PACKAGE_SOURCES_NO_TRUNCATION'
        and limits['missing_dependency'] == 'HOLD_BEFORE_FORECAST', 'CALIBRATION_PREPARATION_BOUND')
    return settings


def _validate_rows(rows, event, revision):
    c.require(type(rows) is list and 1 <= len(rows) <= MAXIMUM_ROWS, 'CALIBRATION_ROWS_BOUND')
    probability.evaluate(rows, event=event, predictor_revision=revision)


def _sigmoid(z):
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def _feature(p):
    p = min(1 - EPSILON, max(EPSILON, p))
    return math.log(p) - math.log1p(-p)


def parameters(points):
    "Parameters."
    prior = math.fsum(w * y for _, y, w in points)
    c.require(0 < prior < 1, 'CALIBRATION_BOTH_LABELS_REQUIRED')
    a, b = 0., math.log(prior) - math.log1p(-prior)

    def objective(a, b):
        return math.fsum(w * (max(z, 0) + math.log1p(math.exp(-abs(z))) - y * z)
                        for x, y, w in points for z in [a * x + b]) + REGULARIZATION * a * a / 2

    for iteration in range(200):
        ga, gb, haa, hab, hbb = REGULARIZATION * a, 0., REGULARIZATION, 0., 0.
        for x, y, w in points:
            p = _sigmoid(a * x + b)
            delta, variance = w * (p - y), w * p * (1 - p)
            ga += delta * x; gb += delta
            haa += variance * x * x; hab += variance * x; hbb += variance
        projected = ga if a > 0 else min(0., ga)
        if max(abs(projected), abs(gb)) <= 1e-9:
            return dict(slope=a, intercept=b, iterations=iteration + 1, converged=True,
                        projected_gradient_maximum=max(abs(projected), abs(gb)))
        c.require(hbb > 0, 'CALIBRATION_HESSIAN')
        if a == 0 and ga >= 0:
            da, db = 0., gb / hbb
        else:
            determinant = haa * hbb - hab * hab
            c.require(determinant > 0, 'CALIBRATION_HESSIAN')
            da, db = (hbb * ga - hab * gb) / determinant, (haa * gb - hab * ga) / determinant
        old, scale = objective(a, b), 1.
        for _ in range(60):
            na, nb = max(0., a - scale * da), b - scale * db
            if objective(na, nb) <= old + 1e-15:
                break
            scale /= 2
        else:
            raise ValueError('CALIBRATION_LINE_SEARCH')
        a, b = na, nb
    raise ValueError('CALIBRATION_NONCONVERGENCE')


def fit(rows, *, event, predictor_revision, training_ref):
    "Fit."
    _validate_rows(rows, event, predictor_revision)
    checked = [responses.check(r.get('answer'), ['PASS', 'FAIL']) for r in rows]
    c.require(all(r['label'] is not None for r in rows), 'CALIBRATION_UNKNOWN_TRAINING_LABEL')
    c.require(all(v['status'] == 'VALID' for v in checked), 'CALIBRATION_INVALID_TRAINING_FORECAST')
    c.require({r['label'] for r in rows} == {'PASS', 'FAIL'}, 'CALIBRATION_BOTH_LABELS_REQUIRED')
    components = probability.component_assignments(rows)
    counts = Counter(components.values())
    points = [(_feature(v['probabilities']['PASS']), int(r['label'] == 'PASS'),
               1 / len(counts) / counts[components[r['id']]]) for r, v in zip(rows, checked)]
    return c.seal(dict(schema_version='reqlox.finite-forecast-sigmoid.v0.1', event=event,
        original_method_revision=predictor_revision, training_ref=deepcopy(training_ref),
        training_rows_sha256=c.digest(rows), training_ids=[r['id'] for r in rows], training_rows=len(rows),
        training_dependency_components=len(counts), training_weighting='EQUAL_DEPENDENCY_COMPONENT',
        fitter='BOUNDED_PROJECTED_NEWTON_V1', parameters=parameters(points),
        feature='LOGIT_OF_RAW_PASS_SCORE_WITH_DECLARED_FEATURE_CLIPPING', feature_clipping_epsilon=EPSILON,
        slope_l2_regularization=REGULARIZATION, nonnegative_slope=True, raw_probabilities_rewritten=False,
        development_candidate_only=True, probabilities_calibrated=False,
        independent_samples_certified=False, execution_authority=False))


def _decision(rows, threshold):
    accepted = []; false_accepts = false_rejects = 0
    for row in rows:
        value = responses.check(row.get('answer'), ['PASS', 'FAIL'])
        if value['status'] != 'VALID' or max(value['probabilities'].values()) < threshold:
            continue
        if row['label'] is None:
            continue
        choice = value['choice']; accepted.append(row['id'])
        false_accepts += choice == 'PASS' and row['label'] == 'FAIL'
        false_rejects += choice == 'FAIL' and row['label'] == 'PASS'
    return dict(false_accepts=false_accepts, false_rejects=false_rejects,
                scored_selection_coverage=len(accepted) / len(rows), selected_ids=accepted)


def assess(settings, model, training_rows, evaluation_rows, *, registration=None, binding_checks=None,
           natural_ids=()):
    "Assess."
    validate_settings(settings);c.check_seal(model)
    if registration is not None:c.check_seal(registration)
    event, revision = settings['event'], settings['predictor_revision']
    _validate_rows(training_rows, event, revision);_validate_rows(evaluation_rows, event, revision)
    expected = fit(training_rows, event=event, predictor_revision=revision, training_ref=model['training_ref'])
    c.require(model['training_ids'] == expected['training_ids']
        and model['training_rows_sha256'] == expected['training_rows_sha256']
        and all(abs(model['parameters'][key] - expected['parameters'][key]) <= 1e-8
                for key in ('slope', 'intercept')), 'CALIBRATION_MODEL_TRAINING_DRIFT')
    raw = probability.evaluate(evaluation_rows, event=event, predictor_revision=revision, binding_checks=binding_checks)
    if binding_checks is not None:
        c.require(all(check['kind'] != 'RAW_CONTEXT_FORECAST_EXECUTION_BINDING_CHECK_V1'
            or check['fixed_postprocessor_sha256'] in (None, model['record_sha256'])
            for check in binding_checks), 'PROBABILITY_BINDING_DRIFT')
    # An otherwise verified raw forecast may deliberately have no prelabel
    # postprocessor. Keep it in the denominator, without retrofitting the model.
    missing_fixed_model = binding_checks is not None and any(
        check['kind'] == 'RAW_CONTEXT_FORECAST_EXECUTION_BINDING_CHECK_V1'
        and check['fixed_postprocessor_sha256'] is None for check in binding_checks)
    derived = None if missing_fixed_model else probability.apply_postprocessor(model, evaluation_rows)
    corrected = None if missing_fixed_model else probability.evaluate(
        derived, event=event, predictor_revision=model['record_sha256'], binding_checks=binding_checks)
    policy = settings['calibration'];reasons = []
    def gate(ok, reason):
        if not ok:reasons.append(reason)
    overlap = {axis: sorted({r[axis] for r in training_rows} & {r[axis] for r in evaluation_rows})
               for axis in GROUP_AXES}
    gate(not any(overlap.values()), 'TRAINING_EVALUATION_GROUP_OVERLAP')
    gate(registration is not None and registration.get('status') == 'VERIFIED_PRELABEL_INPUT_BINDINGS'
         and registration.get('settings_sha256') == settings['record_sha256']
         and registration.get('model_sha256') == model['record_sha256']
         and registration.get('evaluation_ids') == [r['id'] for r in evaluation_rows],
         'PRELABEL_EVALUATION_REGISTRATION_MISSING')
    gate(raw['forecast_execution_bindings_verified'], 'FORECAST_EXECUTION_BINDINGS_MISSING')
    gate(not missing_fixed_model, 'POSTPROCESSOR_NOT_FROZEN_BEFORE_LABELS')
    natural = set(natural_ids)
    gate(natural == {r['id'] for r in evaluation_rows}, 'NATURAL_OSS_PROVENANCE_INCOMPLETE')
    scored = [r for r in evaluation_rows if r['label'] is not None
              and responses.check(r.get('answer'), ['PASS', 'FAIL'])['status'] == 'VALID']
    labels = Counter(r['label'] for r in scored)
    gate(len(scored) >= policy['minimum_natural_scored_rows'], 'NATURAL_SCORED_ROWS_INSUFFICIENT')
    gate(len({r['target_group'] for r in scored}) >= policy['minimum_natural_projects'],
         'NATURAL_PROJECTS_INSUFFICIENT')
    components = probability.component_assignments(evaluation_rows)
    scored_components = len({components[r['id']] for r in scored})
    gate(scored_components >= policy['minimum_dependency_components'], 'DEPENDENCE_SUPPORT_INSUFFICIENT')
    gate(all(r['label_authority'] == 'NATIVE_FINITE_REQUIREMENT_ORACLE' for r in scored),
         'NATURAL_LABEL_AUTHORITY_INCOMPLETE')
    for label, key in [('PASS', 'minimum_pass_labels'), ('FAIL', 'minimum_fail_labels')]:
        gate(labels[label] >= policy[key], 'NATURAL_' + label + '_LABELS_INSUFFICIENT')
    gate(len(scored) / len(evaluation_rows) >= policy['minimum_label_coverage'], 'LABEL_COVERAGE_INSUFFICIENT')
    if corrected is not None:
        gate(raw['scalar_binary_brier'] is not None and corrected['scalar_binary_brier'] is not None
         and raw['scalar_binary_brier'] - corrected['scalar_binary_brier'] >= policy['minimum_brier_improvement'],
         'BRIER_IMPROVEMENT_INSUFFICIENT')
        gate(corrected['binary_log_loss'] is not None and not corrected['log_loss_infinite']
         and (raw['log_loss_infinite'] or raw['binary_log_loss'] is not None
              and corrected['binary_log_loss'] <= raw['binary_log_loss'] + 1e-12), 'LOG_LOSS_REGRESSION')
        gate(corrected['empirical_ece'] is not None and corrected['empirical_ece'] <= policy['maximum_empirical_ece'],
         'EMPIRICAL_RELIABILITY_GAP_TOO_LARGE')
    group_regressions = None if missing_fixed_model else []
    for axis in (() if missing_fixed_model else ('target_group', 'mechanism_group', 'dependency_component')):
        for name in sorted({r[axis] for r in evaluation_rows}):
            original = [r for r in evaluation_rows if r[axis] == name]
            changed = [r for r in derived if r[axis] == name]
            before = probability.evaluate(original, event=event, predictor_revision=revision)
            after = probability.evaluate(changed, event=event, predictor_revision=model['record_sha256'])
            if before['scalar_binary_brier'] is None:continue
            if after['scalar_binary_brier'] > before['scalar_binary_brier'] + 1e-12 or (
                not before['log_loss_infinite'] and (after['log_loss_infinite']
                or after['binary_log_loss'] > before['binary_log_loss'] + 1e-12)):
                group_regressions.append(dict(axis=axis, group=name))
    before = _decision(evaluation_rows, policy['decision_threshold'])
    after = None if missing_fixed_model else _decision(derived, policy['decision_threshold'])
    if after is not None:
        gate(not group_regressions, 'GROUP_SCORE_REGRESSION')
        gate(after['false_accepts'] <= before['false_accepts'], 'FALSE_ACCEPT_REGRESSION')
        gate(after['false_rejects'] <= before['false_rejects'], 'FALSE_REJECT_REGRESSION')
        gate(after['scored_selection_coverage'] >= max(policy['minimum_selection_coverage'],
                                                  before['scored_selection_coverage']), 'SELECTION_COVERAGE_REGRESSION')
    candidate = not reasons
    return c.seal(dict(kind='FINITE_CALIBRATION_ADOPTION_REVIEW_V1',
        status='SCOPED_CANDIDATE_ELIGIBLE' if candidate else 'HELD', reasons=reasons,
        settings_sha256=settings['record_sha256'], model_sha256=model['record_sha256'],
        raw_evaluation=raw, postprocessed_evaluation=corrected, group_overlap=overlap,
        postprocessing_status='HELD_POSTPROCESSOR_NOT_FROZEN_BEFORE_LABELS' if missing_fixed_model else 'EVALUATED',
        scored_dependency_components=scored_components,
        group_score_regressions=group_regressions, raw_decision=before, postprocessed_decision=after,
        serving=dict(mode='SCOPED_CANDIDATE_REQUIRES_EXPLICIT_ACTIVATION' if candidate else 'RAW',
                     threshold=policy['decision_threshold'], postprocessor_sha256=None),
        minimum_counts_are_engineering_gates_not_statistical_proof=True,
        probability_calibration_certified=False, independent_generalization_certified=False,
        iid_attested=False, confidence_interval=None, model_automatically_activated=False,
        execution_authority=False))
