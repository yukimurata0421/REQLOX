# Initial Architecture

## Status

This document records the initial architecture of a working concept called the
**Incident-Derived Resilience Hardening Framework**. The project name is not
finalized. This is an architecture freeze, not evidence that the system has been
implemented or validated.

The following labels distinguish the maturity of statements in this document:

- **Current Design Decision**: a boundary accepted for the initial architecture.
- **Hypothesis**: an idea that must be tested.
- **Open Question**: a decision intentionally deferred.
- **Future Evaluation**: a proposed measurement, not a reported result.
- **Non-goal**: work intentionally outside the current scope.

## Problem statement

AI-assisted software development can support source analysis, code generation,
bug fixing, tests, and application of general engineering practices. Source code
alone, however, does not completely reveal where a system will fail in
production, which failure modes have not yet been experienced, or how an incident
from another system could manifest locally.

Traditional chaos engineering often begins with a failure already imagined by a
developer or operator:

```text
Human imagines failure
        ↓
Chaos experiment
        ↓
System test
```

This leaves failure-space coverage bounded by what people have already imagined.
Real-world postmortems, outage reports, root-cause analyses, operational failures,
and near-miss reports contain additional mechanisms that can broaden that space.

**Hypothesis:** reusable mechanisms can be extracted from those incidents, mapped
to analogous structures in a target system, and converted into controlled fault
experiments. Failures experienced elsewhere could then become failures tested
proactively and safely in a local environment.

## Core objective

Fault injection is a means, not the objective. The objective is to transform
real-world operational failure knowledge into measurable software and system
hardening.

The hardening surface can include:

- application and infrastructure code;
- configuration, retries, timeouts, queues, concurrency, and resource limits;
- dependency handling and recovery logic;
- restart and mutation authority;
- observability and detection;
- control-plane behavior and architecture boundaries.

The intended closed loop is:

```text
External failure knowledge
        ↓
Failure abstraction
        ↓
Target-system mapping
        ↓
Controlled fault experiment
        ↓
Observation
        ↓
Weakness discovery
        ↓
Hardening
        ↓
Re-test
        ↓
Persistent resilience regression
```

## Design principles

### Current Design Decisions

1. Incident provenance remains attached to derived failure knowledge.
2. Failure semantics are separated from unnecessary vendor and system details.
3. A human-authored system contract defines what must remain true.
4. AI output remains proposal-level information.
5. Deterministic policy controls execution authority and safety limits.
6. Experiments use a structured intermediate representation before execution.
7. Results have at least three states: `PASS`, `FAIL`, and `INCONCLUSIVE`.
8. Missing evidence does not silently become `PASS`.
9. Successful hardening is re-tested before it becomes a regression asset.
10. Existing fault-injection providers should be reused where suitable.

## High-level architecture

```text
┌──────────────────────────────────────┐
│ External Failure Knowledge           │
│ Postmortems, incident reports, RCA   │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 1. Source / Provenance               │
│ Identity, time, license, integrity   │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 2. Failure Knowledge Extraction      │
│ Trigger, mechanism, impact, unknowns │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 3. Portable Failure Model            │
│ Reusable failure semantics           │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 4. Target-System Understanding       │
│ Topology, contracts, invariants      │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 5. Failure Mapping                   │
│ Analogous local structures           │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 6. Experiment Generation             │
│ Structured ExperimentSpec            │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 7. Deterministic Safety Gate         │
│ Authority, limits, abort, rollback   │
└──────────────────┬───────────────────┘
                   │ APPROVED
                   ▼
┌──────────────────────────────────────┐
│ 8. Fault-Injection Provider          │
│ Provider selected by capability      │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 9. Observation                       │
│ Metrics, logs, traces, visible state │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 10. Deterministic Oracle             │
│ PASS / FAIL / INCONCLUSIVE           │
└──────────────────┬───────────────────┘
                   │ FAIL
                   ▼
┌──────────────────────────────────────┐
│ 11. Hardening                        │
│ Code, config, architecture, recovery │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ 12. Re-test                          │
│ Execute an equivalent experiment     │
└──────────────────┬───────────────────┘
                   │ PASS
                   ▼
┌──────────────────────────────────────┐
│ 13. Resilience Regression            │
│ Persist reusable regression knowledge│
└──────────────────────────────────────┘
```

