# Incident-Derived Resilience Hardening Framework

> Working title — project naming is not finalized.

This project explores an incident-derived resilience hardening loop: extract
reusable failure mechanisms from real-world incidents, map them onto a target
system, convert them into controlled fault experiments, and retain successful
hardening as resilience regressions.

## Problem

Chaos experiments are often limited to failure modes that developers and
operators have already imagined. Public postmortems and incident reports contain
additional failure knowledge, but that knowledge is rarely translated into
system-specific, repeatable resilience tests.

## Core idea

```text
Real-world incident
        ↓
Failure mechanism
        ↓
Target-system mapping
        ↓
Controlled experiment
        ↓
Observation
        ↓
Hardening
        ↓
Re-test
        ↓
Regression
```

AI may propose interpretations, mappings, experiments, and hardening changes.
Deterministic policy and explicit safety boundaries decide whether any proposal
is executable. Missing evidence must not be treated as a pass.

## Current status

This repository contains an initial architecture freeze. It does not yet contain
an implementation, a selected retrieval architecture, a selected fault-injection
backend, or an operational execution path.

## Documentation

- [Architecture](docs/architecture.md)
- [Conceptual background](docs/concepts.md)
- [ADR-0001: Incident-derived resilience testing](docs/adr/0001-incident-derived-resilience-hardening.md)
- [Apache License 2.0](LICENSE)
