"""Inspect an inherited evaluation scope without starting execution."""
import argparse
import json
import sys
from pathlib import Path

from .evaluation_scope import inspect


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('inspect', help='Read ledger, method and reservation bindings')
    check.add_argument('--preflight', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _, _, _, view = inspect(args.preflight)
        print(json.dumps(view, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status='STOPPED', reason=str(exc)[:200], new_native_campaigns=0)), file=sys.stderr)
        return 2
