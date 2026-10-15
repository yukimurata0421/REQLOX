# Offline UI records and history

The browser UI uses one **OFFLINE_RECORDS_ONLY** policy across Guided check,
Targets, Incident library, Evaluation lab, and Records & history. It permits
local document indexing, static preparation, supplied-answer routing and
probability diagnostics. New native experiments and model calls are disabled.
Direct requests to `/api/run`, `/api/targets/run`, and
`/api/study/compare-run` return HTTP 403 / `UI_EXECUTION_DISABLED` before
runner dispatch. Legacy programmatic enable flags do not override this policy;
`serve --allow-target-experiments`, `--model-scope`, or `--send-to-model` are
rejected before model initialization. The experiment CLI remains a separate
interface requiring its own authorization, identity, isolation and limits.

## Follow an existing result

Start `reqlox demo` with the knowledge dependencies installed. Open the local
URL and select **Records & history**, or use the copied-Target link on the home
page. `/records` contains distinct api, worker, `temppath-readme-v01`, and
composed-caller records. Each has five stages: input, detection, repair,
reinjection or confirmation, and adoption decision. Earlier lock, TTL and
cleanup demonstrations are separate records.

The copied temppath README experiment has two archived campaigns and finite
normal/body-fault observations. No counterexample was found under those
conditions. Four atomic bindings remain HELD, and no temppath repair was
performed. Unchanged-code confirmation is not repaired-code reinjection.
Do not combine this result with the earlier cleanup EIO demonstration.

The common banner shows the archived approval scope: **15/15 campaigns,
62/120 charged seconds, zero additional campaigns authorized**. These counters
are historical evidence, not a new grant for an uploaded Target. A new draft,
freeze, process, cache or session does not reset that scope. Missing raw evidence
from the historical unintended starts remains missing; summary viewing does
not repair that gap.

## Restore private work

Use the same private `--cache` directory to retain drafts and record references
across reloads and server restarts. Knowledge restores its supplied fields,
index, question-plan references and search results without rerunning operations.
Study restores its supplied fields, frozen preparation/review references and
saved diagnostic displays. Records restores the selected archive and stage.
Guided check saves an input draft; it cannot start a new check. Targets restores
selection fields; copy/preparation handles are not silently reused after a
server restart.

**Private workspace history** lists saved summaries and can reopen them. Legacy
artifacts are retained with available aggregate fields only. Completed Study job
summaries are read from disk. An interrupted job with a start record and no
terminal summary is shown as `OUTCOME_UNKNOWN_SERVER_RESTART`, never as success,
and is not retried. Frozen-input start markers remain durable.

Drafts are replaceable private UI state. Execution evidence, native reservations,
receipts, ledgers and terminal outcomes are not replaced. Keep distinct private
cache directories for unrelated users or tasks. Raw supplied text and code are
not included in the distributed archive dataset or published validation report.

## Trace a quotation

In Incident library, add supplied text, build the index, search and choose
**Use excerpt in a check**. The server resolves the selected indexed span from
its original private text, verifies the corpus/index binding, document hash,
source/document revision, exact character offsets and chunk hash, and saves an
immutable excerpt record. The Guided check receives that record ID, not trusted
browser-supplied quotation metadata. Reloading verifies the binding again.
Whitespace and Unicode positions are preserved in the accepted source text.

The input shows the source ID, revision, URL, document hash, exact quote and
span. Editing the input keeps its origin visible while marking the current
input as different from the quotation. This establishes content lineage only:
the URL is not fetched, source rights and incident truth remain unverified, and
it does not grant experiment authority.

Archived public records instead expose clearly labeled **curated input
summaries** and evidence identifiers/hashes. Exact private original text is not
distributed; a summary hash must not be described as the original-source hash.
A hash is not a trusted timestamp or an independent raw-evidence audit.

## Boundaries

Searching a report does not generate Incident IR. Advanced review accepts an
already structured candidate and supplied judgment answers; missing answers
remain UNKNOWN. System IR projection/replay is a separate supported CLI path.
Native comparison is unavailable in this UI; existing observation records can
be inspected without executing code. Calibration candidates remain diagnostic
and HELD with RAW serving where their prerequisites are unverified. UI tests
and browser restoration do not establish independent unused-OSS generalization,
probability calibration, provider connectivity or natural Source added value.

See [local knowledge](local-knowledge.md), [portable evaluation](portable-evaluation.md),
and the [offline UI validation](../publication/ui-record-history-validation.json).

## Hosted verification

The owner-authenticated Cloudflare deployment exposes the same offline records,
history restoration and execution gate. See [Hosted deployment](hosted-deployment.md)
and its [current delivery record](../publication/hosted-ui-record-history.json).
Hosting does not grant new injection or model authority.
