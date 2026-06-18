#!/usr/bin/env bash
# Flat throughput test — 100 concurrent users, no step ramp.
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

THROUGHPUT_USERS="${THROUGHPUT_USERS:-100}"
THROUGHPUT_SPAWN_RATE="${THROUGHPUT_SPAWN_RATE:-100}"
THROUGHPUT_RUN_TIME="${THROUGHPUT_RUN_TIME:-2m}"
export THROUGHPUT_USERS THROUGHPUT_FAIL_PCT="${THROUGHPUT_FAIL_PCT:-10}"
export THROUGHPUT_P95_MS="${THROUGHPUT_P95_MS:-5000}"

REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/throughput_report.html}"
CSV_PREFIX="$ROOT/load_tests/throughput_data"

rm -f "$ROOT/load_tests/throughput_breakpoint.json" "$ROOT/load_tests/throughput_data"*.csv

echo ""
echo "=== Throughput test (flat concurrency) ==="
echo "  Target:     ${LOCUST_HOST}"
echo "  Users:      ${THROUGHPUT_USERS} concurrent (spawn ${THROUGHPUT_SPAWN_RATE}/s)"
echo "  Duration:   ${THROUGHPUT_RUN_TIME}"
echo "  Degraded:   fail >= ${THROUGHPUT_FAIL_PCT}% OR p95 >= ${THROUGHPUT_P95_MS}ms"
echo "  Mark API:   POST /lms/attendance/mark enabled"
echo "  Reports:    throughput_report.html + throughput_summary.html"
echo ""

locust -f "$ROOT/load_tests/throughput_locustfile.py" \
  --host="$LOCUST_HOST" \
  --headless \
  -u "$THROUGHPUT_USERS" \
  -r "$THROUGHPUT_SPAWN_RATE" \
  --run-time "$THROUGHPUT_RUN_TIME" \
  --html "$REPORT_HTML" \
  --csv "$CSV_PREFIX" \
  "$@"

python "$ROOT/load_tests/generate_throughput_summary.py"
python "$ROOT/load_tests/generate_index.py"

echo ""
echo "HTML reports:"
echo "  Summary:  file://$ROOT/load_tests/throughput_summary.html"
echo "  Locust:   file://$REPORT_HTML"
echo "  Index:    file://$ROOT/load_tests/index.html"
echo ""
