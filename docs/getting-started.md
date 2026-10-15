# Getting Started

The following commands use an installed repository checkout. No live model
credentials are needed for initial inspection or the English baseline demo.

## Read an existing demo first

Open the [hosted homepage](https://reqlox.yukimurata0421.dev/) with the existing owner
sign-in, or start the local UI using the instructions below. Choose **View the
recorded demo**. The four steps show the existing input, detected failure,
repair candidate and repeated-fault result. Next/Previous and the example selector
read stored summaries only. They do not run the fresh check or make a model call.


## Install and inspect

Use Python 3.11 or later. For isolated experiments, use Linux with `bubblewrap`,
usable user namespaces, and a Python interpreter whose resolved executable is
under `/usr`. Create the virtual environment from that interpreter.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/reqlox --version
.venv/bin/reqlox inventory --root examples/repository
.venv/bin/reqlox check
```

Inventory reads the example's source without importing it. `check` uses an
isolated `/usr/bin/true` probe and reports `experiments_available`; it does not
qualify a target. If the probe fails, inspect the reported prerequisites before
running an experiment.

## Run the local demo

```bash
.venv/bin/reqlox demo
```

Open the printed loopback URL. Select a report, target, assessment method, and
repair method. The available method identifiers are `baseline`, `recorded`,
and `live`; repair identifiers are `rule`, `recorded`, and `live`.

Choose **Evaluation lab** in the top navigation, or open `/study`, to use the
portable evaluation workspace. It reuses the same local server and styles.
Prepare Python text or supplied dependency wheels, freeze an equal-budget
Source comparison, and review probability datasets. Detailed inputs and worker
receipts stay in private state; downloaded summaries omit code and individual
forecast rows. The workspace makes no model calls or registry requests.

The owned example loads without execution. Native comparison requires its
execution checkbox and an explicit run. Each freeze runs once; another run
requires a fresh freeze. See [Portable evaluation](portable-evaluation.md) for
supported inputs and claim boundaries.

Baseline is a deterministic assessment. The default repair uses a finite rule.
Recorded mode requires separately supplied local assessments or candidate
proposals bound to the exact source, caller, and selected target.
Editing the report can invalidate a recorded lookup. A recorded assessment or
proposal is historical model output; a target experiment started from it is
a separate new execution.

The bundled reports are English, owned synthetic examples. Evidence quotations
refer to the exact supplied report text; the interface does not translate them.

For a CLI run with no target experiment:

```bash
.venv/bin/reqlox demo run --sample negative --method baseline
.venv/bin/reqlox demo run --sample unknown --method baseline
```

The expected statuses are `NOT_SUPPORTED` and `INSUFFICIENT_INFORMATION`.
These are valid non-executing outcomes. A supported report can acquire known
target distributions and execute healthy, fault, repair, and re-injection
stages. Use those paths only in an authorized disposable environment.

## Use the Python API

```python
import reqlox

inventory = reqlox.inventory({"module.py": "value = 1\n"})
conditions = reqlox.source_conditions(
    "report-1", "os.replace() raised OSError during replacement."
)
```

These calls inspect explicitly supplied text. They do not execute a target or
certify the meaning of the failure description.

## Prepare Source conditions

Choose an absolute, private state directory and set `REQLOX_STATE_DIR`. For
example, the following creates a new temporary root with mode `0700`:

```bash
export REQLOX_STATE_DIR="$(mktemp -d)"
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

state = Path(os.environ["REQLOX_STATE_DIR"])
configuration = json.loads(Path("examples/owned-requirements.json").read_text())
(state / "contracts.json").write_text(json.dumps(configuration["contracts"]))
(state / "source.json").write_text(json.dumps({
    "source_texts": {
        "report-1": "os.replace() raised OSError during replacement."
    }
}))
(state / "contracts.json").chmod(0o600)
(state / "source.json").chmod(0o600)
PY
.venv/bin/reqlox prepare --root examples/repository \
  --contracts "$REQLOX_STATE_DIR/contracts.json" \
  --natural-source-input "$REQLOX_STATE_DIR/source.json" \
  --output "$REQLOX_STATE_DIR/prepared.json"
```

This creates a quoted-condition configuration without provider calls or target
campaigns. Inspect its `selection` and held entries before using it. The output
path is immutable; select another filename for another preparation.

## Run a repository repair loop

The following command executes native fault experiments. Run it only on a
disposable execution host within your declared scope:

```bash
.venv/bin/reqlox qualify --root examples/repository \
  --configuration examples/owned-requirements.json \
  --seconds 120 --maximum-native-campaigns 12 --maximum-rounds 3
```

Use the prepared configuration instead to supply explicit Source conditions.
Add `--paired` to run separate Source and No Source loops; its campaign cap is
applied per arm. The overall deadline is shared. A result can be held, rejected,
or stopped even when a command was correctly configured.

Results go under the state root and report their output path. Candidate files
remain in the saved result; the input checkout is not updated. Do not interpret
`ADOPTED_IN_SNAPSHOT` as a deployed change.

To inspect campaign refusal without running a target, use the same configuration
with `--maximum-native-campaigns 0`. The owned example requires campaigns, so
this exits with code `2` and `REUSE_NATIVE_CAMPAIGN_LIMIT`. It records a stopped
loop under a newly allocated run directory.

## Audit a saved result

Start a new command process and use the output path from a completed loop:

```bash
.venv/bin/reqlox audit --kind loop --output /absolute/path/to/saved/run
```

Use `--kind paired` for a paired study. Keep the same `REQLOX_STATE_DIR`, or pass
`--state-dir` to select the root containing the run. Audit checks trusted private
artifacts and their saved method; it executes no new target campaign. A stopped
or incomplete record is not necessarily eligible for a complete-result audit.

## Optional live mode

Install optional dependencies with `.venv/bin/python -m pip install '.[cloud]'`.
Set up application-default credentials separately, create a private model scope,
and explicitly configure project, location, model, deadline, call count, token
limit, and reservations. The checked-in
[scope example](../examples/cloud-scope/phase-user-scope.json) is disabled.

Pass `--model-scope /absolute/private/scope` to the demo. Live mode also requires
the explicit send-to-model choice. No live connectivity or billing result is
claimed by the public validation snapshot. See
[Safety and data](safety-and-data-policy.md) before disclosing text.

For more options, run `reqlox --help`, `reqlox demo --help`, or
`reqlox prepare --help` using the installed entry point.

## Select repositories in a Target

Use `reqlox run --target examples/targets/target.json --repo api --dry-run`
to inspect one registered repository, repeat `--repo` for several, or use
`--all` explicitly. [Target workspaces](target-workspaces.md) explains registration,
shared budgets, input binding and per-repository results.

## Current browser execution boundary

The [Records and history UI](ui-records-and-history.md) applies one offline policy
to all pages. New native runs and model calls are rejected before dispatch.
The old browser enable flag is not supported in serve mode; use the saved-record
flow and private history without resetting any scope ledger. CLI experiments
remain a separate, explicitly authorized workflow.
