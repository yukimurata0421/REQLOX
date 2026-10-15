# Continuous deployment

For the observed result of public main `dffb8f7`, see [Latest delivery](current-delivery.md).

The publication checkout has a GitHub Actions pipeline in
[`.github/workflows/check.yml`](../.github/workflows/check.yml). A push to `main`
runs the offline unit and coverage suite on Python 3.11 and 3.14, checks the
installed wheel, and packages the same commit. Pull requests run validation and
packaging without cloud deployment.

Only successful checks admit the deployment job. Its short-lived federated
identity is restricted to this repository's numeric ID, owner ID, main branch,
push event, and workflow path. No service account key is stored in the repository
or in GitHub secrets. The repository remains private; “publication checkout” does
not describe its GitHub visibility.

## Dedicated deployment boundary

The fixed scope in [`infra/gcp/cicd.json`](../infra/gcp/cicd.json) is the existing
REQLOX UI VM and gateway in the dedicated project. The deployment driver binds
its physical instance ID, loaded host contract, fresh generated context, current
release, persistent state disk, owner secret version, and existing history before
changing anything. It uploads immutable runtime and browser artifacts, reserves
one deployment per commit, and performs a serial stop/start of that UI VM.
A reviewed boot rollout installs the runtime without changing the state disk.

The gateway is built separately, staged without production traffic, and promoted
only after readiness, release, authentication, history, and execution-stop checks.
Browser assets use an immutable commit prefix, preserving earlier assets. No
streaming runtime or other host is part of this workflow.

## Execution remains stopped

The hosted policy retains 15/15 native campaigns and 62/120 charged seconds.
Native execution, model calls, and source fetching remain disabled. The pipeline
runs offline tests and CLI inventory/dry-run checks. Deployment verification sends
empty requests only to confirm the execution endpoints still reject them with
`UI_EXECUTION_DISABLED`; these requests do not start campaigns.

The deployment result contains safe aggregate checks, commit and release hashes,
and gateway identity. Private workspace records, credentials, and raw experiment
evidence are excluded from Actions artifacts. Coverage artifacts retain skipped
native tests explicitly. A deployment or HTTP success is not evidence of a new
repair, reinjection, or independent generalization.

## Failure and rollback

A duplicate commit admission or workflow rerun cannot start another deployment.
Failed admissions and immutable artifacts remain available. If a failure occurs
after UI cutover, the driver attempts one bounded inverse rollback of the saved
VM metadata, reviewed managed files, site pointer and previous Gateway revision.
It reloads the existing secret-version references, then checks readiness and
inherited history. The [recovery record](deployment-recovery-20261015.md) explains
the original metadata-only defect and the corrected returns observed in later failures.
Identity drift stops rollback; an unconfirmed outcome remains unknown. No automatic
deployment retry or experiment-budget reset is performed. A corrected commit must
pass validation again.

Inspect the workflow run and its `deployment-<commit>` result artifact to determine
what actually ran. Configuration and offline tests alone do not establish a
successful cloud deployment. Existing [hosted delivery records](hosted-deployment.md)
remain historical records for their respective revisions.
