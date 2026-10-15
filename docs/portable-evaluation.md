# Portable Evaluation

The `reqlox study` interface connects three local workflows: preparing supported
targets, comparing Source-guided exploration with a source-blind baseline, and
reviewing probability calibration candidates. It accepts explicitly supplied
inputs and makes no model calls or registry requests.

These workflows are available implementation features. Unseen-OSS generalization,
natural Source benefit, and calibrated probabilities remain unestablished.

## Inherited execution scopes

`reqlox scope inspect --preflight PATH` reads a terminal cumulative ledger,
its existing reservation receipts, method hashes, and continuation limits. It
creates no runtime state, makes no network or model calls, and starts no Target.
The command reports recorded consumption and any appended execution stop. Its
output is an input consistency check, not a live health check or authorization.

The Python interface in [`evaluation_scope.py`](../reqlox/evaluation_scope.py)
provides the same checks to a trusted local supervisor:

```python
from reqlox.evaluation_scope import Guard

guard = Guard(preflight_path, new_output_directory,
              identity_reader=read_current_identity,
              observation_reader=read_current_runtime_facts)
guard()                    # Preparation checks; does not reserve a campaign.
guard.reserve_plan(plan)   # Required immediately before an authorized dispatch.
```

The current scope format is `INHERITED_FINITE_EVALUATION_SCOPE_V1`. It references
an immutable `reqlox.cumulative-continuation-terminal.v1` ledger and retains the
ledger's reservation directory. The supervisor supplies read-only identity and
runtime readers; a Target cannot select those readers. An approved native start
also requires a frozen plan binding, a current deadline, and fresh matching
runtime facts. Preparation-only scopes cannot dispatch a Target.

The guard rejects increased cumulative limits, changed inputs, expired windows,
new runtime anomalies, and attempts to use a different reservation directory.
It reserves before dispatch and charges the full continuation window before the
first start. Failed or unknown starts retain their consumption. Another run or
checkout cannot reuse the claim. An execution stop can bind a corrected terminal
ledger without changing historical receipts.

The guard itself neither starts nor terminates children. The caller must use the
isolated executor and enforce CPU 2 seconds, wall 5 seconds, memory 128 MiB, and
cleanup of only its owned children. The inherited scope is capped at 12 campaigns
and 120 seconds. A preparation deadline is separate from its native window;
additional preparation time does not renew native capacity.

Legacy preflights that count only a run directory are refused. The supported
fields and synthetic fixtures are covered by
[`test_evaluation_scope.py`](../tests/test_evaluation_scope.py). These offline
checks do not establish independent Target correctness or repair qualification.

## Browser workspace

Run `reqlox demo` and choose **Evaluation**, or open `/study` on its printed
loopback URL. The workspace uses the same Python interfaces as the CLI:

1. Prepare supplied Python sources or upload a target wheel and its complete
   dependency closure. Select a supported documented caller.
2. Freeze Source text and equal discovery budgets. Native comparison is disabled
   by default; the checkbox and run button stay disabled, and direct requests
   stop before dispatch. Preparation and freezing do not start an experiment.
   A separately authorized supervisor must verify an execution scope before
   enabling native work; a UI flag or checkbox supplies no such authority.
3. Score supplied probability rows, or fit and register a candidate with
   unlabeled confirmation forecasts. Review permits labels to be added while
   rejecting changed forecasts. Editing training or forecast inputs clears
   the page's registration reference.

Browser limits are narrower than the CLI: 128 Python files and 512 KiB of
source text, up to 8 pure-Python wheels and 4 MiB of wheel bytes in total,
256 probability rows, and 180 seconds / 32 campaigns per comparison.
The owned example is synthetic; its labels are already available and provide
no prospective calibration evidence.

The reliability chart and downloads contain aggregate diagnostics only.
Private inputs, individual forecast rows, candidates, and execution receipts
remain under `$REQLOX_STATE_DIR/demo/studies` with the default cache. The server
does not accept arbitrary filesystem paths from browser requests. It shares
one execution lock with the reproduction demo. This is a local application,
not a hosted deployment.

## Prepare a documented target

Preparation reads Python text and author documentation without importing target
code. It supports a bounded synchronous context over an owned path, including
supported direct public classes, factories, and documented public methods.
Documentation establishes the caller; observed behavior is not substituted for
the owner requirement. Missing dependencies and unsupported bindings are held
before any forecast or native execution.

Keep artifacts outside the checkout and installed package:

```bash
export REQLOX_STATE_DIR="$(mktemp -d)"
.venv/bin/reqlox study settings
.venv/bin/reqlox study prepare \
  --root examples/evaluation/repository \
  --documents examples/evaluation/documents.json \
  --project owned-example \
  --output "$REQLOX_STATE_DIR/preparation.json"
```

The example is an owned synthetic control. It is not an unused third-party
project. For other inputs, `--known-projects` accepts a JSON list of previously
exposed project names. That check covers the caller's declared history; it does
not establish independence from every prior conversation or experiment.

### Bind supplied dependency wheels

`reqlox study capsule` accepts a specification containing `target_project` and
`wheels`, each with a local `path` and expected `sha256`. It checks distribution
name/version, archive paths and bounds, pure-Python layout, license notices,
the complete file inventory, and declared dependency versions. It does not
install a package, execute a build, import package code, or infer rights approval.

