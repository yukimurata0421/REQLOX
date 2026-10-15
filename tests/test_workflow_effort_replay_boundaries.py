"""Resealed effort traces retain semantic, ordering, and terminal checks."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import reqlox
reqlox._runtime()
from reqlox_core import incident_reference as reference
from reqlox_core import workflow_effort as effort


class EffortReplayBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.offset = 0
        self.count = 0

    def recorder(self, **options):
        self.count += 1
        return effort.Recorder(self.root / str(self.count), run_id='owned-run',
            binding={'target': 'a' * 64}, cost_sources={'api': 'USD'},
            clock=lambda: self.offset, cpu_clock=lambda: self.offset, **options)

    def completed(self):
        recorder = self.recorder()
        with recorder.stage('probe'):
            self.offset += 2000000000
        recorder.finish()
        return recorder

    def reseal(self, recorder, mutate):
        events = deepcopy(recorder.events)
        mutate(events)
        previous = reference.digest(recorder.meta)
        for index, event in enumerate(events):
            event['previous_sha256'] = previous
            events[index] = reference.seal(event)
            previous = reference.digest(events[index])
        return events

    def test_recorder_copies_binding_and_cost_source_inputs(self):
        binding = {'target': {'revision': 'original'}}
        sources = {'api': 'USD'}
        recorder = effort.Recorder(self.root / 'copy', run_id='owned-run', binding=binding,
            cost_sources=sources, clock=lambda: self.offset)
        binding['target']['revision'] = 'changed'
        sources['api'] = 'JPY'
        recorder.cost('api', reserved='1')
        result = recorder.finish()
        self.assertEqual(result['binding'], {'target': {'revision': 'original'}})
        self.assertEqual(result['cost_sources'], {'api': 'USD'})
        self.assertEqual(effort.read(recorder.directory), result)

    def test_recorder_copies_activity_intervals_before_persisting(self):
        recorder = self.recorder(human_tracking_complete=True)
        self.offset = 2000000000
        intervals = [[0, 1000000000]]
        recorder.intervention('REVIEW', active_intervals_ns=intervals,
            wait_interval_ns=[1000000000, 2000000000], basis='INSTRUMENTED')
        intervals[0][1] = 999999999999
        result = recorder.finish()
        self.assertEqual(result['human_active_seconds'], 1)
        self.assertEqual(result['human_wait_seconds'], 1)
        self.assertEqual(effort.read(recorder.directory), result)

    def test_resealed_sequence_boolean_or_gap_is_rejected(self):
        recorder = self.completed()
        for sequence in (True, 7):
            events = self.reseal(recorder, lambda rows: rows[1].update(sequence=sequence))
            with self.subTest(sequence=sequence), self.assertRaisesRegex(ValueError, 'EFFORT_TRACE_CHAIN'):
                effort.summarize(recorder.meta, events)

    def test_resealed_clock_boolean_or_regression_is_rejected(self):
        recorder = self.completed()
        for offset in (True, -1, 0):
            events = self.reseal(recorder, lambda rows: rows[-1].update(offset_ns=offset))
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'EFFORT_CLOCK'):
                effort.summarize(recorder.meta, events)

    def test_resealed_unknown_event_kind_and_extra_fields_are_rejected(self):
        recorder = self.completed()
        mutations = (lambda rows: rows[0].update(kind='EXECUTE'),
                     lambda rows: rows[0].update(execution_authority=True))
        for mutate in mutations:
            events = self.reseal(recorder, mutate)
            with self.subTest(mutate=mutate), self.assertRaisesRegex(ValueError, 'EFFORT_EVENT_KIND|EFFORT_TRACE_CHAIN'):
                effort.summarize(recorder.meta, events)

    def test_resealed_stage_end_cannot_refer_to_another_stage(self):
        recorder = self.completed()
        events = self.reseal(recorder, lambda rows: rows[1]['data'].update(id='unstarted'))
        with self.assertRaisesRegex(ValueError, 'EFFORT_STAGE_END'):
            effort.summarize(recorder.meta, events)

    def test_resealed_stage_cpu_counters_require_nonnegative_integers(self):
        recorder = self.completed()
        for key in ('cpu_parent_ns', 'cpu_children_ns'):
            for value in (True, -1, 0.0):
                events = self.reseal(recorder, lambda rows: rows[1]['data'].update({key: value}))
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'EFFORT_STAGE_STATUS'):
                    effort.summarize(recorder.meta, events)

    def test_resealed_success_cannot_retain_an_error_class(self):
        recorder = self.completed()
        events = self.reseal(recorder, lambda rows: rows[1]['data'].update(error_class='RuntimeError'))
        with self.assertRaisesRegex(ValueError, 'EFFORT_STAGE_ERROR'):
            effort.summarize(recorder.meta, events)

    def test_resealed_cost_cannot_move_between_currencies(self):
        recorder = self.recorder()
        recorder.cost('api', reserved='1')
        recorder.finish()
        events = self.reseal(recorder, lambda rows: rows[0]['data'].update(currency='JPY'))
        with self.assertRaisesRegex(ValueError, 'EFFORT_COST_IDENTITY'):
            effort.summarize(recorder.meta, events)

    def test_resealed_event_after_terminal_is_rejected(self):
        recorder = self.completed()
        events = self.reseal(recorder, lambda rows: rows.append({
            'sequence': len(rows), 'offset_ns': self.offset, 'kind': 'STAGE_START',
            'data': {'id': 'later', 'name': 'probe'}}))
        with self.assertRaisesRegex(ValueError, 'EFFORT_TERMINAL'):
            effort.summarize(recorder.meta, events)

    def test_missing_terminal_is_rejected_even_with_a_valid_remaining_chain(self):
        recorder = self.completed()
        events = self.reseal(recorder, lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, 'EFFORT_TERMINAL_REQUIRED'):
            effort.summarize(recorder.meta, events)

    def test_failed_stage_and_workflow_completion_remain_separate(self):
        recorder = self.recorder()
        with self.assertRaises(RuntimeError):
            with recorder.stage('probe'):
                raise RuntimeError('owned failure')
        result = recorder.finish()
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['failed_stages'], 1)
        self.assertEqual(result['stages'][0]['error_class'], 'RuntimeError')
        self.assertFalse(result['measurement_grants_execution_authority'])
        self.assertEqual(effort.read(recorder.directory), result)

    def test_replay_rejects_missing_and_extra_event_file_numbers(self):
        for missing in (True, False):
            recorder = self.completed()
            first = recorder.directory / 'events/0000.json'
            if missing:
                first.unlink()
            else:
                (recorder.directory / 'events/9999.json').write_bytes(first.read_bytes())
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'EFFORT_EVENT_FILES'):
                effort.read(recorder.directory)

    def test_replay_rejects_symlinked_metadata_summary_and_event_files(self):
        for relative in ('metadata.json', 'summary.json', 'events/0000.json'):
            recorder = self.completed()
            path = recorder.directory / relative
            saved = recorder.directory / ('saved-' + path.name)
            path.rename(saved)
            path.symlink_to(saved)
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'EFFORT_SYMLINK|EFFORT_EVENT_FILES'):
                effort.read(recorder.directory)

    def test_resealed_metadata_change_does_not_rebind_existing_events(self):
        recorder = self.completed()
        path = recorder.directory / 'metadata.json'
        metadata = json.loads(path.read_bytes())
        metadata['binding']['target'] = 'b' * 64
        path.write_bytes(reference.canonical(reference.seal(metadata)))
        with self.assertRaisesRegex(ValueError, 'EFFORT_TRACE_CHAIN'):
            effort.read(recorder.directory)


if __name__ == '__main__':
    unittest.main()
