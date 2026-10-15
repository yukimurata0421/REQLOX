# ADR-0001: Incident-Derived Reliability Qualification

**Status:** project direction; public implementation scope is documented
separately. This record retains the original reference path.

## Direction

REQLOX connects failure knowledge from other systems to pre-release experiments
on a selected target. The intended product flow includes condition preparation,
supported target mapping, finite execution, observation, candidate repair,
re-injection, and retained verification records.

## Public interface boundary

The current public package implements a bounded subset of that flow. The
caller supplies owner requirements and a supported snapshot or known control.
Model output remains a proposal. Candidate changes are retained in a result
snapshot without checkout writes, merges, releases, or production actions.

This record does not certify product effectiveness or the full future workflow.
The current [architecture](../architecture.md), [public scope](../minimal-implementation-plan.md),
and [current validation](../../publication/evaluation-validation.json) define what a reader
can inspect and use today.

## Related public documentation

- [Concepts](../concepts.md)
- [Getting started](../getting-started.md)
- [Evaluation](../evaluation-plan.md)
- [Safety and data](../safety-and-data-policy.md)
