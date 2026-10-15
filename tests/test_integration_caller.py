"""Synthetic component mocks only; the copied Target is never imported."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from reqlox import integration_worker as w


class CallerTests(unittest.TestCase):
    def test_exercise_fixed_order_and_payloads(self):
        fake = AsyncMock(return_value={'synthetic': True})
        with patch.object(w, 'composed_case', fake):
            rows = asyncio.run(w.exercise('api-mock', 'worker-mock', 'context-mock', Path('/synthetic')))
        self.assertEqual(len(rows), 10)
        self.assertEqual([call.args[4] for call in fake.call_args_list[:5]], list(w.FAULTS))
        self.assertEqual([call.args[5] for call in fake.call_args_list[5:9]], list(w.PAYLOADS))
        self.assertTrue(fake.call_args_list[-1].kwargs['preexisting'])

    def case(self, fault, *, release=True):
        # These explicitly owned mocks model the component boundary, not a Target implementation.
        api = SimpleNamespace(persist=Mock(side_effect=lambda path, data: path.write_bytes(data)))
        async def resource(lock, operation):
            await lock.acquire()
            try:
                await operation()
            finally:
                if release: lock.release()
        worker = SimpleNamespace(use_resource=AsyncMock(side_effect=resource))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            class ContextMock:
                def __enter__(self):
                    self.path = base / 'scratch-mock'; self.path.touch(); return self.path
                def __exit__(self, *args):
                    self.path.unlink()
            row = asyncio.run(w.composed_case(api, worker, ContextMock, base / 'case', fault, b'owned'))
        return row, api, worker

    def test_normal_composes_all_components_and_following_call(self):
        row, api, worker = self.case(None)
        self.assertTrue(row['passed']); self.assertEqual(api.persist.call_count, 2)
        self.assertEqual(worker.use_resource.await_count, 2)

    def test_exception_propagates_and_following_call_is_normal(self):
        row, api, worker = self.case('OPERATION_EXCEPTION_BEFORE_PERSIST')
        self.assertTrue(row['passed']); self.assertEqual(row['exception_type'], 'InjectedError')
        self.assertEqual(api.persist.call_count, 1)

    def test_real_async_task_cancellation_with_mock_components(self):
        row, api, worker = self.case('OPERATION_TASK_CANCEL_BEFORE_PERSIST')
        self.assertTrue(row['passed']); self.assertEqual(row['exception_type'], 'CancelledError')
        self.assertEqual(api.persist.call_count, 1)

    def test_leaked_mock_lock_detected_without_hanging(self):
        row, _, _ = self.case('OPERATION_EXCEPTION_BEFORE_PERSIST', release=False)
        self.assertFalse(row['passed']); self.assertFalse(row['lock_released'])
        self.assertEqual(row['following_normal_error'], 'TimeoutError')

    def test_failed_write_closes_stream_and_records_exact_fault(self):
        stream = MagicMock(); hit = []
        with self.assertRaises(w.InjectedError):
            with w.FailedWrite(stream, hit) as output:
                output.write(b'data')
        stream.__exit__.assert_called_once()
        self.assertEqual(hit, ['API_WRITE_ERROR'])
