# Concepts

REQLOX connects a supplied failure condition, a supported target binding, and a
finite expected behavior. This vocabulary describes the public implementation.

## Main terms

| Term | Meaning here |
| --- | --- |
| Source | A supplied incident description or other failure reference. Its text is evidence to interpret, not an instruction to execute. |
| Target | The selected Python snapshot or known demo implementation being examined. |
| Condition | A bounded trigger, such as a file operation raising an exception or a task being cancelled. |
| Binding | A statically recognized connection between target code and one supported experiment interface. |
| Contract | Explicitly declared expected behavior for that interface. |
| Candidate | A hypothesis, condition, or proposed code change that still needs the corresponding checks. |
| Oracle | A fixed expected result used to compare observations. |
| Re-injection | Running the same selected failure condition against a repair candidate. |
| Held | A candidate or result that lacks the required support, compatible binding, or observation. |
| Snapshot adoption | Keeping a verified candidate in the result's in-memory/saved snapshot; it does not modify the user's checkout. |

## A concrete example

The owned [storage example](../examples/repository/storage.py) writes bytes to a
temporary file, flushes and synchronizes them, and replaces the destination.
The [example contract](../examples/owned-requirements.json) declares expected
bytes, preservation of the previous destination on failure, exception
propagation, and cleanup of the temporary file created by that invocation.

Static inventory can recognize the supported shape. A finite experiment can
then observe selected exceptional paths. The observed result, not recognition
alone, determines whether the contract is violated. A candidate repair remains
limited to that snapshot and those checked conditions.

## Source and No Source

`SOURCE` and `NO_SOURCE` are the experiment arm identifiers.

The ordinary loop records both arms. The `--paired` path gives each arm its own
loop, candidate history, and reusable results. Both start from the same target
snapshot and use the declared owner requirements. External failure text is
supplied to the Source arm; the No Source arm starts without it.

Read initial discoveries, final adoption, executed conditions, and reused
observations separately. Two arms reaching the same repaired snapshot does not
show that Source had no effect on exploration. A difference in exploration
does not automatically show a difference in final repair quality.

## Evidence boundaries

Keep these statements distinct when reading a run:

1. A sentence was found in the supplied Source.
2. A finite condition was extracted from that sentence.
3. The selected target exposes a supported binding.
4. The intended condition was reached during execution.
5. The observation agrees with or violates the declared contract.
6. A candidate satisfies the selected repair and confirmation checks.

The public runtime does not turn that sequence into independent proof of the
original incident's cause. Uncertainty about meaning and missing runtime
evidence remain visible in the result.

## Reading order

Continue with [Architecture](architecture.md) for component boundaries,
[Getting started](getting-started.md) for commands, or [Results](results.md)
for status interpretation. The [documentation index](README.md) lists all pages.
