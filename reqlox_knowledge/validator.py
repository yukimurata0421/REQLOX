"""Reusable validator methods from the development implementation."""
from __future__ import annotations
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

class IncidentKnowledgeValidationError(RuntimeError):
    pass
SCHEMA_BY_CONTRACT = {'ProvenanceRecord': 'provenance-record.v0.1.schema.json', 'SourceDocument': 'source-document.v0.1.schema.json', 'EvidenceSpan': 'evidence-span.v0.1.schema.json', 'IncidentOccurrence': 'incident-occurrence.v0.1.schema.json', 'FailureEvent': 'failure-event.v0.1.schema.json', 'CausalEdge': 'causal-edge.v0.1.schema.json', 'FailurePattern': 'failure-pattern.v0.1.schema.json', 'PatternOccurrence': 'pattern-occurrence.v0.1.schema.json', 'PatternStatistics': 'pattern-statistics.v0.1.schema.json', 'JevJudgment': 'jev-judgment.v0.1.schema.json', 'KnowledgeEmbedding': 'knowledge-embedding.v0.1.schema.json', 'FaultInjectionCandidate': 'fault-injection-candidate.v0.1.schema.json'}
ENTITY_KIND_BY_CONTRACT = {'SourceDocument': 'source_document', 'EvidenceSpan': 'evidence_span', 'IncidentOccurrence': 'incident_occurrence', 'FailureEvent': 'failure_event', 'CausalEdge': 'causal_edge', 'FailurePattern': 'failure_pattern', 'PatternOccurrence': 'pattern_occurrence', 'PatternStatistics': 'pattern_statistics', 'JevJudgment': 'jev_judgment', 'KnowledgeEmbedding': 'embedding', 'FaultInjectionCandidate': 'fault_injection_candidate'}

def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

def graph_fingerprint(pattern: dict) -> str:
    lines = sorted((f"{edge['from']}>{edge['relation']}>{edge['to']}" for edge in pattern['causal_graph']['edges']))
    return sha256_bytes('|'.join(lines).encode('utf-8'))

def failure_pattern_embedding_text(pattern: dict) -> str:
    graph = pattern['causal_graph']
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming = Counter()
    for edge in graph['edges']:
        adjacency[edge['from']].append((edge['relation'], edge['to']))
        incoming[edge['to']] += 1
    starts = sorted((node for node in graph['nodes'] if incoming[node] == 0))
    ordered_edges: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    def visit(node: str) -> None:
        for relation, target in sorted(adjacency[node]):
            key = (node, relation, target)
            if key in seen:
                continue
            seen.add(key)
            ordered_edges.append(f'{node} -[{relation}]-> {target}')
            visit(target)
    for node in starts or sorted(graph['nodes']):
        visit(node)
    for edge in sorted(graph['edges'], key=lambda item: (item['from'], item['relation'], item['to'])):
        key = (edge['from'], edge['relation'], edge['to'])
        if key not in seen:
            ordered_edges.append(f"{edge['from']} -[{edge['relation']}]-> {edge['to']}")
    contexts = ', '.join((f'{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}' for key, value in sorted(pattern['context']['required'].items()))) or 'none'
    deployments = ', '.join(sorted(pattern['applicability']['deployment_context']))
    return '\n'.join(['ENTITY: failure_pattern', f"NAME: {pattern['canonical_name']}", f"TRIGGER: {pattern['trigger']['primitive']}", f'REQUIRED_CONTEXT: {contexts}', 'CAUSAL_GRAPH:', *ordered_edges, f'DEPLOYMENT: {deployments}'])

def evidence_embedding_text(span: dict) -> str:
    claim = span['extracted_claim']
    if claim is None:
        raise IncidentKnowledgeValidationError(f"{span['id']}: candidate evidence without an extracted claim cannot be embedded")
    return '\n'.join(['ENTITY: evidence', f"EVIDENCE_TYPES: {', '.join(sorted(span['evidence_types']))}", f"CLAIM_ORIGIN: {claim['origin']}", f"CLAIM: {claim['subject']} {claim['predicate']} {claim['object']}"])

