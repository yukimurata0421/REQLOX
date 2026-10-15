"""CLI for reusable local source knowledge and explicitly bounded provider work."""
import argparse
import json
from pathlib import Path
import sys

from . import knowledge


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local document search, source-bound IR, and explicit provider work')
    commands = parser.add_subparsers(dest='command', required=True)
    imported = commands.add_parser('import', help='Import supplied document text privately; no network')
    imported.add_argument('--documents', type=Path, required=True)
    fetched = commands.add_parser('fetch', help='Fetch up to three public HTTPS documents only with --execute')
    fetched.add_argument('--url', action='append', required=True)
    fetched.add_argument('--execute', action='store_true')
    indexed = commands.add_parser('index', help='Build the existing local FTS and hashing-vector baseline')
    indexed.add_argument('--corpus', type=Path, required=True)
    indexed.add_argument('--dimension', type=int, default=768)
    searched = commands.add_parser('search', help='Search a supplied local index; scores are ranks')
    searched.add_argument('--index', type=Path, required=True)
    searched.add_argument('--query', required=True)
    searched.add_argument('--mode', choices=('hybrid', 'vector', 'fts'), default='hybrid')
    searched.add_argument('--limit', type=int, default=10)
    searched.add_argument('--publisher', action='append', default=[])
    searched.add_argument('--source-type', action='append', default=[])
    prepared = commands.add_parser('ir-prepare', help='Freeze native IR review questions, quotations, and controls')
    prepared.add_argument('--candidate', type=Path, required=True)
    prepared.add_argument('--source-texts', type=Path, required=True)
    prepared.add_argument('--maximum-questions', type=int, default=24)
    replay = commands.add_parser('replay', help='Replay source, generation and request-bound judge responses; no provider calls')
    replay.add_argument('--bundle', type=Path, required=True)
    system = commands.add_parser('system-prepare', help='Reproject a supported frozen source package; never execute Target code')
    system.add_argument('--package', type=Path, required=True)
    system.add_argument('--state-dir', type=Path)
    system_replay = commands.add_parser('system-replay', help='Replay request-bound System IR fidelity answers; no provider calls')
    system_replay.add_argument('--bundle', type=Path, required=True)
    system_replay.add_argument('--state-dir', type=Path)
    system_archive = commands.add_parser('system-replay-export', help='Bind saved source-fidelity request/response bytes to a plan')
    system_archive.add_argument('--plan', type=Path, required=True)
    system_archive.add_argument('--exchanges', type=Path, required=True)
    system_archive.add_argument('--state-dir', type=Path)
    archive = commands.add_parser('replay-export', help='Bind existing generation and judge archives; no provider calls')
    archive.add_argument('--generation-directory', type=Path, required=True)
    archive.add_argument('--judge-directory', type=Path, required=True)
    routed = commands.add_parser('ir-route', help='Review supplied answers without calling a provider')
    routed.add_argument('--plan', type=Path, required=True)
    routed.add_argument('--judgments', type=Path, required=True)
    gen = commands.add_parser('generation-prepare', help='Freeze a supplied source and the existing generation adapter')
    gen.add_argument('--source-texts', type=Path, required=True)
    gen.add_argument('--source-id', required=True)
    gen.add_argument('--project', required=True)
    gen.add_argument('--maximum-output-tokens', type=int, default=4096)
    scope = commands.add_parser('provider-scope', help='Create a finite scope for one exact frozen plan')
    scope.add_argument('--plan', type=Path, required=True)
    scope.add_argument('--id', required=True)
    scope.add_argument('--deadline', required=True)
    scope.add_argument('--maximum-reserved', required=True)
    scope.add_argument('--per-call-reserved', required=True)
    scope.add_argument('--maximum-concurrent-calls', type=int, default=2)
    scope.add_argument('--allow-external-disclosure', action='store_true')
    for name, help_text in [('judge', 'Run bounded parallel review; execution is opt-in'),
                            ('generate', 'Use the existing generation adapter once; execution is opt-in')]:
        run = commands.add_parser(name, help=help_text)
        run.add_argument('--plan', type=Path, required=True)
        run.add_argument('--scope', type=Path, required=True)
        run.add_argument('--execute', action='store_true')
        if name == 'judge':
            run.add_argument('--workers', type=int, default=2)
            run.add_argument('--api-key-file', type=Path)
    scored = commands.add_parser('score', help='Score all attempted rows, preserving missing labels and vectors')
    scored.add_argument('--input', type=Path, required=True, help='JSON object containing rows and categories')
    validated = commands.add_parser('bundle-validate', help='Validate an existing source knowledge bundle and closure')
    validated.add_argument('--bundle', type=Path, required=True)
    validated.add_argument('--schema-dir', type=Path)
    commands.add_parser('schema', help='Print the installed PostgreSQL and vector reference DDL path')
    for command in (imported, fetched, prepared, routed, gen, scope, scored, replay, archive, commands.choices['judge'], commands.choices['generate']):
        command.add_argument('--state-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        from reqlox_knowledge import reference, storage
        if args.command == 'import':
            result = knowledge.import_documents(storage.read(args.documents), state_dir=args.state_dir)
        elif args.command == 'fetch':
            result = knowledge.fetch_documents(args.url,state_dir=args.state_dir,execute=args.execute)
        elif args.command == 'index':
            result = knowledge.build_index(args.corpus, dimension=args.dimension)
        elif args.command == 'replay':
            result = knowledge.replay_incident(args.bundle, state_dir=args.state_dir)
        elif args.command == 'system-prepare':
            result = knowledge.prepare_system(args.package, state_dir=args.state_dir)
        elif args.command == 'system-replay':
            result = knowledge.replay_system(args.bundle, state_dir=args.state_dir)
        elif args.command == 'system-replay-export':
            result = knowledge.export_system_archive(args.plan, args.exchanges, state_dir=args.state_dir)
        elif args.command == 'replay-export':
            result = knowledge.export_incident_archive(args.generation_directory, args.judge_directory, state_dir=args.state_dir)
        elif args.command == 'search':
            result = knowledge.search(args.index, args.query, mode=args.mode, limit=args.limit,
                publisher=args.publisher, source_type=args.source_type)
        elif args.command == 'ir-prepare':
            result = knowledge.prepare_ir(storage.read(args.candidate), storage.read(args.source_texts),
                state_dir=args.state_dir, max_questions=args.maximum_questions)
        elif args.command == 'generation-prepare':
            texts = storage.read(args.source_texts)
            result = knowledge.prepare_generation(texts[args.source_id], source_id=args.source_id,
                project_id=args.project, state_dir=args.state_dir, maximum_output_tokens=args.maximum_output_tokens)
        elif args.command == 'provider-scope':
            plan = storage.checked_record(args.plan)
            value = knowledge.make_provider_scope(plan, identifier=args.id, deadline_utc=args.deadline,
                maximum_reserved=args.maximum_reserved, per_call_reserved=args.per_call_reserved,
                maximum_concurrent_calls=args.maximum_concurrent_calls,
                external_disclosure_allowed=args.allow_external_disclosure)
            directory = storage.new_directory(storage.state_directory(args.state_dir), 'scope')
            storage.save(directory / 'scope.json', value)
            result = dict(status='SCOPE_CREATED_NO_EXECUTION', scope=str(directory / 'scope.json'),
                currency=value['currency'], maximum_calls=value['maximum_calls'], provider_calls=0)
        elif args.command in ('judge', 'generate'):
            options = dict(state_dir=args.state_dir, execute=args.execute)
            if args.command == 'judge':
                options.update(workers=args.workers, api_key_file=args.api_key_file)
            result = getattr(knowledge, args.command)(args.plan, args.scope, **options)
        elif args.command in ('ir-route', 'score'):
            if args.command == 'ir-route':
                value = knowledge.route_ir(storage.checked_record(args.plan), storage.read(args.judgments))
            else:
                inputs = storage.read(args.input)
                value = knowledge.partial_scores(inputs['rows'], inputs['categories'])
            directory = storage.new_directory(storage.state_directory(args.state_dir), args.command)
            storage.save(directory / 'result.json', value)
            result = dict(status='COMPLETE', output=str(directory / 'result.json'), provider_calls=0,
                natural_truth_certified=False, probabilities_calibrated=False)
        elif args.command == 'bundle-validate':
            result = knowledge.validate_bundle(args.bundle, schema_dir=args.schema_dir)
        else:
            result = dict(status='REFERENCE_DDL', path=str(knowledge.schema_path()), database_connected=False)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result.get('status') != 'STOPPED' else 2
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError) as exc:
        import re
        reason = str(exc) if re.fullmatch('[A-Z][A-Z0-9_]{1,100}', str(exc)) else type(exc).__name__
        stopped = dict(status='STOPPED', reason=reason, provider_calls_unknown=True)
        if args.command in ('replay', 'replay-export', 'system-prepare', 'system-replay', 'system-replay-export'):
            stopped.update(provider_calls_unknown=False, provider_calls=0, target_executions=0, credentials_read=False)
        print(json.dumps(stopped), file=sys.stderr)
        return 2
