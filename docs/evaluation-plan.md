# Evaluation Plan

## Status and evidence position

This is a prospective plan. No controlled result, benchmark, effect size,
discovery rate, miss rate, cost reduction, or statistical significance is
reported.

The motivating evidence is narrower: a developer observed qualitative
improvement in a manual incident-assisted workflow. Its causal contribution,
reproducibility, magnitude, and economics remain unmeasured. The evaluation is
designed to test that observation without denying it or promoting it into a
proven result.

## Hypotheses

### H1 — incident-derived discovery

Under common execution and verification conditions, adding knowledge derived
from real incident reports improves discovery of target-applicable weaknesses
that were not exercised by a frozen baseline test set, compared with free
reasoning or generic fault knowledge alone.

“Previously untested” is relative to a fixed target snapshot and baseline test
set. It does not mean globally novel, first discovered, or absent from model
training data.

### H2 — structured reuse efficiency

Relative to the current manual workflow that provides incident material for
fresh interpretation, structured failure knowledge and mapping reuse can retain
useful discovery and hardening while reducing one or more of model use,
experimental cost, human effort, elapsed time, and repeated work.

Initial knowledge-creation cost, per-target mapping cost, reuse cost, and
invalidation/update cost are measured separately.

### H3 — generalization without overfitting

Hardening produced for one confirmed condition improves behavior under related
holdout conditions not used to design the change. Separately, when a mechanism
is mapped to another target, the workflow correctly distinguishes
`APPLICABLE`, `NOT_APPLICABLE`, and `INSUFFICIENT_INFORMATION`.

H1, H2, and H3 are not bundled acceptance criteria. Any combination of supported
and unsupported results is admissible, including higher discovery with higher
cost, lower cost with lower discovery, or benefit limited to one target.

## Comparison conditions

| Condition | Additional knowledge and workflow |
| --- | --- |
| A — Free reasoning | Target code/configuration, `SystemContract`, frozen baseline tests, and common harness; no added incident material or generic fault catalogue. |
| B — Generic chaos knowledge | A plus a versioned generic fault catalogue and testing considerations. |
| C — Current manual workflow | B plus target-relevant incident reports/postmortems, freshly interpreted and applied in each independent run. |
| D — Structured workflow | The framework's versioned incident/failure knowledge, mappings, candidate generation, and permitted reuse. |

Condition C must be a faithful, practical version of the workflow that motivated
the project, not an intentionally weak prompt. Condition D's reuse is declared
and costed rather than hidden.

All conditions receive equivalent ability to inspect the target, propose
changes, use the common experiment harness, collect evidence, and run the same
verification classes within their authority and budget. Condition A is not
restricted to prose while later conditions receive execution tools.

The historical progression—from free reasoning, to harness ideas, to fault
injection, to incident material—is development context, not a controlled
comparison. The A–D experiment isolates knowledge/workflow contributions under a
new frozen protocol.

## Evaluation units and sampling

An evaluation unit binds:

- one target code/configuration/dependency snapshot;
- one baseline test snapshot and `SystemContract`;
- one condition and independent run context;
- a common maximum budget and common tool/authority surface;
- candidate, execution, result, and review records; and
- a case-selection stratum.

The initial study should remain small enough to audit, then expand only when the
protocol is stable. Case selection includes:

- incident mechanisms expected to be applicable;
- mechanisms expected to be not applicable;
- cases where available evidence is intentionally insufficient;
- targets already well defended by baseline tests; and
- unsuccessful as well as successful historical examples.

Near-duplicate reports or restatements of one cause are grouped so they cannot be
counted as independent discoveries. Selection and grouping are fixed before
condition outcomes are reviewed where feasible.

## Common controls

Hold these constant where possible and record every deviation:

- target code, configuration, dependency, and environment snapshot;
- baseline test set;
- experiment, observation, and verification harness;
- model and reasoning settings;
- available tools, permissions, and network access;
- isolated environment and workload;
- `SystemContract`, oracle, and scoring rules;
- maximum model, experiment, elapsed-time, and human-review budgets; and
- review instructions and adjudication process.

Additional knowledge necessarily changes input volume. The plan therefore does
not claim identical consumption across conditions. It applies common upper
bounds, measures actual use, and explains which input and reuse differences are
being tested.

If a material outcome could be explained by context length alone, add a limited
length-matched control containing similarly sized but non-incident or
non-relevant material. This is an optional follow-up, not a requirement that
makes the initial protocol unmanageably complex.

## Leakage prevention

- Begin each condition in an independent conversation/run context.
- Do not carry candidates, patches, reviewer feedback, or outcomes across
  conditions except the reuse explicitly defined for D.
- When evaluating historical target snapshots, prevent access to future fixes,
  tests, commit messages, issue text, branches, and repository history.
- Record exactly which D artifacts were created before the case and are eligible
  for reuse.
- Freeze source/case selection before outcome review where practical.
- Keep condition labels hidden from weakness adjudicators where the artifacts
  can be meaningfully blinded.
- Record run order and randomize or counterbalance it where practical.
- Repeat runs when model or system behavior is variable.
- Record available seeds. If a provider seed or model internals are unavailable,
  record `not_observed`; do not claim they were fixed.

## Candidate lifecycle and denominators

Each generated candidate is assigned one terminal or current state without
collapsing distinct causes:

