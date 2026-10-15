"Finite reliability controls and verification."
import ast
import json
from pathlib import Path
import gzip
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reqlox_core'))
import reliability_reuse as reuse
import run_reliability_reuse as runner

TEXT = '''import os
import tempfile

def write_text(destination: str, content: str) -> None:
    """Keep the original public parameters and documentation."""
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=os.path.dirname(destination), prefix='owned-') as stream:
        pending = stream.name
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, destination)

def neighboring():
    return 17
'''
JSON = TEXT.replace('import tempfile','import tempfile\nimport json').replace('write_text(', '_stage(')+'''
def store(destination, record):
    return _stage(destination, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
'''
FD = TEXT.replace("    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=os.path.dirname(destination), prefix='owned-') as stream:\n        pending = stream.name", "    descriptor, pending = tempfile.mkstemp(dir=os.path.dirname(destination), prefix='owned-')\n    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:")
JSON_DUMP = TEXT.replace('import tempfile','import tempfile\nimport json').replace('stream.write(content)',
    "json.dump(content, stream, ensure_ascii=False, indent=2)\n        stream.write('\\n')")
ASSIGNED_JSON = JSON.replace('return _stage(destination, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))',
    'encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)\n    return _stage(destination, encoded)')


def site_for(text=JSON):
    inventory=reuse.inventory({'store.py':text})
    if not inventory['accepted']:
        raise AssertionError(inventory['held'])
    return inventory['accepted'][0]


