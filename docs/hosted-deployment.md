# Hosted deployment

The owner-authenticated [records workspace](https://reqlox.yukimurata0421.dev/records) was verified
on 14 October 2026 at 21:59 JST. The backend reported READY
with release `9d5d858fd14877081bb3e99ef455e398e3c6ceb6daefd217b6ee9d178a2a5907`.
Gateway revision `reqlox-web-gateway-00003-jlt` received 100% of traffic.
The [current UI delivery record](../publication/hosted-ui-record-history.json)
identifies the runtime, gateway, fourteen browser assets and verification scope.
Continued hosting remains enabled on the same dedicated VM and state disk.
The [initial delivery](../publication/hosted-integration-deployment.json),
[hosting-policy change](../publication/continuous-hosting.json) and
[earlier three-example tour](../publication/recorded-demo-tour.json) remain historical records.

## Reading the recorded demo

Open **Records & history** from the [homepage](https://reqlox.yukimurata0421.dev/), or select its
integration-record entry. The record selector includes the api, worker, temppath
README and composed-caller results. Follow the five stages:
**Input → Detection → Repair → Reinjection / confirmation → Adoption decision**.
The selected record and stage survive a page reload and a new browser process.
The older three-example tour remains available on the homepage.

Temppath's copied-Target record retains **four HELD atomic bindings**, no repair
and no adopted repair. Its unchanged-code confirmation is distinguished from
reinjection after repair. The earlier temporary-file cleanup demonstration is a
separate historical record. Source summaries and evidence hashes can be opened
with **Trace Source and evidence**; original private quotations are not distributed.

The five UI screens share **OFFLINE_RECORDS_ONLY**: the closed ledger remains
**15/15 campaigns and 62/120 charged seconds**, with zero additional campaigns
authorized. Guided checks, Target campaigns and Study native comparisons are disabled
both in the browser and at the server boundary. No new injection or model call
was performed for this deployment.

Actual Chromium checks through the Cloudflare URL covered the four copied-Target
records through all five stages, restored input and record drafts, existing private
history summaries, and responsive layouts at widths 1440 and 390. A separate browser
process reopened saved state. The three execution POST endpoints returned 403
`UI_EXECUTION_DISABLED` before dispatch. Server-restart persistence remains separately
covered by the previous offline validation; no extra hosted-service restart was used
for the restoration check. See [Records and history](ui-records-and-history.md).

## What the workspace displays

The archived copied-module result shows 15/15 cumulative native campaigns and
62/120 charged seconds. The existing api/worker candidate passed the same
fault, normal and boundary conditions in repair validation and fresh reinjection;
adoption remains limited to the isolated composed caller. Temppath retains four
HELD atomic bindings and no repair. The earlier missing raw evidence remains
unrecovered. See [copied-module integration](copied-module-integration.md).

The hosted aggregate uses `ARCHIVED_LOCAL_HASH_AUDIT`. It is a safe projection
of a completed local audit, not a new remote raw-evidence audit. Additional
Target execution is disabled. No native campaign or model inference was started
by this deployment. Raw evidence, copied Targets and private judgment records
were excluded from the uploaded runtime and browser assets.

## Delivery checks and operating boundary

The authenticated public API reported the expected READY revision. Anonymous
requests returned 401 and a wrong Origin returned 403. All fourteen uploaded assets
matched their pinned receipts; nine non-HTML assets also matched byte-for-byte through
the public domain. Cloudflare adds analytics markup to HTML; its script was blocked
by the existing Content Security Policy. Owner authorization was attached only to
the configured origin during browser checks. Immutable private evidence was rechecked
against its retained manifests; the existing missing-evidence gap remains unrecovered.

The existing dedicated demo VM and state disk were retained. Owner and provider
secret versions and access policies were retained; paid model calls remain
disabled. The first rollout failed because restrictive startup directory
permissions prevented the service account from importing the package. It rolled
back to the previous release. A reviewed method-bound successor corrected those
permissions and passed readiness. The failed release and rollback evidence
remain private and preserved.

The owner explicitly authorized continued UI hosting after the initial rollout.
The VM's automatic stop deadline, maximum run duration and termination action
have been removed. The former **13 October 2026, 00:41:32.264 JST** deadline
is retained in the initial delivery record as history. That scheduling change retained the VM,
state disk, authentication and secret versions. The current UI release is identified above. A controlled
stop/start was used for the scheduling change; the backend returned READY and
actual browser rendering passed at all three widths after the start.

The experiment ledger remains closed at **15/15 campaigns and 62/120 charged
seconds**. Removing the UI hosting deadline does not reset that ledger or grant
new injection authority. Additional native Target execution and paid model calls
remain disabled. This establishes the current hosting configuration and observed
availability; it does not establish a future availability guarantee.

## Maintaining this deployment

The public Terraform module accepts the reviewed startup script, the exact
observed runtime metadata and an explicit hosting mode. `continuous_hosting`
defaults to `false`, preserving finite demo leases. The current authorized
configuration sets it to `true` with an empty `termination_time`, omitting all
automatic VM termination fields. A continuous mode with a retained deadline is
rejected. Runtime
metadata must remain semantically equal to the module's hash-bound configuration.
The retained `lease_seconds` field in existing runtime metadata describes the
original allocation; the effective hosting policy is the live GCP scheduling
configuration. Native worker limits and the experiment ledger are separate.
Preserve historical releases, state records and failed-rollout markers when
reconciling the local state after a reviewed in-place rollout. Do not apply an
old plan or treat a source-file path change as authority to recreate the VM.
The pinned provider plans a replacement when removing `termination_time`; that
plan was rejected. The scheduling change used the
[Compute Engine scheduling command](https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/set-scheduling)
on the stopped, identity-checked VM. The refreshed successor state and then-current
variables produced a plan with zero creates, updates and deletes. That historical plan
does not describe the later UI release. Current release variables and object receipts
are retained privately; refresh and reconcile state before generating another plan.

Before another runtime change, inspect the dedicated VM's root-owned contract,
fresh context, physical identity, current release, preserved state and existing
hosting policy. The reviewed rollout helper is restricted to the dedicated
isolated demo role. Production stream components and other hosts are outside
this deployment scope. No Git commit or push was performed.

These checks establish delivery of this revision and display of the archived
finite result. They do not establish independent generalization, probability
calibration, Source added value, or a new live repair experiment.

The [continuous deployment guide](continuous-deployment.md) describes the checked-main
workflow and its separate deployment result artifacts.

## Later delivery checkpoint

The [2026-10-15 CI delivery record](../publication/ci-delivery-20261015.json) supersedes
the earlier no-commit/no-push delivery procedure as a current deployment reference.
The earlier observations remain historical. The new [read-only demo](read-only-demo.md)
is a subsequent source change and is not part of that deployed checkpoint.
