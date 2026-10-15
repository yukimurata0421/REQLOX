"""Static protocol bindings reject unsupported and ambiguous ownership."""

from reqlox.offline_testing import install as _install_offline_guard
_install_offline_guard()

import hashlib
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
'''


class PortableBindingBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binding = dict(module='owned', owner_class='Owner', owner_kwargs={},
            context_class='Context', context_property='writer', probe='locked', probe_kind='PROPERTY')

    def index(self, source=SOURCE):
        (self.root / 'owned.py').write_text(source)
        return portable.declarations(self.root, 'owned')

    def test_declarations_hash_exact_source_without_executing_top_level_code(self):
        source = "raise RuntimeError('must not import')\n" + SOURCE
        index = self.index(source)
        proof = portable.validate_binding(self.binding, index)
        self.assertEqual(proof['source_sha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertTrue(proof['static_declarations_only'])
        self.assertTrue(proof['runtime_types_required'])

    def test_package_init_is_used_when_module_file_is_absent(self):
        package = self.root / 'owned'
        package.mkdir()
        (package / '__init__.py').write_text(SOURCE)
        proof = portable.validate_binding(self.binding, portable.declarations(self.root, 'owned'))
        self.assertEqual(proof['source_sha256'], hashlib.sha256(SOURCE.encode()).hexdigest())

    def test_unknown_and_missing_binding_fields_are_rejected(self):
        index = self.index()
        unknown = self.binding | {'execution_authority': True}
        missing = self.binding.copy()
        del missing['probe']
        for binding in (unknown, missing):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, 'PORTABLE_BINDING_SCHEMA'):
                portable.validate_binding(binding, index)

    def test_unknown_classes_and_invalid_identifiers_are_rejected(self):
        index = self.index()
        for key in ('owner_class', 'context_class', 'probe'):
            for value in ('Missing', 'invalid-name', '', None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    portable.validate_binding(self.binding | {key: value}, index)

    def test_each_sync_context_protocol_method_is_rejected(self):
        for name in ('__aenter__', '__aexit__'):
            source = SOURCE.replace('async def ' + name, 'def ' + name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'PORTABLE_ASYNC_PROTOCOL_REQUIRED'):
                portable.validate_binding(self.binding, self.index(source))

    def test_method_probe_and_property_probe_are_not_interchangeable(self):
        index = self.index(SOURCE.replace('    @property\n    def locked', '    def locked'))
        method = self.binding | {'probe_kind': 'METHOD'}
        self.assertTrue(portable.validate_binding(method, index)['runtime_types_required'])
        with self.assertRaisesRegex(ValueError, 'PORTABLE_PROBE_SHAPE'):
            portable.validate_binding(self.binding, index)
        with self.assertRaisesRegex(ValueError, 'PORTABLE_PROBE_SHAPE'):
            portable.validate_binding(method, self.index())

    def test_owner_context_accessor_must_be_a_property(self):
        index = self.index(SOURCE.replace('    @property\n    def writer', '    def writer'))
        with self.assertRaisesRegex(ValueError, 'PORTABLE_CONTEXT_PROPERTY'):
            portable.validate_binding(self.binding, index)

    def test_self_context_binding_requires_matching_owner_and_context_class(self):
        binding = self.binding | {'owner_class': 'Context', 'context_property': None}
        self.assertTrue(portable.validate_binding(binding, self.index())['runtime_types_required'])
        with self.assertRaisesRegex(ValueError, 'PORTABLE_SELF_CONTEXT_TYPE'):
            portable.validate_binding(self.binding | {'context_property': None}, self.index())

    def test_inherited_sync_override_cannot_use_async_base_as_proof(self):
        source = SOURCE.replace('class Context(Protocol):',
            'class Context(Protocol):\n    def __aexit__(self, *args): pass')
        with self.assertRaisesRegex(ValueError, 'PORTABLE_ASYNC_PROTOCOL_REQUIRED'):
            portable.validate_binding(self.binding, self.index(source))

    def test_multilevel_local_inheritance_can_establish_async_protocol(self):
        source = SOURCE.replace('class Context(Protocol):',
            'class Middle(Protocol): pass\nclass Context(Middle):')
        self.assertTrue(portable.validate_binding(self.binding, self.index(source))['runtime_types_required'])

    def test_cyclic_local_inheritance_is_a_controlled_rejection(self):
        source = SOURCE.replace('class Protocol:', 'class Protocol(Context):').replace(
            '    async def __aenter__(self): pass\n    async def __aexit__(self, *args): pass\n', '    pass\n')
        with self.assertRaisesRegex(ValueError, 'PORTABLE_METHOD_MISSING'):
            portable.validate_binding(self.binding, self.index(source))

    def test_qualified_external_base_cannot_supply_an_async_protocol(self):
        source = SOURCE.replace('Context(Protocol)', 'Context(external.Protocol)')
        with self.assertRaisesRegex(ValueError, 'PORTABLE_METHOD_MISSING'):
            portable.validate_binding(self.binding, self.index(source))


if __name__ == '__main__':
    unittest.main()
