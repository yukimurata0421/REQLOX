# Reviewer Guide

REQLOX turns quoted failure conditions into bounded experiments and repair
checks. A reviewer can inspect how the implementation prepares a supported
caller, limits execution, retains unknown outcomes, and verifies a candidate
without writing to the target checkout.

## A short review

1. Read the [overview](../README.md) for the problem, available interfaces, and
   current limits.
2. Follow [Getting started](getting-started.md) to inspect owned examples and
   open the local browser demo.
3. Try the unsupported and insufficient-information reports. Both should hold
   without a target experiment.
4. Inspect [Portable evaluation](portable-evaluation.md) for target preparation,
   an equal-budget comparison, and calibration diagnostics. The **Evaluation**
   workspace lets you follow these stages and inspect aggregate results.
5. Read [Architecture](architecture.md) and [Evaluation](evaluation-plan.md) to
   distinguish implementation checks from effectiveness claims.

## Implementation evidence

| Engineering question | Inspect |
| --- | --- |
| How are original inputs and dependencies fixed? | [`capsule.py`](../reqlox/capsule.py), [`studies.py`](../reqlox/studies.py) |
| How is a documented caller found without importing the target? | [`reliability_signature_context.py`](../reqlox_core/reliability_signature_context.py), [`reliability_path_context.py`](../reqlox_core/reliability_path_context.py) |
| Is the Source comparison fair within its finite scope? | [`reliability_incident_conditions.py`](../reqlox_core/reliability_incident_conditions.py), [`run_reliability_incident_conditions.py`](../reqlox_core/run_reliability_incident_conditions.py) |
| How are leakage and missing outcomes handled? | [`studies.py`](../reqlox/studies.py), [`test_public_studies.py`](../tests/test_public_studies.py) |
| What prevents an unsupported model execution? | [`cloud_model.py`](../reqlox_demo/cloud_model.py), [`test_public_runtime.py`](../tests/test_public_runtime.py) |

The public material contains usable contracts, readable implementation, owned
examples, tests, and concise validation boundaries. Private incident corpora,
provider records, candidate-selection history, and experiment journals are not
distributed. Their absence is not presented as evidence of successful
generalization, Source benefit, or calibration.

The current browser application is local. This repository does not establish a
cloud deployment or a submitted competition entry.
