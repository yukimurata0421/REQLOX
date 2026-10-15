# Documentation

These pages describe the current public REQLOX package: its purpose, available
interfaces, component structure, input/output contracts, and evidence limits.
They are a usage and inspection guide, not a transcript of development history.

## Choose a reading path

| Goal | Read in order |
| --- | --- |
| Try the package | [Project overview](../README.md) → [Getting started](getting-started.md) → [Results](results.md) |
| Understand the structure | [Concepts](concepts.md) → [Architecture](architecture.md) → [Data contracts](data-contracts.md) |
| Review the engineering work | [Architecture](architecture.md) → [Evaluation](evaluation-plan.md) → [Safety and data](safety-and-data-policy.md) |
| Run tests and inspect coverage | [Tests and coverage](testing.md) → [Coverage validation](../publication/coverage-validation.json) |
| Review the project quickly | [Reviewer guide](reviewer-guide.md) → [Getting started](getting-started.md) → [Evaluation](evaluation-plan.md) |
| Inspect the copied-module continuation | [Copied-module integration](copied-module-integration.md) → [Tests](testing.md) |
| Select repositories in one Target | [Target workspaces](target-workspaces.md) → [Results](results.md) |
| Run the evaluation interfaces | [Portable evaluation](portable-evaluation.md) → [Results](results.md) |
| Use current document and IR methods | [Local incident knowledge](local-knowledge.md) → [Data contracts](data-contracts.md) |
| Reproduce source-to-IR review without new calls | [Incident reproduction](incident-reproduction.md) → [Validation record](../publication/incident-reproduction.json) |
| Reproduce code/spec-to-System-IR review | [System IR reproduction](system-ir-reproduction.md) → [Validation record](../publication/system-ir-reproduction.json) |
| Read the existing repair demo | [Getting started](getting-started.md) → [Recorded demo delivery](../publication/recorded-demo-tour.json) |
| Inspect automatic deployment | [Continuous deployment](continuous-deployment.md) → [Workflow](../.github/workflows/check.yml) |
| Inspect the hosted revision | [Hosted deployment](hosted-deployment.md) → [Current UI delivery record](../publication/hosted-ui-record-history.json) |
| Check current delivery scope | [Public scope](minimal-implementation-plan.md) → [Current local validation](../publication/knowledge-port.json) |

## Inspect the implementation

| Question | Starting point |
| --- | --- |
| What can a user invoke? | [`reqlox/cli.py`](../reqlox/cli.py), [`pyproject.toml`](../pyproject.toml) |
| How are Source and Target kept distinct? | [Data contracts](data-contracts.md), [`reliability_source_conditions.py`](../reqlox_core/reliability_source_conditions.py) |
| How does a repair reach snapshot adoption? | [`run_reliability_improvement_loop.py`](../reqlox_core/run_reliability_improvement_loop.py) |
| What differs between the comparison arms? | [`run_reliability_paired.py`](../reqlox_core/run_reliability_paired.py) |
| How are dependencies and evaluation inputs fixed? | [`capsule.py`](../reqlox/capsule.py), [`studies.py`](../reqlox/studies.py) |
| What stops or bounds a model call? | [`cloud_model.py`](../reqlox_demo/cloud_model.py), [`test_public_runtime.py`](../tests/test_public_runtime.py) |
| How are documents, IR and parallel reviews reused? | [`knowledge.py`](../reqlox/knowledge.py), [Local incident knowledge](local-knowledge.md) |
| Which paths were actually checked? | [Evaluation](evaluation-plan.md), [`publication/knowledge-port.json`](../publication/knowledge-port.json) |

The [direction record](adr/0001-incident-derived-resilience-hardening.md) retains
the existing architectural reference. Current commands and artifacts are
documented on the operational pages above.

The [earlier documentation snapshot](../publication/documentation.json) remains
a historical record. Current checks are recorded separately in the current
validation record; private development journals are not published.
