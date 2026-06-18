#!/usr/bin/env bash
# Run ALL load tests; each writes HTML reports + index.html.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f "$ROOT/venv/bin/activate" ]] && source "$ROOT/venv/bin/activate"

POLLING_REPORT="${LOAD_TEST_POLLING_REPORT:-$ROOT/load_tests/report.html}"
MARK_REPORT="${LOAD_TEST_MARK_REPORT:-$ROOT/load_tests/mark_report.html}"
THROUGHPUT_REPORT="${LOAD_TEST_THROUGHPUT_REPORT:-$ROOT/load_tests/throughput_report.html}"

echo ""
echo "=========================================="
echo "  AI Attendance — full load test suite"
echo "=========================================="
echo ""

echo ">>> [1/3] Polling test → $POLLING_REPORT"
LOAD_TEST_REPORT_HTML="$POLLING_REPORT" "$ROOT/load_tests/run.sh"

echo ""
echo ">>> [2/3] Mark burst test → $MARK_REPORT"
LOAD_TEST_REPORT_HTML="$MARK_REPORT" "$ROOT/load_tests/run_mark_session_test.sh"

echo ""
echo ">>> [3/3] Throughput / stress test → $THROUGHPUT_REPORT"
LOAD_TEST_REPORT_HTML="$THROUGHPUT_REPORT" "$ROOT/load_tests/run_throughput_test.sh"

python "$ROOT/load_tests/generate_index.py"

echo ""
echo "=========================================="
echo "  All HTML reports"
echo "=========================================="
echo "  Index:      file://$ROOT/load_tests/index.html"
echo "  Polling:    file://$POLLING_REPORT"
echo "  Mark:       file://$MARK_REPORT"
echo "  Throughput: file://$ROOT/load_tests/throughput_summary.html"
echo "=========================================="
echo ""
