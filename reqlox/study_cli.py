"""Local entry points for portable evaluation artifacts."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import _runtime, studies


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('INPUT_FILE_BOUNDARY')
    return json.loads(path.read_text())


def _write(path, value):
    path = Path(path).absolute()
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('OUTPUT_MUST_STAY_OUTSIDE_PACKAGE')
    if path.exists() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('OUTPUT_ALREADY_EXISTS_OR_LINKED')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    _runtime()
    parser = argparse.ArgumentParser(description='Local preparation, Source comparison, and calibration diagnostics')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('settings', help='Print public settings; RAW serving and no automatic activation')
    capsule = sub.add_parser('capsule', help='Inspect supplied wheel bytes without installing them')
    capsule.add_argument('--specification', type=Path, required=True)
    capsule.add_argument('--output', type=Path, required=True)
    prepare = sub.add_parser('prepare', help='Discover documented bounded callers without importing the target')
    inputs = prepare.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--root', type=Path)
    inputs.add_argument('--capsule', type=Path)
    prepare.add_argument('--documents', type=Path, required=True, help='JSON map of document names to text')
    prepare.add_argument('--project', required=True)
    prepare.add_argument('--known-projects', type=Path, help='JSON list of previously exposed projects')
    prepare.add_argument('--output', type=Path, required=True)
    freeze = sub.add_parser('compare-freeze', help='Freeze equal-budget Source and source-blind searches')
    freeze.add_argument('--preparation', type=Path, required=True)
    freeze.add_argument('--source', type=Path, required=True, help='JSON containing documents, url, and source_type')
    freeze.add_argument('--recipe-index', type=int, default=0)
    freeze.add_argument('--budget', type=int, default=4)
    freeze.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('compare-run', help='Run frozen plans in new bounded private namespaces')
    run.add_argument('--freeze', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--state-dir', type=Path, required=True)
    run.add_argument('--seconds', type=int, default=180)
    run.add_argument('--maximum-campaigns', type=int, default=32)
    for command in ('score', 'calibrate-fit'):
        p = sub.add_parser(command)
        p.add_argument('--dataset', type=Path, required=True)
        p.add_argument('--output', type=Path, required=True)
    register = sub.add_parser('calibrate-register', help='Register a candidate and unlabeled confirmation forecasts')
    register.add_argument('--model', type=Path, required=True)
    register.add_argument('--training', type=Path, required=True)
    register.add_argument('--forecasts', type=Path, required=True)
    register.add_argument('--output', type=Path, required=True)
    review = sub.add_parser('calibrate-review', help='Report scores with an explicit provenance hold')
    review.add_argument('--registration', type=Path, required=True)
    review.add_argument('--training', type=Path, required=True)
    review.add_argument('--confirmation', type=Path, required=True)
    review.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'settings':
            print(json.dumps(studies.settings(), indent=2))
            return 0
        if args.command == 'capsule':
            spec = _read(args.specification)
            value = studies.inspect_wheels(spec['wheels'], target_project=spec['target_project'])
        elif args.command == 'prepare':
            capsule = _read(args.capsule) if args.capsule else None
            if capsule:
                sources = capsule['sources']
            else:
                import run_reliability_reuse
                sources = run_reliability_reuse.load_snapshot(args.root.resolve())
            value = studies.prepare_context(sources, _read(args.documents), project=args.project,
                known_projects=[] if args.known_projects is None else _read(args.known_projects), capsule=capsule)
        elif args.command == 'compare-freeze':
            spec = _read(args.source)
            source = studies.supplied_source(spec['documents'], url=spec['url'], source_type=spec['source_type'])
            value = studies.freeze_comparison(_read(args.preparation), source,
                                             recipe_index=args.recipe_index, budget=args.budget)
        elif args.command == 'compare-run':
            os.environ['REQLOX_STATE_DIR'] = str(args.state_dir.absolute())
            value = studies.run_comparison(_read(args.freeze), args.output,
                seconds=args.seconds, maximum_campaigns=args.maximum_campaigns)
            print(json.dumps(dict(status=value.get('status', 'COMPLETE'), output=str(args.output),
                native_campaigns=value['native_campaigns'], provider_calls=0)))
            return 0
        elif args.command in ('score', 'calibrate-fit'):
            data = _read(args.dataset)
            operation = studies.score_forecasts if args.command == 'score' else studies.fit_calibration
            value = operation(data['rows'], event=data['event'], predictor_revision=data['predictor_revision'])
        elif args.command == 'calibrate-register':
            value = studies.register_confirmation(_read(args.model), _read(args.training)['rows'],
                                                 _read(args.forecasts)['rows'])
        else:
            value = studies.review_calibration(_read(args.registration), _read(args.training)['rows'],
                                              _read(args.confirmation)['rows'])
        _write(args.output, value)
        print(json.dumps(dict(status=value.get('status', 'COMPLETE'), output=str(args.output), provider_calls=0)))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status='STOPPED', reason=str(exc)[:200], provider_calls=0)), file=sys.stderr)
        return 2
