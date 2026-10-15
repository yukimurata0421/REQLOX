"""Prepare, explicitly execute, or read-only audit a copied-module continuation."""
import argparse
import json
from pathlib import Path
from . import target_integration as integration


def main(argv=None):
    parser = argparse.ArgumentParser(description='Whole-module integration of the approved copied Target')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Read and copy inputs only; no Target import or native launch')
    prepare.add_argument('--scope', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--baseline', type=Path, required=True, help='Fresh read-only delivery observation including unit properties')
    inspect = commands.add_parser('inspect', help='Verify prepared hashes without starting any process')
    inspect.add_argument('--output', type=Path, required=True)
    execute = commands.add_parser('execute', help='Requires separate final approval; failed starts consume budget')
    execute.add_argument('--output', type=Path, required=True)
    execute.add_argument('--grant', type=Path, required=True)
    audit = commands.add_parser('audit', help='Read retained observations without executing archived code')
    audit.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            value = integration.prepare(args.scope, args.output, runtime_baseline=args.baseline)
        elif args.command == 'inspect':
            value = integration.capacity(integration.check_bundle(args.output))
        elif args.command == 'execute':
            value = integration.execute(args.output, args.grant)
        else:
            value = integration.audit(args.output)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status='DENIED_OR_UNCONFIRMED', reason=str(exc)[:160],
                             automatic_retry=False), ensure_ascii=False))
        return 2
