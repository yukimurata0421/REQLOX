# Minimal Implementation Plan

## Status

This is a proposed implementation sequence. No phase has started, no backend or
target has been selected, and no completion criterion has been met. The plan
keeps the smallest coherent path while preserving safety and evaluation needs.

## First vertical slice

The first slice should connect:

- a small, human-selected set of incident sources with reviewed use rights;
- one deliberately isolated and disposable target;
- one structured failure mechanism;
- one evidence-grounded `TargetMapping`;
- one existing fault-injection backend behind a narrow adapter;
- one human-approved, frozen `SystemContract` and independent oracle;
- one serial experiment with injection and cleanup confirmation;
- one local, inspectable `EvidenceBundle`;
- one human-reviewed hardening change applied only in isolation;
- same-condition and one related holdout re-test; and
- separately measured first-use and reuse consumption.

The preferred teaching mechanism is either bounded retry amplification against a
finite resource pool or lost response after a committed test side effect. The
choice is made only after confirming that the selected target exposes the
required mechanism and that the backend can inject and remove the condition
safely. The mechanism must not be forced onto a non-applicable target.

## v0.x shape

Use one CLI/library process and a local artifact tree. Modules may separate
parsing, mapping, policy, execution, observation, oracle, and reporting in code,
but no module initially requires its own service, database, deployment, or
repository.

Execution is serial. The implementation supports exactly one target adapter and
one injector capability needed by the first slice. The adapter consumes typed
parameters rather than arbitrary model-generated commands.

An illustrative artifact layout is:

```text
workspace/
  sources/              # metadata and only permitted source representations
  incidents/            # IncidentModel revisions
  failures/             # FailureModel revisions
  targets/              # versioned target evidence manifests
  mappings/             # TargetMapping revisions
  contracts/            # human-approved SystemContract versions
  experiments/          # specs and deterministic safety decisions
  runs/                  # event manifests and EvidenceBundles
  hardening/             # reviewed HardeningRecords
  regressions/           # RegressionCases
```

This layout is explanatory. Exact filenames, serialization, and commands are
open and must not be documented as available until implemented.

## Phase 0 — freeze the demonstrator

**Work:** select the isolated target, one mechanism, a small source set, one
backend capability, target snapshot method, and reviewers. Define data handling,
budgets, clean-state requirements, and exclusions before code.

**Artifacts:**

- source-selection and rights record;
- target/environment identity and disposable reset method;
- initial `SystemContract` and oracle specification;
- mechanism applicability checklist;
- backend capability/cleanup assessment; and
- measurement sheet for model/tool use, infrastructure, elapsed time, and human
  effort.

**Complete when:** an authorized reviewer can determine from the artifacts what
may run, what must never run, how the fault and cleanup will be confirmed, and
what evidence produces each verdict. Any unknown that affects safety remains a
stop, not an implementation assumption.

## Phase 1 — local contracts and lineage

**Work:** implement local serialization/validation for `SourceRecord`,
`IncidentModel`, `FailureModel`, target snapshot manifest, `TargetMapping`, and
`SystemContract`. Preserve per-claim provenance and revision edges.

**Artifacts:**

- versioned local records for the selected source/mechanism/target;
- validation errors for missing evidence and invalid rights scope;
- deterministic artifact references and integrity metadata; and
- a human-reviewed applicability decision.

**Complete when:** the same inputs produce reviewable records; source statements
and inference are distinguishable; the mapping cannot become `APPLICABLE` with
required conditions unknown; target or contract change marks dependent mappings
stale.

## Phase 2 — non-executing experiment planning

**Work:** generate and validate a typed `ExperimentSpec`, implement the
deterministic policy evaluator, and exercise only rejection/dry planning paths.

**Artifacts:**

- one frozen spec linked to all inputs;
- one policy decision format;
- allow/deny tests for target, operation, duration, intensity, budget,
  observations, and cleanup; and
- preflight drift and stale-cache tests.

**Complete when:** every field that can change effect is bounded by contract and
policy; free-form instructions cannot reach an adapter; unknown/stale inputs fail
closed; changing a semantic field invalidates the decision.

## Phase 3 — isolated execution and evidence

