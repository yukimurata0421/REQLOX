#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} == --help ]]; then
  cat <<'USAGE'
Create an environment: python3 -m venv .venv
Install: .venv/bin/python -m pip install .
Inspect: .venv/bin/python -m reqlox inventory --root examples/repository
Probe:   .venv/bin/python -m reqlox check
UI:      .venv/bin/python -m reqlox demo
Repair:  .venv/bin/python -m reqlox qualify --root examples/repository --configuration examples/owned-requirements.json
Audit:   .venv/bin/python -m reqlox audit --output <printed-output-directory>
Tests:   .venv/bin/python scripts/check.py

The UI binds to localhost. Linux, bubblewrap, and a Python executable under /usr
are required for isolated experiments. Results go to ~/.local/state/reqlox;
REQLOX_STATE_DIR selects another absolute, user-owned directory with mode 0700.
No provider credentials are needed for baseline and recorded-model modes.
Live calls require the optional cloud dependencies, a private scope directory,
an explicit deadline/call/reservation bound, and consent to send the input.
Cloud reservations are configured bounds, not a verified invoice or cost cap.
Use --model-scope <private-directory> with the UI; the example scope is disabled.
Native integration tests are opt-in: REQLOX_RUN_NATIVE_TESTS=1.
USAGE
  exit 0
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
reqlox_python="${REQLOX_PYTHON:-python3}"
if [[ -z ${REQLOX_PYTHON:-} && -x .venv/bin/python ]]; then
  reqlox_python=.venv/bin/python
fi
"$reqlox_python" -m reqlox check
"$reqlox_python" -m reqlox demo "$@"