- `APPLICABLE`, `NOT_APPLICABLE`, or `INSUFFICIENT_INFORMATION` mapping;
- `NOT_RUN` due to budget, duplication, risk, or prioritization;
- `REJECTED` by the safety gate;
- `EXPERIMENT_INVALID` because prerequisites or injection failed;
- `EVIDENCE_INSUFFICIENT`;
- `NO_WEAKNESS_CONFIRMED` under a valid experiment; or
- `WEAKNESS_CONFIRMED` and independently adjudicated.

If “precision” is reported, the report must name its denominator, ground-truth
or adjudication rule, and treatment of unexecuted and inconclusive candidates.
Because the total number of real weaknesses is normally unknown, the study does
not report whole-system recall or coverage of the unknown failure universe.

## Primary outcomes

### 1. Independently confirmed weaknesses

Count deduplicated weaknesses that:

- have an applicable, evidence-grounded mapping;
- were established by a valid experiment;
- violate a predeclared functional, safety, recovery, or performance condition;
  and
- pass independent review of evidence and duplicate grouping.

Candidate count, document count, experiment count, and stop count are not
substitutes.

### 2. Incremental weaknesses beyond baseline tests

Count confirmed weaknesses not exercised by the frozen baseline test set. This
is an incremental value relative to that snapshot, not a claim of global
novelty.

### 3. Candidate disposition

Report counts and rates for every mapping, run, validity, verdict, and attribution
state. This exposes wasted candidates, safety rejections, harness limitations,
and evidence gaps rather than hiding them in one success rate.

### 4. Hardening outcomes

For each accepted hardening candidate, separately report:

- same-condition re-test;
- related holdout conditions not used to design the fix;
- normal functional tests;
- normal-load performance effects; and
- regressions, side effects, and unresolved scope.

An exact replay that repeatedly passes supports regression protection. It does
not by itself support H3.

## Cost and effort outcomes

Measure when observable:

- model/tool utilization exposed by the platform;
- experimental infrastructure time and direct cost;
- wall-clock elapsed time;
- human review, correction, and setup time;
- cost per independently confirmed weakness; and
- cost per accepted, verified improvement.

A hosted agent's weekly/product allowance is not interchangeable with API token
counts or billed currency. Metrics use their native units. Unobserved values are
`not_observed` or `null`, never estimated without an explicit method.

If zero weaknesses or improvements are confirmed, cost per result is undefined
and reported as `null` with the zero denominator, not as zero.

For structured reuse, report:

```text
total cost
  = initial knowledge extraction and validation
  + per-target mapping
  + experiment and verdict
  + update and invalidation handling
  + human review
```

Report first-use and later reuse cohorts separately. Include the cost and harm of
incorrect reuse, stale mappings, and unnecessary revalidation rather than only
cache savings.

## Safety and harness evaluation

Safety is tested with declared negative cases, not inferred from observing zero
incidents. The harness evaluation includes whether it:

- rejects an unallowlisted target and prohibited operation;
- rejects excessive duration, intensity, concurrency, or cost;
- detects target-identity or contract drift immediately before execution;
- stops or refuses a verdict when mandatory observation is absent;
- distinguishes injection failure from target success;
- distinguishes harness/infrastructure failure from target failure;
- invokes cleanup after normal completion, abort, and harness error;
- verifies cleanup rather than equating a stop request with reversal; and
- prevents state from one experiment contaminating the next.

These are design-time test cases. Safety is not validated until the implemented
controls and failure paths are exercised in an isolated environment.

## Review and adjudication

At least one reviewer not responsible for generating the candidate examines the
mapping, experiment validity, evidence, contract verdict, duplicate grouping,
and hardening scope. Disagreements and changed verdicts are retained.

Where expert labels are uncertain, use multiple reviewers or an explicit
adjudication step and report agreement. Reviewer time is part of cost.

## Analysis

Begin with per-condition counts, rates with denominators, run-level distributions,
paired case comparisons, and uncertainty intervals. With repeated runs nested
within cases and targets, analysis must account for that dependence rather than
treat every candidate as independent.

For small or sparse samples, emphasize exact descriptive results, case-level
paired/permutation methods where appropriate, and confidence/credible intervals
rather than asymptotic claims. Predeclare the primary outcome and duplicate
grouping before the main comparison. Select any later mixed-effects or
hierarchical model only when sample size and structure support it.

No statistical significance, accuracy, savings target, or expected multiplier is
asserted before measurement.

## Interpretation matrix

| Observation | Supported interpretation | Not supported automatically |
| --- | --- | --- |
| C > A/B in confirmed weaknesses | incident material may add discovery value under this protocol | D is efficient or generalizes |
| D ≈ C with lower measured burden | structured reuse may support H2 for tested cases | H1 or cross-target validity |
| D < C | structure/reuse may be losing useful context | manual workflow is universally superior |
| Same-condition pass only | known weakness did not recur in exact tested condition | H3 generalization |
| Correct non-applicable decisions | mapping can avoid some unnecessary experiments | whole-system coverage or recall |
| Safety negatives pass | tested controls behaved as specified | safety in untested environments or production |

## Reporting checklist

Every evaluation report identifies target and baseline versions, conditions,
budgets and actual consumption, candidate denominators, invalid experiments,
missing data, duplicate decisions, same-condition versus holdout outcomes,
reviewer process, and limitations. Negative and inconclusive results are retained
alongside favorable results.
