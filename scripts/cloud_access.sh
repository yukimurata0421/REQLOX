#!/bin/bash
# Authenticate with gcloud first, then open http://127.0.0.1:8765.
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo 'Usage: bash scripts/cloud_access.sh PROJECT ZONE INSTANCE' >&2
  exit 2
fi
exec gcloud compute start-iap-tunnel "$3" 8080 \
  --local-host-port=127.0.0.1:8765 --project="$1" --zone="$2"
