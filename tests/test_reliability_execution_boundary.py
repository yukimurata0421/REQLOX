"""Launcher limits and unsafe observations are rejected without native workers."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import reqlox
reqlox._runtime()
import run_reliability_reuse as runner


class ExecutionBoundaryTests(unittest.TestCase):
    def test_launcher_is_limited_before_namespace_setup_and_failed_attempt_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'attempt'
            with patch.object(runner, 'method_identity', return_value={}), \
                 patch.object(runner, 'runtime_identity', return_value={}), \
                 patch.object(runner.subprocess, 'Popen', side_effect=OSError('owned launch failure')) as launch:
                with self.assertRaises(OSError):
                    runner.execute(directory, {}, Path(temporary))
            command = launch.call_args.args[0]
            self.assertEqual(command[:7], ['/usr/bin/prlimit', '--cpu=2:2', '--as=134217728:134217728',
                '--fsize=131072:131072', '--core=0:0', '--', '/usr/bin/bwrap'])
            self.assertIn('--unshare-all', command)
            self.assertIn('--clearenv', command)
            self.assertEqual(command[command.index('--cap-drop')+1], 'ALL')
            receipt = json.loads((directory/'receipt.json').read_text())
            self.assertEqual(receipt['status'], 'STOPPED')
            self.assertFalse(receipt['automatic_retry'])

    def test_observed_root_capability_home_or_unbounded_resources_fail_closed(self):
        plan = {'site': {'family': 'atomic_file'}}
        parent = {name: name+'-parent' for name in ('user','mnt','pid','net')}
        boundary = dict(uid=1000, effective_capabilities=0, home_visible=False,
            cpu_seconds=[2,2], memory_bytes=[134217728,134217728],
            file_bytes=[131072,131072], core_bytes=[0,0])
        observed = dict(plan_sha256=runner.reuse.c.digest(plan), family='atomic_file',
            namespaces={name:name+'-child' for name in parent}, external_action_attempts=0,
            maximum_rss_kib=32000, execution_boundary=boundary)
        changes = dict(uid=0, effective_capabilities=1, home_visible=True, cpu_seconds=[3,3],
            memory_bytes=[268435456,268435456], file_bytes=[-1,-1], core_bytes=[-1,-1])
        for name, value in changes.items():
            with self.subTest(name=name):
                modified=deepcopy(observed); modified['execution_boundary'][name]=value
                with self.assertRaisesRegex(ValueError, 'REUSE_EXECUTION_BOUNDARY'):
                    runner.check_observation(modified, plan, parent)
