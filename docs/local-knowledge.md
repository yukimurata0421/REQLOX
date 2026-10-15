# Local Incident Knowledge

`reqlox knowledge` and `reqlox.knowledge` expose the current development methods
for document retrieval, hybrid search, native incident IR review, and partial
proper scores. Runtime artifacts remain outside the public package. The owned
examples exercise interfaces; they are not external incident evidence.

For one offline source-to-IR-to-judge path, use
[Incident reproduction](incident-reproduction.md). Generation also returns a
frozen `review_plan` for the subsequent judge stage; its original exchanges can
be exported and replayed without another provider call.

## Install and try the local path

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[knowledge]'
.venv/bin/python examples/knowledge/run_local.py
.venv/bin/reqlox demo
```

Open the printed local URL and choose **Knowledge**. The workspace imports
supplied text, builds an index, searches excerpts, checks IR quotations, freezes
review questions, routes supplied answers, and reports score bounds. It accepts
no credentials or arbitrary local filesystem paths. These operations make no
provider calls. The reproduction and evaluation workspaces remain available.

The remaining CLI examples assume `source .venv/bin/activate`.

The example script returns artifact paths for further CLI use. Its empty review
map preserves unknown judgments and produces no accepted atomic projection.
Provide `--state-dir /absolute/private/path` to choose a private runtime root.

## Documents and retrieval

An import input is a JSON list of `{url, text}` objects; `title`, `publisher`, and
`source_type` are optional. Each text is at most 512 KiB, the CLI import accepts
at most 200 documents and 16 MiB in total, and the browser accepts at most 32
documents within its 1 MiB request bound. Duplicate canonical URLs are held.

```bash
reqlox knowledge import --documents examples/knowledge/documents.json
reqlox knowledge index --corpus /absolute/path/from/import/corpus.json
reqlox knowledge search --index /absolute/path/from/index/index.json --query 'worker lock'
```

Import treats the URL as an identity for supplied text; it does not download the
page or certify its publisher. The optional acquisition command is explicit:

```bash
reqlox knowledge fetch --url https://example.org/report
# Add --execute only for an authorized public-page request.
```

The default checks arguments without DNS resolution or HTTP requests. Execution
accepts at most three HTTPS URLs, checks public addresses and each redirect,
limits each response to 512 KiB and each URL to six HTTP attempts, retains
responses privately, and stops on failure. It has no automatic retry. This is
a local acquisition utility, not a hardened arbitrary-URL hosting service.
Acquisition does not establish source rights or permit external model disclosure.

Search reuses the existing SQLite FTS5 and hashing TF-IDF methods. It supports
`hybrid`, `vector`, and `fts` modes, publisher and source-type filters, chunk
offsets and hashes, and component-integrity checks. Ranking scores are not
probabilities or source-entailment decisions. No embedding service is called.

## Source-bound native IR

The native candidate contract is
`reqlox.incident-hypothesis-set.v0.1`: quoted evidence spans, observed assertions,
attribute assertions, event alternatives, and relation hypotheses. Inputs keep
candidate status and have no mutation or canonicalization authority.

```bash
reqlox knowledge ir-prepare --candidate examples/knowledge/candidate.json \
  --source-texts examples/knowledge/source-texts.json
reqlox knowledge ir-route --plan /absolute/path/from/preparation/plan.json \
  --judgments /absolute/path/to/supplied-judgments.json
```

Preparation verifies the entire source hash, exact character offsets, quote
hashes, schema, typed references, and hypothesis closure. It freezes source
fidelity questions, separate observed-event atomicity questions, and six owned
structural comparator controls. Batches and method hashes are bound to the plan.
Changed input or changed methods require a new plan.

Routing requires three qualifying repeats at the existing 0.85 operating floor.
Missing repeats remain unresolved. Compound-event false accepts in the controls
hold the atomic projection. Alternative events remain in the original candidate;
they are not silently selected. Attributes and relations must satisfy their own
source support and endpoint closure. This does not verify incident membership,
causality, real-world truth, or applicability to a Target.

## Explicit generation and parallel review

Generation uses the current development adapter and its pinned model. It receives
an exact source and a bounded quote catalog. Returned references must select
catalog entries; the caller restores their original text and offsets and validates
the candidate locally. A generated candidate still needs separate review.

```bash
reqlox knowledge generation-prepare --source-texts examples/knowledge/source-texts.json \
  --source-id owned-lock-report --project your-project-id
