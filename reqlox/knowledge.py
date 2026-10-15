"""Public Python entry points for local source knowledge and IR review."""


def fetch_documents(urls, **options):
    from reqlox_knowledge.acquisition import fetch
    return fetch(urls, **options)


def import_documents(documents, **options):
    from reqlox_knowledge.corpus import import_documents as implementation
    return implementation(documents, **options)


def build_index(corpus_path, **options):
    from reqlox_knowledge.corpus import build_index as implementation
    return implementation(corpus_path, **options)


def search(index_path, query, **options):
    from reqlox_knowledge.corpus import search_index
    return search_index(index_path, query, **options)


def prepare_ir(candidate, source_texts, **options):
    from reqlox_knowledge.ir import prepare
    return prepare(candidate, source_texts, **options)


def route_ir(plan, judgments):
    from reqlox_knowledge.ir import route
    return route(plan, judgments)


def prepare_generation(text, **options):
    from reqlox_knowledge.generation import prepare
    return prepare(text, **options)


def generate(plan_path, scope_path, **options):
    from reqlox_knowledge.generation import execute
    return execute(plan_path, scope_path, **options)


def make_provider_scope(plan, **options):
    from reqlox_knowledge.provider import make_scope
    return make_scope(plan, **options)


def judge(plan_path, scope_path, **options):
    from reqlox_knowledge.provider import execute
    return execute(plan_path, scope_path, **options)


def replay_incident(bundle_path, **options):
    from reqlox_knowledge.pipeline import replay
    return replay(bundle_path, **options)


def prepare_system(package_directory, **options):
    from reqlox_system.core import prepare
    return prepare(package_directory, **options)


def replay_system(bundle_path, **options):
    from reqlox_system.core import replay
    return replay(bundle_path, **options)


def export_system_archive(plan_path, exchanges_path, **options):
    from reqlox_system.core import export_archive
    return export_archive(plan_path, exchanges_path, **options)


def export_incident_archive(generation_directory, judge_directory, **options):
    from reqlox_knowledge.pipeline import export_archive
    return export_archive(generation_directory, judge_directory, **options)


def partial_scores(rows, categories):
    from reqlox_knowledge.partial_scores import report
    return report(rows, categories)


def validate_bundle(bundle_path, *, schema_dir=None):
    from pathlib import Path
    from reqlox_knowledge import validator
    return validator.validate_bundle(Path(bundle_path), Path(schema_dir) if schema_dir else
                                     Path(validator.__file__).parent / 'data/schemas')


def schema_path():
    from pathlib import Path
    import reqlox_knowledge
    return Path(reqlox_knowledge.__file__).parent / 'data/incident-knowledge-model-v0.1.sql'
