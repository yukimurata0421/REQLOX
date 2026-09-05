# Data Contracts and Invalidation

## Status

This document defines conceptual data contracts. It is not an implemented
schema, serialization format, API, or compatibility guarantee. Field names are
stable design vocabulary only; exact types and required/optional rules remain a
v0.x implementation decision.

## Shared rules

Every artifact has:

- a project-unique `id`, `contract_type`, and `contract_version`;
- `created_at`, `created_by_kind` (`HUMAN`, `MODEL`, `HARNESS`, or `IMPORT`), and
  lifecycle status;
- explicit references to input artifact IDs and versions;
- provenance for individual claims where source and inference can be confused;
- integrity metadata for stored bytes or canonical representations;
- uncertainty, missing fields, and invalidation status represented explicitly;
- visibility and retention classification; and
- an append-only revision or supersession relationship rather than silent
  replacement of historical evidence.

Integrity hashes can detect changes and bind versions. They do not prove that a
claim is true, that a target was safe, that an experiment occurred, or that an
artifact was collected correctly.

The lineage must make these versions traceable where relevant:

- source material and extraction rules;
- model, model settings, prompt/template, and available tools;
- target code, configuration, dependencies, topology, permissions, and baseline
  tests;
- `SystemContract`, mapping, experiment, policy, harness, injection adapter, and
  oracle;
- execution environment and observation collectors; and
- hardening change and each re-test.

## Provenance vocabulary

A claim in a derived record uses one of these origins:

- `SOURCE_REPORTED`: directly supported by a cited part of permitted source
  material;
- `PROJECT_INFERENCE`: inferred by a human or model and not reported as such by
  the source;
- `TARGET_OBSERVED`: established from versioned target evidence;
- `EXPERIMENT_OBSERVED`: established during a recorded experiment; or
- `UNKNOWN`: not established by available evidence.

Quoting, summarizing, extracting, storing, sending to an external model, and
publishing are separate permissions. A `SourceRecord` must not collapse them
into one “public” flag.

## `SourceRecord`

**Purpose:** identify an external source and encode what may be acquired,
retained, processed, disclosed to a model, quoted, or redistributed.

**Principal fields:**

- canonical URL or non-public source locator;
- publisher, title, source type, publication date, and retrieved timestamp;
- source revision/version and retrieval status;
- content or reference integrity metadata;
- known license/terms, attribution requirements, and decision owner;
- separate `acquisition_scope`, `local_retention_scope`,
  `model_disclosure_scope`, `quotation_scope`, and `publication_scope`;
- allowed stored representation, such as metadata only, limited excerpts,
  private copy, or separately reviewed derived facts; and
- uncertainty, access restrictions, expiry, and recheck date.

**Input:** a human-selected incident report, postmortem, near-miss record, or
other operational source plus a source-specific rights decision.

**Output:** a source identity and permitted evidence surface usable by
`IncidentModel`; it does not output an executable instruction.

**Validation:** URL/locator and publisher are present; retrieval status and time
are recorded; source revision is identifiable where available; every processing
scope is explicit; unknown rights do not default to redistribution; secrets and
personal/private identifiers are excluded from public artifacts.

**Update:** create a new revision when the source changes, terms become clearer,
access expires, or a rights decision changes. Preserve the earlier record for
historical experiment lineage when legally permitted.

**Invalidation:** derived public artifacts are blocked or reviewed when the
source becomes unavailable, its identity cannot be verified, terms conflict with
the planned use, stored bytes fail integrity checks, or the permitted disclosure
scope narrows.

## `IncidentModel`

**Purpose:** represent what a source reports without mixing those statements
with the project's interpretation.

**Principal fields:**

- referenced `SourceRecord` and source revision;
- reported symptoms, impact, timeline, environment, and relevant actors;
- source-reported cause and contributing factors;
- source-reported mitigations and follow-up changes;
- unresolved questions, contradictions, and source limitations;
- per-claim source locations and provenance kinds; and
- extraction model/prompt/tool versions and human review state.

**Input:** only the representation permitted by a valid `SourceRecord`.

**Output:** cited incident facts and explicitly marked inferences used to propose
one or more `FailureModel` records.

**Validation:** all factual claims have a source reference or are marked
`PROJECT_INFERENCE`; “reported cause” is not labeled independently verified;
timeline ordering and timezone uncertainty are explicit; omitted or
inaccessible material is not guessed.

**Update:** revise when source material changes, extraction errors are corrected,
or a different permitted representation supplies new evidence. Extraction with
a changed model may be added as a new revision or comparison, not silently
substituted.

