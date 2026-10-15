# Public UI deployment recovery

The recovery and edge corrections were followed by successful deployment of
public main `dffb8f7` and real Cloudflare browser checks. See
[Latest delivery](current-delivery.md) and the
[new checkpoint](../publication/read-only-delivery-20261015.json). Earlier failed
releases, rollback outcomes and the original UNKNOWN record below remain retained.

The `ca50603c` release passed both offline Python jobs and its staged Gateway
checks, then failed the public-origin asset check. The edge added an analytics
script to HTML, so the response no longer matched the tested asset hash.
Public static responses now send
`Cache-Control: public, no-transform, max-age=0, must-revalidate`, retaining the
exact-byte verification and requiring immediate revalidation. Private pages,
management APIs and rejected requests retain `no-store, no-transform`.
Cloudflare documents `public, no-transform` for preventing
[automatic analytics injection](https://developers.cloudflare.com/web-analytics/get-started/).
Asset checks also retain the route, phase, HTTP status, size, safe response headers,
analytics-markup presence and both hashes on failure.

The first successor, `be1e91f`, used `no-store, no-transform` and passed staged
checks. Public-origin HTML still gained 367 bytes and failed strict verification.
That failure is retained; the corrected rollback restored the previous release
and the same 37 history entries. It was not retried. The public-only header change
requires a separately tested successor and its own delivery result.

The next successor, `a936347`, also passed staged verification and failed at the
public edge. Both successor rollbacks were exercised and restored the old UI.
The live Worker still used `cacheTtl: 0`, which
[forces caching and overrides origin instructions](https://developers.cloudflare.com/workers/runtime-apis/request/#the-cf-property-requestinitcfproperties).
The edge response had a four-hour browser cache policy and an injected analytics
script despite the direct Gateway response preserving the tested HTML.

The dedicated Worker now uses `cache: "no-store"` for origin fetches, preserves
the response body and CSP, retains the public allowlist's origin cache policy
with `no-transform`, and returns `no-store, no-transform` for private and rejected
requests. Existing hostname and origin bindings are unchanged. No zone-wide
setting or analytics configuration was changed. Some zone-rule and analytics
inventory calls were denied by the existing credential; those settings remain
unconfirmed. After the Worker update, the restored old UI matched the direct
Gateway's body hash and CSP, contained no added analytics script, and anonymous
management requests returned 401 with the private cache policy.

CI checks that edge boundary before reserving or cutting over a new release.
Staged anonymous verification and public-origin verification now have separate
result fields. An origin failure cannot inherit a successful staged flag.
Strict asset hashes remain required, and each failed commit stays consumed.

The first rollback restored VM metadata but reused an older forward-startup
script. The guest still pointed at the failed release, and the forward script
refused that binding. The application subsequently failed credential setup after
boot. Restoring metadata alone did not restore the application.

`infra/gcp/runtime_rollback.py` performs a separate, bounded inverse operation:
it checks the physical VM, collector, original contract, backup hashes, current
runtime and site pointer before restoring the previous managed files and pointer.
It reloads the existing secret versions through the restored bootstrap. Each
return has a durable reservation and retained failed-state evidence; incomplete
returns are rejected. A completed return can reload credentials on a later boot
without applying the restore again. Unknown identities or changed authority are
rejected. No private state is copied into the release or reset.

At the recovery checkpoint on 2026-10-15 JST, a separately authorized one-time
return restored the previous release. HTTP observation confirmed 37 unchanged
private history entries, and all 661 pre-existing private files retained their
hashes. This does not change the original failed deployment or UNKNOWN rollback
record. A new UI release still requires its own tested commit and deployment
record; the failed commit is not rerun.

Offline tests restore real temporary files and a symlink while substituting
service, metadata and secret-loading effects. They cover an applied release,
tampered backups, foreign authority, incomplete reservations and ordinary boots
after a completed return. These tests are not live failure injection. The
experiment ledger remains closed at 15/15 campaigns and 62/120 charged seconds.
