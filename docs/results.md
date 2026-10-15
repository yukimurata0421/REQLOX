# Reading Results

Read a result's scope, execution state, and observations before interpreting its
status. A successful command, a completed study, and an adopted repair describe
different outcomes.

## Repository loop statuses

| Status | Interpretation |
| --- | --- |
| `ADOPTED_IN_SNAPSHOT` | A candidate passed the loop's selected repair and fresh confirmation checks and is retained in the result snapshot. |
| `NO_COUNTEREXAMPLE` | The selected valid finite observations produced no counterexample in that run. |
| `HELD_NO_EXECUTION` | No eligible observation rows were executed. |
| `HELD_FAULT_NOT_REACHED` | A selected condition did not reach the required fault observation. |
| `REJECTED_BASELINE_INVALID` | The observed normal behavior did not meet the declared contract. |
| `REJECTED_REPAIR_UNQUALIFIED` | A discovered counterexample lacked a qualifying repair. |
| `REJECTED_NO_CHANGE` | The loop did not obtain the required candidate change. |
| `ROUND_LIMIT` | The loop reached its round bound without final adoption. |
| `STOPPED` | An exception or prerequisite/budget failure interrupted the workflow; inspect the retained terminal record. |

A paired `COMPLETE` means the paired study produced and verified its summary.
Inspect `SOURCE` and `NO_SOURCE` outcomes separately; `COMPLETE` does not imply
that either arm adopted a repair. The `reqlox qualify` wrapper exits with `0`
for snapshot adoption or a completed paired study, `1` for other returned
outcomes, and `2` for the handled stop/error path.

## Demo statuses

| Status | Interpretation |
| --- | --- |
| `NOT_SUPPORTED` | The assessment does not support this demo's selected failure hypothesis. |
| `INSUFFICIENT_INFORMATION` | The available assessment does not support proceeding with this hypothesis. |
| `REPRODUCED_AND_REPAIRED` | The known-control observations satisfied the demo's finite reproduction and repair checks. |
| `NOT_REPRODUCED` | The selected finite observations did not reproduce the chosen cleanup weakness. |
| `CONTRACT_MISMATCH` | Observations differed from the frozen finite expectations. |
| `STOPPED` | The run could not complete; inspect its execution state and retained records. |

Read `native_attempts`, `native_executions`, `native_execution_status`,
`stage_observations`, and `stage_matches` together. An attempted execution with
unknown completion is not an observed pass or an observed target failure.
Recorded model assessments and forecasts remain recorded predictions, even
when a new worker execution follows them.

## Inspect a run

1. Identify the target snapshot, owner contract, supplied Source, method, and
   selected budget in the input or study record.
2. Check whether any binding or condition was held before execution.
3. Check which worker plans were attempted and which observations completed.
4. Compare normal behavior, fault reachability, repair, and confirmation.
5. Inspect candidate files and the final adoption scope.
6. Audit an eligible completed result in a new process, using its private state
   root. Keep stopped and incomplete terminal records separate.

The [artifact map](data-contracts.md) identifies the files. For repository loops,
`round-00-decision.json` describes the initial decision and `result.json` records
the loop outcome. In paired studies, inspect each arm's directory as well as
the top-level summary.

## Common next steps

| Observation | Next action within the same scope |
| --- | --- |
| Isolation probe fails | Check the reported Linux, interpreter, `bubblewrap`, and namespace prerequisites. |
| Inventory holds a binding | Read its reason and supported binding scope; do not count it as an executed target. |
| Campaign or deadline limit stops a run | Preserve the terminal record. Carry consumption forward across the authorized scope; a different name does not renew its budget or deadline. Obtain explicit approval for any permitted bounded continuation. |
| Recorded lookup rejects edited text | Restore the original sample or choose another available assessment path. |
| Model state contains a stopped/unresolved attempt | Inspect the private scope and attempt records; do not delete the ledger to disguise a resend. |
| Audit rejects a result | Check scope, completeness, recorded hashes, and claim fields; retain the original artifacts. |

These actions describe the available interfaces. They do not authorize a broader
target, production action, or automatic retry.

## Claims the status does not establish

For `reqlox study`, `READY_STATICALLY` means preparation found supported
bindings and pinned prerequisites; native behavior is still unobserved.
A generated-condition comparison reports both arms and may complete with
zero additional Source adoptions. A calibration diagnostic review is `HELD`
because supplied rows do not verify natural, prospective forecast provenance.
Read the artifact kind as well as its status.

`NO_COUNTEREXAMPLE` does not prove that no weakness exists. Snapshot adoption
does not prove production fitness or cross-target generalization. A hash check
does not verify an incident's cause. A predicted success probability is not
calibrated accuracy. A reserved amount is not an invoice or a measured total
cost.

See [Evaluation](evaluation-plan.md) for the published validation scope and
further measurement questions.

## Repository groups and repair records

