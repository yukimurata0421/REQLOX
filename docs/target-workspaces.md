# Run a Target containing several repositories

A Target is a named group of repository roots. Register each repository with its
own contract configuration, then select names with `--repo`. Repository names
are values, so the same command works for `api`, `worker`, or a different project.
The commands use existing static binding and finite repair methods.

## Try the owned two-repository example

From this checkout after installation:

```bash
.venv/bin/reqlox target list --target examples/targets/target.json
.venv/bin/reqlox run --target examples/targets/target.json --repo api --dry-run
.venv/bin/reqlox run --target examples/targets/target.json --repo api --repo worker --dry-run
```

These commands execute no Target code and make no provider calls. A dry run
creates no runtime state. It reports accepted and executable sites, held bindings
with their reasons, and hashes of code, contracts, dependencies and method.
The bundled `api` tests atomic byte-file cleanup; `worker` tests asynchronous
resource release. Both are owned examples, not independent OSS evaluation.

On a host where isolated experiments are permitted:

```bash
.venv/bin/reqlox run --target examples/targets/target.json --all \
  --seconds 120 --maximum-native-campaigns 12 --maximum-rounds 3
```

`--all` explicitly selects every registered repository. Alternatively repeat
`--repo` to select a subset. Selection is required; unknown or duplicate names
stop before experiments. `scripts/reqlox` provides the same commands directly
from a checkout, and `python3 -m reqlox` is another entry point.

## Copy selected repositories into a local Target

Register existing local repository roots, then copy their selected inputs into
a new private workspace. This requires no VM, repository import, dependency
installation, report fetching, or provider call. Namespace isolation and the
execution host's permission rules still apply when starting experiments.

```bash
export REQLOX_STATE_DIR="$HOME/.local/state/reqlox"
mkdir -p -m 700 "$REQLOX_STATE_DIR/target-snapshots"
reqlox target snapshot --target ./target.json --repo api --repo worker \
  --output "$REQLOX_STATE_DIR/target-snapshots/my-system"
reqlox target snapshot-audit --output "$REQLOX_STATE_DIR/target-snapshots/my-system"
reqlox run --target "$REQLOX_STATE_DIR/target-snapshots/my-system/target.json" --all --dry-run
```

The output contains `target.json`, `snapshot.json`, `repositories/NAME`,
`contracts/NAME.json`, and explicitly specified wheels under `dependencies/NAME`.
The existing selection rules choose Python files; their bytes and repository
order are preserved. Git metadata, unselected files, logs, caches, and whole home
directories are not copied. All copies share a 64 MiB / 4096-file limit; each
specified wheel is limited to 16 MiB. The parent must be owned by the current
user with mode `0700`; output directories use `0700` and files use `0600`.

Original selected inputs are checked before and after copying. Existing outputs
are never overwritten, and failed partial directories are retained. A copy
without a successful receipt is incomplete. `snapshot-audit` verifies the copied
file set, hashes, manifest, contracts, dependencies, and selection order without
executing Target code. It does not recheck the current original checkout, verify
a repair, grant execution authority, or establish independent generalization.
Local hashes and seals do not provide a trusted timestamp or external signature.

The optional `snapshot_receipt` manifest field binds a copy and its prepared
configurations to the saved receipt. Preparation and execution reject missing
receipts, modified copies, and prepared roots redirected to original repositories.
Copy membership is frozen; register a new original manifest to select more roots.
Use the copied manifest as input to `target prepare`, then inspect and run the
resulting configuration. A prepared configuration retains its copied roots.

## Register your repository roots

Create the manifest outside the repository roots, using an existing parent
directory. Paths supplied to registration resolve from your current directory;
stored relative paths resolve from the manifest location.

```bash
reqlox target init --target ./target.json --name my-system
reqlox target add --target ./target.json --repo api \
  --path ./repositories/api --configuration ./contracts/api.json
reqlox target add --target ./target.json --repo worker \
  --path ./repositories/worker --configuration ./contracts/worker.json
reqlox target list --target ./target.json
reqlox run --target ./target.json --repo api --repo worker --dry-run
```

