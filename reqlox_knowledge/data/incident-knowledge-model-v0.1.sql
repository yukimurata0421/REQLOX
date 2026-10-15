-- REQLOX Incident Knowledge Model v0.1
-- Reference PostgreSQL + pgvector DDL. This file is not applied automatically.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS reqlox_knowledge;
SET search_path TO reqlox_knowledge, public;

CREATE TABLE provenance_record (
    id text PRIMARY KEY CHECK (id ~ '^prov_[a-f0-9]{20}$'),
    contract_version text NOT NULL CHECK (contract_version = '0.1.0'),
    activity_type text NOT NULL,
    agent jsonb NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz NOT NULL CHECK (ended_at >= started_at),
    input_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    output_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    parameters_sha256 char(64) NOT NULL,
    processing_boundary jsonb NOT NULL
);

CREATE TABLE source_document (
    id text PRIMARY KEY CHECK (id ~ '^srcdoc_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    lifecycle_status text NOT NULL,
    organization text,
    publisher text NOT NULL,
    source_url text NOT NULL,
    canonical_url text NOT NULL,
    source_type text NOT NULL,
    published_at timestamptz,
    retrieved_at timestamptz,
    title text NOT NULL,
    language text NOT NULL,
    raw_sha256 char(64),
    normalized_sha256 char(64) NOT NULL,
    raw_location text,
    normalized_text_location text NOT NULL,
    raw_retention text NOT NULL,
    fetch_status text NOT NULL,
    immutable boolean NOT NULL CHECK (immutable),
    normalization_version text NOT NULL,
    rights jsonb NOT NULL,
    exact_duplicate_of text REFERENCES source_document(id),
    near_duplicate_cluster_id text,
    legacy_refs jsonb NOT NULL,
    processing_boundary jsonb NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (id, revision_id),
    CHECK (exact_duplicate_of IS NULL OR exact_duplicate_of <> id),
    CHECK (
        (raw_retention = 'RETAINED' AND raw_sha256 IS NOT NULL
            AND raw_location IS NOT NULL AND retrieved_at IS NOT NULL)
        OR (raw_retention = 'HASH_ONLY_RIGHTS_RESTRICTED'
            AND raw_sha256 IS NOT NULL AND raw_location IS NULL)
        OR (raw_retention = 'LEGACY_NOT_RETAINED' AND raw_location IS NULL)
    )
);

CREATE INDEX source_document_canonical_url_idx ON source_document (canonical_url);
CREATE INDEX source_document_normalized_sha_idx ON source_document (normalized_sha256);
CREATE INDEX source_document_near_cluster_idx ON source_document (near_duplicate_cluster_id)
    WHERE near_duplicate_cluster_id IS NOT NULL;

CREATE TABLE evidence_span (
    id text PRIMARY KEY CHECK (id ~ '^ev_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    source_document_id text NOT NULL REFERENCES source_document(id),
    start_char bigint NOT NULL CHECK (start_char >= 0),
    end_char bigint NOT NULL CHECK (end_char > start_char),
    section text,
    content_hash char(64) NOT NULL,
    evidence_types text[] NOT NULL,
    extracted_claim jsonb,
    extraction jsonb NOT NULL,
    verification jsonb NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (source_document_id, start_char, end_char, content_hash),
    CHECK (
        verification->>'status' = 'CANDIDATE'
        OR (extracted_claim IS NOT NULL AND jsonb_typeof(extracted_claim) = 'object')
    )
);

CREATE TABLE incident_occurrence (
    id text PRIMARY KEY CHECK (id ~ '^inc_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    lifecycle_status text NOT NULL,
    canonical_name text NOT NULL,
    organization text NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    time_precision text NOT NULL,
    deployment_context text NOT NULL,
    infrastructure text[] NOT NULL DEFAULT '{}',
    technologies text[] NOT NULL DEFAULT '{}',
    impact jsonb NOT NULL,
    incident_cluster_id text NOT NULL,
    identity_verification jsonb NOT NULL,
    incident_identity_confidence double precision NOT NULL
        CHECK (incident_identity_confidence BETWEEN 0 AND 1),
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    CHECK (ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX incident_occurrence_cluster_idx ON incident_occurrence (incident_cluster_id);
CREATE INDEX incident_occurrence_environment_idx ON incident_occurrence (deployment_context);

CREATE TABLE incident_source_document (
    incident_id text NOT NULL REFERENCES incident_occurrence(id) ON DELETE CASCADE,
    source_document_id text NOT NULL REFERENCES source_document(id),
    source_role text NOT NULL CHECK (source_role IN ('PRIMARY', 'SUPPORTING')),
    PRIMARY KEY (incident_id, source_document_id)
);

CREATE TABLE incident_evidence (
    incident_id text NOT NULL REFERENCES incident_occurrence(id) ON DELETE CASCADE,
    evidence_id text NOT NULL REFERENCES evidence_span(id),
    PRIMARY KEY (incident_id, evidence_id)
);

CREATE TABLE failure_event (
    id text PRIMARY KEY CHECK (id ~ '^fe_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    incident_id text NOT NULL REFERENCES incident_occurrence(id) ON DELETE CASCADE,
    sequence integer NOT NULL CHECK (sequence >= 0),
    layer text NOT NULL,
    fault_family text NOT NULL,
    primitive text NOT NULL,
    subtype text,
    component jsonb NOT NULL,
    event_state jsonb NOT NULL,
    observation jsonb NOT NULL,
    confidence jsonb NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (incident_id, sequence, id)
);

CREATE TABLE failure_event_evidence (
    failure_event_id text NOT NULL REFERENCES failure_event(id) ON DELETE CASCADE,
    evidence_id text NOT NULL REFERENCES evidence_span(id),
    PRIMARY KEY (failure_event_id, evidence_id)
);

CREATE TABLE causal_edge (
    id text PRIMARY KEY CHECK (id ~ '^edge_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    incident_id text NOT NULL REFERENCES incident_occurrence(id) ON DELETE CASCADE,
    from_event_id text NOT NULL REFERENCES failure_event(id),
    to_event_id text NOT NULL REFERENCES failure_event(id),
    relation text NOT NULL CHECK (relation IN (
        'causes', 'contributes_to', 'amplifies', 'triggers',
        'prevents_recovery', 'masks', 'correlated_with', 'unknown'
    )),
    causality_type text NOT NULL,
    explicitly_stated boolean NOT NULL,
    inferred boolean NOT NULL,
    confidence jsonb NOT NULL,
    jev_judgment_id text,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL,
    CHECK (from_event_id <> to_event_id),
    CHECK (explicitly_stated <> inferred)
);

CREATE TABLE causal_edge_evidence (
    causal_edge_id text NOT NULL REFERENCES causal_edge(id) ON DELETE CASCADE,
    evidence_id text NOT NULL REFERENCES evidence_span(id),
    PRIMARY KEY (causal_edge_id, evidence_id)
);

CREATE TABLE failure_pattern (
    id text PRIMARY KEY CHECK (id ~ '^fp_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    pattern_version integer NOT NULL CHECK (pattern_version >= 1),
    canonical_name text NOT NULL,
    trigger_primitive text NOT NULL,
    required_context jsonb NOT NULL,
    optional_context jsonb NOT NULL,
    causal_graph jsonb NOT NULL,
    graph_fingerprint_sha256 char(64) NOT NULL,
    applicability jsonb NOT NULL,
    injection jsonb NOT NULL,
    evidence_summary jsonb NOT NULL,
    frequency_signal jsonb NOT NULL,
    lifecycle_status text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- A graph fingerprint retrieves candidates; context still participates in canonicalization.
CREATE INDEX failure_pattern_graph_fingerprint_idx
    ON failure_pattern (graph_fingerprint_sha256, pattern_version);

CREATE TABLE pattern_occurrence (
    id text PRIMARY KEY CHECK (id ~ '^po_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    pattern_id text NOT NULL REFERENCES failure_pattern(id),
    incident_id text NOT NULL REFERENCES incident_occurrence(id),
    match_type text NOT NULL,
    structural_similarity double precision NOT NULL CHECK (structural_similarity BETWEEN 0 AND 1),
    semantic_similarity double precision NOT NULL CHECK (semantic_similarity BETWEEN 0 AND 1),
    evidence_strength double precision NOT NULL CHECK (evidence_strength BETWEEN 0 AND 1),
    jev_judgment_id text,
    created_at timestamptz NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (pattern_id, incident_id)
);

CREATE TABLE pattern_occurrence_event (
    pattern_occurrence_id text NOT NULL REFERENCES pattern_occurrence(id) ON DELETE CASCADE,
    failure_event_id text NOT NULL REFERENCES failure_event(id),
    PRIMARY KEY (pattern_occurrence_id, failure_event_id)
);

CREATE TABLE pattern_statistics (
    id text PRIMARY KEY CHECK (id ~ '^pstats_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    pattern_id text NOT NULL UNIQUE REFERENCES failure_pattern(id),
    computed_at timestamptz NOT NULL,
    computation_version text NOT NULL,
    raw_document_count integer NOT NULL CHECK (raw_document_count >= 1),
    unique_incident_count integer NOT NULL CHECK (unique_incident_count >= 1),
    independent_organization_count integer NOT NULL CHECK (independent_organization_count >= 1),
    independent_source_count integer NOT NULL CHECK (independent_source_count >= 1),
    environment_count integer NOT NULL CHECK (environment_count >= 1),
    first_seen_at timestamptz,
    last_seen_at timestamptz,
    occurrence_by_environment jsonb NOT NULL,
    occurrence_by_year jsonb NOT NULL,
    frequent_in_corpus boolean NOT NULL,
    real_world_probability double precision,
    reporting_bias_acknowledged boolean NOT NULL CHECK (reporting_bias_acknowledged),
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    CHECK (real_world_probability IS NULL)
);

CREATE TABLE jev_judgment (
    id text PRIMARY KEY CHECK (id ~ '^jev_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    purpose text NOT NULL,
    subject_type text NOT NULL,
    subject_id text NOT NULL,
    subject_revision_id text,
    provider text NOT NULL,
    model text NOT NULL CHECK (model = 'jev'),
    model_version text NOT NULL,
    question jsonb NOT NULL,
    input_sha256 char(64) NOT NULL,
    result_choice text NOT NULL,
    probabilities jsonb NOT NULL,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    outcome text NOT NULL CHECK (outcome IN ('SUPPORTED', 'NOT_SUPPORTED', 'INCONCLUSIVE')),
    threshold double precision NOT NULL CHECK (threshold BETWEEN 0 AND 1),
    decision text NOT NULL CHECK (decision IN ('ACCEPT', 'REVIEW', 'REJECT')),
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb
);

ALTER TABLE causal_edge
    ADD CONSTRAINT causal_edge_jev_fk FOREIGN KEY (jev_judgment_id) REFERENCES jev_judgment(id);
ALTER TABLE pattern_occurrence
    ADD CONSTRAINT pattern_occurrence_jev_fk FOREIGN KEY (jev_judgment_id) REFERENCES jev_judgment(id);

CREATE TABLE knowledge_embedding (
    id text PRIMARY KEY CHECK (id ~ '^embk_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    entity_type text NOT NULL CHECK (entity_type IN ('incident', 'evidence', 'failure_pattern', 'causal_path')),
    entity_id text NOT NULL,
    source_entity_ids text[] NOT NULL CHECK (cardinality(source_entity_ids) >= 1),
    causal_path jsonb,
    embedding_model text NOT NULL,
    embedding_model_version text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions >= 1),
    schema_version text NOT NULL,
    input_text text NOT NULL,
    input_sha256 char(64) NOT NULL,
    embedding vector NOT NULL,
    authority text NOT NULL CHECK (authority = 'INDEX_ONLY_NOT_SOURCE_OF_TRUTH'),
    rebuildable boolean NOT NULL CHECK (rebuildable),
    created_at timestamptz NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    CHECK (
        (entity_type = 'causal_path' AND causal_path IS NOT NULL)
        OR (entity_type <> 'causal_path' AND causal_path IS NULL)
    ),
    UNIQUE (entity_type, entity_id, embedding_model, embedding_model_version, schema_version, input_sha256)
);

-- Create one pgvector ANN index per pinned model/dimension after the model is selected.
-- An untyped vector column deliberately prevents silently mixing dimensions into one index.

CREATE TABLE fault_injection_candidate (
    id text PRIMARY KEY CHECK (id ~ '^fic_[a-f0-9]{20}$'),
    revision_id text NOT NULL,
    pattern_id text NOT NULL REFERENCES failure_pattern(id),
    target_ref jsonb NOT NULL,
    applicability_judgment_id text NOT NULL REFERENCES jev_judgment(id),
    fault jsonb NOT NULL,
    frequency_signal double precision NOT NULL CHECK (frequency_signal BETWEEN 0 AND 1),
    severity_signal double precision NOT NULL CHECK (severity_signal BETWEEN 0 AND 1),
    evidence_strength double precision NOT NULL CHECK (evidence_strength BETWEEN 0 AND 1),
    architecture_match double precision NOT NULL CHECK (architecture_match BETWEEN 0 AND 1),
    injectability double precision NOT NULL CHECK (injectability BETWEEN 0 AND 1),
    novelty double precision NOT NULL CHECK (novelty BETWEEN 0 AND 1),
    composite_score double precision,
    execution_state text NOT NULL CHECK (execution_state = 'PROPOSED_NON_EXECUTABLE'),
    policy_decision text NOT NULL CHECK (policy_decision = 'BLOCKED_PENDING_EXPERIMENT_POLICY'),
    authorization_ref text,
    created_at timestamptz NOT NULL,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    CHECK (composite_score IS NULL),
    CHECK (authorization_ref IS NULL)
);

CREATE TABLE fault_injection_candidate_occurrence (
    candidate_id text NOT NULL REFERENCES fault_injection_candidate(id) ON DELETE CASCADE,
    pattern_occurrence_id text NOT NULL REFERENCES pattern_occurrence(id),
    PRIMARY KEY (candidate_id, pattern_occurrence_id)
);

CREATE TABLE artifact_provenance (
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    provenance_id text NOT NULL REFERENCES provenance_record(id),
    PRIMARY KEY (entity_type, entity_id, provenance_id)
);

COMMIT;
