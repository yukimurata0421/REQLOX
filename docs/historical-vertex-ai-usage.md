# Historical Vertex AI usage

One retained development run on 2026-09-26 JST used Google Cloud Vertex AI's
`generateContent` operation to generate an Incident IR candidate from incident
material. Its manifest records one external API call and one completed proposal.
On 2026-10-15, a local read-only check verified the proposal file against the
manifest's SHA-256 and size, matched the recorded model identities, and checked
the external-API transport and completed-response metadata.

The candidate remained `MODEL_PROPOSAL_REVIEW_REQUIRED` with mutation authority
`NONE`. A completed response does not establish accepted IR, JEV accuracy,
repair success or authority to execute a Target.

The [safe machine-readable summary](../publication/vertex-ai-usage-20260926.json)
contains the date, service/API, purpose, counts, review/authority state and
evidence hashes. It exports no original incident text, prompts, proposal body,
provider response, response identifier, authorization record, credential,
absolute path or personal judgment. Model identity and provider metadata are
represented by hashes; the complete supporting files remain private.

This is a local verification of saved records, not a fresh provider query or
an independent provider attestation. Current connectivity, availability and
competition eligibility were not checked. No new inference was invoked.

## Relationship to the delivered application

Historical inference, deterministic saved-response IR/JEV replay, the later
copied-Target checks with existing repair candidates, and today's read-only
archive are separate operations. The earlier call is not a demonstration of
one automatic path from an arbitrary incident to an arbitrary repair. It does
not establish independent generalization, Source added value or calibration.

The [latest delivery](current-delivery.md) verifies the public UI and its access
boundary. It does not prove qualifying AI usage by deployment alone. Before a
competition submission, map this historical role and its permitted evidence
to the applicable requirements; do not publish the private raw files.

The current copied Target scope stays closed at 15/15 campaigns and 62/120
charged seconds. This documentation check made zero model calls and zero
native campaigns, and neither resets nor extends that scope.
