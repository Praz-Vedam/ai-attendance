#!/usr/bin/env bash
# 100-concurrent mark-attendance simulation for one class session.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/venv/bin/activate"
fi

pip install -q -r "$ROOT/load_tests/requirements.txt"

export MARK_USERS="${MARK_USERS:-100}"
export MARK_SPAWN_RATE="${MARK_SPAWN_RATE:-100}"
export MARK_RUN_TIME="${MARK_RUN_TIME:-3m}"
REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/mark_report.html}"

python "$ROOT/load_tests/setup_local.py"
python "$ROOT/load_tests/prepare_mark_session.py"

if [[ -f "$ROOT/load_tests/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/load_tests/local.env"
  set +a
fi

export LOCUST_HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"

echo ""
echo "=== Mark session load test ==="
echo "  Users:      ${MARK_USERS} (concurrent burst)"
echo "  Spawn rate: ${MARK_SPAWN_RATE}/s"
echo "  Session:    CLASS_SESSION_ID=${CLASS_SESSION_ID:-unset}"
echo "  Target:     ${LOCUST_HOST}"
echo "  Report:     ${REPORT_HTML}"
echo ""

LOCUST_ARGS=(
  -f "$ROOT/load_tests/mark_session_locustfile.py"
  --host="$LOCUST_HOST"
  --headless
  -u "$MARK_USERS"
  -r "$MARK_SPAWN_RATE"
  --run-time "$MARK_RUN_TIME"
  --html "$REPORT_HTML"
)

# Allow extra locust flags via "$@"
if [[ $# -gt 0 ]]; then
  LOCUST_ARGS+=("$@")
fi

locust "${LOCUST_ARGS[@]}"

echo ""
echo "HTML report: $REPORT_HTML"
echo "Open: file://$REPORT_HTML"
