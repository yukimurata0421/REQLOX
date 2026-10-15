"""Commands for a Target with explicitly registered repositories."""
import argparse
import json
import os
from pathlib import Path
import sys
from . import targets


def main(argv=None):
    parser = argparse.ArgumentParser(description='Plan and run named repositories with one shared finite budget')
    commands = parser.add_subparsers(dest='command', required=True)
    target = commands.add_parser('target', help='Register and list repositories')
    actions = target.add_subparsers(dest='action', required=True)
    init = actions.add_parser('init', help='Create a new Target manifest')
    init.add_argument('--target', type=Path, required=True)
    init.add_argument('--name', required=True)
    add = actions.add_parser('add', help='Register one repository and its owned contract configuration')
    add.add_argument('--target', type=Path, required=True)
    add.add_argument('--repo', required=True)
    add.add_argument('--path', type=Path, required=True)
    add.add_argument('--configuration', type=Path, required=True)
    add.add_argument('--dependency', type=Path)
    prepare = actions.add_parser('prepare', help='Prepare private configurations using existing Source methods')
    prepare.add_argument('--target', type=Path, required=True)
    preparation_selection = prepare.add_mutually_exclusive_group(required=True)
    preparation_selection.add_argument('--repo', action='append', default=[])
    preparation_selection.add_argument('--all', action='store_true', dest='all_repositories')
    prepare.add_argument('--output', type=Path, required=True)
    source_mode = prepare.add_mutually_exclusive_group()
    source_mode.add_argument('--natural-source-input', type=Path)
    source_mode.add_argument('--condition-input', type=Path)
    source_mode.add_argument('--source-index', type=Path)
    prepare.add_argument('--packets', type=Path)
    prepare.add_argument('--specification-input', type=Path)
    audit = actions.add_parser('audit', help='Audit aggregate records without running archived code or targets')
    audit.add_argument('--output', type=Path, required=True)
    listing = actions.add_parser('list', help='List registered names without executing code')
    listing.add_argument('--target', type=Path, required=True)
    snapshot = actions.add_parser('snapshot', help='Copy selected repositories into a new private Target workspace')
    snapshot.add_argument('--target', type=Path, required=True)
    snapshot_selection = snapshot.add_mutually_exclusive_group(required=True)
    snapshot_selection.add_argument('--repo', action='append', default=[])
    snapshot_selection.add_argument('--all', action='store_true', dest='all_repositories')
    snapshot.add_argument('--output', type=Path, required=True)
    snapshot_audit = actions.add_parser('snapshot-audit', help='Verify copied inputs without executing Target code')
    snapshot_audit.add_argument('--output', type=Path, required=True)
    run = commands.add_parser('run', help='Inspect or run explicitly selected repositories')
    run.add_argument('--target', type=Path, required=True)
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument('--repo', action='append', default=[], help='Registered name; repeat to select several')
    selection.add_argument('--all', action='store_true', dest='all_repositories')
    run.add_argument('--dry-run', action='store_true', help='Validate and hash the plan; no state writes or native execution')
    run.add_argument('--paired', action='store_true')
    run.add_argument('--state-dir', type=Path)
    run.add_argument('--name')
    run.add_argument('--seconds', type=int, default=120)
    run.add_argument('--maximum-native-campaigns', type=int, default=12, help='Shared by every repository, round and arm')
    run.add_argument('--maximum-rounds', type=int, default=3)
    run.add_argument('--expect-plan-sha256', help='Require the identity from a reviewed dry run')
    run.add_argument('--authorization', type=Path, help='Explicit single-use continuation of a frozen authorization ledger')
    args = parser.parse_args(argv)
    previous = os.environ.get('REQLOX_STATE_DIR')
    try:
        if args.command == 'target':
            if args.action == 'init':
                result = targets.init(args.target, args.name)
            elif args.action == 'add':
                result = targets.add(args.target, args.repo, args.path, args.configuration, args.dependency)
            elif args.action == 'prepare':
                from .target_prepare import save_bundle
                def supplied(path):
                    return None if path is None else targets.read_json(targets.path_at(str(path), Path.cwd()))
                result = save_bundle(args.target, args.repo, args.output, args.all_repositories,
                    natural_source=supplied(args.natural_source_input), condition_input=supplied(args.condition_input),
                    source_index=args.source_index, packets=supplied(args.packets),
                    specification_input=supplied(args.specification_input))
            elif args.action == 'audit':
                from .target_audit import audit
                result = audit(args.output)
            elif args.action == 'snapshot':
                from .target_snapshot import save_bundle
                result = save_bundle(args.target, args.repo, args.output, args.all_repositories)
            elif args.action == 'snapshot-audit':
                from .target_snapshot import verify
                result = verify(args.output)
            else:
                result = targets.listing(args.target)
        else:
            if args.state_dir is not None:
                os.environ['REQLOX_STATE_DIR'] = str(args.state_dir.absolute())
            planned, prepared, roots = targets.prepare(args.target, args.repo, args.all_repositories,
                paired=args.paired, seconds=args.seconds, campaigns=args.maximum_native_campaigns, rounds=args.maximum_rounds,
                authorization=args.authorization)
            if args.expect_plan_sha256 is not None and args.expect_plan_sha256 != planned['plan_sha256']:
                raise ValueError('Target plan changed since the reviewed dry run')
            if args.dry_run:
                result = planned
            else:
                from reqlox_paths import state_root
                result = targets.execute(planned, prepared, roots, state_root(), name=args.name, expected=args.expect_plan_sha256)
        print(json.dumps(result, ensure_ascii=False))
        if result['status'] in ('PLANNED', 'TARGET_CREATED', 'REPOSITORY_REGISTERED', 'TARGET_LISTED', 'SNAPSHOTTED', 'PREPARED', 'VERIFIED', 'COMPLETE'):
            return 0
        return 2 if result['status'] == 'STOPPED' else 1
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps(dict(status='STOPPED', reason=str(exc), provider_calls=0), ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if previous is None:
            os.environ.pop('REQLOX_STATE_DIR', None)
        else:
            os.environ['REQLOX_STATE_DIR'] = previous
