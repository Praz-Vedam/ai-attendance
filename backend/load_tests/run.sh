#!/usr/bin/env bash
# Run Locust against the AI attendance backend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/venv/bin/activate"
fi

pip install -q -r "$ROOT/load_tests/requirements.txt"

python "$ROOT/load_tests/setup_local.py"

if [[ -f "$ROOT/load_tests/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/load_tests/local.env"
  set +a
fi

export LOCUST_HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"
REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/report.html}"

# Default: headless 300-user run with HTML report (pass args to override, e.g. for web UI)
if [[ $# -eq 0 ]]; then
  set -- --headless -u 300 -r 30 --run-time 5m
fi

LOCUST_ARGS=("$@")
HAS_HEADLESS=0
HAS_HTML=0
for arg in "${LOCUST_ARGS[@]}"; do
  [[ "$arg" == "--headless" ]] && HAS_HEADLESS=1
  [[ "$arg" == "--html" ]] && HAS_HTML=1
done

if [[ "$HAS_HEADLESS" -eq 1 && "$HAS_HTML" -eq 0 ]]; then
  LOCUST_ARGS+=(--html "$REPORT_HTML")
fi

locust -f "$ROOT/load_tests/locustfile.py" --host="$LOCUST_HOST" "${LOCUST_ARGS[@]}"

if [[ -f "$REPORT_HTML" ]]; then
  echo ""
  echo "HTML report: $REPORT_HTML"
  echo "Open: file://$REPORT_HTML"
fi
