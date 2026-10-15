# Reproduce System IR and its source-fidelity review

The development builder and the packaged CLI now share one deterministic
System IR projection and one source-fidelity question builder. The supported
adapter is `stream-cra-evidence-lineage-v1`: it reads a frozen source package
containing the existing evidence-lineage graph, its captured schema, policy,
code, source manifest, and evidence. It does not infer arbitrary architectures
from arbitrary repositories.

This path regenerates System IR from the captured graph and checks it against
the package's archived System IR witness. It then derives JEV questions from
exact source pointers and bounded code excerpts. Target Python is parsed with
AST, never imported or executed. A historical native-validator receipt remains
historical; this command does not rerun that validator or inspect live runtime.
Only the System IR inputs are checked; other package planes are not a new
full-package validation claim.

## Run the owned protocol control

Use a new absolute private directory outside the checkout or installation.
The fixture contains fictitious code and synthetic responses; its small graph
and fixture-only schema are not substitutes for a real system's contract.

```bash
mkdir -m 700 /absolute/private/system-reproduction
python3 examples/knowledge/create_system_replay_fixture.py \
  --package-output /absolute/private/system-reproduction/owned-package \
  --output /absolute/private/system-reproduction/owned-bundle.json
python3 -m reqlox knowledge system-prepare \
  --package /absolute/private/system-reproduction/owned-package \
  --state-dir /absolute/private/system-reproduction/prepared
python3 -m reqlox knowledge system-replay \
  --bundle /absolute/private/system-reproduction/owned-bundle.json \
  --state-dir /absolute/private/system-reproduction/first
python3 -m reqlox knowledge system-replay \
  --bundle /absolute/private/system-reproduction/owned-bundle.json \
  --state-dir /absolute/private/system-reproduction/second
```

Compare `result_sha256`, plus emitted `system-ir.json`, `plan.json`, and
`result.json`. The same frozen inputs, responses, and implementation produce
the same artifact bytes. Private output directory names differ intentionally.
An explicit state environment variable works without home information; no home
lookup is needed when the destination is configured. Both wrappers are available through `reqlox.knowledge.prepare_system` and
`reqlox.knowledge.replay_system`.

## Use a supported real package and saved responses

`system-prepare --package /absolute/private/frozen-package` writes a sealed
`plan.json` and regenerated `system-ir.json`. The plan embeds the bounded source
snapshot, System IR, questions, source revision, and implementation/schema
hashes. Keep it private: it contains source bytes and review excerpts.

For original saved wire exchanges, an `exchanges.json` array contains:

```json
[{"batch_id":"sirjb_<20 hex digits>","exchange":{
  "request":{"body_base64":"<original request bytes>","sha256":"<64 hex digits>"},
  "response":{"body_base64":"<original response bytes>","sha256":"<64 hex digits>"},
  "http_status":200
}}]
```

`reqlox_system.core.wire(raw_bytes)` constructs those byte envelopes. Never
reconstruct a missing request or use an answer from another review lane.
Export checks each original request against the exact state/model/questions
bytes derived from the frozen plan, then creates a self-contained replay bundle:

```bash
python3 -m reqlox knowledge system-replay-export \
  --plan /absolute/private/prepared/plan.json \
  --exchanges /absolute/private/exchanges.json \
  --state-dir /absolute/private/export
python3 -m reqlox knowledge system-replay \
  --bundle /absolute/path/printed/by/export/bundle.json \
  --state-dir /absolute/private/replayed
```

These commands make zero provider calls and read no credentials. They add no
live dispatch command, spending scope, disclosure permission, or experiment
authority. Existing authorized provider runners remain separate. Method drift
stops replay; preserve the matching implementation with its archive. Declared
`SAVED_PROVIDER_EXCHANGES` provenance and hashes do not authenticate an external
provider origin.

## What a result means

Each System IR element gets one source-fidelity question. The input-derived
count replaces the legacy fixed count of 133. Missing or failed responses stay
unknown, with no retry. `REPLAY_COMPLETE` describes response processing, not IR
acceptance. `SUPPORTED` at the existing uncalibrated 0.85 operating floor becomes
`AUTONOMOUS_CANDIDATE`; contradiction, insufficient information, below-floor,
and missing judgments remain `TERMINAL_QUARANTINE`. No result makes the System
IR canonical or grants mutation authority.

System IR source fidelity asks whether the captured evidence supports an IR
element. **Failure IR × System IR applicability is a separate question.** It
must not reuse a fidelity answer or promote unknown applicability into approval.

The [validation record](../publication/system-ir-reproduction.json) separates:

- Real frozen-source reprojection and exact comparison with the old builder.
- Isolated development/public/installed-package replay using synthetic fidelity
  answers, including both a six-element control and the private 133-element
  source package.
- Offline replay of seven saved real cross-IR applicability judgments; all
  remain `INSUFFICIENT_INFORMATION` / `HUMAN_ON_EXCEPTION`.

No saved real System IR-only fidelity response archive was found in the checked
local locations. Fresh JEV connectivity, fresh-call answer repeatability, and
an independent operator's full execution, and other operating systems or library
versions remain unverified. This validation
does not establish live architecture correctness, unused-Target generalization,
probability calibration, or Source added value. Regression checks also cover explicit storage without home information and
serial UI operations: a completed operation releases its lock before its HTTP
response is sent; genuinely active work still rejects concurrent operations.
The local server code was fixed without deploying or restarting a service.

No raw Target snapshots,
provider responses, or private reasoning records are published.

See [incident reproduction](incident-reproduction.md) for the separate report
and postmortem route, and [local incident knowledge](local-knowledge.md) for the
existing interfaces.