**Invalidation:** invalidate or require review when the `SourceRecord` or its
permitted input becomes invalid, claim citations no longer resolve, the source
revision changes materially, or extraction provenance is missing.

## `FailureModel`

**Purpose:** describe a reusable failure mechanism without reducing it to a
label such as `network_failure`.

**Principal fields:**

- enabling conditions and explicit exclusions;
- trigger and time/order constraints;
- mechanism and propagation path;
- finite resources and saturation/release behavior;
- expected observations and distinguishing evidence;
- possible mitigations reported by the source, kept separate from project
  proposals;
- uncertainty, alternative mechanisms, and abstraction limits; and
- supporting `IncidentModel` claims and inference provenance.

A valid model can express combinations such as:

```text
retry × response latency × finite workers × delayed release
```

**Input:** one or more valid `IncidentModel` records and explicit project
inferences.

**Output:** a candidate mechanism that can be assessed against targets. It is not
yet a target mapping or an experiment.

**Validation:** mechanism, enabling conditions, propagation, observations,
exclusions, uncertainty, and evidence references are present; abstraction does
not claim greater generality than sources support; near-duplicate mechanisms
have an explicit relationship.

**Update:** add a new revision when evidence strengthens or contradicts a
mechanism, exclusions change, or multiple models are merged/split. Preserve the
relationship to earlier IDs used by experiments.

**Invalidation:** require review when supporting incident claims are invalid,
the abstraction loses its cited basis, contradictory evidence is unresolved, or
the representation cannot distinguish the proposed mechanism from alternatives.

## `TargetMapping`

**Purpose:** record whether and why a `FailureModel` applies to a particular,
versioned target.

**Principal fields:**

- referenced `FailureModel` and target snapshot identity;
- code, configuration, dependency, topology, permissions, and baseline-test
  evidence used for the mapping;
- target components and paths corresponding to each mechanism element;
- `confirmed_conditions`, `unconfirmed_conditions`, and `contradictions`;
- decision: `APPLICABLE`, `NOT_APPLICABLE`, or
  `INSUFFICIENT_INFORMATION`;
- evidence-grounded rationale, uncertainty, and reviewer; and
- model/prompt/tool versions used to propose the mapping.

**Input:** a valid `FailureModel`, target snapshot, baseline tests, and applicable
`SystemContract`.

**Output:** an applicability decision. Only `APPLICABLE` mappings may supply an
experiment candidate; other decisions remain useful negative evidence.

**Validation:** target identity is resolvable; every required mechanism
condition is mapped to evidence, contradiction, or unknown; the decision follows
those states; missing information is not converted into applicability; mapping
claims do not exceed read authority.

**Update:** create a new revision when additional target evidence resolves an
unknown or a reviewed correction changes the rationale.

**Invalidation:** target code, configuration, dependencies, topology,
permissions, baseline tests, relevant contract, or underlying failure mechanism
changes invalidate the affected portion. The mapping must be re-established
before a dependent experiment executes.

## `SystemContract`

**Purpose:** provide the human-controlled definition of protected behavior,
permitted degradation, authority, observation requirements, budgets, and stop
conditions.

**Principal fields:**

- owner and authorized approvers;
- target identities, permitted environments, and blast-radius boundary;
- protected functions, invariants, and required baseline behavior;
- allowed degradation and recovery time/condition;
- permitted and prohibited operations and protected resources;
- required observations and oracle rules;
- maximum intensity, duration, cost, and concurrent experiments;
- stop, cleanup, and post-cleanup verification conditions; and
- freeze timestamp, approval evidence, expiry, and change history.

**Input:** human decisions grounded in target ownership, operational policy, and
an identified isolated environment. AI may help draft but cannot approve it.

**Output:** a frozen contract referenced by mappings, specifications, policy
decisions, oracles, and results.

**Validation:** an authorized owner approved the exact version; target and
environment are explicit; allow and deny rules are deterministic enough to
enforce; observation, stop, and budget requirements are defined; expiry has not
passed.

**Update:** only authorized humans can issue a new version. The change record
separates contract changes from target fixes and explains which downstream
artifacts require re-evaluation.

**Invalidation:** expiry, owner revocation, target identity change, authority or
permission change, protected-resource change, environment reclassification, or
unenforceable stop/observation rules makes it ineligible for execution.

## `ExperimentSpec`

**Purpose:** freeze a proposed experiment before policy evaluation and execution.

**Principal fields:**

