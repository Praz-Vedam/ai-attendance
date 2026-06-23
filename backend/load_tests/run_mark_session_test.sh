#!/usr/bin/env bash
# Mark-attendance load test — N requests paced across a time window.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/venv/bin/activate"
fi

pip install -q -r "$ROOT/load_tests/requirements.txt"

export LOCUST_USERS="${LOCUST_USERS:-300}"
export MARK_USERS="${MARK_USERS:-100}"
export POLL_USERS="${POLL_USERS:-$((LOCUST_USERS - MARK_USERS))}"
export MARK_WINDOW_SECONDS="${MARK_WINDOW_SECONDS:-15}"
export MARK_DISTRIBUTION="${MARK_DISTRIBUTION:-burst}"
export MARK_BURST_SECONDS="${MARK_BURST_SECONDS:-3}"
export MARK_RUN_TIME="${MARK_RUN_TIME:-2m}"
export LOCUST_RUN_TIME="${LOCUST_RUN_TIME:-$MARK_RUN_TIME}"
if [[ -z "${MARK_SPAWN_RATE:-}" ]]; then
  MARK_SPAWN_RATE="${LOCUST_USERS}"
fi
export MARK_SPAWN_RATE
REPORT_HTML="${LOAD_TEST_REPORT_HTML:-$ROOT/load_tests/mark_report.html}"
SUMMARY_HTML="${LOAD_TEST_SUMMARY_HTML:-$ROOT/load_tests/mark_load_test_report.html}"
CSV_PREFIX="${LOAD_TEST_CSV_PREFIX:-$ROOT/load_tests/mark_session}"
export LOAD_TEST_REPORT_TITLE="${LOAD_TEST_REPORT_TITLE:-Mark Session Load Test}"

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
echo "  Total users:  ${LOCUST_USERS} (${POLL_USERS} polling + ${MARK_USERS} marking)"
echo "  Mark window:  ${MARK_USERS} marks within ${MARK_WINDOW_SECONDS}s (${MARK_DISTRIBUTION})"
echo "  Spawn rate:   ${MARK_SPAWN_RATE}/s"
echo "  Run time:     ${LOCUST_RUN_TIME}"
echo "  Session:    CLASS_SESSION_ID=${CLASS_SESSION_ID:-unset}"
echo "  Target:     ${LOCUST_HOST}"
echo "  Report:     ${REPORT_HTML}"
echo "  Summary:    ${SUMMARY_HTML}"
echo ""

LOCUST_ARGS=(
  -f "$ROOT/load_tests/mark_session_locustfile.py"
  --host="$LOCUST_HOST"
  --headless
  -u "$LOCUST_USERS"
  -r "$MARK_SPAWN_RATE"
  --run-time "$LOCUST_RUN_TIME"
  --html "$REPORT_HTML"
  --csv "$CSV_PREFIX"
)

# Allow extra locust flags via "$@"
if [[ $# -gt 0 ]]; then
  LOCUST_ARGS+=("$@")
fi

LOCUST_EXIT=0
locust "${LOCUST_ARGS[@]}" || LOCUST_EXIT=$?

export LOAD_TEST_REPORT_HTML="$REPORT_HTML"
export LOAD_TEST_SUMMARY_HTML="$SUMMARY_HTML"
export LOAD_TEST_CSV_PREFIX="$CSV_PREFIX"
python "$ROOT/load_tests/generate_mark_summary.py" || true

if [[ "${ENABLE_POST_REVIEW:-0}" == "1" && "$LOCUST_EXIT" -eq 0 ]]; then
  echo ""
  echo "=== Post-test: submit + deferred spoof/location review ==="
  python "$ROOT/load_tests/post_deferred_review.py" || LOCUST_EXIT=$?
fi

echo ""
if [[ -f "$SUMMARY_HTML" ]]; then
  echo "=== HTML report (primary) ==="
  echo "  $SUMMARY_HTML"
  echo "  Open: file://$SUMMARY_HTML"
fi
if [[ -f "$REPORT_HTML" ]]; then
  echo ""
  echo "Locust native report: $REPORT_HTML"
  echo "Open: file://$REPORT_HTML"
fi

exit "$LOCUST_EXIT"