Each configuration uses the same owned contracts as `qualify`. See
[`examples/targets/api.contracts.json`](../examples/targets/api.contracts.json)
and [`worker.contracts.json`](../examples/targets/worker.contracts.json).
Do not invent contract authority from an incident. Missing contracts or
unsupported shapes remain held. No repository-specific shell commands, hooks,
package installation, dependency fetching, paid calls or deployments occur.

The Target runner dispatches `atomic_file`, `async_resource`, `elapsed_ttl`,
`atomic_context`, and an explicitly configured documented path context. Atomic
context methods qualify bounded file persistence. Path contexts use the separate
`DOCUMENTED_SYNC_PATH_CONTEXT_V1` method described below. Their package reexports
and lifecycle methods may still be held by atomic-write binding; those reasons
remain in `atomic_held_bindings`. Selecting a documented caller does not turn
these atomic holds into successful executions or repairs.

## Select a documented path context

The included [owned path-context example](../examples/targets/path-context/target.json)
contains its README, source and full configuration:

```bash
reqlox run --target examples/targets/path-context/target.json --repo resource \
  --seconds 30 --maximum-native-campaigns 2 --dry-run
```

Use an explicit `path_context` configuration with `contracts: {}`. Its four
fields are `profile`, `documents`, `recipe`, and `contract`. The recipe must be
an existing author example returned by the path-context method; its module,
symbol, literal arguments and document spans are checked against the selected
source and saved documents. The contract has ID
`documented.path-context-release.v1`, scope `DOCUMENTED_WITH_EXIT_ONLY`, and a
hashed `document`/`span` supporting release on leaving the `with` context.
Missing, changed or negated release evidence is rejected. See the
[example configuration](../examples/targets/path-context/context.configuration.json).

`target prepare` preserves this configuration and its evidence. This method
rejects incident Source modes, additional hypotheses, paired execution and
dependency wheels. It does not infer an atomic writer or an EIO retry policy.
The selected finite checks cover normal exit, body `Exception` and
`BaseException`, repeated construction, and preservation of another invocation's
file. Normal and repeat cases are recorded separately. Cleanup system-call
failures are outside this documented contract.

The first native campaign runs these checks in an isolated process. A PASS
permits one fresh-process confirmation using the same plan. A counterexample is
retained as `COUNTEREXAMPLE_NO_SUPPORTED_REPAIR`; this adapter has no supported
repair generator or adoption path. A failed or unknown launch stops execution
and consumes its reserved attempt. The saved result and aggregate audit bind
both stages to the source, document, contract and execution method. Preparation
alone verifies no runtime outcome.

The manifest format is defined by
[`schemas/target.v1.schema.json`](../schemas/target.v1.schema.json).
A Target supports at most 16 repositories. Names contain 1–64 letters, digits,
dots, underscores or hyphens. Repository roots must be distinct, non-overlapping
and free of symlinks. Git roots use tracked Python files; directory snapshots
use a bounded walk. Untracked Git files and test/vendor/state directories are
excluded. Review the plan to confirm the intended code was selected.

A repository can specify a local `dependency` wheel for the existing TTL method.
This is not a dependency resolver. `--paired` uses separate Source/No Source
snapshots and prepares supplied `source_texts`; it rejects dependency wheels
and explicit hypotheses that this paired execution path does not consume.
Non-paired execution accepts prepared `hypotheses` with their `source_texts`.

## Freeze the inputs and interpret the result

To bind execution to an inspected plan, copy its `plan_sha256` into
`--expect-plan-sha256`. Keep the selection, paired mode and budget options the
same. A changed plan stops before experiments.

```bash
reqlox run --target ./target.json --repo api --dry-run
reqlox run --target ./target.json --repo api --expect-plan-sha256 REVIEWED_SHA256
```

