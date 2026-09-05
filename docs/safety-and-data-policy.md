# Safety and Data-Use Policy

## Status and default boundary

This is a design policy, not an implemented safety control or proof of safety.
The v0.x default target is a disposable or otherwise isolated test environment.
Always-on services, production system services, management networks,
authentication infrastructure, and real user data are excluded by default.

No document, model proposal, cached approval, or successful earlier run grants
execution authority. Production applicability, if ever considered, requires a
separate design, evidence, and explicit authorization process.

## Authority model

Authority is deny-by-default and scoped to an exact combination of:

- target and environment identity;
- permitted operation class;
- blast radius and protected resources;
- maximum intensity, duration, concurrency, and cost;
- valid `SystemContract` version;
- approved harness and adapter capabilities; and
- approval lifetime and stop conditions.

AI may propose a structured `ExperimentSpec`, but free-form output cannot be
executed directly or used to expand authority. The deterministic policy gate
accepts only typed operations supported by the selected adapter and refuses
unknown targets, fields, capabilities, or policy states.

An approval authorizes at most the exact requested operation within existing
human authority. It does not authorize neighboring components, escalation to a
larger failure domain, alternative backends, follow-up experiments, or cleanup by
an otherwise prohibited mutation.

## Required preflight

Immediately before execution, the gate verifies:

1. physical/logical target identity and isolated-environment classification;
2. target code, configuration, dependencies, and baseline state required by the
   mapping and spec;
3. current `SystemContract`, policy, and approval identity and expiry;
4. adapter/harness capability and expected cleanup support;
5. allowlist and denylist results for every operation and resource;
6. remaining model, infrastructure, time, and human-attention budget;
7. maximum one active experiment for v0.x;
8. mandatory observation availability and clock/window readiness; and
9. a clean baseline with no unresolved state from an earlier experiment.

Unknown, stale, mismatched, or unobservable prerequisites fail closed. A spec
that was safe when generated can be rejected at execution time.

## Bounded execution

Every experiment has enforced upper bounds for:

- affected target instances/resources;
- operation intensity and workload;
- fault and total experiment duration;
- retry and operation count;
- infrastructure or direct cost;
- observation and recovery wait; and
- concurrent experiments, fixed at one for the initial design.

Candidate generation and experiment execution have separate budgets. Exhausting
a discovery budget does not justify executing a cheaper unsafe candidate, and an
experiment budget does not authorize unbounded model/tool use.

## Observation and verdict safety

The spec declares evidence required to confirm that the intended fault is
active, evaluate the target, detect stop conditions, and confirm cleanup.

- If injection is not established, the target is not marked `PASS`.
- If mandatory observation is unavailable, the run stops or refuses a target
  verdict according to the contract.
- If the harness fails, the result attributes that failure separately and does
  not assign it to the target without evidence.
- If the harness exits cleanly, target recovery still requires target evidence.
- If clocks, target identity, or observation windows cannot be aligned, the
  verdict is evidence-insufficient.

The oracle is independent from candidate and patch generation. A target change,
`SystemContract` change, and oracle change are separate review events.

## Stop, cleanup, and residual state

The design distinguishes:

- **stop requested:** no additional fault action should be introduced;
- **injection removed:** the adapter reports that the injected condition is no
  longer applied;
- **cleanup verified:** independent observations confirm the expected clean
  state; and
- **impact reversed:** the target's effects are fully restored.

These states are not equivalent. An experiment may be stoppable even when its
effects are irreversible or their reversal is uncertain. v0.x should avoid such
operations by restricting targets and operations, preferring disposable
environments, and rejecting a spec whose safe terminal state cannot be verified.

Cleanup is idempotent where the backend supports it and is attempted on normal
completion, stop condition, timeout, and harness exception. A supervisor or
backend lease/TTL should bound injected state if the controller disappears, but
TTL is supplementary: the design still requires explicit cleanup and
verification. A failed cleanup leaves the environment quarantined and blocks the
next experiment.

## State isolation between experiments

Before each run, the harness compares the target against a declared clean
baseline. After each run, it records and verifies:

