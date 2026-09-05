# Incident-Derived Resilience Hardening Framework

> Working title. The repository slug and project name are not final.

This project is intended to turn failures that actually occurred in other
systems into experiments that search for weaknesses in a target system, then
retain verified improvements so they can be reused.

The project addresses two related problems:

1. free-form model reasoning and generic fault catalogues may miss combinations
   of conditions that exist in a particular target; and
2. repeatedly asking a model to reinterpret incident reports, target code,
   configuration, logs, and earlier trials can require substantial model use,
   experiment cost, elapsed time, and human review.

The proposed response is to preserve provenance, separate incident reports from
derived failure mechanisms, map those mechanisms to versioned target evidence,
and place every executable experiment behind a deterministic safety gate.

## Current status

**Design and evaluation planning only.** This repository does not contain an
implementation, usable CLI, selected fault-injection backend, operational
execution path, benchmark result, or production authorization.

A developer has observed qualitative improvement from a manual workflow that
adds incident reports and postmortems to AI-assisted investigation of a target
system. Effect size, causal contribution, reproducibility, discovery and miss
rates, and cost-effectiveness have not been measured under controlled
conditions. The observation motivates the hypotheses; it does not prove them.

## Proposed lifecycle

```text
External incident or postmortem
        ↓
SourceRecord → IncidentModel → FailureModel
        ↓
TargetMapping + human-owned SystemContract
        ↓
ExperimentSpec
        ↓
Deterministic Policy / Safety Gate
        ↓ approved only for an isolated target
Fault injection → injection confirmation → observation
        ↓
Independent Oracle → EvidenceBundle
        ↓
Human-reviewed hardening → same-condition and holdout re-tests
        ↓
HardeningRecord + RegressionCase
        ↓
Further exploration and reuse
```

AI may interpret evidence and propose mappings, experiments, and improvements.
It does not turn free text into execution authority, weaken a `SystemContract`,
or decide that missing evidence is a successful result.

## What the project will test

- **H1 — discovery:** whether incident-derived knowledge improves discovery of
  target-applicable, previously untested weaknesses over free reasoning or a
  generic fault catalogue under comparable execution conditions;
- **H2 — efficiency:** whether structured reuse preserves useful discovery and
  improvement while reducing model use, infrastructure cost, elapsed time, or
  human effort relative to the current manual incident-assisted workflow; and
- **H3 — generalization:** whether a hardening change helps under related
  conditions not used to produce it, and whether mappings to another target can
  correctly distinguish applicable, not applicable, and insufficient evidence.

The hypotheses are independent. Discovery may improve while cost rises;
efficiency may improve while discovery falls; or results may be target-specific.

## Scope

The initial candidate is one CLI/library process with local, inspectable
artifacts and one isolated target. Conceptual responsibilities do not imply
separate services, databases, or repositories. The project is not intended to
cover every incident, reproduce another company's environment, replace existing
fault injectors, delegate arbitrary production operations to AI, or guarantee
whole-system resilience with a single score.

Ops Evidence Synthesis (OES) remains an independent project. A future adapter may
exchange an explicitly defined evidence format, but OES is not a dependency and
its code or licensing is not incorporated here.

## Documentation

- [Architecture](docs/architecture.md)
- [Data contracts and invalidation](docs/data-contracts.md)
- [Evaluation plan](docs/evaluation-plan.md)
- [Safety and data-use policy](docs/safety-and-data-policy.md)
- [Minimal implementation plan](docs/minimal-implementation-plan.md)
- [Development context and conceptual background](docs/concepts.md)
- [ADR-0001: Incident-derived resilience testing](docs/adr/0001-incident-derived-resilience-hardening.md)
- [Apache License 2.0](LICENSE)

Third-party incident material is not automatically covered by this repository's
license. Its acquisition, local retention, model disclosure, quotation, and
redistribution require separate source-specific decisions.