class SerializedFlowTests(unittest.TestCase):
    def test_public_json_wrapper_is_bound_to_private_text_helper_without_import(self):
        site=site_for();b=site['binding']
        self.assertEqual(site['symbol'],'store');self.assertEqual(b['entry_symbol'],'store')
        self.assertEqual(b['repair_symbol'],'_stage');self.assertEqual(b['kind'],reuse.serialized.KIND)
        self.assertEqual(b['caller_profile']['format'],'JSON_OBJECT_UTF8')
        self.assertEqual(b['backend_profile']['format'],'TEXT_UTF8');self.assertEqual(len(b['call_graph']),1)
        self.assertFalse(site['modules_imported']);self.assertFalse(b['input_domain_qualified'])

    def test_direct_text_and_descriptor_backends_share_the_public_profile(self):
        for text,kind in ((TEXT,'GENERATOR_CONTEXT'),(FD,'FD_GENERATOR_CONTEXT')):
            b=site_for(text)['binding'];self.assertEqual(b['io_kind'],kind)
            self.assertEqual(b['caller_profile'],{'format':'TEXT_UTF8','options':{}})
            self.assertFalse(b['descriptor_open_failure_qualified'])

    def test_aliases_and_renamed_symbols_are_bound_without_target_name(self):
        text=JSON.replace('import os','import os as filesystem').replace('os.','filesystem.')
        text=text.replace('import tempfile','from tempfile import NamedTemporaryFile as owned_file').replace('tempfile.NamedTemporaryFile','owned_file')
        text=text.replace('_stage','_persist').replace('store(', 'publish(')
        site=site_for(text);revised=reuse.apply_candidate({'store.py':text},site,reuse.candidate(site))
        self.assertTrue(site_for(revised['store.py'])['binding']['protected'])
        self.assertEqual(site['binding']['entry_symbol'],'publish')

    def test_repair_changes_only_the_original_helper_and_preserves_wrapper(self):
        site=site_for();result=reuse.apply_candidate({'store.py':JSON},site,reuse.candidate(site))['store.py']
        before=ast.parse(JSON);after=ast.parse(result)
        for name in ('store','neighboring'):
            self.assertEqual(ast.dump(next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name==name)),
                             ast.dump(next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==name)))
        old=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='_stage')
        new=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='_stage')
        self.assertEqual(ast.dump(old.args),ast.dump(new.args));self.assertEqual(ast.dump(old.returns),ast.dump(new.returns))
        self.assertEqual(ast.get_docstring(old),ast.get_docstring(new))
        rebound=site_for(result);self.assertTrue(rebound['binding']['protected'])
        self.assertEqual(reuse.candidate(rebound),rebound['code'])

    def test_two_edges_are_finite_and_cycles_or_deeper_graphs_are_held(self):
        indirect=JSON.replace('return _stage(destination, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))',
            'return _relay(destination, json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))')+'\ndef _relay(path, text):\n    return _stage(path, text)\n'
        self.assertEqual(site_for(indirect)['binding']['serialized_flow_ir']['helper_depth'],2)
        too_deep=indirect.replace('return _stage(path, text)','return _second(path, text)')+'\ndef _second(path, text):\n    return _stage(path,text)\n'
        self.assertFalse(reuse.inventory({'store.py':too_deep})['accepted'])
        cyclic=indirect.replace('return _stage(path, text)','return store(path,text)')
        self.assertFalse(reuse.inventory({'store.py':cyclic})['accepted'])

    def test_foreign_path_duplicated_payload_and_double_serialization_are_held(self):
        for text in (JSON.replace('_stage(destination, json.dumps','_stage(record, json.dumps'),
                     JSON.replace('json.dumps(record,','json.dumps(destination,'),
                     JSON.replace('stream.write(content)','stream.write(json.dumps(content))')):
            self.assertFalse(reuse.inventory({'store.py':text})['accepted'])

    def test_unknown_serializers_dynamic_options_and_custom_creation_are_held(self):
        for text in (JSON.replace('json.dumps(record,','encoder(record,'),
                     JSON.replace('sort_keys=True','sort_keys=setting'),
                     JSON.replace('indent=2','default=custom'),
                     JSON.replace("encoding='utf-8'","encoding='latin-1'"),
                     JSON.replace('tempfile.NamedTemporaryFile','temporary_creator'),
                     JSON.replace("mode='w'","mode='a'")):
            self.assertFalse(reuse.inventory({'store.py':text})['accepted'])

    def test_module_declaration_effects_and_helper_shadowing_are_held(self):
        for extra in ('\nimport external_dependency\n','\nside_effect()\n','\ndef eager(value=side_effect()):\n    pass\n',
                      '\nclass Custom:\n    pass\n','\n_stage=None\n','\n@unknown\ndef other():\n    pass\n'):
            self.assertFalse(reuse.inventory({'store.py':JSON+extra})['accepted'])
        self.assertFalse(reuse.inventory({'store.py':JSON.replace('def store(destination, record):','def store(destination, _stage):').replace('json.dumps(record,','json.dumps(_stage,')})['accepted'])

    def test_supplied_candidate_cannot_replace_profile_owned_path_or_signature(self):
        site=site_for();candidate=reuse.candidate(site)
        for code in (candidate.replace('stream.write(content)','stream.write(json.dumps(content))'),
                     candidate.replace('os.replace(pending, destination)','os.replace(destination, pending)'),
                     candidate.replace('_stage(destination, content)','_stage(content, destination)')):
            with self.assertRaises(ValueError):reuse.apply_candidate({'store.py':JSON},site,code)

    def test_direct_json_expression_is_a_separate_finite_profile(self):
        source=TEXT.replace('import tempfile','import tempfile\nimport json').replace('stream.write(content)',
            'stream.write(json.dumps(content, ensure_ascii=False))')
        self.assertEqual(site_for(source)['binding']['caller_profile']['format'],'JSON_OBJECT_UTF8')

    def test_json_dump_and_literal_newline_are_bound_to_the_same_owned_stream(self):
        b=site_for(JSON_DUMP)['binding']
        self.assertEqual(b['payload_write_style'],'JSON_DUMP');self.assertTrue(b['caller_profile']['trailing_newline'])
        _,encoded=reuse.serialized.sample(b['caller_profile'],'EMPTY');self.assertEqual(encoded,b'{}\n')
        source=reuse.apply_candidate({'store.py':JSON_DUMP},site_for(JSON_DUMP),reuse.candidate(site_for(JSON_DUMP)))['store.py']
        self.assertTrue(site_for(source)['binding']['protected'])

    def test_json_dump_foreign_stream_extra_writes_and_nonliteral_suffix_are_held(self):
        for source in (JSON_DUMP.replace('json.dump(content, stream,','json.dump(content, destination,'),
                       JSON_DUMP.replace("stream.write('\\n')","stream.write(content)"),
                       JSON_DUMP.replace("stream.write('\\n')","stream.write(suffix)"),
                       JSON_DUMP.replace("stream.write('\\n')","stream.write('\\n')\n        stream.write('\\n')")):
            self.assertFalse(reuse.inventory({'store.py':source})['accepted'])

    def test_serialized_assignment_is_a_bound_wrapper_edge(self):
        b=site_for(ASSIGNED_JSON)['binding'];self.assertEqual(b['call_graph'][0]['serialized_variable'],'encoded')
        self.assertEqual(b['caller_profile'],site_for(JSON)['binding']['caller_profile'])
        for source in (ASSIGNED_JSON.replace('encoded =','record ='),
                       ASSIGNED_JSON.replace('return _stage(destination, encoded)','return _stage(destination, record)'),
                       ASSIGNED_JSON.replace('encoded = json.dumps','encoded = custom_serializer')):
            self.assertFalse(reuse.inventory({'store.py':source})['accepted'])

    def test_candidate_cannot_drop_json_newline_or_replace_dump_style(self):
        site=site_for(JSON_DUMP);candidate=reuse.candidate(site)
        without_newline=''.join(line for line in candidate.splitlines(keepends=True) if line.strip()!="stream.write('\\n')")
        self.assertNotEqual(without_newline,candidate)
        for changed in (without_newline,
                        candidate.replace('json.dump(content, stream, ensure_ascii=False, indent=2)',
                                          'stream.write(json.dumps(content, ensure_ascii=False, indent=2))')):
            with self.assertRaises(ValueError):reuse.apply_candidate({'store.py':JSON_DUMP},site,changed)





    def test_postponed_call_annotations_and_import_mutation_are_held(self):
        for source in ('from __future__ import annotations\n'+JSON.replace('content: str','content: make_type()'),
                       JSON+'\nos.replace = replacement\n',
                       JSON+'\njson = None\n'):
            self.assertFalse(reuse.inventory({'store.py':source})['accepted'])

    def test_two_public_profiles_share_one_helper_without_duplicate_cleanup(self):
        source=JSON+'\ndef plain(destination, content):\n    return _stage(destination, content)\n'
        sources={'store.py':source};sites=reuse.inventory(sources)['accepted']
        self.assertEqual(len(sites),2)
        rows=[dict(site_id=s['id'],observed=dict(repair_pass=True,candidate_code=reuse.candidate(s))) for s in sites]
        revised={**sources,**reuse.compose_patches(sources,rows)}
        rebound=reuse.inventory(revised)['accepted']
        self.assertEqual(len(rebound),2);self.assertTrue(all(s['binding']['protected'] for s in rebound))
        helper=next(n for n in ast.parse(revised['store.py']).body if isinstance(n,ast.FunctionDef) and n.name=='_stage')
        self.assertEqual(sum(isinstance(n,ast.Try) for n in ast.walk(helper)),1)

    def test_owned_confirmation_grid_is_source_independent_for_serialized_entry(self):
        site=site_for();proposal=reuse.propose(site,[],6,include_owned_grid=True)
        self.assertEqual(len(reuse.qualification_faults(site,proposal)),6)
        self.assertTrue(proposal['generic_program_pool_source_input_independent'])

    def test_profile_samples_are_finite_and_unknown_input_domain_stays_unqualified(self):
        declared=site_for(TEXT)['binding']['caller_profile']
        self.assertEqual(reuse.serialized.sample(declared,'EMPTY'),('',b''))
        self.assertEqual(reuse.serialized.sample(declared,'UNICODE'),('\u8a18\u9332\n\u5024','\u8a18\u9332\n\u5024'.encode()))
        for case in ('BASE','EMPTY','UNICODE'):
            payload,encoded=reuse.serialized.sample(site_for(JSON)['binding']['caller_profile'],case)
            self.assertEqual(json.loads(encoded),payload)
        self.assertFalse(site_for()['binding']['input_domain_qualified'])
        with self.assertRaises(ValueError):reuse.serialized.sample({'format':'JSONL','options':{}})


if __name__=='__main__':unittest.main()
