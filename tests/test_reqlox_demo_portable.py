from pathlib import Path
import tempfile
import unittest
from reqlox_demo import portable


SOURCE = '''class Protocol:
    async def __aenter__(self): pass
    async def __aexit__(self, *args): pass
class Context(Protocol):
    @property
    def locked(self): return False
class Owner:
    @property
    def writer(self): return Context()
    writer_lock = writer
'''


class PortableBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'example.py').write_text(SOURCE)
        self.index = portable.declarations(self.root,'example')
        self.binding = dict(module='example',owner_class='Owner',owner_kwargs={},context_class='Context',
            context_property='writer_lock',probe='locked',probe_kind='PROPERTY')

    def tearDown(self): self.temp.cleanup()

    def test_property_alias_and_local_inherited_async_protocol(self):
        proof=portable.validate_binding(self.binding,self.index)
        self.assertTrue(proof['static_declarations_only'])
        self.assertTrue(proof['runtime_types_required'])

    def test_unsupported_constructor_and_probe_are_rejected(self):
        for key,value in [('owner_kwargs',{'path':'external'}),('probe','absent'),
                          ('probe_kind','METHOD'),('context_property','unknown'),('module','other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                portable.validate_binding({**self.binding,key:value},self.index)

    def test_external_inheritance_cannot_establish_context_protocol(self):
        (self.root/'example.py').write_text(SOURCE.replace('Context(Protocol)','Context(ExternalProtocol)'))
        with self.assertRaises(ValueError):portable.validate_binding(self.binding,portable.declarations(self.root,'example'))

    def test_self_context_type_and_async_probe_are_rejected(self):
        with self.assertRaises(ValueError):portable.validate_binding({**self.binding,'context_property':None},self.index)
        (self.root/'example.py').write_text(SOURCE.replace('def locked','async def locked'))
        with self.assertRaises(ValueError):portable.validate_binding(self.binding,portable.declarations(self.root,'example'))

    def test_cancellation_is_a_separate_condition(self):
        rows=portable.cases()
        self.assertEqual(len(rows),5)
        self.assertEqual(sum(r['fault_kind']=='TASK_CANCEL' for r in rows),1)
        self.assertEqual(sum(r['exception']=='CancelledError' for r in rows),2)


if __name__=='__main__':unittest.main()
