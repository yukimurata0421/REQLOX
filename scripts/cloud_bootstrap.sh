#!/bin/bash
# Bootstrap the project APIs required to plan IAM and service enablement with an
# explicit quota project. All workload APIs and resources remain in Terraform.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo 'Usage: bash scripts/cloud_bootstrap.sh PROJECT' >&2
  exit 2
fi
exec gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com \
  --project="$1" --billing-project="$1" --quiet