- injected resources/rules removed;
- processes, data stores, queues, and dependencies at the expected baseline;
- test data and side effects removed or the disposable environment destroyed;
- no unresolved adapter lease or external operation; and
- observations drained and uniquely associated with the completed run.

If clean-state verification fails, the target is not reused. The record remains
an infrastructure/harness safety issue rather than being silently repaired by a
broader unauthorized action.

## Approval changes

Changes within an already approved exact spec are limited to non-semantic
metadata corrections. Any change to target, operation, intensity, duration,
load, contract, oracle, observation, cleanup, backend, or budget creates a new
specification and safety decision.

Additional human authorization is required before expanding environment class,
target set, protected-resource access, privileges, network reach, data class,
concurrency, or production relevance.

## Negative safety tests

The eventual implementation must be tested in isolation with inputs that should
be refused, including:

- unknown or unallowlisted target;
- protected production-like resource;
- unsupported free-form command;
- excessive duration, intensity, scope, concurrency, or cost;
- stale contract, changed target identity, and mismatched adapter version;
- missing required observation or cleanup capability;
- prompt-like instructions embedded in a source, log, code comment, or artifact;
- attempt to weaken the oracle or contract through a target patch; and
- a second run while previous state is unresolved.

Observing zero unauthorized operations in normal runs is not sufficient evidence
that these controls work. Each rejection path and fail-closed behavior needs
positive evidence.

## Untrusted input handling

Incident reports, postmortems, web pages, tickets, logs, source code, comments,
generated content, and imported structured data are untrusted input. Natural
language inside them is evidence to interpret, never authority to call tools,
change policy, disclose data, or execute commands.

Input processing should:

- preserve source/data boundaries and provenance;
- separate quoted/reported facts from model or human inference;
- constrain parsers and adapters to typed, validated fields;
- reject or quarantine malformed and over-limit input;
- prevent source content from selecting tools or credentials;
- minimize data passed to any external model; and
- record redactions and unavailable context so outputs do not imply completeness.

## Third-party material

Public accessibility does not imply unrestricted copying, model disclosure, or
redistribution. For each source, the project separately decides:

1. whether it may be acquired;
2. what may be retained locally and for how long;
3. whether content may be sent to a third-party model;
4. what may be quoted or transformed internally; and
5. what may be published.

Unknown terms default to metadata/reference-only or deferred public use until
reviewed. A summary or structured abstraction is not assumed to be freely
redistributable merely because it is transformed. Publisher, URL, version,
retrieval time, known terms, attribution, and allowed storage/publication scope
remain attached through `SourceRecord` lineage.

The repository does not vendor full external postmortems by default. Where a
source permits only linking, public records contain the link and original
project-authored analysis within the reviewed scope.

## Private and sensitive data

For internal incident material, local retention, model disclosure, and output
publication are separately controlled. The public repository must not contain:

- credentials, tokens, private keys, or secret-like values;
- personal information not expressly approved for publication;
- private addresses, account IDs, internal topology, or target identifiers;
- raw logs or evidence containing sensitive values;
- private source text or derived details whose publication is not authorized; or
- caches, databases, workspaces, virtual environments, or runtime artifacts.

Redaction is reviewed against the evidence needed for a claim. If safe
publication removes a verdict prerequisite, the public result is labeled
insufficient or publishes only a narrower claim.

## License boundary

Repository-authored material remains under the repository's Apache License 2.0.
That license is not automatically applied to third-party source text, excerpts,
data, or separately licensed tools. Every retained external item keeps its own
rights and attribution information; unresolved licensing is recorded as
unresolved rather than guessed.

OES remains a separate project. Any future interchange uses an explicitly
defined evidence format or adapter and does not presume code incorporation or a
license change.

## Initial exclusions

The initial design excludes production fault injection, autonomous repair,
unbounded tests, multiple concurrent experiments, multiple cloud backends,
privileged fallback escalation, and experiments whose cleanup or safe terminal
state cannot be verified. Merely leaving a backend or final project name open is
not a safety blocker for continuing design work.
