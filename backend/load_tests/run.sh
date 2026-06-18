#!/usr/bin/env bash
# Load test — polling + mark attendance, 100 concurrent users, 2 minutes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f "$ROOT/venv/bin/activate" ]] && source "$ROOT/venv/bin/activate"
pip install -q -r "$ROOT/load_tests/requirements.txt"

export ENABLE_MARK_TASK="${ENABLE_MARK_TASK:-1}"
python "$ROOT/load_tests/setup_local.py"
python "$ROOT/load_tests/prepare_mark_session.py"

if [[ -f "$ROOT/load_tests/local.env" ]]; then
  set -a && source "$ROOT/load_tests/local.env" && set +a
fi

export LOCUST_HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"
REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/report.html}"

# Default: 100 users, 2 minutes, includes POST /lms/attendance/mark
[[ $# -eq 0 ]] && set -- --headless -u 300 -r 300 --run-time 2m

ARGS=("$@")
HAS_HEADLESS=0
HAS_HTML=0
for a in "${ARGS[@]}"; do
  [[ "$a" == "--headless" ]] && HAS_HEADLESS=1
  [[ "$a" == "--html" ]] && HAS_HTML=1
done

if [[ "$HAS_HTML" -eq 0 ]]; then
  ARGS+=(--html "$REPORT_HTML")
  if [[ "$HAS_HEADLESS" -eq 0 ]]; then
    ARGS=(--headless "${ARGS[@]}")
  fi
fi

echo ""
echo "=== Load test (polling + mark attendance) ==="
echo "  Target:   ${LOCUST_HOST}"
echo "  Users:    100 concurrent"
echo "  Duration: 2m (override with --run-time)"
echo "  Mark API: POST /lms/attendance/mark enabled"
echo "  Session:  CLASS_SESSION_ID=${CLASS_SESSION_ID:-unset}"
echo ""

locust -f "$ROOT/load_tests/locustfile.py" --host="$LOCUST_HOST" "${ARGS[@]}"

python "$ROOT/load_tests/generate_index.py"

if [[ -f "$REPORT_HTML" ]]; then
  echo ""
  echo "HTML report: $REPORT_HTML"
  echo "Open: file://$REPORT_HTML"
  echo "All reports: file://$ROOT/load_tests/index.html"
fi
