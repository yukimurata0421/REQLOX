# Evaluation

The public runtime has a bounded validation snapshot. Product effectiveness,
Source contribution, and independent generalization remain separate evaluation
questions.

## Current implementation checks

The [test and coverage guide](testing.md) describes the current portable suite,
critical-file thresholds, and separate runtime overview. The
[coverage validation](../publication/coverage-validation.json) records 501
discovered tests, including 29 native skips, and the measured source hashes.
These checks establish unit behavior and coverage, not native repair qualification.

The [current UI validation](../publication/ui-validation.json) covers the two
browser workspaces and their packaged runtime. The preceding
[evaluation implementation validation](../publication/evaluation-validation.json)
reports portable tests, installation from a code-only wheel, English interface
checks, and bounded execution of owned controls before the UI extension.
Its file hashes are historical. No private model records,
incident text, acquired OSS bundle, or development journal is included.

The public `study` interface checks local dependency capsules, documented caller
preparation, equal-budget Source comparisons, and frozen calibration diagnostics.
Its illustrative datasets are synthetic. Supplied probability rows do not
authenticate natural forecasts or native labels; their calibration review
remains `HELD` and the serving configuration remains `RAW`.

## Earlier runtime validation

[`publication/validation.json`](../publication/validation.json) records the
earlier 2026-10-11 JST check with Python 3.14.4. Its scope was:

| Check | Recorded result |
| --- | --- |
| Portable unit suite | 264 discovered; 236 passed; 28 native integration tests skipped; no failures or errors. |
| Distribution | A wheel was built and installed in a separate virtual environment. |
| Installed interfaces | Static inventory, condition preparation, zero-campaign refusal, and audit of a held result passed. |
| Local HTTP interface | Assets and four negative/unknown runs passed; no target experiments occurred in those runs. |
| Healthy workers | Gold, baseline, and candidate workers ran for both known demo controls in isolated namespaces. |
| Optional model adapter | Mock transport and bounded-call terminal tests passed. |

The healthy worker check injected no faults and did not qualify a repair. Live
model connectivity, native fault and re-injection campaigns, and cloud
deployment were not tested in that snapshot.

The [test selection record](../publication/test-selection.json) identifies the
public test scope and opt-in classes. These counts are for the public package,
not the full development workspace.

## Running the available checks

From an installed repository checkout:

```bash
env -u REQLOX_RUN_NATIVE_TESTS .venv/bin/python scripts/check.py
.venv/bin/reqlox check
```

The first command runs the portable suite with native campaigns disabled. The
second probes isolation with `/usr/bin/true`; it runs no target experiment.

[`scripts/healthy_smoke.py`](../scripts/healthy_smoke.py) checks only healthy
stages for the known controls. It can acquire the pinned distributions and
start isolated workers. Optional native integration tests can be enabled with
`REQLOX_RUN_NATIVE_TESTS=1` only on an authorized disposable execution host.
They include real fault and cancellation paths.

## What a finite result establishes

Inspect the target snapshot, owner contract, selected condition, observed
outcome, candidate identity, and confirmation record together. A completed
worker alone is insufficient. Missing observations and conditions that were not
reached remain visible.

For a repair, report normal behavior, discovery of the original counterexample,
same-condition re-injection, and fresh confirmation separately. A successful
known-control case is a finite result for that case. It is not an unused-target
evaluation or a calibrated probability estimate.

## Source contribution

The `--paired` path provides separate Source and No Source loops. Compare:

- initial fault discoveries and conditions reached;
- final adopted members and rejected or held outcomes;
- executed campaigns and historical observations reused;
- Source conditions that are new relative to the fixed owner grid; and
- elapsed time, human effort, and observed costs where recorded.

Use the same initial target, owner requirements, execution bounds, and scoring
scope. Record run order and every changed input. A Source condition duplicating
an existing condition is not a newly discovered failure mechanism.

The current owned comparison exercises Source and source-blind paths. Zero
additional Source adoptions remain zero; these controls do not establish
natural Source benefit. Neither unit-test counts nor healthy-worker results
establish that effect. See [Portable evaluation](portable-evaluation.md) for the
shared exploration and confirmation contract.

## Effort and cost

The package includes helpers for workflow effort and discovery metrics. Their
presence does not establish measured savings. Keep elapsed time, human active
time, wait time, retries, and model/execution consumption separate.

Reserved, estimated, and invoiced amounts describe different observations.
Unknown amounts remain unknown. A local cloud reservation is bookkeeping based
on supplied per-call values; it is not a verified billing cap.

## Further evaluation

Further studies may measure discovery beyond frozen baseline tests, correctness
on previously unused targets, reuse invalidation, and total effort. Those are
prospective studies, not results reported by this public release. Record held,
failed, unexecuted, and inconclusive cases in their denominators alongside
successful cases.

See [Results](results.md) for field-level interpretation and
[Public scope](minimal-implementation-plan.md) for remaining work.