```bash
.venv/bin/reqlox study capsule \
  --specification /absolute/path/to/wheel-specification.json \
  --output "$REQLOX_STATE_DIR/capsule.json"
.venv/bin/reqlox study prepare \
  --capsule "$REQLOX_STATE_DIR/capsule.json" \
  --documents /absolute/path/to/documents.json \
  --project your-project \
  --output "$REQLOX_STATE_DIR/preparation-with-dependencies.json"
```

File checks follow the [distribution RECORD format](https://packaging.python.org/en/latest/specifications/recording-installed-packages/).
Requirement parsing uses the [packaging requirement API](https://packaging.pypa.io/en/stable/requirements.html).
The supported capsule is intentionally finite: pure-Python wheels, complete
supplied dependency closure, no extras or direct-URL dependencies, and no binary
extensions or installation-time path hooks. A capsule can be ready statically
while the selected native context still produces an unknown outcome.

## Compare Source and No Source

```bash
.venv/bin/reqlox study compare-freeze \
  --preparation "$REQLOX_STATE_DIR/preparation.json" \
  --source examples/evaluation/source.json \
  --budget 4 \
  --output "$REQLOX_STATE_DIR/comparison.json"
.venv/bin/reqlox study compare-run \
  --freeze "$REQLOX_STATE_DIR/comparison.json" \
  --state-dir "$REQLOX_STATE_DIR" \
  --output "$REQLOX_STATE_DIR/comparison-run" \
  --seconds 180 --maximum-campaigns 32
```

The freeze binds original input text, method hashes, equal discovery budgets,
the common caller and oracle, a shared repair generator, and the same
confirmation envelope. The No Source planner inspects target deletion syntax
without reading the Source payload. Source projection uses exact supplied text
spans and a finite cleanup-condition grammar. Neither planner is exhaustive.

The original normal case must pass before discovery. An injected condition
must actually occur in every required case and repeat before a pass is retained.
Unsupported execution, unreached conditions, and missing receipts remain unknown.
Repairs are retained only in private copies. The source checkout is not edited.

Read both arms separately. A completed comparison can show zero additional
Source benefit or no eligible repair adoption. Supplied text is bound locally;
the interface does not authenticate external incident retrieval or causation.

## Score and register calibration candidates

The shipped datasets illustrate the interface with synthetic examples. Their
scores describe those examples and provide no evidence of population calibration.

```bash
.venv/bin/reqlox study score \
  --dataset examples/evaluation/confirmation.json \
  --output "$REQLOX_STATE_DIR/raw-scores.json"
.venv/bin/reqlox study calibrate-fit \
  --dataset examples/evaluation/training.json \
  --output "$REQLOX_STATE_DIR/candidate.json"
.venv/bin/reqlox study calibrate-register \
  --model "$REQLOX_STATE_DIR/candidate.json" \
  --training examples/evaluation/training.json \
  --forecasts examples/evaluation/forecasts.json \
  --output "$REQLOX_STATE_DIR/registration.json"
.venv/bin/reqlox study calibrate-review \
  --registration "$REQLOX_STATE_DIR/registration.json" \
  --training examples/evaluation/training.json \
  --confirmation examples/evaluation/confirmation.json \
  --output "$REQLOX_STATE_DIR/review.json"
```

Each dataset declares an event, predictor revision, and complete row denominator.
Rows contain an ID, event/revision, a binary probability answer, a label or
`null`, label authority, and Source/Target/mechanism/dependency groups. Optional
content and external-distribution hashes can prevent overlap beyond project
names. Missing forecasts and unknown labels remain in coverage accounting.

Registration rejects already labeled confirmation inputs and shared declared
groups/content. Review verifies that forecasts and the single trained candidate
were preserved; it does not refit on confirmation labels. These are local
integrity checks, not a trusted timestamp or proof of natural provenance.

The public row-input review returns `HELD`: it cannot establish that supplied
forecasts preceded independently observed natural outcomes. The shipped serving
settings remain `RAW`, threshold `0.85`, with no automatic candidate activation.
Minimum sample counts are engineering review gates, not statistical proof.

## Python API

```python
from reqlox import studies

prepared = studies.prepare_context(sources, documents, project="your-project")
source = studies.supplied_source(source_documents, url="https://example.test/report")
frozen = studies.freeze_comparison(prepared, source, budget=4)
scores = studies.score_forecasts(rows, event=event, predictor_revision=revision)
```

See [Data contracts](data-contracts.md), [Results](results.md), and
[Safety and data](safety-and-data-policy.md) for artifact and claim boundaries.

The development checkout now provides the same Incident library and Evaluation
lab assets and adapters. [The parity validation record](../publication/development-ui-parity.json)
records isolated HTTP/browser checks using owned examples, with no new model
calls or native campaigns. This record does not update an existing hosted release.

## Current browser execution boundary

The [Records and history UI](ui-records-and-history.md) applies one offline policy
to all pages. New native runs and model calls are rejected before dispatch.
The old browser enable flag is not supported in serve mode; use the saved-record
flow and private history without resetting any scope ledger. CLI experiments
remain a separate, explicitly authorized workflow.
