#!/usr/bin/env python3
"""Check a Terraform plan against an explicit project and owned resource prefix."""
import argparse
import json
from pathlib import Path


def validate(plan, project, prefix, maximum_additions=40, replace_instance_id=None):
    if plan.get("errored") is True:
        raise ValueError("Terraform planning failed")
    variables = plan["variables"]
    if variables["project_id"]["value"] != project or variables["name"]["value"] != prefix:
        raise ValueError("Plan target differs from the authorized project or prefix")
    changes = []
    replacements = 0
    allowed_types = {"google_billing_budget", "google_compute_disk", "google_compute_firewall",
        "google_compute_network", "google_compute_subnetwork", "google_project_service", "google_pubsub_topic",
        "google_secret_manager_secret", "google_secret_manager_secret_iam_member", "google_service_account",
        "google_storage_bucket", "google_storage_bucket_iam_member", "google_storage_bucket_object",
        "google_compute_instance", "google_iap_tunnel_instance_iam_member"}
    for resource in plan.get("resource_changes", []):
        actions = resource["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        kind = resource["type"]
        after = resource["change"].get("after") or {}
        before = resource["change"].get("before") or {}
        if kind not in allowed_types or resource.get("mode") != "managed":
            raise ValueError("Resource type is outside the dedicated deployment")
        if actions != ["create"]:
            scoped_replacement = replace_instance_id is not None and actions == ["delete", "create"]
            if kind == "google_compute_instance":
                scoped_replacement = scoped_replacement and str(before.get("instance_id")) == str(replace_instance_id) and before.get("name") == prefix and before.get("project") == project
            elif kind == "google_iap_tunnel_instance_iam_member":
                canonical = f"projects/{project}/iap_tunnel/zones/{variables['zone']['value']}/instances/{prefix}"
                scoped_replacement = scoped_replacement and before.get("instance") in (prefix, canonical) and before.get("project") == project and before.get("member") == after.get("member")
            else:
                scoped_replacement = False
            if not scoped_replacement:
                raise ValueError("Only the explicitly observed dedicated VM and its existing IAP grant may be replaced")
            replacements += 1
        if kind == "google_secret_manager_secret_version":
            raise ValueError("Secret values must never enter Terraform state")
        if after.get("project") not in (None, project):
            raise ValueError("Cross-project change is forbidden")
        identity = after.get("name") or after.get("account_id")
        if identity and kind not in ("google_storage_bucket", "google_storage_bucket_object") and not identity.startswith(prefix):
            raise ValueError("Resource identity is outside the owned prefix")
        if kind == "google_compute_instance":
            if after["machine_type"] not in ("e2-small", "e2-medium"):
                raise ValueError("Machine exceeds the bounded demo allocation")
            scheduling = after["scheduling"][0]
            if scheduling["instance_termination_action"] != "STOP" or scheduling["max_run_duration"][0]["seconds"] > 86400:
                raise ValueError("VM lease is missing or too long")
            if scheduling["on_host_maintenance"] != "MIGRATE" or scheduling["automatic_restart"] is not False:
                raise ValueError("Standard E2 instances require migration and this demo forbids automatic restart")
        if kind == "google_compute_firewall":
            if after.get("source_ranges") != ["35.235.240.0/20"] or after.get("direction") != "INGRESS" or after.get("allow") != [{"ports": ["8080"], "protocol": "tcp"}]:
                raise ValueError("UI ingress must be restricted to the IAP range and port")
        if kind in ("google_storage_bucket_iam_member", "google_secret_manager_secret_iam_member"):
            expected_role = "roles/storage.objectViewer" if kind.startswith("google_storage") else "roles/secretmanager.secretAccessor"
            if after.get("role") != expected_role or after.get("member") != f"serviceAccount:{prefix}-runtime@{project}.iam.gserviceaccount.com":
                raise ValueError("Runtime IAM must grant only the dedicated account read access")
        if kind == "google_iap_tunnel_instance_iam_member":
            if after.get("instance") != prefix or after.get("role") != "roles/iap.tunnelResourceAccessor" or after.get("member") not in variables["iap_members"]["value"]:
                raise ValueError("IAP access is outside the explicit member allowlist")
        if kind.endswith("iam_member") and after.get("member") in ("allUsers", "allAuthenticatedUsers"):
            raise ValueError("Anonymous access is forbidden")
        changes.append({"address": resource["address"], "action": "replace" if actions != ["create"] else "create"})
    if not 1 <= len(changes) <= maximum_additions:
        raise ValueError("Unexpected resource change count")
    return {"status": "PASS", "project": project, "prefix": prefix, "changes": changes,
            "deletes": replacements, "replaced_instance_id": replace_instance_id,
            "persistent_data_deleted": False, "secret_values_in_state": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--prefix", default="reqlox-demo")
    parser.add_argument("--replace-instance-id", help="Explicit observed ID of the disposable dedicated VM only")
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.plan_json.read_bytes()), args.project, args.prefix,
                             replace_instance_id=args.replace_instance_id), indent=2))


if __name__ == "__main__":
    main()
