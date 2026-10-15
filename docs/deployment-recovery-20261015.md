# Public UI deployment recovery

The `ca50603c` release passed both offline Python jobs and its staged Gateway
checks, then failed the public-origin asset check. The edge added an analytics
script to HTML, so the response no longer matched the tested asset hash.
The Gateway now sends `Cache-Control: no-store, no-transform`, retaining the
exact-byte verification. Cloudflare documents that `no-transform` prevents
[automatic analytics injection](https://developers.cloudflare.com/web-analytics/get-started/).
Asset checks also retain the route, phase, HTTP status, size and both hashes on failure.

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
