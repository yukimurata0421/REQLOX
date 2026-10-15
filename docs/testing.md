# Tests and coverage

Run the portable unit suite and a coverage gate from a repository checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[knowledge,test]'
env -u REQLOX_RUN_NATIVE_TESTS .venv/bin/python -B scripts/coverage_check.py \
  --suite unit --output coverage-report --seconds 120
```

Use a new output directory for each run, such as `coverage-report-next`.
The runner preserves existing reports and bounds its owned test process to
120 seconds. It refuses the native-test flag; it does not create a network
namespace. Provider responses and campaign dispatch are mocked by the unit
suite. UI tests use local HTTP servers and owned fixtures.

## Native evidence retention

Native execution needs a separately approved host, frozen plans, an inherited
ledger and a deadline. Setting `REQLOX_RUN_NATIVE_TESTS=1` is a test selection
switch; it grants no execution authority. The path-context launcher requires a
`before_native` callback that checks and reserves the authorized campaign
immediately before process creation. A missing callback is rejected; denied
reservations and failed starts are kept, with no automatic retry.

Use `reqlox.native_evidence.retained_workspace(base, label)` for native test
fixtures. `base` must be an existing user-owned directory with mode `0700`,
outside automatic temporary-directory cleanup. The helper retains input,
observation and error files after return, assertion failure or interruption.
It writes an `OPEN` record before yielding and a terminal file inventory when
control returns. An abrupt process termination can leave the `OPEN` record;
the helper never deletes its workspace or releases a reservation.

The terminal inventory records local hashes, not execution certification.
Missing receipts, namespace observations or case rows remain unconfirmed;
a passing assertion cannot reconstruct deleted raw evidence. Never rerun a
campaign to replace missing evidence in an exhausted or stopped scope.
The [retention checks](../tests/test_native_evidence.py) use synthetic files
and mocked process creation, including budget denial and failed-start cases.
The [selected validation record](../publication/native-evidence-validation.json)
records 44 passing offline checks across retention, context dispatch and the
inherited scope guard. It adds no native qualification result.

## Policy and reports

[`coverage-policy.json`](../coverage-policy.json) defines the source directories,
test selections, critical files, and thresholds. Each critical file must reach
**95% statement coverage and 90% branch coverage**. Missing files, absent branch
measurement, invalid counts, and empty critical files fail the gate. Percentages
are checked before rounding. Files without branches report `N/A` for branches.

The selected files cover the public API/runtime import, CLI, saved-result audit,
portable experiment protocol, and effort ledger. This is a focused regression
gate; the aggregate alone cannot compensate for an under-covered critical file.
The [`gate tests`](../tests/test_coverage_gate.py) verify those failure cases.

The overview includes every Python runtime file in `reqlox/`, `reqlox_core/`,
`reqlox_demo/`, and `reqlox_knowledge/`, including unexecuted native workers.
Tests, examples, deployment scripts, and infrastructure are outside that runtime
denominator. No runtime file is omitted to increase the displayed total.
`--suite critical` runs a smaller diagnostic selection; CI uses `--suite unit`.

Reports contain:

- `summary.json`: test results, skipped IDs, per-file gate, overview counts,
  interpreter/tool versions, and source/policy/configuration hashes;
- `coverage.json` and `coverage.xml`: machine-readable coverage;
- `html/index.html`: source-level missing lines and branches.

Statement and branch percentages are reported separately. The coverage tool's
combined percentage is not the statement percentage. Generated reports are
ignored by Git; the source distribution includes the policy and runner.
GitHub Actions is configured to check Python 3.11 and 3.14 and retain reports
for seven days.

## Recorded validation

The [coverage validation record](../publication/coverage-validation.json)
records the tested source hashes and counts. The local Python 3.14.4 run
discovered 501 tests: **472 passed, 29 native tests skipped**, no failures or
errors. The 93 added tests cover static bindings, protocol results, CLI stop
states, saved evidence, resealed effort traces, and the coverage gate.

| Measurement | Statements | Branches |
| --- | --- | --- |
| Critical files together | 533/538 (99.07%) | 139/142 (97.89%) |
| All four runtime packages | 7018/11956 (58.70%) | 1657/3740 (44.30%) |

Every critical file passed its individual threshold. The overview shows the
remaining runtime coverage gap, including workers not run by this portable
suite. Mocked observations verify orchestration and result interpretation;
they do not qualify a native repair or establish independent generalization.
The source distribution was built and extracted into a separate directory;
its 165 focused tests and coverage gate passed. The coverage policy, runner,
test files, and guide were present, and the wheel declared the `test` extra.
Native integration remains a separate authorized experiment scope described
in [Evaluation](evaluation-plan.md). Local Python 3.11 execution and remote CI
execution were not performed in this validation.