```

Each provider stage needs a scope bound to its exact plan hash, future deadline,
call count, per-call reservation, total reservation, and concurrency limit. The
scope command validates these bounds and makes no calls. Generation reservations
use `gcp_jpy`; judge reservations use `jev_usd`. The caller supplies those amounts;
they are not verified prices or a hard billing cap.

```bash
reqlox knowledge provider-scope --plan /absolute/path/to/plan.json --id review-001 \
  --deadline 2099-01-01T00:00:00+00:00 --maximum-reserved 0.06 \
  --per-call-reserved 0.01 --maximum-concurrent-calls 2
reqlox knowledge judge --plan /absolute/path/to/plan.json \
  --scope /absolute/path/to/scope.json --workers 2
```

The example deadline and amounts are placeholders. Set a short operational
deadline and a justified reservation covering every planned call. Without
`--execute`, judge and generation commands read no credentials and send no
requests. Actual execution also requires a scope created with
`--allow-external-disclosure`. Source text cannot supply that permission.

The judge reads `TYPESAFE_API_KEY` or an explicit `--api-key-file`; a supplied
key file must be user-owned, private, and free of symlinks. An explicit file takes
priority over the environment. Store it outside the repository. Generation uses
the existing local access-token helper. Neither path sends a credential to the
browser or writes it into an artifact. Cloud secret registration is a separate
deployment task.

Independent judge batches run concurrently, with one batch's three repeats
ordered. A shared thread and file lock reserves each attempt before dispatch.
The ledger, original request/response bodies, normalized answers and original
probability vectors stay private. Rounding correction is recorded separately
and does not establish calibration. Failure retains its reservation and unknown
outcome, stops queued work, and permits already in-flight work to finish. A scope
cannot be rerun; a separately authorized successor uses a new scope identity.
Generation and judging are dependent stages, not simultaneous calls. Scope
ledgers do not reconcile a project's historical spending or cloud invoices.

## Probability diagnostics and SQL

```bash
reqlox knowledge score --input examples/knowledge/scores.json
reqlox knowledge schema
```

Scoring reuses the latest partial-score implementation. Rows supply an explicit
label authority and dependency component. Missing labels and vectors remain in
the full attempted denominator, with Brier and log-loss bounds, infinite-loss
flags, and equal-component summaries. These are partial-identification bounds,
not confidence intervals or a proof of population calibration. See
[Portable evaluation](portable-evaluation.md) for the existing separate
calibration-candidate interfaces.

The schema command prints the installed PostgreSQL and pgvector reference DDL.
It creates no database and makes no connection. Immutable artifacts remain the
local source of truth; SQLite serves this local search implementation. A working
PostgreSQL runtime backend, migrations, and cloud deployment are not implemented
by this port. The existing knowledge-bundle validator is also available through
`reqlox knowledge bundle-validate --bundle /absolute/path/to/bundle.json`.

## Python API and validation

The public wrappers are in [`reqlox/knowledge.py`](../reqlox/knowledge.py);
namespaced implementation modules and packaged contracts are in
[`reqlox_knowledge`](../reqlox_knowledge). This path does not import the private
development checkout or need its corpus. The
[port validation record](../publication/knowledge-port.json) records method
origins, packaged files, and checked boundaries.

Local tests cover hash drift, unknown routing, alternatives, negative controls,
parallel reservations, interrupted outcomes, response preservation, UI origin
checks, and installation outside the development import path. Mock transports
exercise provider protocols without live calls. They do not establish live
provider connectivity, independent unused-Target performance, natural Source
benefit, or probability calibration.

## System IR source fidelity

The supported source-package projection and request-bound offline JEV replay use
[`system-prepare`, `system-replay-export`, and `system-replay`](system-ir-reproduction.md).
This is separate from Incident IR generation and cross-IR applicability.

## Development UI parity

The development and public Incident library use the same HTML, JavaScript,
workspace stylesheet, examples, and local adapter. Search excerpts can be
passed into the guided-check input without starting a check. The
[parity record](../publication/development-ui-parity.json) separates browser
verification from native execution and provider work.

## Current browser execution boundary

The [Records and history UI](ui-records-and-history.md) applies one offline policy
to all pages. New native runs and model calls are rejected before dispatch.
The old browser enable flag is not supported in serve mode; use the saved-record
flow and private history without resetting any scope ledger. CLI experiments
remain a separate, explicitly authorized workflow.
