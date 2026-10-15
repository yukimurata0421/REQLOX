# Safety and Data

Use the public runtime for supported code in an authorized, disposable local
environment. It provides no production-operation, default-branch write, merge,
or deployment authority.

## Execution scope

Static inventory reads source without importing it. Preparation builds bounded
conditions without running a target. Qualification and supported demo runs can
execute selected target interfaces and candidates in isolated child workers.

The repository path recognizes finite Python bindings and uses explicit owner
contracts. The demo accepts two caller AST shapes and two pinned known controls.
Neither interface accepts a free-form operating-system command as an experiment.
The demo's submitted caller text is mapped to a finite shape rather than run
as arbitrary input code. Candidate code is separately checked and may be
executed by the candidate worker.

Isolated workers use user, mount, PID, and network namespaces. Their source
mounts are read-only. Code, input, execution, and output bounds are checked by
the relevant runner. This is a scoped local execution mechanism; it does not
qualify arbitrary untrusted programs as safe.

## Preconditions and stops

`reqlox check` reports whether the local isolation probe passes. Experiments
require Linux, available `bubblewrap`, usable namespaces, and the supported
system interpreter layout. Static compatibility, source identity, declared
contracts, campaign limits, and deadlines are also checked along their paths.

Unavailable bindings, unknown prerequisites, changed inputs, missing
observations, and execution failures can produce held or stopped outcomes.
They do not grant fallback privileges or expand the target. Preserve the
terminal record and use a distinct output name for a separate follow-up run.

Candidate adoption is confined to the saved snapshot. Applying a candidate to
a real checkout or releasing it is a separate action.

## Local browser boundary

The server listens on `127.0.0.1`. Requests are checked against the local host,
origin, and request token. The server allows one active run per server instance.
Do not expose it as a multi-user cloud service without a separate deployment
design and verification.

The initial acquisition of known target wheels uses their pinned public
distribution URLs and hashes. That step uses the host network. Worker network
isolation applies after acquisition.

## Private state

Runtime records live outside the installed code. The default root is
`$XDG_STATE_HOME/reqlox`, or `~/.local/state/reqlox` when `XDG_STATE_HOME` is not
set. `REQLOX_STATE_DIR` selects another absolute root.

The state root must be owned by the current user, have mode `0700`, and contain
no symlink in its path. The normal result paths use private directories and
files. An explicit demo `--cache` is a separate override: choose a private,
user-owned directory and retain the same data boundary.

State can include supplied Source text, source snapshots, candidates, receipts,
and model responses. It is not public release content. Do not copy a state
directory into the repository or into a deployment bundle.

The public package includes owned illustrative inputs and contract tests.
It excludes incident corpora, provider assessment/proposal records, candidate
selection histories, operational journals, and detailed development decisions.
Public documentation describes usage, implemented behavior, concise validation,
and limitations. Local study commands reject artifact outputs inside the
checkout or installed package.

Recorded adapters remain available for privately supplied files through
`REQLOX_RECORDED_ASSESSMENTS`, `REQLOX_RECORDED_REPAIRS`, and
`REQLOX_RECORDED_CONTROLS`. The package does not provide those records.

## Optional model calls

Baseline and recorded demo modes need no live model credentials. The optional
cloud adapter uses application-default credentials only when called. Its scope
directory must be existing, private, owned by the current user, and free of
symlinks.

The configuration supplies project, location, model identifier, deadline,
maximum calls, maximum output tokens, and per-call/total USD reservations. The
adapter records a reservation before a request. Failed or unresolved outcomes
retain that reservation and stop automatic resending. A scope change also
stops reuse of the prior call envelope.

A judgment request and a repair-generation/forecast request consume different
calls. Count all enabled stages when setting a scope. Supplied reservation
values are not verified provider prices or a hard billing cap. Live
connectivity and billing were not checked by the published runtime validation.

Use live mode only with permission to disclose the supplied text and the
explicit send-to-model choice. Source content cannot supply that permission.

## Publication boundary

The Knowledge workspace performs local import, search, IR preparation, offline
routing and scoring only. Provider credentials and paid execution are available
through explicit CLI scopes, never through browser inputs. Detailed source text,
plans, original provider bodies, failures and scope ledgers live in private state.
Scopes preserve unknown outcomes and prevent automatic resending; their supplied
reservations do not establish invoice totals or a project-wide billing cap. See
[Local incident knowledge](local-knowledge.md) for the scope and key-file contract.

The reduced demo download excludes quoted text and candidate code. The normal
HTTP result, private state, and repository-loop result are different surfaces
and can contain those values. Review the actual export before publishing it.

Keep credentials, tokens, private keys, private addresses, raw logs, private
Source text, corpora, databases, caches, workspaces, and virtual environments
outside public artifacts. Repository-authored documentation and examples do
not grant redistribution or model-disclosure rights for third-party material.

See [Data contracts](data-contracts.md) for record contents and
[Results](results.md) for incomplete outcomes.