## Initial contract boundaries

These boundaries are concepts, not implemented schemas.

### `SourceIncident`

Identifies the external source and its provenance. Candidate fields include the
source URL, publisher, title, source type, publication and retrieval timestamps,
license metadata, provenance, and integrity metadata.

### `FailureMechanism`

Represents failure semantics with unnecessary vendor or product details removed
where possible. For example:

```text
dependency degradation
+ unbounded retry
+ bounded resource pool
+ traffic amplification
= resource exhaustion or cascading failure
```

### `SystemContract`

Defines, through human-controlled input, what must remain true. Candidate content
includes objectives, invariants, service-level indicators, protected resources,
authority boundaries, prohibited mutations, critical dependencies, and the
allowed mutation surface. The architecture does not assume that an AI model has
complete understanding of the target system.

### `TargetMapping`

Maps a `FailureMechanism` onto target components, dependencies, resources,
services, processes, code paths, queues, or network paths. A future representation
may include supporting evidence, confidence, and explicit uncertainty.

### `ExperimentSpec`

Provides a structured intermediate representation rather than immediately
executing generated shell commands. Candidate content includes the target,
failure type, parameters, intensity, duration, expected symptoms, expected
detection and recovery, invariants, and abort conditions.

### `SafetyDecision`

Records a deterministic decision about whether an `ExperimentSpec` may execute,
including the applicable authority and enforced limits.

### `ObservationBundle`

Contains the observability evidence collected during and after an experiment.

### `ExperimentResult`

Records at least `PASS`, `FAIL`, or `INCONCLUSIVE`. An incomplete observation
bundle cannot support `PASS` merely because a failure was not observed.

### `RegressionCase`

Represents a reusable experiment that passed after a hardening change was applied
and the equivalent failure condition was tested again.

## AI and deterministic responsibility

### AI may propose

- incident interpretation and failure-mechanism extraction;
- abstraction of reusable semantics;
- target-system investigation and analogous-structure discovery;
- target mappings and experiment designs;
- hardening changes;
- interpretation support for collected results.

### AI alone must not authorize

- experiment execution or destructive mutation;
- target selection outside an allowlist;
- blast radius, concurrency, maximum intensity, or maximum duration;
- mutation of protected resources;
- abort enforcement or rollback;
- production mutation;
- a final evidence-dependent `PASS` decision.

**Current Design Decision:** AI may propose. Deterministic policy decides whether
a proposal is executable.

## Safety boundary

An experiment is ineligible for execution unless deterministic controls can
enforce all applicable constraints:

- explicit execution authority;
- allowed and protected targets;
- bounded blast radius, duration, intensity, and concurrency;
- preconditions and stop conditions;
- enforceable abort behavior;
- a defined rollback or safe terminal state;
- sufficient observation to evaluate invariants.

The initial architecture grants no production authority and defines no autonomous
production-destruction path. Safety violations—including unauthorized mutation,
limit violations, protected-resource mutation, abort failure, and unintended
destructive action—have a target count of zero.

## Retrieval and context strategy

**Open Question:** Direct context, search, retrieval-augmented generation, vector
databases, agent-tool protocols, repository-native access, web retrieval, and
hybrid approaches remain candidates.

The current hypotheses are that search or retrieval may help with external
incident knowledge, tool interfaces may help with live repository or system
access, and fixed direct context may suit system contracts and safety policy.
These hypotheses are not selected architecture.

Retrieval and agent-tool architecture will be selected empirically rather than
assumed upfront.

