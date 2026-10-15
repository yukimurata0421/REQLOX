# Reproduce the source-to-IR review path

`reqlox knowledge replay` runs the supplied source, saved generation response,
IR validation, frozen review questions, and saved judge responses through one
offline path. It reads no credentials, sends no requests, and starts no Target
experiments. Development and public checkouts use the same portable module files.

## Run the owned control

Install the package with its `knowledge` extra. Choose a new private directory
outside the checkout; existing evidence must stay unchanged.

```bash
mkdir -m 700 /absolute/private/reproduction
python3 examples/knowledge/create_replay_fixture.py \
  --output /absolute/private/reproduction/bundle.json
python3 -m reqlox knowledge replay \
  --bundle /absolute/private/reproduction/bundle.json \
  --state-dir /absolute/private/reproduction/first
python3 -m reqlox knowledge replay \
  --bundle /absolute/private/reproduction/bundle.json \
  --state-dir /absolute/private/reproduction/second
```

The fixture is explicitly `OWNED_SYNTHETIC_CONTROL`. Its generation response
and judge answers are owned protocol examples, not real external incident
evidence or newly observed provider answers. It checks reproducible mechanics.

Compare the two `result_sha256` values and the emitted `candidate.json`,
`review-plan.json`, `route.json`, and `result.json`. Those files are deterministic
for the same frozen bundle and methods. Output directory names are intentionally
different. Each run also retains the original request and response bytes privately.

## Replay existing stage archives

Generation now stores its frozen plan and exact request, and automatically
produces a `review-plan.json` for the next judge stage. The judge stores that
plan and each request before dispatch. Existing provider scopes, disclosure
permission, deadlines, and reservations still apply to actual provider work.
The offline replay commands add no execution authority.

```bash
python3 -m reqlox knowledge replay-export \
  --generation-directory /absolute/private/generation-archive \
  --judge-directory /absolute/private/judge-archive \
  --state-dir /absolute/private/export
python3 -m reqlox knowledge replay \
  --bundle /absolute/path/printed/by/export/bundle.json \
  --state-dir /absolute/private/replayed
```

Export requires the matching frozen generation and review plans, and original
request and response bytes. Older archives without those files cannot be made
complete by guessing or recreating missing evidence. Method drift also stops
replay; preserve the archive and its matching implementation separately.

## What is checked

The bundle binds the exact source text, source hash, quote catalog, prompt,
schema, policy, and module hashes. Every archived request must match the request
derived from its frozen plan byte for byte. Matching question names alone is
insufficient. Duplicate attempts, changed source or methods, unknown quote
references, malformed responses, and changed wire hashes are rejected.

Missing judge repeats and archived judge failures retain unknown outcomes.
`REPLAY_COMPLETE` means all required archived responses were processed; it does
not mean the IR was accepted. A complete set of insufficient-information answers
can have no atomic projection. The existing three-repeat and structural-control
rules still decide that projection.

`SAVED_PROVIDER_EXCHANGES` declares the archive's supplied provenance. A matching
hash does not independently authenticate a provider origin. Replay neither
certifies incident membership, natural truth, causality, population calibration,
nor applicability to a Target.

Replaying saved responses reproduces recorded processing. Repeating fresh model
calls on the same report is a different check; identical fresh IR, probabilities,
or outcomes are not guaranteed by this command. Live connectivity and a real
independent operator's end-to-end execution remain separate validation tasks.

See [Local incident knowledge](local-knowledge.md) for the individual generation
and judging interfaces, and [the reproduction validation record](../publication/incident-reproduction.json)
for the scope actually checked.