def incident_embedding_text(incident: dict, events: list[dict]) -> str:
    ordered_events = sorted(events, key=lambda item: (item['sequence'], item['id']))
    return '\n'.join(['ENTITY: incident', f"ORGANIZATION: {incident['organization']}", f"DEPLOYMENT: {incident['environment']['deployment_context']}", f"INFRASTRUCTURE: {', '.join(sorted(incident['environment']['infrastructure'])) or 'none'}", f"TECHNOLOGIES: {', '.join(sorted(incident['environment']['technologies'])) or 'none'}", f"SYMPTOMS: {', '.join(sorted(incident['impact']['symptoms'])) or 'none'}", 'FAILURE_EVENTS:', *[f"{event['sequence']}: {event['layer']}/{event['primitive']}" for event in ordered_events]])

def causal_path_embedding_text(path: dict) -> str:
    return '\n'.join(['ENTITY: causal_path', 'PATH:', *[f"{edge['from']} -[{edge['relation']}]-> {edge['to']}" for edge in path['edges']]])

def jev_input_payload(judgment: dict) -> dict:
    return {'purpose': judgment['purpose'], 'subject': judgment['subject'], 'model': judgment['model'], 'question': judgment['question']}

def jev_policy_decision(judgment: dict) -> str:
    result = judgment['result']
    policy = judgment['policy']
    selected_probability = result['probabilities'][result['choice']]
    if result['outcome'] == 'INCONCLUSIVE':
        return 'REVIEW'
    if min(result['confidence'], selected_probability) < policy['threshold']:
        return 'REVIEW'
    if result['outcome'] == 'SUPPORTED' and result['choice'] in policy['accept_choices']:
        return 'ACCEPT'
    if result['outcome'] == 'NOT_SUPPORTED' and result['choice'] in policy['reject_choices']:
        return 'REJECT'
    return 'REVIEW'

def judgment_accepts(judgment: dict, *, purpose: str | set[str], entity_type: str, entity_id: str) -> bool:
    purposes = {purpose} if isinstance(purpose, str) else purpose
    subject = judgment['subject']
    return judgment['purpose'] in purposes and subject['entity_type'] == entity_type and (subject['entity_id'] == entity_id) and (judgment['policy']['decision'] == 'ACCEPT')

def schema_registry(schema_dir: Path) -> tuple[Registry, dict[str, dict]]:
    registry = Registry()
    schemas: dict[str, dict] = {}
    for path in sorted(schema_dir.glob('*.schema.json')):
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        if '$id' in schema:
            registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
        schemas[path.name] = schema
    return (registry, schemas)

def validate_schema(value: dict, schema_name: str, schemas: dict[str, dict], registry: Registry, label: str) -> None:
    schema = schemas[schema_name]
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        details = '; '.join((f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors))
        raise IncidentKnowledgeValidationError(f'{label}: {details}')

def safe_bundle_path(bundle_dir: Path, relative: str) -> Path:
    path = (bundle_dir / relative).resolve()
    root = bundle_dir.resolve()
    if not path.is_relative_to(root):
        raise IncidentKnowledgeValidationError(f'path escapes bundle: {relative}')
    return path

def load_hashed_file(bundle_dir: Path, file_ref: dict) -> tuple[Path, bytes]:
    path = safe_bundle_path(bundle_dir, file_ref['path'])
    if not path.is_file():
        raise IncidentKnowledgeValidationError(f"bundle file missing: {file_ref['path']}")
    payload = path.read_bytes()
    digest = sha256_bytes(payload)
    if digest != file_ref['sha256']:
        raise IncidentKnowledgeValidationError(f"bundle hash mismatch: {file_ref['path']} expected={file_ref['sha256']} actual={digest}")
    return (path, payload)

def resolve_bundle_blob(location: str | None, bundle_dir: Path, blob_by_path: dict[str, dict]) -> tuple[bytes, str] | None:
    if location is None:
        return None
    prefix = 'bundle://'
    if not location.startswith(prefix):
        raise IncidentKnowledgeValidationError(f'validated bundles require bundle:// blob locations: {location}')
    relative = location[len(prefix):]
    if relative not in blob_by_path:
        raise IncidentKnowledgeValidationError(f'blob is not declared in bundle: {relative}')
    _, payload = load_hashed_file(bundle_dir, blob_by_path[relative])
    return (payload, blob_by_path[relative]['sha256'])