## Fault-injection backend

**Open Question:** No provider is selected. Future candidates may include Chaos
Mesh, Litmus, `tc`/`netem`, Toxiproxy, systemd, container or Kubernetes
primitives, and managed cloud fault-injection services. The primary purpose is
not to reimplement a general-purpose fault injector.

## Hardening automation boundary

The future loop may be:

```text
FAIL
  ↓
AI proposes a patch
  ↓
Isolated branch
  ↓
Tests
  ↓
Equivalent fault experiment
  ↓
PASS
  ↓
Human review
  ↓
Merge
```

**Current Design Decision:** AI does not receive direct write authority to the
default branch. Automatic merge and production mutation are not assumed.

## Relationship to Ops Evidence Synthesis

Ops Evidence Synthesis (OES) and this project have separate responsibilities.

```text
OES                                  This framework
Incident                             Incident knowledge
  ↓                                    ↓
Evidence                             Failure abstraction
  ↓                                    ↓
Investigation                        System mapping
  ↓                                    ↓
Hypothesis                           Experiment
  ↓                                    ↓
Evidence-grounded review             Fault injection
  ↓                                    ↓
Human decision                       Observation
                                       ↓
                                     Hardening
                                       ↓
                                     Regression
```

OES addresses incident investigation and evidence governance. This framework
addresses resilience experimentation and the hardening loop. OES is not a
required dependency, and this project does not change OES licensing or commercial
policy. A future integration adapter is possible but undecided.

## Third-party source policy

**Current Design Decision:** publicly accessible content is not assumed to permit
unrestricted redistribution. Derived records should retain the source URL,
publisher, publication and retrieval timestamps, available license metadata,
provenance, and integrity metadata. Structured failure representations may be
stored, but the architecture does not automatically vendor and redistribute full
third-party postmortems.

This design principle is not a legal determination. Precise ingestion,
retention, quotation, and redistribution rules remain future work.

## Future evaluation

No evaluation result is claimed yet. Candidate measurements are:

- **Failure Extraction Accuracy:** correctness of extracted failure semantics.
- **Target Mapping Accuracy:** correctness of mappings to target structures.
- **Executable Experiment Rate:** share of mappings converted into safe,
  executable experiments.
- **Novel Failure Coverage:** failure modes added beyond existing human-authored
  tests; this is an important candidate KPI.
- **Reproduction Fidelity:** similarity between the injected failure semantics or
  symptoms and those reported by the source incident.
- **Hardening Yield:** share of source incidents that lead to meaningful code,
  architecture, or configuration improvements and successful re-tests.
- **Inconclusive Rate:** share of evaluations that lack enough evidence or
  mapping certainty for a verdict.
- **Safety Violations:** unauthorized mutation, boundary violations, abort
  failures, and unintended destructive actions; the target is zero.
- **Generalization Benefit:** whether hardening against one failure also improves
  behavior under related failures that were not directly used for that change.

Metric definitions, datasets, baselines, and acceptance thresholds remain open.

## Non-goals

The initial architecture does not aim to:

- create a replacement for existing chaos-engineering platforms;
- enable autonomous production destruction or unrestricted privileged access;
- automatically collect and redistribute complete third-party postmortems;
- open-source OES or change its rights policy;
- require a particular model provider, retrieval method, or agent-tool protocol;
- claim production readiness, validated safety, or successful hardening results;
- finalize the project name or turn conceptual analogies into implementation
  terminology.

## Open questions

- Direct context, RAG, an agent-tool protocol, or a hybrid?
- Which model or provider is appropriate for each reasoning task?
- How should a target system and its evidence be represented?
- Which provider abstraction supports controlled, portable experiments?
- How should deterministic oracles be specified and implemented?
- What hardening authority can be safely automated?
- Under what conditions, if any, could production applicability be considered?
- What should the project ultimately be called?