- mode (`EXPLORATION` or `REGRESSION`) and candidate rationale;
- exact target/environment identity and required clean baseline;
- referenced mapping, contract, source/model lineage, and baseline tests;
- operation, injection conditions, load, order, duration, intensity, and upper
  bounds;
- method and evidence required to confirm injection establishment;
- observation plan and independent oracle version;
- stop triggers, cleanup actions, cleanup verification, and residual-risk rule;
- model, experiment, infrastructure, elapsed-time, and human-review budgets; and
- harness and adapter capability/version requirements.

**Input:** an applicable mapping, valid contract, selected mode, supported
adapter capability, and a candidate budget.

**Output:** a non-executable proposal for deterministic `SafetyDecision` review.

**Validation:** all referenced versions resolve; operation is typed rather than
free-form shell text; target, upper bounds, confirmation, observations, oracle,
stop, cleanup, and budget are complete; no field expands contract authority.

**Update:** specifications are frozen. Any semantic change creates a new version
and requires a new policy decision.

**Invalidation:** any referenced mapping or contract invalidation, target or
environment drift, adapter/harness incompatibility, expired authority, budget
change, or unavailable required observation prevents execution.

## `SafetyDecision`

**Purpose:** record a deterministic accept/reject decision for one exact spec in
one current execution context.

**Principal fields:** spec and contract versions, target preflight identity,
policy version, checks and evidence, enforced limits, decision, rejection
reasons, approval expiry, and decision timestamp.

**Input:** frozen `ExperimentSpec`, current `SystemContract`, current target
preflight, current policy, and remaining budget.

**Output:** `APPROVED` with machine-enforced limits or `REJECTED` with reasons.

**Validation:** decision is reproducible from declared policy inputs; all deny
rules are fail-closed; approval does not exceed the contract; human or AI prose
cannot bypass checks.

**Update:** never edit a decision after issue. Re-evaluation produces a new
record.

**Invalidation:** any change in spec, contract, target preflight, policy,
authority, budget, or approval lifetime voids an approval before execution.

## `ExperimentResult`

**Purpose:** separate what the harness did, whether the fault was established,
how the target behaved, and where an observed problem originated.

**Principal fields:**

- execution state;
- experiment-validity state;
- target verdict;
- problem attribution;
- start/end timestamps and observable environment identity;
- injection and cleanup confirmation;
- observation completeness and oracle result;
- deviations, nondeterministic factors, and unresolved unknowns; and
- references to spec, decision, evidence bundle, harness, adapter, oracle,
  target, model, and contract versions.

**Input:** execution events, injection checks, observations, cleanup evidence,
and independent oracle output.

**Output:** a multidimensional result suitable for review, not a single success
boolean.

**Validation:** a target verdict requires valid experiment conditions and
complete required evidence; injection failure cannot yield `CONTRACT_MET`;
harness errors are not assigned to the target without evidence; all timestamps
and version references are present.

**Update:** issue an amended record only to correct metadata or attach late
evidence, preserving the original and reason. A new execution creates a new
result.

**Invalidation:** results remain historical evidence, but become ineligible for
current comparisons if lineage, evidence integrity, target identity, or verdict
logic cannot be verified. Oracle changes do not retroactively rewrite verdicts.

## `EvidenceBundle`

**Purpose:** bind the evidence needed to audit an experiment and every claim made
from it.

**Principal fields:** manifest; referenced or retained inputs; policy checks;
execution event stream; injection confirmation; metrics/logs/traces/state within
permitted retention; oracle inputs/output; stop and cleanup evidence; integrity
metadata; gaps; redactions; visibility; and retention/expiry rules.

**Input:** artifacts created before, during, and after a rejected or executed
experiment.

**Output:** an auditable evidence manifest whose public form may contain only
safe, approved subsets or references.

**Validation:** required manifest entries are present or explicitly missing;
clocks/timezones and observation windows are recorded; redaction does not hide a
verdict prerequisite; secrets and private identifiers are excluded from public
forms; each conclusion identifies supporting entries.

**Update:** append redaction decisions, verified corrections, or newly available
evidence as revisions; never overwrite raw historical evidence in place.

**Invalidation:** integrity failure, missing required evidence, unauthorized data
inclusion, ambiguous target/window identity, or broken lineage prevents a
conclusive verdict or publication as applicable.

## `HardeningRecord`

**Purpose:** connect one reviewed target change to the demonstrated weakness and
before/after evidence without overstating generality.

**Principal fields:** weakness/result references; target change identity and
review; contract/oracle versions; before evidence; same-condition re-test;
holdout-condition re-tests; normal-function and performance checks; scope;
unverified conditions; regressions; and rollback or non-adoption decision.