def index_artifacts(artifacts: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id: dict[str, dict] = {}
    by_kind_and_id: dict[str, dict] = {}
    for artifact in artifacts:
        artifact_id = artifact['id']
        if artifact_id in by_id:
            raise IncidentKnowledgeValidationError(f'duplicate artifact id: {artifact_id}')
        by_id[artifact_id] = artifact
        kind = ENTITY_KIND_BY_CONTRACT.get(artifact['contract_type'])
        if kind:
            by_kind_and_id[f'{kind}:{artifact_id}'] = artifact
    return (by_id, by_kind_and_id)

def require_refs(owner: str, refs: list[str], available: set[str], label: str) -> None:
    missing = sorted(set(refs) - available)
    if missing:
        raise IncidentKnowledgeValidationError(f'{owner}: unknown {label} refs {missing}')

def independent_document_key(source_id: str, source_documents: dict[str, dict]) -> str:
    """Resolve exact duplicates, then collapse a near-document cluster."""
    seen = set()
    current = source_id
    while True:
        if current in seen:
            raise IncidentKnowledgeValidationError(f'{source_id}: exact duplicate chain contains a cycle')
        seen.add(current)
        source = source_documents[current]
        duplicate = source['dedup']['exact_duplicate_of']
        if duplicate is None:
            cluster = source['dedup']['near_duplicate_cluster_id']
            return f'near:{cluster}' if cluster is not None else f'source:{current}'
        current = duplicate

def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None

def validate_bundle(bundle_path: Path, schema_dir: Path, *, registry: Registry | None=None, schemas: dict[str, dict] | None=None) -> dict:
    bundle_dir = bundle_path.resolve().parent
    if registry is None or schemas is None:
        registry, schemas = schema_registry(schema_dir)
    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    validate_schema(bundle, 'incident-knowledge-bundle.v0.1.schema.json', schemas, registry, str(bundle_path))
    taxonomy_path, taxonomy_payload = load_hashed_file(bundle_dir, bundle['taxonomy'])
    taxonomy = json.loads(taxonomy_payload)
    validate_schema(taxonomy, 'failure-taxonomy.v0.1.schema.json', schemas, registry, str(taxonomy_path))
    primitive_rows = taxonomy['primitives']
    primitive_ids = [row['id'] for row in primitive_rows]
    if len(primitive_ids) != len(set(primitive_ids)):
        raise IncidentKnowledgeValidationError('taxonomy contains duplicate primitive ids')
    if not {'OTHER', 'UNKNOWN'}.issubset(primitive_ids):
        raise IncidentKnowledgeValidationError('taxonomy must retain OTHER and UNKNOWN')
    primitive_layers = {row['id']: row['layer'] for row in primitive_rows}
    relation_ids = set(taxonomy['causal_relations'])
    mechanisms = set(taxonomy['injection_mechanisms'])
    blob_by_path = {item['path']: item for item in bundle['blobs']}
    if len(blob_by_path) != len(bundle['blobs']):
        raise IncidentKnowledgeValidationError('bundle contains duplicate blob paths')
    for blob in bundle['blobs']:
        load_hashed_file(bundle_dir, blob)
    artifacts = []
    for artifact_ref in bundle['artifacts']:
        artifact_path, artifact_payload = load_hashed_file(bundle_dir, artifact_ref)
        artifact = json.loads(artifact_payload)
        if artifact.get('contract_type') != artifact_ref['contract_type']:
            raise IncidentKnowledgeValidationError(f'{artifact_path}: manifest contract_type does not match artifact')
        if artifact.get('id') != artifact_ref['artifact_id']:
            raise IncidentKnowledgeValidationError(f'{artifact_path}: manifest artifact_id does not match artifact')
        schema_name = SCHEMA_BY_CONTRACT[artifact['contract_type']]
        validate_schema(artifact, schema_name, schemas, registry, str(artifact_path))
        artifacts.append(artifact)
    by_id, by_kind_and_id = index_artifacts(artifacts)
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for artifact in artifacts:
        by_contract[artifact['contract_type']].append(artifact)
    provenance_ids = {item['id'] for item in by_contract['ProvenanceRecord']}
    for artifact in artifacts:
        refs = artifact.get('provenance_refs')
        if refs is not None:
            require_refs(artifact['id'], refs, provenance_ids, 'provenance')
    source_documents = {item['id']: item for item in by_contract['SourceDocument']}
    source_text: dict[str, str] = {}
    for source in source_documents.values():
        raw = resolve_bundle_blob(source['content']['raw_location'], bundle_dir, blob_by_path)
        if source['content']['raw_retention'] == 'RETAINED' and raw is None:
            raise IncidentKnowledgeValidationError(f"{source['id']}: retained raw source requires raw_location")
        if raw and sha256_bytes(raw[0]) != source['content']['raw_sha256']:
            raise IncidentKnowledgeValidationError(f"{source['id']}: raw SHA-256 mismatch")
        normalized = resolve_bundle_blob(source['content']['normalized_text_location'], bundle_dir, blob_by_path)
        assert normalized is not None
        normalized_payload = normalized[0]
        if sha256_bytes(normalized_payload) != source['content']['normalized_sha256']:
            raise IncidentKnowledgeValidationError(f"{source['id']}: normalized SHA-256 mismatch")
        try:
            source_text[source['id']] = normalized_payload.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise IncidentKnowledgeValidationError(f"{source['id']}: normalized text is not UTF-8") from exc
        duplicate = source['dedup']['exact_duplicate_of']
        if duplicate is not None and duplicate not in source_documents:
            raise IncidentKnowledgeValidationError(f"{source['id']}: exact duplicate source is missing")
        if duplicate is not None:
            original = source_documents[duplicate]
            for field in ('raw_sha256', 'normalized_sha256'):
                if source['content'][field] != original['content'][field]:
                    raise IncidentKnowledgeValidationError(f"{source['id']}: exact duplicate {field} does not match")
    source_dedup_keys = {source_id: independent_document_key(source_id, source_documents) for source_id in source_documents}
    judgments = {item['id']: item for item in by_contract['JevJudgment']}
    for judgment in judgments.values():
        subject_key = f"{judgment['subject']['entity_type']}:{judgment['subject']['entity_id']}"
        if subject_key not in by_kind_and_id:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: subject does not exist: {subject_key}")
        subject_revision = judgment['subject']['revision_id']
        if subject_revision is not None and by_kind_and_id[subject_key].get('revision_id') != subject_revision:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: subject revision does not match the artifact")
        candidates = judgment['question']['candidates']
        probabilities = judgment['result']['probabilities']
        if set(probabilities) != set(candidates):
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: probability keys must equal question candidates")
        if judgment['result']['choice'] not in candidates:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: result choice is not a question candidate")
        if abs(sum(probabilities.values()) - 1.0) > 1e-06:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: probabilities must sum to 1")
        expected_input_hash = sha256_bytes(canonical_json_bytes(jev_input_payload(judgment)))
        if judgment['input_sha256'] != expected_input_hash:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: input SHA-256 does not match the bounded question")
        expected_decision = jev_policy_decision(judgment)
        if judgment['policy']['decision'] != expected_decision:
            raise IncidentKnowledgeValidationError(f"{judgment['id']}: policy decision must be {expected_decision}")
    evidence = {item['id']: item for item in by_contract['EvidenceSpan']}
    for span in evidence.values():
        source_id = span['source_document_id']
        if source_id not in source_documents:
            raise IncidentKnowledgeValidationError(f"{span['id']}: source document does not exist")
        start = span['locator']['start_char']
        end = span['locator']['end_char']
        text = source_text[source_id]
        if not start < end <= len(text):
            raise IncidentKnowledgeValidationError(f"{span['id']}: evidence offsets are outside normalized text")
        actual = sha256_bytes(text[start:end].encode('utf-8'))
        if span['content_hash'] != actual:
            raise IncidentKnowledgeValidationError(f"{span['id']}: evidence content hash mismatch")
        extraction = span['extraction']
        if extraction['extractor'] == 'llm' and (extraction['model_provider'] is None or extraction['model'] is None):
            raise IncidentKnowledgeValidationError(f"{span['id']}: LLM extraction requires provider and model")
        verification = span['verification']
        if verification['status'] != 'CANDIDATE' and span['extracted_claim'] is None:
            raise IncidentKnowledgeValidationError(f"{span['id']}: reviewed evidence requires an extracted claim")
        if verification['status'] == 'ACCEPTED':
            judgment_id = verification['jev_judgment_id']
            if judgment_id not in judgments:
                raise IncidentKnowledgeValidationError(f"{span['id']}: accepted evidence requires a Jev judgment")
            if not judgment_accepts(judgments[judgment_id], purpose='evidence_support', entity_type='evidence_span', entity_id=span['id']):
                raise IncidentKnowledgeValidationError(f"{span['id']}: evidence Jev judgment is not an ACCEPT for this span")
    incidents = {item['id']: item for item in by_contract['IncidentOccurrence']}
    for incident in incidents.values():
        require_refs(incident['id'], incident['source_document_ids'], set(source_documents), 'source document')
        require_refs(incident['id'], incident['evidence_ids'], set(evidence), 'evidence')
        for evidence_id in incident['evidence_ids']:
            if evidence[evidence_id]['source_document_id'] not in incident['source_document_ids']:
                raise IncidentKnowledgeValidationError(f"{incident['id']}: evidence comes from an unlisted source document")
        start = parse_datetime(incident['time']['started_at'])
        end = parse_datetime(incident['time']['ended_at'])
        if start and end and (end < start):
            raise IncidentKnowledgeValidationError(f"{incident['id']}: ended_at precedes started_at")
        verification = incident['identity_verification']
        require_refs(incident['id'], verification['jev_judgment_ids'], set(judgments), 'Jev judgment')
        if verification['method'] == 'JEV' and (not verification['jev_judgment_ids']):
            raise IncidentKnowledgeValidationError(f"{incident['id']}: JEV identity verification requires a judgment")
        if verification['method'] == 'JEV' and (not any((judgment_accepts(judgments[judgment_id], purpose='same_incident', entity_type='incident_occurrence', entity_id=incident['id']) for judgment_id in verification['jev_judgment_ids']))):
            raise IncidentKnowledgeValidationError(f"{incident['id']}: JEV identity verification lacks an ACCEPT for this incident")
        if incident['lifecycle_status'] == 'CANONICAL' and verification['status'] != 'ACCEPTED':
            raise IncidentKnowledgeValidationError(f"{incident['id']}: canonical incident identity is not accepted")
    events = {item['id']: item for item in by_contract['FailureEvent']}
    for event in events.values():
        if event['incident_id'] not in incidents:
            raise IncidentKnowledgeValidationError(f"{event['id']}: incident does not exist")
        require_refs(event['id'], event['evidence_ids'], set(evidence), 'evidence')
        require_refs(event['id'], event['jev_judgment_ids'], set(judgments), 'Jev judgment')
        primitive = event['primitive']
        if primitive not in primitive_layers:
            raise IncidentKnowledgeValidationError(f"{event['id']}: primitive is not in the pinned taxonomy")
        expected_layer = primitive_layers[primitive]
        if expected_layer != 'any' and expected_layer != event['layer']:
            raise IncidentKnowledgeValidationError(f"{event['id']}: primitive belongs to layer {expected_layer}")
        observed = event['observation']['observed']
        status = event['observation']['status']
        if observed != (status == 'SOURCE_OBSERVED'):
            raise IncidentKnowledgeValidationError(f"{event['id']}: observed flag and observation status disagree")
        if observed and (not event['evidence_ids']):
            raise IncidentKnowledgeValidationError(f"{event['id']}: observed event requires evidence")
        if status == 'REQLOX_INFERRED' and (not event['jev_judgment_ids']):
            raise IncidentKnowledgeValidationError(f"{event['id']}: inferred event requires a Jev judgment")
        if status == 'REQLOX_INFERRED' and (not any((judgment_accepts(judgments[judgment_id], purpose={'failure_family_classification', 'primitive_classification', 'evidence_support'}, entity_type='failure_event', entity_id=event['id']) for judgment_id in event['jev_judgment_ids']))):
            raise IncidentKnowledgeValidationError(f"{event['id']}: inferred event lacks an ACCEPT judgment for this event")
    edges = {item['id']: item for item in by_contract['CausalEdge']}
    for edge in edges.values():
        if edge['incident_id'] not in incidents:
            raise IncidentKnowledgeValidationError(f"{edge['id']}: incident does not exist")
        if edge['from_event_id'] == edge['to_event_id']:
            raise IncidentKnowledgeValidationError(f"{edge['id']}: causal edge cannot reference itself")
        require_refs(edge['id'], [edge['from_event_id'], edge['to_event_id']], set(events), 'event')
        if any((events[event_id]['incident_id'] != edge['incident_id'] for event_id in [edge['from_event_id'], edge['to_event_id']])):
            raise IncidentKnowledgeValidationError(f"{edge['id']}: edge events must belong to the same incident")
        if edge['relation'] not in relation_ids:
            raise IncidentKnowledgeValidationError(f"{edge['id']}: relation is not in the pinned taxonomy")
        support = edge['support']
        if support['explicitly_stated'] == support['inferred']:
            raise IncidentKnowledgeValidationError(f"{edge['id']}: exactly one support mode must be true")
        require_refs(edge['id'], edge['evidence_ids'], set(evidence), 'evidence')
        if support['explicitly_stated'] and (not edge['evidence_ids']):
            raise IncidentKnowledgeValidationError(f"{edge['id']}: explicitly stated relation requires evidence")
        if support['inferred']:
            judgment_id = edge['jev_judgment_id']
            if judgment_id not in judgments:
                raise IncidentKnowledgeValidationError(f"{edge['id']}: inferred relation requires a Jev judgment")
            if not judgment_accepts(judgments[judgment_id], purpose='causal_edge_supported', entity_type='causal_edge', entity_id=edge['id']):
                raise IncidentKnowledgeValidationError(f"{edge['id']}: inferred relation lacks an ACCEPT for this edge")
    patterns = {item['id']: item for item in by_contract['FailurePattern']}
    for pattern in patterns.values():
        graph = pattern['causal_graph']
        nodes = set(graph['nodes'])
        unknown_nodes = nodes - set(primitive_ids)
        if unknown_nodes:
            raise IncidentKnowledgeValidationError(f"{pattern['id']}: graph nodes outside taxonomy {sorted(unknown_nodes)}")
        if pattern['trigger']['primitive'] not in nodes:
            raise IncidentKnowledgeValidationError(f"{pattern['id']}: trigger is not a graph node")
        for edge in graph['edges']:
            if edge['from'] not in nodes or edge['to'] not in nodes:
                raise IncidentKnowledgeValidationError(f"{pattern['id']}: graph edge references an unknown node")
            if edge['from'] == edge['to']:
                raise IncidentKnowledgeValidationError(f"{pattern['id']}: graph self edge is not allowed")
            if edge['relation'] not in relation_ids:
                raise IncidentKnowledgeValidationError(f"{pattern['id']}: graph relation is outside taxonomy")
        expected_fingerprint = graph_fingerprint(pattern)
        if graph['fingerprint']['sha256'] != expected_fingerprint:
            raise IncidentKnowledgeValidationError(f"{pattern['id']}: graph fingerprint mismatch")
        unknown_mechanisms = set(pattern['injection']['mechanisms']) - mechanisms
        if unknown_mechanisms:
            raise IncidentKnowledgeValidationError(f"{pattern['id']}: unknown injection mechanisms {sorted(unknown_mechanisms)}")
    occurrences = {item['id']: item for item in by_contract['PatternOccurrence']}
    occurrences_by_pattern: dict[str, list[dict]] = defaultdict(list)
    seen_pattern_incidents = set()
    for occurrence in occurrences.values():
        if occurrence['pattern_id'] not in patterns:
            raise IncidentKnowledgeValidationError(f"{occurrence['id']}: failure pattern does not exist")
        if occurrence['incident_id'] not in incidents:
            raise IncidentKnowledgeValidationError(f"{occurrence['id']}: incident does not exist")
        pattern_incident = (occurrence['pattern_id'], occurrence['incident_id'])
        if pattern_incident in seen_pattern_incidents:
            raise IncidentKnowledgeValidationError(f"{occurrence['id']}: duplicate pattern occurrence for one incident")
        seen_pattern_incidents.add(pattern_incident)
        require_refs(occurrence['id'], occurrence['matched_event_ids'], set(events), 'event')
        if any((events[event_id]['incident_id'] != occurrence['incident_id'] for event_id in occurrence['matched_event_ids'])):
            raise IncidentKnowledgeValidationError(f"{occurrence['id']}: matched events belong to another incident")
        judgment_id = occurrence['jev_judgment_id']
        if judgment_id is not None:
            if judgment_id not in judgments:
                raise IncidentKnowledgeValidationError(f"{occurrence['id']}: Jev judgment does not exist")
            if judgments[judgment_id]['purpose'] != 'same_failure_pattern':
                raise IncidentKnowledgeValidationError(f"{occurrence['id']}: Jev judgment purpose is not same_failure_pattern")
            if not judgment_accepts(judgments[judgment_id], purpose='same_failure_pattern', entity_type='pattern_occurrence', entity_id=occurrence['id']):
                raise IncidentKnowledgeValidationError(f"{occurrence['id']}: match judgment is not an ACCEPT for this occurrence")
        occurrences_by_pattern[occurrence['pattern_id']].append(occurrence)
    statistics = {item['id']: item for item in by_contract['PatternStatistics']}
    stats_by_pattern = {item['pattern_id']: item for item in statistics.values()}
    if len(stats_by_pattern) != len(statistics):
        raise IncidentKnowledgeValidationError('multiple PatternStatistics rows for one pattern')
    for pattern_id, pattern in patterns.items():
        stats_id = pattern['evidence_summary']['pattern_statistics_id']
        if stats_id not in statistics:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: PatternStatistics does not exist')
        stats = statistics[stats_id]
        if stats['pattern_id'] != pattern_id:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: PatternStatistics points to another pattern')
        matched = occurrences_by_pattern.get(pattern_id, [])
        incident_rows = [incidents[item['incident_id']] for item in matched]
        incident_ids = {item['id'] for item in incident_rows}
        source_ids = {source_id for item in incident_rows for source_id in item['source_document_ids']}
        independent_source_keys = {source_dedup_keys[source_id] for source_id in source_ids}
        organizations = {item['organization'] for item in incident_rows}
        environments = {item['environment']['deployment_context'] for item in incident_rows}
        expected_counts = {'raw_document_count': len(source_ids), 'unique_incident_count': len(incident_ids), 'independent_organization_count': len(organizations), 'independent_source_count': len(independent_source_keys), 'environment_count': len(environments)}
        for field, expected in expected_counts.items():
            if stats[field] != expected:
                raise IncidentKnowledgeValidationError(f'{stats_id}: {field} must be {expected}')
        expected_environments = dict(sorted(Counter((item['environment']['deployment_context'] for item in incident_rows)).items()))
        if stats['occurrence_by_environment'] != expected_environments:
            raise IncidentKnowledgeValidationError(f'{stats_id}: occurrence_by_environment does not match incidents')
        observed_times = [parse_datetime(item['time']['started_at']) for item in incident_rows if item['time']['started_at'] is not None]
        expected_years = dict(sorted(Counter((str(value.year) for value in observed_times)).items()))
        if stats['occurrence_by_year'] != expected_years:
            raise IncidentKnowledgeValidationError(f'{stats_id}: occurrence_by_year does not match known incident start times')
        expected_first = min(observed_times) if observed_times else None
        expected_last = max(observed_times) if observed_times else None
        if parse_datetime(stats['first_seen_at']) != expected_first:
            raise IncidentKnowledgeValidationError(f'{stats_id}: first_seen_at does not match known incident start times')
        if parse_datetime(stats['last_seen_at']) != expected_last:
            raise IncidentKnowledgeValidationError(f'{stats_id}: last_seen_at does not match known incident start times')
        summary = pattern['evidence_summary']
        if summary['incident_count'] != stats['unique_incident_count']:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: incident summary count does not match statistics')
        if summary['organization_count'] != stats['independent_organization_count']:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: organization summary count does not match statistics')
        if summary['source_document_count'] != stats['raw_document_count']:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: document summary count does not match statistics')
        if pattern['frequency_signal']['observed_incidents'] != stats['unique_incident_count']:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: frequency incident count does not match statistics')
        if pattern['frequency_signal']['organizations'] != stats['independent_organization_count']:
            raise IncidentKnowledgeValidationError(f'{pattern_id}: frequency organization count does not match statistics')
    embeddings = by_contract['KnowledgeEmbedding']
    for embedding in embeddings:
        if embedding['dimensions'] != len(embedding['vector']):
            raise IncidentKnowledgeValidationError(f"{embedding['id']}: vector length does not match dimensions")
        if embedding['input_sha256'] != sha256_bytes(embedding['input_text'].encode('utf-8')):
            raise IncidentKnowledgeValidationError(f"{embedding['id']}: input SHA-256 mismatch")
        entity_type = embedding['entity_type']
        source_entity_ids = embedding['source_entity_ids']
        expected_text = None
        if entity_type == 'failure_pattern':
            pattern = patterns.get(embedding['entity_id'])
            if pattern is None:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: failure pattern does not exist")
            if source_entity_ids != [pattern['id']]:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: failure-pattern source ids must contain only the pattern")
            expected_text = failure_pattern_embedding_text(pattern)
        elif entity_type == 'evidence':
            span = evidence.get(embedding['entity_id'])
            if span is None:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: evidence span does not exist")
            if source_entity_ids != [span['id']]:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: evidence source ids must contain only the span")
            expected_text = evidence_embedding_text(span)
        elif entity_type == 'incident':
            incident = incidents.get(embedding['entity_id'])
            if incident is None:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: incident does not exist")
            if source_entity_ids != [incident['id']]:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: incident source ids must contain only the incident")
            incident_events = [event for event in events.values() if event['incident_id'] == incident['id']]
            expected_text = incident_embedding_text(incident, incident_events)
        else:
            path = embedding['causal_path']
            require_refs(embedding['id'], source_entity_ids, set(events), 'failure event')
            nodes = path['nodes']
            edges_in_path = path['edges']
            if len(source_entity_ids) != len(nodes):
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path must identify one source event per node")
            if len(edges_in_path) != len(nodes) - 1:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path edge count must be node count minus one")
            incident_ids = {events[event_id]['incident_id'] for event_id in source_entity_ids}
            if len(incident_ids) != 1:
                raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path source events span multiple incidents")
            for event_id, node in zip(source_entity_ids, nodes):
                if events[event_id]['primitive'] != node:
                    raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path node does not match its source event")
            incident_id = next(iter(incident_ids))
            observed_edges = {(edge['from_event_id'], edge['to_event_id'], edge['relation']) for edge in edges.values() if edge['incident_id'] == incident_id}
            for index, edge in enumerate(edges_in_path):
                if edge['from'] != nodes[index] or edge['to'] != nodes[index + 1]:
                    raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path edges do not follow node order")
                edge_key = (source_entity_ids[index], source_entity_ids[index + 1], edge['relation'])
                if edge_key not in observed_edges:
                    raise IncidentKnowledgeValidationError(f"{embedding['id']}: causal path edge is not grounded in a CausalEdge")
            expected_text = causal_path_embedding_text(path)
        if embedding['input_text'] != expected_text:
            raise IncidentKnowledgeValidationError(f"{embedding['id']}: embedding text is not deterministic")
    scenarios = by_contract['FaultInjectionCandidate']
    for scenario in scenarios:
        pattern = patterns.get(scenario['pattern_id'])
        if pattern is None:
            raise IncidentKnowledgeValidationError(f"{scenario['id']}: failure pattern does not exist")
        require_refs(scenario['id'], scenario['pattern_occurrence_ids'], set(occurrences), 'pattern occurrence')
        if any((occurrences[item]['pattern_id'] != pattern['id'] for item in scenario['pattern_occurrence_ids'])):
            raise IncidentKnowledgeValidationError(f"{scenario['id']}: occurrence belongs to another pattern")
        judgment = judgments.get(scenario['applicability_judgment_id'])
        if judgment is None or judgment['purpose'] != 'architecture_applicable':
            raise IncidentKnowledgeValidationError(f"{scenario['id']}: architecture applicability judgment is missing")
        if not judgment_accepts(judgment, purpose='architecture_applicable', entity_type='failure_pattern', entity_id=pattern['id']):
            raise IncidentKnowledgeValidationError(f"{scenario['id']}: applicability judgment is not an ACCEPT for this pattern")
        if scenario['fault']['mechanism'] not in pattern['injection']['mechanisms']:
            raise IncidentKnowledgeValidationError(f"{scenario['id']}: mechanism is not allowed by the pattern")
    return {'status': 'VALID', 'bundle_id': bundle['id'], 'taxonomy_version': taxonomy['taxonomy_version'], 'artifacts': len(artifacts), 'counts': {key: len(value) for key, value in sorted(by_contract.items())}, 'graph_fingerprints': {pattern_id: pattern['causal_graph']['fingerprint']['sha256'] for pattern_id, pattern in sorted(patterns.items())}}
