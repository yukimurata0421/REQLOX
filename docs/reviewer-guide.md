# Reviewer Guide

REQLOX turns quoted failure conditions into bounded experiments and repair
checks. A reviewer can inspect how the implementation prepares a supported
caller, limits execution, retains unknown outcomes, and verifies a candidate
without writing to the target checkout.

## A short review

1. Read the [overview](../README.md) for the problem, available interfaces, and
   current limits.
2. Open the [read-only review](read-only-demo.md) to inspect saved input, detection,
   candidate, re-injection and decision records without new execution.
3. Inspect the retained unsupported and insufficient-information outcomes.
   The current browser execution policy is `OFFLINE_RECORDS_ONLY`; do not start
   a fresh experiment under the exhausted copied Target scope.
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

The existing owner application was deployed to GCP and verified through the
configured browser origin. The [dated CI delivery checkpoint](../publication/ci-delivery-20261015.json)
binds its tested main commit and installed release. The new anonymous read-only
routes belong to a later release; verify their current live behavior through the
[read-only entry](https://reqlox.yukimurata0421.dev/demo/). Cloud delivery does not prove
a submitted competition entry or qualifying Cloud AI usage. See the
[review register](review-follow-up-20261015.md) for remaining evidence gates.
