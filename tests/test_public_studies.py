"""Exercise leakage, missing evidence, artifact drift, and shared budgets."""
import base64
from copy import deepcopy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import reqlox
from reqlox import studies
from reqlox.capsule import inspect_wheels
from reqlox.study_cli import _write

ROOT = Path(__file__).resolve().parents[1]


def wheel(directory, name='owned-example', requirements=(), source=None):
    module = name.replace('-', '_')
    prefix = module + '-1.0.dist-info/'
    files = {module + '.py': (source or 'raise RuntimeError("target code must not be imported during preparation")\n').encode(),
             prefix + 'METADATA': ('Metadata-Version: 2.4\nName: ' + name + '\nVersion: 1.0\n' +
                 ''.join('Requires-Dist: ' + r + '\n' for r in requirements)).encode(),
             prefix + 'WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             prefix + 'licenses/LICENSE': b'Owned synthetic fixture notice\n'}
    table = io.StringIO()
    writer = csv.writer(table)
    for member, raw in files.items():
        writer.writerow([member, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='), str(len(raw))])
    writer.writerow([prefix + 'RECORD', '', ''])
    files[prefix + 'RECORD'] = table.getvalue().encode()
    path = Path(directory) / (module + '-1.0-py3-none-any.whl')
    with zipfile.ZipFile(path, 'w') as archive:
        for member, raw in files.items():
            archive.writestr(member, raw)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class CapsuleTests(unittest.TestCase):
    def test_inspection_does_not_import_target_and_missing_dependencies_hold(self):
        with tempfile.TemporaryDirectory() as d:
            spec = wheel(d, requirements=['helper>=1,<2'])
            value = inspect_wheels([spec], target_project='owned-example')
            self.assertEqual(value['status'], 'HELD')
            self.assertFalse(value['package_code_imported'])
            self.assertIn('DEPENDENCY_WHEEL_MISSING', {r['reason'] for r in value['holds']})

    def test_dependency_version_and_original_source_files_are_bound(self):
        with tempfile.TemporaryDirectory() as d:
            target = wheel(d, requirements=['helper>=1,<2'])
            helper = wheel(d, name='helper')
            value = inspect_wheels([target, helper], target_project='owned-example')
            self.assertEqual(value['status'], 'READY_STATICALLY')
            self.assertEqual(value['dependency_edges']['owned-example'], ['helper'])
            self.assertEqual(len(value['distributions']), 2)
            self.assertFalse(value['rights_approval_inferred'])

    def test_hash_drift_and_record_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            spec = wheel(d)
            with self.assertRaisesRegex(ValueError, 'WHEEL_HASH_DRIFT'):
                inspect_wheels([dict(spec, sha256='0' * 64)], target_project='owned-example')
            path = Path(spec['path'])
            with zipfile.ZipFile(path) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
            files['owned_example.py'] = b'pass\n'
            with zipfile.ZipFile(path, 'w') as archive:
                for name, raw in files.items():
                    archive.writestr(name, raw)
            spec['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'WHEEL_RECORD_DRIFT'):
                inspect_wheels([spec], target_project='owned-example')

    def test_mismatched_versions_and_extras_hold(self):
        for requirement, reason in [('helper>=2', 'DEPENDENCY_VERSION_MISMATCH'),
                                    ('helper[extra]>=1', 'DEPENDENCY_URL_OR_EXTRAS_UNSUPPORTED')]:
            with self.subTest(requirement=requirement), tempfile.TemporaryDirectory() as d:
                value = inspect_wheels([wheel(d, requirements=[requirement]), wheel(d, name='helper')],
                                       target_project='owned-example')
                self.assertIn(reason, {r['reason'] for r in value['holds']})

    def test_wheel_filename_and_metadata_identity_must_agree(self):
        with tempfile.TemporaryDirectory() as d:
            spec = wheel(d)
            changed = Path(d)/'another_project-1.0-py3-none-any.whl'
            Path(spec['path']).rename(changed)
            with self.assertRaisesRegex(ValueError, 'FILENAME_METADATA_DRIFT'):
                inspect_wheels([dict(spec, path=str(changed))], target_project='owned-example')

    def test_invalid_archive_is_a_structured_boundary_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'owned_example-1.0-py3-none-any.whl'
            p.write_bytes(b'not a wheel archive')
            with self.assertRaisesRegex(ValueError, 'ARCHIVE_OR_ENCODING_INVALID'):
                inspect_wheels([dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())],
                               target_project='owned-example')


class PreparationAndComparisonTests(unittest.TestCase):
    def setUp(self):
        p = ROOT / 'examples/evaluation/repository/owned_context.py'
        self.sources = {p.name: p.read_text()}

    def test_author_documentation_discovers_a_caller_without_behavior_as_spec(self):
        value = studies.prepare_context(self.sources, {}, project='owned-example')
        self.assertEqual(value['status'], 'READY_STATICALLY')
        self.assertEqual(len(value['recipes']), 1)
        self.assertFalse(value['implementation_behavior_used_as_specification'])
        self.assertFalse(value['all_chat_unused_verified'])

    def test_declared_history_and_missing_dependency_hold_before_execution(self):
        value = studies.prepare_context(self.sources, {}, project='Owned_Example', known_projects=['owned-example'])
        self.assertEqual(value['status'], 'HELD')
        sources = dict(self.sources)
        sources['owned_context.py'] = 'import missing_public_dependency\n' + sources['owned_context.py']
        value = studies.prepare_context(sources, {}, project='owned-example')
        self.assertIn('MISSING_PINNED_DEPENDENCY', {r['reason'] for r in value['holds']})

    def test_source_never_changes_the_source_blind_arm_or_common_budget(self):
        prepared = studies.prepare_context(self.sources, {}, project='owned-example')
        before = deepcopy(prepared)
        first = studies.freeze_comparison(prepared, studies.supplied_source({'r': 'unlink failed with EIO.'}, url='https://example.test/owned'))
        second = studies.freeze_comparison(prepared, studies.supplied_source({'r': 'unlink failed with EBUSY.'}, url='https://example.test/owned'))
        self.assertEqual(first['plans']['NO_SOURCE'], second['plans']['NO_SOURCE'])
        self.assertEqual(len(first['plans']['SOURCE']), len(first['plans']['NO_SOURCE']))
        self.assertTrue(first['no_source_target_guided_condition_generation'])
        self.assertFalse(first['baseline_is_exhaustive'])
        self.assertEqual(prepared, before)

    def test_zero_campaign_limit_retains_terminal_without_launching(self):
        prepared = studies.prepare_context(self.sources, {}, project='owned-example')
        frozen = studies.freeze_comparison(prepared, studies.supplied_source({'r': 'unlink failed with EIO.'}, url='https://example.test/owned'))
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'REQLOX_STATE_DIR': str(Path(d)/'state')}):
            from reqlox_paths import ensure_state
            state = ensure_state()
            output = state / 'zero-budget'
            with self.assertRaisesRegex(ValueError, 'CAMPAIGN_BOUND'):
                studies.run_comparison(frozen, output, maximum_campaigns=0)
            self.assertTrue((output/'terminal.json').is_file())
            self.assertEqual(list(output.rglob('launch.json')), [])

    def test_capsule_targets_do_not_discover_only_dependency_callers(self):
        with tempfile.TemporaryDirectory() as d:
            source = next(iter(self.sources.values()))
            value = inspect_wheels([wheel(d, requirements=['helper>=1']), wheel(d, name='helper', source=source)],
                                   target_project='owned-example')
            prepared = studies.prepare_context(value['sources'], {}, project='owned-example', capsule=value)
            self.assertEqual(prepared['status'], 'HELD')
            self.assertEqual(prepared['recipes'], [])

    def test_repair_rebinds_position_without_replacing_original_author_evidence(self):
        import reliability_path_context as context
        prepared = studies.prepare_context(self.sources, {}, project='owned-example')
        original = prepared['recipes'][0]
        modified = {n: '# An extra line in a private candidate.\n' + text for n, text in self.sources.items()}
        rebound = context.candidate_recipe(original, modified, {})
        self.assertNotEqual(rebound['span']['start'], original['span']['start'])
        self.assertEqual(rebound['span']['sha256'], original['span']['sha256'])
        self.assertEqual(rebound['signature_sha256'], original['signature_sha256'])
        changed_docs = {n: text.replace('owned temporary file', 'another invocation file') for n, text in modified.items()}
        with self.assertRaises(ValueError):
            context.candidate_recipe(original, changed_docs, {})
        changed_signature = {n: text.replace('def __init__(self, path):', 'def __init__(self, path, extra=1):')
                             for n, text in modified.items()}
        with self.assertRaises(ValueError):
            context.candidate_recipe(original, changed_signature, {})


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        data = ROOT / 'examples/evaluation'
        self.training = json.loads((data/'training.json').read_text())
        self.forecasts = json.loads((data/'forecasts.json').read_text())
        self.confirmation = json.loads((data/'confirmation.json').read_text())
        self.model = studies.fit_calibration(self.training['rows'], event=self.training['event'],
                                            predictor_revision=self.training['predictor_revision'])

    def register(self, forecasts=None):
        return studies.register_confirmation(self.model, self.training['rows'],
            self.forecasts['rows'] if forecasts is None else forecasts)

    def test_unknown_and_missing_forecasts_remain_in_denominator(self):
        rows = deepcopy(self.confirmation['rows'])
        rows[0]['answer'] = None
        report = studies.score_forecasts(rows, event=self.training['event'],
                                        predictor_revision=self.training['predictor_revision'])
        self.assertEqual(report['total_rows'], 3)
        self.assertEqual(report['scored_rows'], 1)
        self.assertFalse(report['probabilities_calibrated'])

    def test_prelabel_registration_rejects_labeled_inputs_and_shared_content(self):
        with self.assertRaisesRegex(ValueError, 'ROWS_BOUND'):
            self.register([])
        with self.assertRaisesRegex(ValueError, 'ALREADY_LABELED'):
            self.register(self.confirmation['rows'])
        for axis in ['source_group', 'target_group', 'mechanism_group', 'dependency_component']:
            rows = deepcopy(self.forecasts['rows'])
            rows[0][axis] = self.training['rows'][0][axis]
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, 'OVERLAP'):
                self.register(rows)
        self.training['rows'][0]['reachable_module_sha256'] = ['shared-content']
        self.model = studies.fit_calibration(self.training['rows'], event=self.training['event'],
                                            predictor_revision=self.training['predictor_revision'])
        rows = deepcopy(self.forecasts['rows'])
        rows[0]['reachable_module_sha256'] = ['shared-content']
        with self.assertRaisesRegex(ValueError, 'OVERLAP'):
            self.register(rows)

    def test_review_rejects_changed_forecasts_and_never_certifies_synthetic_rows(self):
        registration = self.register()
        rows = deepcopy(self.confirmation['rows'])
        rows[0]['answer']['probabilities'] = {'PASS': .9, 'FAIL': .1}
        with self.assertRaisesRegex(ValueError, 'FORECAST_DRIFT'):
            studies.review_calibration(registration, self.training['rows'], rows)
        report = studies.review_calibration(registration, self.training['rows'], self.confirmation['rows'])
        self.assertEqual(report['status'], 'HELD')
        self.assertFalse(report['automatic_activation'])
        self.assertFalse(report['probability_calibration_certified'])
        self.assertEqual(report['serving']['mode'], 'RAW')

    def test_unknown_training_labels_and_normalized_probabilities_are_rejected(self):
        for change in ('unknown', 'normalized'):
            rows = deepcopy(self.training['rows'])
            if change == 'unknown':
                rows[0]['label'] = None
                rows[0]['label_authority'] = 'UNKNOWN'
            else:
                rows[0]['answer']['normalization_applied'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                studies.fit_calibration(rows, event=self.training['event'],
                                        predictor_revision=self.training['predictor_revision'])

    def test_outputs_cannot_replace_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'result.json'
            _write(p, {'owned': True})
            with self.assertRaisesRegex(ValueError, 'ALREADY_EXISTS'):
                _write(p, {'owned': False})
            self.assertEqual(json.loads(p.read_text()), {'owned': True})
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_PACKAGE'):
            _write(ROOT/'unpublished-input.json', {'private': True})
