# REQLOX

**Use incident knowledge to test and repair reliability weaknesses before release.**

REQLOX provides a Python library, a command-line interface, and a local browser
demo for finite reliability experiments. It connects quoted failure conditions
to supported Python code, compares observations with a fixed contract, and
retains repair candidates and verification records.

The product goal is to reduce repeated investigation and human intervention
while keeping results inspectable. Those savings are not quantified by this
public validation snapshot.

The public implementation covers bounded code patterns and known demo targets.
It does not provide a general incident-to-production repair service.

## Try it locally

Use Python 3.11 or later. Isolated experiments require Linux, `bubblewrap`,
working user namespaces, and a Python executable that resolves under `/usr`.
A virtual environment created from that interpreter is supported.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[knowledge]'
.venv/bin/reqlox inventory --root examples/repository
.venv/bin/reqlox check
.venv/bin/reqlox demo
```

Open the local URL printed by the last command. The server binds to
`127.0.0.1`; it is not a public hosting endpoint. The demo uses two known
controls, `py-cachify` and `readerwriterlock`, and a bounded lock-cleanup
scenario. The browser UI now supports offline records, input drafts and static
preparation; all new native execution and model calls are disabled at one
server boundary. See [Records and history](docs/ui-records-and-history.md).
Recorded assessments and repair proposals are optional local inputs; detailed
model and experiment records are not bundled.

Choose **Evaluation** in the navigation to prepare documented targets, freeze
Source and No Source comparison inputs, and review probability diagnostics in the
same local UI. Its owned examples, private artifacts, and aggregate result
exports are described in [Portable evaluation](docs/portable-evaluation.md).

For an initial run that does not execute a target:

```bash
.venv/bin/reqlox demo run --sample negative --method baseline
```

Choose **Knowledge** to import and search supplied reports, prepare source-bound
incident IR, and review missing probability outcomes. The current local methods
are available through the CLI and Python API as well. See
[Local incident knowledge](docs/local-knowledge.md) for an owned end-to-end
example and explicit provider scopes.

See [Getting started](docs/getting-started.md) for the repository repair loop,
condition preparation, state directories, and saved-result audits.

## Select repositories in a Target

An explicit documented path-context configuration also connects author README
examples to finite exit-release checks and fresh-process confirmation. Try the
[owned example](examples/targets/path-context/target.json) and read its
[contract and budget boundaries](docs/target-workspaces.md#select-a-documented-path-context).

Use a private copy of registered repositories for local preparation and isolated
experiments. A VM is optional; the execution host must permit the bounded
namespace workers. Copying alone does not verify a fault or a repair.

```bash
export REQLOX_STATE_DIR="$HOME/.local/state/reqlox"
mkdir -p -m 700 "$REQLOX_STATE_DIR/target-snapshots"
.venv/bin/reqlox target snapshot --target examples/targets/target.json --all \
  --output "$REQLOX_STATE_DIR/target-snapshots/my-system"
.venv/bin/reqlox target snapshot-audit --output "$REQLOX_STATE_DIR/target-snapshots/my-system"
.venv/bin/reqlox run --target "$REQLOX_STATE_DIR/target-snapshots/my-system/target.json" --all --dry-run
```


A Target manifest groups named repository roots and their individual contract
configurations. From this checkout after installation, inspect the owned `api`
and `worker` examples:

```bash
.venv/bin/reqlox target list --target examples/targets/target.json
.venv/bin/reqlox run --target examples/targets/target.json --repo api --dry-run
.venv/bin/reqlox run --target examples/targets/target.json --repo api --repo worker --dry-run
.venv/bin/reqlox run --target examples/targets/target.json --all --dry-run
```

Repeat `--repo` to select several names, or use `--all` to explicitly select every
registered repository. Dry runs inspect and hash the plan without executing
Target code, calling a provider, or creating runtime state.

On a host where isolated experiments are permitted, execute a bounded run:

```bash
.venv/bin/reqlox run --target examples/targets/target.json --all \
  --seconds 120 --maximum-native-campaigns 12 --maximum-rounds 3
```

The execution deadline and native campaign limit are shared across all selected
repositories, comparison arms, and repair rounds. Candidates are adopted in
isolated snapshots. See [Target workspaces](docs/target-workspaces.md) for
`target init`, `target add`, contract configuration, and saved results.

Prepare supplied Source text with registered contracts, then audit an aggregate
result without executing another experiment:

```bash
.venv/bin/reqlox target prepare --target examples/targets/target.json --all \
  --natural-source-input examples/targets/source-input.json --output PRIVATE_NEW_DIRECTORY