A `reqlox run` Target result contains separate repository statuses. A completed
comparison does not make a held comparison arm successful. Shared budget stops
retain remaining repository names as `NOT_RUN_AFTER_STOP`; partial outcomes are
not an application-wide PASS. See [Target workspaces](target-workspaces.md).

The Guided check distinguishes fresh included-rule execution from three archived
repair records. Their Sources differ: the lock record uses an owned synthetic
report; the TTL record uses incident clock knowledge under an owned elapsed-time
requirement; the temporary-file record uses an API reference summary and an owned
one-time EIO condition. The lock record covers one generated candidate and 12
conditions with four stages (48 observations), not 12 independent repairs.
The TTL count is 29 cases per final candidate and arm. Fresh lock counts are
reported as conditions times four stages, separately from these records.

Supported preparation and calibration diagnostics are implemented. Independent
unseen-OSS repair generalization, natural incident Source added value and
population probability calibration remain unestablished. A diagnostic fit is
not an activated or certified calibrated probability; review remains held when
prospective evidence is missing.

Use `reqlox target audit --output PRIVATE_RUN_DIRECTORY` for aggregate Target records. `VERIFIED` covers record consistency; stopped children retain unverified semantics, and a missing terminal remains `INCOMPLETE`. See [Target workspaces](target-workspaces.md).

For `DOCUMENTED_SYNC_PATH_CONTEXT_V1`, `NO_COUNTEREXAMPLE` requires the initial
finite observations and a fresh-process confirmation of the same plan.
`COUNTEREXAMPLE_NO_SUPPORTED_REPAIR` retains an initial failure without an
invented cleanup-error policy; `CONFIRMATION_FAILED` retains a failure in the
second campaign. This adapter generates and adopts no repair. Atomic binding
holds remain a separate plan field even when a documented context is executable.
Its Target integration has been tested with mocked native observations; these
tests do not establish a new external Target execution result.

## Executed local copied-Target control

A bounded local run on 2026-10-12 executed the included owned `api` and `worker`
examples from receipted private copies. Eight sequential native campaigns took
about 6 seconds within a 12-campaign / 120-second scope. All launches completed;
no additional model calls, cloud actions, or deployments occurred.

| Owned copy | Campaigns | Initial counterexamples | Candidate re-injection | Normal regression | Fresh-process confirmation | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| api | 4 | 6 of 6 probes | 6/6 | 10/10 | 6/6 | `ADOPTED_IN_SNAPSHOT` |
| worker | 4 | 4 of 6 probes | 6/6 | 2/2 | 6/6 | `ADOPTED_IN_SNAPSHOT` |

Counts combine the two comparison arms. They are repeated finite observations,
not independent repairs. The API copy leaked its temporary file after WRITE,
FSYNC, and REPLACE errors; the candidate removed only its own temporary file
and preserved exceptions and existing files. The worker copy leaked its lock
after an exception or task cancellation; the candidate released it in `finally`.
Cancellation while waiting to acquire already passed in the original worker
and is not counted as a discovered defect.

The run covered 36 fault-condition applications and 20 normal observations
(8 baselines and 12 candidate regressions). A third known copied repository
retained four unsupported bindings and received no injection or invented owner
contract. The aggregate therefore remained `PARTIAL`; the read-only audit at
that execution revision verified both adoptions and the held terminal. A later
method revision can reject re-auditing these saved records without changing that
historical result. Original inputs and the
receipted copies stayed unchanged. Candidates were retained only as derived
isolated snapshots.

These controls establish execution of the bounded local loop. They do not
establish independent unseen-OSS generalization, probability calibration,
natural Source added value, production fitness, or cross-service behavior.
Private receipts, raw observations, copies, and detailed local judgments are
not included in the public checkout.


## Documented path-context continuation

An explicitly approved continuation of the same known copied Target executed
two sequential path-context campaigns, bringing the cumulative scope to 10 of
12 campaigns. Seven seconds of prior conservative consumption were retained,
and the complete additional 30-second window was charged in advance. Native
execution finished in about 1.67 seconds, within its approved deadline.

The initial campaign and fresh-process confirmation used the same README-bound
plan. Eight body Exception/BaseException applications and sixteen normal-exit or
repeat observations passed across both campaigns. Resource release, propagation
of injected body failures, and another invocation's file preservation passed.
No counterexample, repair candidate, or adoption occurred. The four atomic-write
binding holds remain separate. Cleanup-system-call EIO failures are outside this
documented exit-release requirement.

The read-only aggregate audit returned `VERIFIED`. Worker observations confirmed
a non-root UID, zero capabilities, no visible home, isolated network namespaces,
and effective CPU/memory limits. The local UI serves audited counts with native
execution disabled. Original selected sources, configurations and the receipted
copy stayed unchanged. These repeated finite checks do not establish independent
unseen-OSS generalization, calibrated probabilities, incident Source added value,
or a verified repair. Raw evidence remains private.
