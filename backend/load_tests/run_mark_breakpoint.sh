#!/usr/bin/env bash
# Find max stable concurrent POST /lms/attendance/mark for the target VM.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f "$ROOT/venv/bin/activate" ]] && source "$ROOT/venv/bin/activate"
pip install -q -r "$ROOT/load_tests/requirements.txt"

python "$ROOT/load_tests/setup_local.py"

if [[ -f "$ROOT/load_tests/local.env" ]]; then
  set -a && source "$ROOT/load_tests/local.env" && set +a
fi

export LOCUST_HOST="${LOCUST_HOST:-http://127.0.0.1:8000}"
export BREAKPOINT_STEPS="${BREAKPOINT_STEPS:-50,100,150,200,250,300,350,400,450,500}"
export BREAKPOINT_RUN_TIME="${BREAKPOINT_RUN_TIME:-90s}"
export BREAKPOINT_COOLDOWN_SEC="${BREAKPOINT_COOLDOWN_SEC:-5}"
export BREAKPOINT_FAIL_PCT="${BREAKPOINT_FAIL_PCT:-10}"
export BREAKPOINT_P95_MS="${BREAKPOINT_P95_MS:-15000}"

echo ""
echo "=== Mark breakpoint test (POST /lms/attendance/mark) ==="
echo "  Target:   ${LOCUST_HOST}"
echo "  Steps:    ${BREAKPOINT_STEPS}"
echo "  Per step: ${BREAKPOINT_RUN_TIME} (+ ${BREAKPOINT_COOLDOWN_SEC}s cooldown)"
echo "  Degraded: fail >= ${BREAKPOINT_FAIL_PCT}% OR p95 >= ${BREAKPOINT_P95_MS}ms"
echo ""

python "$ROOT/load_tests/find_mark_breakpoint.py"
python "$ROOT/load_tests/generate_index.py"

echo ""
echo "Results:"
echo "  JSON:    file://$ROOT/load_tests/mark_breakpoint.json"
echo "  Summary: file://$ROOT/load_tests/mark_breakpoint_summary.html"
echo ""