**Input:** confirmed target weakness, reviewed candidate change, and predeclared
verification plan.

**Output:** an accepted, rejected, or inconclusive hardening record. Acceptance
does not itself create production authority.

**Validation:** target change is separate from contract/oracle changes; before
and after target identities are known; the original condition and normal path
are checked; holdout evidence is labeled separately; failures and side effects
are retained.

**Update:** new tests, reversions, or discovered limitations create revisions
with preserved prior claims.

**Invalidation:** target drift, reverted change, incompatible contract/oracle,
invalid source experiment, or later contradictory evidence limits or withdraws
reuse claims.

## `RegressionCase`

**Purpose:** preserve a known weakness and verified check for recurrence under a
defined compatibility boundary.

**Principal fields:** source hardening record; executable spec template;
contract/oracle requirements; target compatibility predicate; expected valid
injection and verdict; baseline and cleanup requirements; last valid run;
known limitations; and retirement rule.

**Input:** a `HardeningRecord` with a valid same-condition re-test and reviewed
scope.

**Output:** a reusable regression candidate. Generalization or portability is
not inferred from exact replay.

**Validation:** compatibility can be checked before use; injection establishment
and oracle requirements remain observable; the case cannot weaken the active
contract; historical evidence is linked.

**Update:** issue a new version when adapters, target compatibility, parameters,
or oracle requirements change. Keep exact-replay and holdout variants distinct.

**Invalidation:** incompatible target/configuration/dependency/permission
changes, contract or oracle changes, unsupported adapter/harness versions,
unverifiable history, or retired behavior prevents execution until reviewed.

## Cache boundaries

The project uses four logical cache units; v0.x may implement them as local
artifact reuse rather than a cache service:

1. **Incident knowledge:** `SourceRecord` → `IncidentModel` → `FailureModel`.
2. **Target mapping:** `FailureModel` + target snapshot + `SystemContract` →
   `TargetMapping`.
3. **Executable experiment candidate:** mapping + contract + capabilities →
   `ExperimentSpec` and current `SafetyDecision`.
4. **Execution evidence:** immutable result/evidence records and derived
   hardening/regression records.

| Change | Incident knowledge | Target mapping | Experiment candidate | Historical result |
| --- | --- | --- | --- | --- |
| Source revision/rights | Review affected models | Review transitively | Block if lineage/rights invalid | Preserve if permitted; restrict use/publication |
| Failure mechanism | New revision | Invalidate affected mappings | Invalidate dependents | Preserve historical lineage |
| Target code/config | Reuse | Invalidate affected mapping | Invalidate | Preserve, no longer current evidence |
| Dependencies/topology | Reuse | Invalidate affected mapping | Invalidate | Preserve, reassess comparability |
| Permissions/authority | Reuse | Review authority-related claims | Invalidate approval/spec as needed | Preserve |
| `SystemContract` | Reuse | Review affected mapping | Invalidate | Preserve under old contract |
| Oracle/harness/adapter | Reuse | Usually reuse | Invalidate incompatible specs | Preserve; do not rewrite verdict |
| Model/prompt | Source facts remain | Mapping may require revalidation | Generated spec requires review | Observations remain; model-derived claims retain version |

Invalidation is targeted through lineage rather than deleting all artifacts. A
cache hit never bypasses current target identity, contract, policy, or safety
preflight.

## Assets across model changes

Assets intended to survive model replacement include source metadata and
permitted evidence, human-approved contracts, target snapshots, deterministic
policy decisions, raw observations, oracle definitions and outputs, reviewed
hardening changes, and regression history.

Model-generated incident interpretations, abstractions, mappings, candidate
ranking, and experiment or hardening proposals retain their model/prompt/tool
lineage. They may still be reused as proposals, but require validation against
current evidence and contracts. A new model does not automatically invalidate
raw evidence, and an old model's output does not become trusted merely because it
was cached.

## Illustrative serialization

The following is explanatory YAML, not an implemented schema or accepted CLI
input:

```yaml
contract_type: TargetMapping
contract_version: design-example-1
id: mapping-example-retry-pool
failure_model_ref: failure-example-retry-retention@1
target_snapshot_ref: target-example@revision-placeholder
system_contract_ref: contract-example@1
decision: INSUFFICIENT_INFORMATION
confirmed_conditions:
  - bounded worker pool exists
unconfirmed_conditions:
  - retries can overlap before worker release
evidence:
  - kind: TARGET_OBSERVED
    ref: target-evidence-placeholder
limitations:
  - Hypothetical and unexecuted; no real target is identified.
```
