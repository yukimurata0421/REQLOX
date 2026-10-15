# Copied-module integration

`reqlox integration` connects complete copied modules through an owned caller:
`worker.use_resource(asyncio.Lock, operation)` → `TemporaryPathContext` →
`api.persist`. It observes exception propagation, destination bytes, resource
release, temporary-file ownership, cleanup, and a following normal call.
The API and worker inputs are small owned function examples. This is finite
component integration; it does not exercise an HTTP or queue service.

The five fixed faults are write, fsync and replace exceptions at the API boundary,
an operation exception, and actual task cancellation before persistence. Normal
cases include ordinary, empty, NUL and Unicode bytes. A boundary case preserves
another invocation's existing pending file. The caller uses the existing
atomic-bytes and async-release contracts and the documented with-exit cleanup
behavior. It adds no cleanup-EIO retry requirement. Four held atomic bindings
and the absence of a temppath repair remain explicit.

## Prepare and inspect

This implementation supports one explicit host-contract continuation for an
already receipted private copy. It is not a general permission to run on any
host. The root-owned contract, old ledgers and stop record, original receipt,
existing adopted snapshots and observed runtime identity must match. The
receipt's recorded root prevents moving the scope to reset its shared fence.
Inputs and raw results remain private; this repository contains no Target copy.

```bash
reqlox integration prepare --scope "$PRIVATE_SCOPE" \
  --output "$PRIVATE_PREPARATION" --baseline "$PRIVATE_BASELINE"
reqlox integration inspect --output "$PRIVATE_PREPARATION"
```

The baseline is a fresh read-only delivery observation, including oneshot
`Type`/`ExecMainStatus` and timer `Unit`. Preparation checks hashes and syntax,
copies complete modules and freezes three plans. It imports no Target and
starts no process. `pending-grant.json` contains no approval timestamp.

## Final approval and execution

The operator must obtain separate final execution approval for the reviewed
bundle before supplying a private grant with status `APPROVED_FINAL_EXECUTION`,
the exact bundle hash, an actual approval receipt time and approval reference.
The CLI does not issue consent. Editing a grant is not proof of user approval;
the local operator is responsible for recording it faithfully.

```bash
reqlox integration execute --output "$PRIVATE_PREPARATION" --grant "$PRIVATE_FINAL_GRANT"
reqlox integration audit --output "$PRIVATE_RETAINED_RUN"
```

The closed prior scope stays at twelve campaigns and 42 charged seconds. Only
this explicit exception permits attempts 13–15. A single exclusive claim
reserves the full twenty-second window before the first dispatch, charging 62
seconds cumulatively. Failed starts consume attempts. A different output or run
cannot release, retry or reset the claim. The ordinary twelve-campaign guards
retain their limits.

Attempt 13 uses original modules. Attempt 14 requires a reached counterexample
and a passing normal baseline. Attempt 15 requires improvement and passing
regressions using the existing candidate, then repeats the same conditions in
a fresh child. Adoption requires all three stages and verified receipts.

Execution must finish within twenty seconds of starting and within five minutes
of final approval. Each serial child has CPU 2 s, wall 5 s, memory 128 MiB,
output 128 KiB and core 0. Limits apply before bubblewrap; network, home and
credentials are excluded, and capabilities are dropped. The child verifies
namespaces and limits before Target import. Hash drift, unknown boundaries,
new delivery anomalies and expired deadlines stop subsequent dispatches.
Only an owned experiment process group may be terminated.

The retained workspace records plans, launch metadata, observations, errors,
receipts and a terminal inventory. Read-only audit checks those hashes and
adoption conditions without executing archived code. Missing evidence remains
unknown. Historical unauthorized launches and missing raw evidence are retained
as gaps, not converted into qualification evidence.

## Offline verification

Run the selected tests with real launches and network connections denied:

```bash
python3 -B scripts/verify_offline.py --root . --pattern test_target_integration.py
python3 -B scripts/verify_offline.py --root . --pattern test_integration_caller.py
```

These tests use synthetic component mocks and observations, not the copied
Target. Offline success does not establish native isolation or a repair result.
The [selected validation record](../publication/copied-module-integration-validation.json)
records 67 passing checks and CLI preparation, inspection and pending-grant denial.
The earlier preparation record remains historical. The [native result](../publication/copied-module-integration-native-result.json) records three executed campaigns: original fault cases failed 5/5 while normal cases passed 4/4; the existing candidate and fresh-process confirmation each passed all ten cases. The cumulative scope is closed at 15 campaigns and 62 charged seconds. Native execution and browser verification finished within the conservative approval deadline; administrative finalization and UI server cleanup happened later. Four held bindings, no temppath repair and historical missing raw evidence remain explicit. This known-component result establishes neither independent OSS generalization, probability calibration nor Source added value.

Start a read-only local view of a retained, audited run with `reqlox demo serve --integration-run "$PRIVATE_RETAINED_RUN"`. The Targets page shows shared campaign accounting, per-phase counts, adoption scope and held/unknown boundaries. Leave native execution disabled; viewing results starts no experiments.
