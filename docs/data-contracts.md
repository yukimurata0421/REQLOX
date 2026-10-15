# Data Contracts

The public interfaces consume Python source mappings and bounded JSON inputs.
Repository experiment records and demo records have different formats. This
page identifies the current formats and their producers.

## Target snapshot

The Python API accepts a mapping from relative `.py` paths to source text.
The CLI loads that mapping from `--root`. If the root is the top level of a Git
repository, it uses tracked Python files. Otherwise it performs a bounded
directory scan. Test, vendored, target-copy, corpus, and environment directories
are excluded by the loader.

Source and directory links are rejected. The current source limits include
1,024 Python files, 262,144 bytes per file, and 16,777,216 bytes in total.
Unsupported shapes remain held or unrecognized; inventory is not a promise that
an arbitrary repository can be executed.

## Qualification configuration

[`examples/owned-requirements.json`](../examples/owned-requirements.json) is a
minimal configuration for the owned storage example:

```json
{
  "contracts": {
    "atomic_file": {
      "id": "owned.atomic-bytes.v1",
      "basis": "Owner-declared storage requirements",
      "scope": "The selected owned snapshot only"
    }
  },
  "maximum_probes": 3,
  "source_texts": {},
  "hypotheses": []
}
```

This abbreviated example explains the fields; use the checked-in configuration
when following the quickstart.

| Field | Role |
| --- | --- |
| `contracts` | Family-specific contract ID, owner basis, and scope. |
| `maximum_probes` | The finite initial exploration bound. |
| `source_texts` | Source IDs mapped to the original supplied text. |
| `hypotheses` | Explicitly supplied, evidence-bound hypotheses for the ordinary loop. |
| `specification_texts` | Optional target specification text used by the paired preparation path. |

The paired CLI prepares owner requirements and Source conditions for separate
arms. It does not use an ordinary `hypotheses` list as a replacement for that
preparation. Source text and target specification text retain separate roles.

## Condition preparation

`reqlox prepare` requires a target root, an output path, one contract input, and
one condition input:

| Option | Expected input |
| --- | --- |
| `--contracts` | The contract mapping itself, not the complete qualification configuration. |
| `--specification-input` | An object containing `specification_texts` and `owner_policies`. |
| `--condition-input` | An object containing `records` and `source_texts`. |
| `--natural-source-input` | An object containing `source_texts` for bounded lexical preparation. |

Choose one of the first two options and one of the last two. The condition
input and output paths must be under the private state root. The output must
not already exist. Preparation creates a configuration and selection record;
it executes no target campaign or provider call.

Original quote offsets and hashes identify evidence in the supplied text.
Translation, editing, or combining paragraphs changes that evidence. Prepared
records retain held conditions and do not certify semantic support.

## Saved repository artifacts

```text
state/runs/<name>/
  input.json
  method/
  round-00/
    study.json
    method/
    result.json
    ... worker plans and receipts ...
  round-00-decision.json
  result.json
```

`--paired` adds separate `source/` and `no_source/` loop directories under the
study root. A stopped run may contain only the inputs and terminal record that
were reached before the stop; do not assume the complete layout exists.

The loop result includes `status`, round history, `native_campaigns`,
`reused_arms`, `adopted_files`, and claim-limit fields. A paired `COMPLETE`
record summarizes both arms; each arm has its own outcome. Method archives
and input hashes belong to that run.

## Demo records and export

The demo writes beneath `state/demo/runs/<run_id>/` by default. Its result uses
`reqlox.hackathon-demo-result.v0.1` and includes the assessment, finite cases,
stage observations, execution status, and scope flags. Not every field is
present when the run stops before a stage.

The downloadable view removes evidence quotations, evidence-handle content,
candidate code, and candidate rationale. It retains result fields and hashes.
The ordinary HTTP response and private files can contain more detail than that
reduced download.

## Integrity and reuse

Canonical JSON hashes, source hashes, method hashes, and runtime identity bind
the local records. Changed inputs cannot be treated as an unchanged cached
result. A newly verified historical record is not a new target execution.

These hashes provide local integrity checks. They are not a trusted timestamp,
signature from an independent authority, or proof that a Source claim is true.
Audit only records produced and retained in a trusted private state directory;
the audit imports the saved method after its recorded hashes are checked.

## Included schemas

[`schemas/`](../schemas) contains versioned contracts for incident hypotheses,
evidence spans, system contracts, and workflow policy. These describe additional
structured exchange boundaries. They are not all mandatory inputs to the public
CLI, and their presence does not mean the complete broader workflow is exposed
by this package.

See [Results](results.md) for outcome interpretation and
[Getting started](getting-started.md) for executable commands.