**Work:** connect the one approved adapter in the disposable target. Verify
injection establishment, required observations, stop behavior, cleanup, and
clean-state recovery. Record each dimension of `ExperimentResult` separately.

**Artifacts:**

- run event manifest and bounded timestamps;
- injection and cleanup confirmation;
- oracle input/output;
- multidimensional result and attribution; and
- complete or explicitly incomplete `EvidenceBundle`.

**Complete when:** the harness can demonstrate both a valid run and essential
negative paths: injection not established, mandatory observation absent,
prohibited request rejected, harness error distinguished, cleanup verified, and
next-run contamination blocked. A clean controller exit is not sufficient.

## Phase 4 — human-reviewed hardening and re-test

**Work:** only if a valid run confirms a weakness, create a candidate target
change on an isolated development branch/worktree, review it, and apply it to the
disposable target. Keep the contract, load, and oracle frozen for the exact
re-test. Predeclare one related holdout condition not used to design the change.

**Artifacts:**

- reviewed target change identity;
- before/after evidence under the same condition;
- normal functional and relevant performance checks;
- holdout-condition result; and
- `HardeningRecord` with scope, side effects, and unknowns.

**Complete when:** the original weakness has a conclusive same-condition result,
normal behavior is checked, the holdout result is reported separately whether
positive or negative, and no contract/oracle change is hidden inside the target
fix.

If the initial run confirms no weakness or is inconclusive, retain that result
and do not manufacture a hardening phase.

## Phase 5 — regression and measured reuse

**Work:** create a `RegressionCase` only from a valid hardening record, then rerun
it after a compatible target change. Reuse the validated incident/failure
knowledge for a fresh mapping or holdout selection and measure reuse effort.

**Artifacts:**

- regression compatibility predicate and run;
- first-use versus reuse cost record;
- invalidation behavior for a target or contract change; and
- limitations on portability and generalization.

**Complete when:** exact regression replay, holdout exploration, and cross-target
mapping are distinguishable; stale mappings/specs do not execute; costs are
reported in observable native units with missing values explicit.

## Progression gates

Progress to a second mechanism or target only after:

- lineage and invalidation work for the first slice;
- negative policy and harness cases pass in isolation;
- injection removal and clean state are independently confirmed;
- at least one complete result exists, including a legitimate no-weakness or
  inconclusive result;
- first-use cost and human effort are measured; and
- reviewers agree that adding a case tests a new question rather than duplicating
  the first experiment.

Progress to parallel execution, another backend, or a persistent service only
when measured workload and failure modes establish a need. Each would require a
new concurrency, authority, cleanup, and evidence design.

## Explicitly excluded from the first slice

- automatic crawling or bulk ingestion;
- large vector databases or a fixed retrieval architecture;
- multi-agent voting or autonomous planning swarms;
- production targets or automatic production repair;
- multiple injectors, clouds, or operating systems;
- distributed control, locks, or scheduling;
- management Web UI;
- automatic default-branch changes or merges;
- OES as a dependency or incorporated code; and
- performance, discovery, savings, or safety claims before evaluation.

A hackathon or cloud demonstration, if later useful, is an adapter/demo outside
the core dependency set and cannot redefine the core safety boundary.

## Open design decisions

- exact isolated target and first mechanism;
- source set and source-specific retention/model/publication permissions;
- serialization format and compatibility policy;
- target snapshot and clean-state proof;
- existing injection backend and minimum adapter interface;
- deterministic policy language/implementation;
- oracle representation and independent review process;
- observable model/tool utilization metrics;
- retrieval/context strategy after measuring the manual path; and
- thresholds for expanding targets or capabilities.

Final naming, production applicability, autonomous hardening authority, and
distributed architecture remain outside v0.x and are not prerequisites for the
first design-to-evidence slice.

## First implementation task

After this documentation is reviewed, the smallest implementation task is:

> Define and validate local, versioned representations for `SourceRecord`,
> `FailureModel`, `TargetMapping`, and a human-approved `SystemContract` for one
> hypothetical/disposable-target case, including provenance and invalidation,
> without adding an execution adapter.

This creates the minimum trustworthy input boundary for later experiment
planning while keeping fault injection and runtime mutation out of the first
implementation change.
