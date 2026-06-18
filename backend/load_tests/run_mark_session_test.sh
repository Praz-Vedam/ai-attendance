#!/usr/bin/env bash
# 150-concurrent POST /lms/attendance/mark burst within a 30s window.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f "$ROOT/venv/bin/activate" ]] && source "$ROOT/venv/bin/activate"
pip install -q -r "$ROOT/load_tests/requirements.txt"

export MARK_USERS="${MARK_USERS:-150}"
export MARK_SPAWN_RATE="${MARK_SPAWN_RATE:-150}"
export MARK_RUN_TIME="${MARK_RUN_TIME:-30s}"
REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/mark_report.html}"

python "$ROOT/load_tests/setup_local.py"
python "$ROOT/load_tests/prepare_mark_session.py"

if [[ -f "$ROOT/load_tests/local.env" ]]; then
  set -a && source "$ROOT/load_tests/local.env" && set +a
fi

export LOCUST_HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"

echo ""
echo "=== Mark session load test ==="
echo "  Users:   ${MARK_USERS} @ ${MARK_SPAWN_RATE}/s (burst)"
echo "  Window:  ${MARK_RUN_TIME}"
echo "  Session: CLASS_SESSION_ID=${CLASS_SESSION_ID:-unset}"
echo "  Target:  ${LOCUST_HOST}"
echo "  Report:  ${REPORT_HTML}"
echo ""

locust -f "$ROOT/load_tests/mark_session_locustfile.py" \
  --host="$LOCUST_HOST" \
  --headless \
  -u "$MARK_USERS" \
  -r "$MARK_SPAWN_RATE" \
  --run-time "$MARK_RUN_TIME" \
  --html "$REPORT_HTML" \
  "$@"

python "$ROOT/load_tests/generate_index.py"

echo ""
echo "HTML report: $REPORT_HTML"
echo "Open: file://$REPORT_HTML"
echo "All reports: file://$ROOT/load_tests/index.html"
