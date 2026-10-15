"""Measure all configured source files and gate each critical file separately."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def relative_path(value):
    if (type(value) is not str or not value or '\\' in value or
            PurePosixPath(value).is_absolute() or any(part in ('.', '..') for part in value.split('/'))):
        raise ValueError('COVERAGE_POLICY_PATH')
    return value


def load_policy(path):
    value = json.loads(Path(path).read_text())
    if value.get('schema') != 'reqlox.coverage-policy.v1':
        raise ValueError('COVERAGE_POLICY_SCHEMA')
    for key in ('minimum_line_percent', 'minimum_branch_percent'):
        threshold = value.get(key)
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 100:
            raise ValueError('COVERAGE_POLICY_THRESHOLD')
    for key in ('source_directories', 'unit_test_roots', 'critical_test_modules', 'critical_files'):
        rows = value.get(key)
        if type(rows) is not list or not rows or any(type(row) is not str for row in rows) or len(set(rows)) != len(rows):
            raise ValueError('COVERAGE_POLICY_SELECTION')
        for row in rows:
            relative_path(row)
    return value


def counts(summary, covered, total):
    hit, size = summary.get(covered), summary.get(total)
    if type(hit) is not int or type(size) is not int or not 0 <= hit <= size:
        raise ValueError('COVERAGE_REPORT_COUNTS')
    return hit, size


def evaluate(report, policy):
    if report.get('meta', {}).get('branch_coverage') is not True:
        raise ValueError('COVERAGE_BRANCH_MEASUREMENT_REQUIRED')
    rows = []
    for name in policy['critical_files']:
        if name not in report.get('files', {}):
            raise ValueError('COVERAGE_CRITICAL_FILE_MISSING: ' + name)
        summary = report['files'][name]['summary']
        lines, statements = counts(summary, 'covered_lines', 'num_statements')
        branches, total_branches = counts(summary, 'covered_branches', 'num_branches')
        if not statements:
            raise ValueError('COVERAGE_CRITICAL_FILE_EMPTY: ' + name)
        line_percent = 100 * lines / statements
        branch_percent = 100 * branches / total_branches if total_branches else None
        passed = (100 * lines >= policy['minimum_line_percent'] * statements and
            (not total_branches or 100 * branches >= policy['minimum_branch_percent'] * total_branches))
        rows.append(dict(file=name, covered_lines=lines, statements=statements,
            covered_branches=branches, branches=total_branches, line_percent=line_percent,
            branch_percent=branch_percent, passed=passed))
    return dict(passed=all(row['passed'] for row in rows), files=rows)


def worker(output, suite_name, policy):
    import coverage
    from offline_test_guard import install
    denied = install()
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT), *[str(ROOT / name) for name in policy['source_directories']],
        *[str(ROOT / name) for name in policy['unit_test_roots']]]
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in policy['critical_files']}
    measurement = coverage.Coverage(config_file=str(ROOT / '.coveragerc'),
        source=[str(ROOT / name) for name in policy['source_directories']], data_file=str(output / '.coverage'))
    measurement.start()
    with tempfile.TemporaryDirectory(prefix='reqlox-coverage-state-') as state:
        os.environ['REQLOX_STATE_DIR'] = state
        if suite_name == 'critical':
            suite = unittest.defaultTestLoader.loadTestsFromNames(policy['critical_test_modules'])
        else:
            suite = unittest.TestSuite(unittest.TestLoader().discover(str(ROOT / name), pattern='test_*.py')
                for name in policy['unit_test_roots'])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    measurement.stop()
    measurement.save()
    # No runtime file or native worker is omitted to improve the displayed total.
    measurement.json_report(outfile=str(output / 'coverage.json'))
    measurement.xml_report(outfile=str(output / 'coverage.xml'))
    measurement.html_report(directory=str(output / 'html'))
    raw = json.loads((output / 'coverage.json').read_text())
    gate = evaluate(raw, policy)
    unchanged = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in before.items())
    summary = dict(schema='reqlox.coverage-result.v1', suite=suite_name, coverage_version=coverage.__version__,
        python_version=sys.version.split()[0],
        policy_sha256=hashlib.sha256((ROOT / 'coverage-policy.json').read_bytes()).hexdigest(),
        coverage_configuration_sha256=hashlib.sha256((ROOT / '.coveragerc').read_bytes()).hexdigest(),
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=[test.id() for test, _ in result.skipped], critical_gate=gate,
        overview_totals=raw['totals'], source_sha256=before, sources_unchanged=unchanged,
        native_tests_enabled=False, denied_execution_attempts=denied,
        passed=result.wasSuccessful() and gate['passed'] and unchanged and not denied)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: summary[key] for key in ('suite', 'tests_run', 'failures', 'errors', 'passed')}))
    for row in gate['files']:
        branch = 'N/A' if row['branch_percent'] is None else f"{row['branch_percent']:.2f}%"
        print(f"{row['file']}: lines={row['line_percent']:.2f}% branches={branch} {'PASS' if row['passed'] else 'FAIL'}")
    return 0 if summary['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('critical', 'unit'), default='critical')
    parser.add_argument('--output', type=Path, default=ROOT / 'coverage-report')
    parser.add_argument('--seconds', type=int, default=120, help='Wall limit for the owned test process (1..600)')
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.environ.get('REQLOX_RUN_NATIVE_TESTS') == '1':
        parser.error('This coverage profile requires native experiments to be disabled.')
    if not 1 <= args.seconds <= 600:
        parser.error('seconds must be 1..600')
    policy = load_policy(ROOT / 'coverage-policy.json')
    output = args.output.absolute()
    if args._worker:
        return worker(output, args.suite, policy)
    if any(path.is_symlink() for path in (output, *output.parents)) or any(
            output.is_relative_to(ROOT / name) for name in policy['source_directories'] + policy['unit_test_roots']):
        parser.error('Report output must be outside source/test directories and must not use symlinks.')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--_worker',
        '--suite', args.suite, '--output', str(output)]
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=args.seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        (output / 'summary.json').write_text(json.dumps(dict(schema='reqlox.coverage-result.v1',
            suite=args.suite, passed=False, status='STOPPED_WALL_LIMIT', seconds=args.seconds)) + '\n')
        return 124


if __name__ == '__main__':
    raise SystemExit(main())
