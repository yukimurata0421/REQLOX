# REQLOX

**Check reliability requirements against controlled failures in Python code.**

REQLOX connects a reported failure condition to a supported caller, checks the
caller's stated requirements, and records whether a repair survives the same
failure and normal regression checks. It provides a Python API, CLI and browser
view of saved results.

## One example: a failed file sync

Consider the owned [`persist` example](examples/repository/storage.py).
A report such as “fsync failed with an I/O error” supplies a failure hypothesis.
The owner supplies the requirement separately: preserve the destination, propagate
the error and remove only this invocation's temporary file.

| Step | What the check does |
| --- | --- |
| Input | Bind the report's `FSYNC` condition to the supported `persist` caller |
| Detection | Raise a selected sync error; the original code leaves its pending file |
| Candidate | Wrap the write/replace sequence in cleanup guarded by ownership |
| Re-injection | Apply the same failure to the candidate, then check normal calls |
| Decision | Adopt only in the isolated derived snapshot when all required checks pass |

The relevant change has this shape (excerpt; full rewrite in
[`repository_atomic_write.repair`](reqlox_core/repository_atomic_write.py)):

```diff
- with pending.open("xb") as output:
-     output.write(data)
-     output.flush()
-     os.fsync(output.fileno())
- os.replace(pending, destination)
+ temporary_created = False
+ try:
+     with pending.open("xb") as output:
+         temporary_created = True
+         output.write(data)
+         output.flush()
+         os.fsync(output.fileno())
+     os.replace(pending, destination)
+ finally:
+     if temporary_created:
+         pending.unlink(missing_ok=True)
```

Open [the saved review](https://reqlox.yukimurata0421.dev/demo/) and select
**api · copied Target repair**. That archived record contains four native
campaigns, six failed original observations, six passing re-injections, ten
normal regressions and six passing confirmation observations. These are
dependent cases for one candidate. The report sentence above is illustrative;
the saved run used owned requirements and curated inputs, not a natural-incident
transfer study. Viewing it starts no new experiment.

## Start with inspection

Use Python 3.11 or later:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[knowledge]'
.venv/bin/reqlox inventory --root examples/repository
.venv/bin/reqlox run --target examples/targets/target.json --all --dry-run
.venv/bin/reqlox demo
```

Inventory reads Python syntax without importing the Target. The dry run prepares
the selection without executing it. The local UI supports saved records, input
drafts, static preparation and history restoration; new model calls and native
execution are disabled at the server boundary.

| Goal | Start here |
| --- | --- |
| Follow the existing result | [Read-only review](docs/read-only-demo.md) |
| Prepare your own supported caller | [Getting started](docs/getting-started.md) and [Target workspaces](docs/target-workspaces.md) |
| Understand extraction and comparison | [Source comparison scope](docs/source-comparison-scope.md) |
| Inspect the design and code | [Reviewer guide](docs/reviewer-guide.md) and [Architecture](docs/architecture.md) |
| Run offline checks | [Tests and coverage](docs/testing.md) |
| Explore document/IR interfaces | [Knowledge](docs/local-knowledge.md) and [System IR](docs/system-ir-reproduction.md) |

## What the implementation covers

The core binds four supported families: atomic file writes, atomic file contexts,
asynchronous resource release and elapsed-time expiry. Report projection uses a
bounded lexical grammar; caller binding uses syntax and documented interfaces.
Repair generation uses deterministic family rewrites or explicitly supplied
candidates. Optional model proposals and applicability review are separate
from execution authority; [one historical provider call](docs/historical-vertex-ai-usage.md)
is documented independently of the copied-Target runs.

The comparison interface supports fixed and Target-guided source-blind planners.
Both arms share an available primitive library and equal declared budgets.
Source can change ordering or select a condition outside a particular baseline;
this measures a finite planner comparison, not general incident understanding.

## Limits and evidence

Native execution requires separately approved copied inputs, Linux namespaces,
resource limits and a durable budget. Model output and review scores cannot
authorize execution. Originals are preserved; candidates affect isolated copies.

The archived copied-Target scope is closed at **15/15 campaigns, 62/120 charged
seconds**. Temppath retains **four HELD bindings**, with no repair or repair
re-injection. Missing historical raw evidence remains `UNKNOWN_UNRECOVERED`.
HELD means a binding is not qualified; UNKNOWN means an outcome is unconfirmed.
Independent generalization, Source added value, probability calibration and
human-effort savings remain research questions.

Current delivery: [verified release](docs/current-delivery.md).
Documentation: [guide](docs/README.md).
Dated validation and operational history: [archive index](docs/history/README.md).
The [previous README](README.history-20261015.md) is retained as a dated snapshot.
