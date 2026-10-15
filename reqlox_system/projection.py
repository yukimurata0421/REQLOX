"""Existing deterministic projection for the supported evidence-lineage graph."""
import json
import hashlib
from reqlox_knowledge.reference import require
TARGET_ID = "target_stream_cra"
GRAPH_PATH = "harness/scenarios/cra_evidence_lineage_v1.json"
POLICY_PATH = "policy/fast_recovery_policy_v2.json"
def canonical_json_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def sha256_bytes(value):return hashlib.sha256(value).hexdigest()
def stable_id(prefix,*parts):return prefix+sha256_bytes("\0".join(parts).encode())[:20]
def project(graph,policy,source_manifest,evidence):
    require(source_manifest["target_id"]==TARGET_ID,"SYSTEM_UNSUPPORTED_PROJECT_BINDING")
    created_at=source_manifest["created_at"];revision_id=source_manifest["revision_id"];source_manifest_id=source_manifest["id"]
    system_ir_id=stable_id("sir_",TARGET_ID)
    plane_ir_ids={plane:stable_id("spir_",TARGET_ID,plane)for plane in ("SUT","OBSERVATION","ORACLE","CONTROL")}
    environment_ir_id=stable_id("eir_",TARGET_ID);architecture_ir_id=stable_id("dsair_",TARGET_ID)
    evidence_by_pointer={(e["source_file"]["path"],e["locator"]["value"]):e["id"]for e in evidence if e["locator"]["kind"]=="JSON_POINTER"}
    counts={k:len(graph[k])for k in ("hosts","layers","nodes","edges","restart_domains","failure_modes")}
    graph_evidence = lambda pointer: [evidence_by_pointer[(GRAPH_PATH, pointer)]]
    policy_evidence = lambda pointer: [evidence_by_pointer[(POLICY_PATH, pointer)]]
    hosts = [
        {
            "id": item["id"],
            "expected_identity": item["expected_host_id"],
            "role": item["role"],
            "authority": item["authority"],
            "evidence_ids": graph_evidence("/hosts"),
        }
        for item in graph["hosts"]
    ]
    layers = [
        {**item, "evidence_ids": graph_evidence("/layers")}
        for item in graph["layers"]
    ]
    components = [
        {
            "id": item["id"],
            "name": item["label"],
            "component_type": item["kind"],
            "layer": item["layer"],
            "host": item["host"],
            "authority": item["authority"],
            "failure_domain": item["failure_domain"],
            "source_refs": item["source_refs"],
            "implementation_refs": item["implementation_refs"],
            "unit_templates": item["unit_templates"],
            "identity_attributes": item["identity_fields"],
            "freshness_attributes": item["freshness_fields"],
            "current_value_policy": item["current_value_policy"],
            "evidence_ids": graph_evidence("/nodes"),
        }
        for item in graph["nodes"]
    ]
    dependencies = [
        {
            "id": item["id"],
            "from_component_id": item["from"],
            "to_component_id": item["to"],
            "relationship": item["relationship"],
            "mode": item["mode"],
            "evidence_description": item["evidence"],
            "required_bindings": item["required_bindings"],
            "assertion": item["assertion"],
            "failure_policy": item["failure_policy"],
            "source_refs": item["contract_refs"],
            "evidence_ids": graph_evidence("/edges"),
        }
        for item in graph["edges"]
    ]
    restart_domains = [
        {
            "id": item["id"],
            "label": item["label"],
            "component_ids": item["scope_nodes"],
            "event": item["event"],
            "identity_changes": item["identity_changes"],
            "must_preserve": item["must_preserve"],
            "observed_by_dependency_ids": item["observed_by_edges"],
            "observation_sources": item["observation_sources"],
            "normal_meaning": item["normal_meaning"],
            "qualification_rule": item["soak_rule"],
            "new_epoch_when": item["new_epoch_when"],
            "evidence_ids": graph_evidence("/restart_domains"),
        }
        for item in graph["restart_domains"]
    ]
    failure_surfaces = [
        {
            "id": item["id"],
            "name": item["label"],
            "trigger": item["trigger"],
            "affected_component_ids": item["affected_nodes"],
            "dependency_ids": item["evidence_edges"],
            "restart_domain_ids": item["restart_domains"],
            "source_refs": item["source_refs"],
            "detector_refs": item["detector_refs"],
            "oracle_refs": item["oracle_refs"],
            "sequence_test_refs": item["sequence_test_refs"],
            "evidence_absence_domain": item["evidence_absence_domain"],
            "formal_rule": item["formal_rule"],
            "required_qualification": item["required_qualification"],
            "evidence_ids": graph_evidence("/failure_modes"),
        }
        for item in graph["failure_modes"]
    ]
    all_ids = {
        "hosts": sorted(item["id"] for item in hosts),
        "layers": sorted(item["id"] for item in layers),
        "components": sorted(item["id"] for item in components),
        "dependencies": sorted(item["id"] for item in dependencies),
        "restart_domains": sorted(item["id"] for item in restart_domains),
        "failure_surfaces": sorted(item["id"] for item in failure_surfaces),
    }
    system_ir = {
        "$schema": "../../schemas/system-ir.v0.1.schema.json",
        "id": system_ir_id,
        "contract_type": "SystemIR",
        "contract_version": "0.1.0",
        "revision_id": revision_id,
        "created_at": created_at,
        "target": {
            "id": TARGET_ID,
            "name": "Stream Central Restart Authority",
            "kind": "DISTRIBUTED_CONTROL_PLANE",
            "source_manifest_id": source_manifest_id,
        },
        "review": {
            "status": "SOURCE_DERIVED_REVIEW_REQUIRED",
            "human_reviewed": False,
            "jev_required": False,
            "jev_judgment_ids": [],
        },
        "architecture": {
            "hosts": hosts,
            "layers": layers,
            "components": components,
            "dependencies": dependencies,
            "restart_domains": restart_domains,
        },
        "failure_surfaces": failure_surfaces,
        "target_specific_context": {
            "derived_ir_refs": {
                "plane_ir_ids": plane_ir_ids,
                "environment_ir_id": environment_ir_id,
                "distributed_architecture_ir_id": architecture_ir_id,
            },
            "source_graph": {
                "schema": graph["schema"],
                "status": graph["status"],
                "purpose": graph["purpose"],
                "boundaries": graph["boundaries"],
                "owner_verification": graph["owner_verification"],
                "live_overlay_contract": graph["live_overlay_contract"],
            },
            "policy_snapshot": policy,
        },
        "runtime_state": {
            "status": "NOT_OBSERVED_SOURCE_ONLY",
            "live_evidence_included": False,
            "running_release_verified": False,
            "environment_ir_required": True,
        },
        "coverage": {
            "source_counts": counts,
            "projected_counts": counts,
            "id_set_sha256": sha256_bytes(canonical_json_bytes(all_ids)),
            "complete_source_projection": True,
        },
        "execution_boundary": {
            "state": "NON_EXECUTABLE_ANALYSIS_ONLY",
            "mutation_authority": "NONE",
            "production_fault_injection_allowed": False,
            "experiment_generation_authorized": False,
        },
        "evidence_ids": [item["id"] for item in evidence],
        "limitations": [
            "SOURCE_DERIVED_CANDIDATE_NOT_HUMAN_ACCEPTED",
            "LIVE_RELEASE_CONFIGURATION_AND_HEALTH_NOT_OBSERVED",
            "EXTERNAL_STREAM_V3_CODE_AND_ENVIRONMENT_NOT_INCLUDED",
            "NO_APPLICABILITY_DECISION_OR_EXPERIMENT_AUTHORITY",
        ],
    }

    return system_ir
