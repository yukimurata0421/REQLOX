# Reviewer guide

Start with the [file-sync example](../README.md#one-example-a-failed-file-sync),
then open the [saved review](https://reqlox.yukimurata0421.dev/demo/) and select
**api · copied Target repair**. Follow Input, Detection, Repair, Re-injection and
Decision. The UI reads archived summaries and starts no experiment.

## Inspect the implementation

| Question | Code or guide |
| --- | --- |
| How is code read without importing a Target? | [`inventory`](../reqlox_core/reliability_reuse.py), [Target workspaces](target-workspaces.md) |
| Where do failure conditions come from? | [Source comparison scope](source-comparison-scope.md), [`source_conditions`](../reqlox_core/reliability_source_conditions.py) |
| How is the repair constructed? | [`repository_atomic_write`](../reqlox_core/repository_atomic_write.py), [`candidate`](../reqlox_core/reliability_reuse.py) |
| How are observations classified? | [`observation_status`](../reqlox_core/reliability_reuse_worker.py) |
| What prevents unauthorized execution? | [Safety and data](safety-and-data-policy.md), [`target_integration`](../reqlox/target_integration.py) |
| Can the implementation be checked offline? | [Tests and coverage](testing.md) |
| How is the public reading surface isolated? | [Architecture](architecture.md), [Read-only boundary](read-only-demo.md) |

## Terms used in results

| Term | Meaning |
| --- | --- |
| Source | Supplied incident or failure material used to propose a condition |
| IR | A structured intermediate record of incident or system facts |
| JEV | Applicability review of a failure hypothesis against a system; it cannot authorize execution |
| HELD | A binding or decision lacks the required qualification or support |
| UNKNOWN | An outcome is unconfirmed; missing evidence is retained |
| Capsule | A manifest-bound bundle of supplied package and dependency files |

Known copied-module results, model proposals and Source comparisons are separate
evidence. Read the [claim boundaries](source-comparison-scope.md) before drawing
effectiveness conclusions. The latest observed release is in
[Current delivery](current-delivery.md); older release/test snapshots and
operational records are in the [archive](history/README.md).
