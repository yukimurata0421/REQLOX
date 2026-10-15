"""A completed response must permit the next request; active work remains held."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import ast
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit


class ResponseLockTests(unittest.TestCase):
    def handler(self):
        # Execute the real request method with an owned engine, without importing
        # or launching any Target/native experiment dependencies.
        path=Path(__file__).resolve().parents[1]/'reqlox_demo/server.py'
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='do_POST')
        namespace=dict(json=json,urlsplit=urlsplit,TARGET_OPERATIONS=set(),OPERATIONS=set(),KNOWLEDGE_OPERATIONS=set(),WORKSPACE_OPERATIONS={"history"},check_execution=lambda path:None,
            MAXIMUM_REQUEST_BYTES=1024,public_view=lambda value:value,public_error=lambda exc:type(exc).__name__)
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),namespace)
        calls=[]
        server=SimpleNamespace(token='OWNED_CONTROL',server_port=1,run_lock=threading.Lock(),engine=SimpleNamespace(run=lambda value:None),workspace=SimpleNamespace(dispatch=lambda operation,value:calls.append(value) or {}))
        receiver=SimpleNamespace(path='/api/workspace/history',headers={'Content-Type':'application/json','Content-Length':'2','X-REQLOX-Token':server.token},
            rfile=io.BytesIO(b'{}'),server=server,valid_host=lambda:True,valid_origin=lambda:True)
        return namespace['do_POST'],receiver,calls

    def test_completed_response_releases_lock_before_transport_can_expose_it(self):
        method,receiver,calls=self.handler();responses=[]
        def send(value,status=200):
            if status==200:self.assertFalse(receiver.server.run_lock.locked())
            responses.append(status)
        receiver.send=send;method(receiver)
        self.assertEqual(responses,[200]);self.assertEqual(len(calls),1)

    def test_actual_inflight_operation_still_rejects_a_new_request(self):
        method,receiver,calls=self.handler();responses=[]
        receiver.send=lambda value,status=200:responses.append(status)
        receiver.server.run_lock.acquire()
        try:method(receiver);self.assertTrue(receiver.server.run_lock.locked())
        finally:receiver.server.run_lock.release()
        self.assertEqual(responses,[409]);self.assertFalse(calls)


if __name__=='__main__':unittest.main()