`--seconds` is one execution deadline for all selected repositories, starting
after static preparation. Static preparation has separate repository/file bounds. The campaign budget
is also shared across repositories, comparison arms and repair rounds. Each
native attempt reserves a slot before dispatch. Failed and unknown attempts
retain their reservations. Processing is sequential in explicit selection order;
there is no parallel native execution or automatic retry after a terminal.
Insufficient budget stops the current run and preserves remaining names as
`NOT_RUN_AFTER_STOP`.

When an authorization already covers earlier runs, an optional manifest
`authorization` path binds execution to an explicit continuation record. The
same record can be supplied with `--authorization`; a different manifest-bound
record is rejected. Preparation preserves this path, and snapshot creation
rejects an already authorized manifest: make the copy before adding its grant.

`reqlox.authorization-continuation.v1` records hash-bound terminal ledger and
execution summary references, prior attempt and charged-time consumption,
inherited maxima, narrower new campaign/window limits, a concrete deadline,
selected source/configuration/method bindings, and a shared private reservation
directory. `APPROVAL_REQUIRED` can be inspected but cannot execute. Only an
explicitly approved, unexpired record can claim a single execution. Its exclusive
claim charges the complete new window conservatively before native dispatch;
new reservations continue the previous attempt numbers. All frontends share
that fence, including another run name or checkout. This local record enforces
the supplied bounds; it is not a signature or a substitute for the host owner's
authorization. An expired earlier deadline needs explicit owner approval for a
bounded continuation, without overwriting the earlier ledger or restoring its
consumed budget.

Private state defaults to `$XDG_STATE_HOME/reqlox` or `~/.local/state/reqlox`;
`--state-dir` selects another private directory. State must have mode `0700` and cannot be inside a registered repository.
Run output under `STATE/target-runs` must not overlap any repository. The same
private state root may contain a separate `STATE/target-snapshots` subtree. Each run has a unique directory
under `target-runs/`, containing an input plan, immutable native reservations,
per-repository evidence, and aggregate `result.json`. Reusing `--name` cannot
replace an earlier terminal. Runtime directories are user-owned private data;
do not commit them.

The aggregate reports each repository separately. `COMPLETE` requires all
selected finite contracts to complete, with no held bindings. `PARTIAL` retains
held or rejected results. `STOPPED` preserves the reason, previous results and
unexecuted names. Exit codes are `0` for planning or complete execution, `1` for
partial execution and `2` for a stop or invalid input. Child results can be
checked with `reqlox audit --kind loop` or `--kind paired`, using that child's
output directory.

A candidate is adopted only in an isolated snapshot. Selected Python source snapshots are
checked for drift and are not patched. The `checkout_unchanged_scope` field
identifies this observation boundary. Multiple repository results do not imply
cross-service integration, independent samples, an application-wide PASS,
independent generalization, natural Source added value or probability calibration.
Those claims require their own evidence. This interface adds reusable selection
and execution orchestration, not a new empirical effectiveness result.


## Prepare Source inputs for a selected Target

`target prepare` connects existing owner contracts to the existing supplied-text,
structured-condition, or local candidate-index preparation method. It creates a
new private bundle and preserves the original manifest and configuration files.
For a runnable owned example:

```bash
export REQLOX_STATE_DIR="$HOME/.local/state/reqlox"
mkdir -p -m 700 "$REQLOX_STATE_DIR"
reqlox target prepare --target examples/targets/target.json --all \
  --natural-source-input examples/targets/source-input.json \
  --output "$REQLOX_STATE_DIR/prepared-example"
reqlox run --target "$REQLOX_STATE_DIR/prepared-example/target.json" --all --dry-run
```

Use a new output name each time. The bundled Source is an illustrative owned
report, not an external incident effectiveness result. Without a new Source
input, preparation uses registered Source text, or preserves a no-Source
configuration. It retains extracted candidates and held conditions separately
from the configuration consumed by `run`. Output configurations are limited to
256 KiB. Unsupported conditions and missing owner requirements remain held.

