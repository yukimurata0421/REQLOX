# ADR-0001: Use real-world incidents to expand resilience testing beyond human-imagined failure modes

- **Status:** Accepted as an initial architecture direction
- **Date:** 2026-09-04
- **Scope:** Architecture exploration only; no implementation or production authority

## Context

Human-authored chaos experiments are often bounded by failures that developers or
operators already imagine. Source analysis and general engineering practices can
identify many risks, but they do not completely expose production failure modes
that have not yet been experienced or show how failures from other systems could
manifest locally.

Public postmortems, outage reports, root-cause analyses, and other operational
records contain failure knowledge gathered from real events. Their
system-specific details are not always portable, but their underlying mechanisms
may be reusable.

## Problem

Human imagination limits failure-space coverage. A resilience program that tests
only pre-imagined failures may omit mechanisms already observed elsewhere.

## Decision

Explore an architecture that:

1. extracts reusable failure mechanisms from real incidents;
2. maps those mechanisms to analogous structures in a target system;
3. converts mappings into structured, controlled experiments;
4. evaluates results through observable evidence and deterministic oracles;
5. hardens the system when a weakness is demonstrated; and
6. persists successful hardening as reusable resilience regression cases after
   an equivalent re-test passes.

This is a decision to explore and evaluate the architecture. It is not a claim
that extraction, mapping, experiment generation, or automated hardening is already
implemented or effective.

## Safety decision

AI output remains proposal-level information. Mutation authority stays behind
deterministic policy and explicit safety boundaries.

Execution requires enforceable decisions about allowed and protected targets,
blast radius, intensity, duration, concurrency, abort conditions, rollback, and
authority. Evidence-dependent results must distinguish `PASS`, `FAIL`, and
`INCONCLUSIVE`; incomplete evidence must not silently produce `PASS`.

The initial architecture provides no default-branch write authority, automatic
merge authority, or production mutation authority to AI-generated proposals.

## Consequences

### Positive

- broader exploration of the failure space;
- reusable operational knowledge across systems;
- a measurable path from incident knowledge to hardening;
- portable incident-derived resilience tests;
- persistent regression assets after verified hardening.

### Negative and risks

- incorrect failure abstraction;
- incorrect target-system mapping;
- unsafe experiment proposals;
- source provenance and licensing complexity;
- model nondeterminism;
- observability gaps;
- false confidence caused by weak or incomplete evidence;
- provider-specific behavior that reduces portability.

## Open questions

- Direct context, RAG, an agent-tool protocol, or a hybrid?
- Which model or provider should be used for each task?
- How should the target system and its evidence be represented?
- What fault-provider abstraction is appropriate?
- How should deterministic oracles be specified and implemented?
- How much hardening authority can safely be automated?
- Under what conditions, if any, is production applicability acceptable?
- What should the final project name be?
