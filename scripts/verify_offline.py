"""Deny real child launches and network connections during selected offline checks."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--pattern',required=True)
args=parser.parse_args()
root=args.root.resolve()
os.environ.pop('REQLOX_RUN_NATIVE_TESTS',None)
sys.path[:0]=[str(root),str(root/'tools'),str(root/'reqlox_core'),str(root/'tests')]
denied=[]
def deny_process(*a,**kw):
    denied.append('PROCESS')
    raise RuntimeError('OFFLINE_REAL_PROCESS_START_DENIED')
def deny_network(*a,**kw):
    denied.append('NETWORK')
    raise RuntimeError('OFFLINE_NETWORK_DENIED')
with patch.object(subprocess,'Popen',side_effect=deny_process),patch.object(socket,'create_connection',side_effect=deny_network):
    suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),denied_attempts=denied,real_child_processes_started=0,new_native_campaigns=0,new_provider_calls=0)))
sys.exit(0 if result.wasSuccessful() and not denied else 1)