`--condition-input` accepts `records` and `source_texts` for existing structured
condition preparation. `--source-index` with `--packets` reuses an existing local
candidate index. Source modes are mutually exclusive. `--specification-input`
accepts a `repositories` mapping covering exactly the selected names; each entry
has `specification_texts` and `owner_policies`. This reuses specification checks
and rejects reclassifying incident text as Target requirements. Extraction does
not establish semantic support or grant execution authority. The generated
configuration is for ordinary loops; paired execution continues to reject
explicit hypotheses it does not consume. No dependency fetching is added.

## Audit a multi-repository run

```bash
reqlox target audit --output PRIVATE_RUN_DIRECTORY
```

Use the `output` reported by `run`. New runs retain sealed inputs and aggregate
results, selected source/configuration snapshots, plan-bound per-repository
reservations, and child file hashes. The audit checks selection order, contracts,
Source, the shared deadline and budget, child records, and unexecuted names.
It executes no archived Python. Completed children use the currently installed
verifier only when method hashes match; a method mismatch stops the audit.
Older record formats are not rewritten or silently migrated.

`VERIFIED` means the aggregate records are consistent. Inspect
`child_semantics_verified` and `verified_repositories` separately: stopped and
unexecuted children remain unverified. If the aggregate terminal is missing,
`INCOMPLETE` retains `UNKNOWN_TERMINAL`. The audit writes no recovery state,
returns no reservation, and starts no new experiment. It checks historical
snapshot observations, not the current checkout or trusted external time.

## Use the local Target workspace

```bash
reqlox demo --target-manifest examples/targets/target.json
```

Open **Targets**, select repository names, and choose **Copy selection into Target**.
Preparation and inspection use that private copy. Changing the selection
requires a new copy. Repeat `--target-manifest` to register more named Targets.
The browser accepts only startup-registered manifests and calls the same
preparation, planning, execution, and audit methods as the CLI. It accepts no
arbitrary filesystem paths. Input changes invalidate the inspected plan.
Same-origin/token checks and the server's shared run lock cover these operations.

To inspect existing results, start the server with the same private
`REQLOX_STATE_DIR` and a registered manifest for that Target. **Saved observations**
lists at most 256 local run directories for registered Target names.
**Load and audit saved result** verifies the records before returning finite
counts for discovery, re-injection, normal regression, confirmation, held sites,
and candidate file names. Documented path contexts show the initial and fresh
confirmation observations and retain atomic binding holds separately. It starts
no experiments and returns no raw Source,
candidate code, absolute paths, or traces. Stopped children and paired runs whose
observations are not summarized display **Unconfirmed**. Records from a different
method revision can remain unsupported by the current audit; archived code is
never executed to restore compatibility.

Native reliability workers require a non-root user, zero effective capabilities,
and no visible home directory. `prlimit` applies CPU time of 2 seconds and an
address-space limit of 128 MiB before namespace setup; the parent enforces a
5-second wall limit. Worker observations record the effective limits and
namespace identities. A per-run CLI budget does not renew an authorization that
covers several runs: preserve the shared attempt ledger and remaining deadline
when an authorized scope requires them.

Native Target experiments are disabled by default. Campaign limit zero can
check budget stops and saved-record audits without running Target code. Enable
`--allow-target-experiments` only on an explicitly permitted isolated experiment
host. Candidate files are retained in private snapshots; original repository
files are not patched. This interface does not establish independent OSS
performance, natural Source added value, or calibrated probabilities.

## Current browser execution boundary

The [Records and history UI](ui-records-and-history.md) applies one offline policy
to all pages. New native runs and model calls are rejected before dispatch.
The old browser enable flag is not supported in serve mode; use the saved-record
flow and private history without resetting any scope ledger. CLI experiments
remain a separate, explicitly authorized workflow.