.venv/bin/reqlox run --target PRIVATE_NEW_DIRECTORY/target.json --all --dry-run
.venv/bin/reqlox target audit --output PRIVATE_RUN_DIRECTORY
.venv/bin/reqlox demo --target-manifest examples/targets/target.json
```

Replace `PRIVATE_NEW_DIRECTORY` with a new directory under the private
`REQLOX_STATE_DIR` (default `~/.local/state/reqlox`), using an existing parent, and `PRIVATE_RUN_DIRECTORY` with a run's reported output directory. The
**Targets** page first copies the selection, then uses the same preparation, planning, run, and audit methods.
Native Target experiments are disabled in the UI by default. See
[Target workspaces](docs/target-workspaces.md) for isolation and audit boundaries.


## What is included

| Interface | Available behavior |
| --- | --- |
| `reqlox target` / `reqlox run` | Register multiple repositories in a Target, inspect an explicit selection, and run with one shared finite budget. |
| `reqlox inventory` | Inspect a Python snapshot without importing target code; report accepted and held bindings. |
| `reqlox prepare` | Prepare supplied, quoted failure conditions against declared contracts. |
| `reqlox qualify` | Run a bounded repair loop on a supported snapshot; retain candidate changes without writing to the checkout. |
| `reqlox qualify --paired` | Run separate Source and No Source arms from the same initial snapshot. |
| `reqlox audit` | Verify a saved result using its recorded method and current claim checks; execute no new target experiments. |
| `reqlox demo` | Inspect evidence and finite observations in a local UI. |
| `reqlox study` | Prepare documented targets and dependency capsules, compare equal-budget Source/No Source exploration, and review calibration candidates. |
| `reqlox knowledge` | Import or explicitly fetch reports, search a local index, freeze and review native IR, run explicitly scoped generation and parallel judging, and retain partial score bounds. |
| Python API | Use `reqlox.inventory()`, `reqlox.source_conditions()`, and `reqlox.studies` on explicitly supplied inputs. |

The repository also includes schemas, owned examples, portable unit tests,
optional native integration tests, and an optional cloud model adapter.

## Read the project

- [Documentation index](docs/README.md): choose a path through the public documentation.
- [Reviewer guide](docs/reviewer-guide.md): a short path through runnable behavior and inspectable engineering evidence.
- [Concepts](docs/concepts.md): Source, Target, contracts, candidates, and result boundaries.
- [Architecture](docs/architecture.md): implemented data flow and component locations.
- [Data contracts](docs/data-contracts.md): inputs, saved artifacts, and integrity checks.
- [Target workspaces](docs/target-workspaces.md): register repositories, inspect a plan, and execute selected names.
- [Results](docs/results.md): interpret statuses and inspect a completed or stopped run.
- [Evaluation](docs/evaluation-plan.md): published validation scope and further measurements.
- [Tests and coverage](docs/testing.md): portable checks, per-file thresholds, reports, and remaining coverage gaps.
- [Records and history](docs/ui-records-and-history.md): common execution gate, archived outcomes, private restoration and exact Source lineage.
- [Portable evaluation](docs/portable-evaluation.md): local preparation, Source comparison, and probability diagnostics.
- [Local incident knowledge](docs/local-knowledge.md): document search, current IR methods, explicit provider scopes, and reference SQL.
- [System IR reproduction](docs/system-ir-reproduction.md): frozen code/spec projection and request-bound offline review.
- [Safety and data](docs/safety-and-data-policy.md): execution and disclosure boundaries.
- [Public scope](docs/minimal-implementation-plan.md): available capabilities and remaining work.

## Validation scope

The [knowledge port validation](publication/knowledge-port.json) covers the local
knowledge interfaces and their installation. The [UI validation](publication/ui-validation.json) covers the earlier browser
workspaces and their packaged runtime. The earlier
[evaluation implementation validation](publication/evaluation-validation.json)
records checks of this public implementation, installation outside the
development import path, English interfaces, and bounded owned controls.
The [earlier runtime snapshot](publication/validation.json) is historical;
its file hashes do not describe the updated implementation.

Implementation verification and owned controls do not establish effectiveness
on independent unseen projects, natural Source benefit, or probability
calibration. An owner-authenticated cloud workspace was deployed on 12 October
2026 (JST). The [hosted deployment record](docs/hosted-deployment.md) identifies
the revision verified through the public browser, its archived result display,
and the existing automatic stop deadline. Deployment and archived summaries
do not establish a new live experiment. New browser checks are disabled. The CLI baseline needs no
paid model call.

## Limits and license

Accepted static bindings are candidates for the supported finite contracts;
they are not proof of a defect or of compatibility with arbitrary Python.
A successful finite repair does not establish cross-target generalization,
incident-cause accuracy, production readiness, or a measured reduction in cost.

Repository-authored material is licensed under [Apache License 2.0](LICENSE).
External incident text and downloaded target distributions retain their own
rights and licenses. Raw corpora, private evidence, credentials, and runtime
state are not part of this public repository.
