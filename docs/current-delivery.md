# Latest verified delivery

The anonymous [read-only review](https://reqlox.yukimurata0421.dev/demo/) was
deployed from public main `dffb8f79062aa9b0dda94395457b185bc56aedf2` and checked
through Cloudflare on 2026-10-15 at 21:08–21:13 JST. The VM's release identity
was subsequently rechecked by read-only observation. Exact times and safe
results are in the [delivery checkpoint](../publication/read-only-delivery-20261015.json).
This is an observed checkpoint, not a future availability guarantee.

| Identity | Verified value |
| --- | --- |
| Actions | [38731637902](https://github.com/yukimurata0421/REQLOX/actions/runs/38731637902), all four jobs succeeded |
| Runtime SHA-256 | `ccae5e8006d269295200f37f07b3152aeb9822b9171f8042e278e39804bfbaf4` |
| Gateway revision | `reqlox-web-gateway-00017-kej`, 100% traffic |
| Python checks | 3.11 and 3.14: 712 tests each, 29 native skips each, zero failures/errors |
| Copied Target ledger | 15/15 campaigns, 62/120 charged seconds, zero remaining campaigns |

## What was observed

Separate anonymous and owner browsers checked all seven archived records and
their five stages, record/stage restoration after reload, Source/evidence hashes,
and a 390-pixel mobile layout. Temppath retained four HELD atomic bindings,
no repair and no repair re-injection. Normal public browsing used only static
GET/HEAD reads and did not call the Workspace API.

Anonymous management requests returned 401. Public writes returned 405 and
public route escape returned 404. Owner execution requests returned 403
`UI_EXECUTION_DISABLED` before dispatch. Private/rejected responses retained
`no-store, no-transform`; public static responses retained immediate revalidation
and `no-transform`. The tested HTML was not modified by an analytics injection.
Private history and the state disk were preserved. Browser captures and raw
audit records remain private; only selected summaries and hashes are published.

The rollback correction restored the previous managed files and site pointer
as well as VM metadata, using the existing secret-version references. Two later
failed deployments exercised that corrected return successfully. The final
successful deployment did not use rollback. The dedicated edge Worker was
updated once without changing its hostname or origin bindings. Some zone-rule
and analytics inventory requests were denied by the existing credential; those
settings remain unconfirmed and were not changed. See [recovery](deployment-recovery-20261015.md).

## Keep historical records separate

The [earlier CI checkpoint](../publication/ci-delivery-20261015.json),
[14 October records delivery](../publication/hosted-ui-record-history.json),
[initial hosted delivery](../publication/hosted-integration-deployment.json),
and [19:34 source-only review](review-follow-up-20261015.md) remain unchanged.
Their release hashes, test counts and pending-delivery statements describe
their original observation windows. The failed `ca50603c`, `be1e91f` and
`a936347` releases and their outcomes remain retained. They were not rerun.
The original UNKNOWN rollback record is not rewritten by a later recovery.

The application commit above identifies the deployed public release; a local
development checkout or a later documentation edit is not that release's identity.

## Historical inference and remaining gates

The [historical Vertex AI usage summary](historical-vertex-ai-usage.md) records
one earlier Incident IR candidate-generation call. That call, saved-response
IR/JEV replay, the copied-module repair checks and the public archive are separate
operations. Neither deployment nor a loaded credential proves a new inference.

No new native campaign or model call was made for this delivery or documentation
alignment. The missing historical raw observations remain `UNKNOWN_UNRECOVERED`.
Independent unused-OSS generalization, Source added value, probability calibration
and human-effort savings remain unproven.

Competition linkage/submission and eligibility, a completed video, public source
access, a maintenance owner, a cost ceiling and sustained availability still
require separate evidence or decisions. Video production materials stay in the
development checkout and are not part of this publication.

See [Architecture](architecture.md), [Read-only review](read-only-demo.md),
[Continuous deployment](continuous-deployment.md), and [Documentation](README.md).
