"""
Fixed-concurrency throughput test — flat N users (default 100), no step ramp.

Run: ./load_tests/run_throughput_test.sh
Reports: throughput_report.html, throughput_summary.html
"""

from __future__ import annotations

import json
import os

from locust import events
from locust.runners import MasterRunner, WorkerRunner

from locust_users import ENABLE_MARK_TASK, HealthUser, StudentPoller, TeacherPoller  # noqa: F401

if ENABLE_MARK_TASK:
    from locust_users import StudentMarker  # noqa: F401

LOAD_TESTS_DIR = __import__("pathlib").Path(__file__).resolve().parent
BREAKPOINT_FILE = LOAD_TESTS_DIR / "throughput_breakpoint.json"

FAIL_PCT = float(os.getenv("THROUGHPUT_FAIL_PCT", "10"))
P95_MS = float(os.getenv("THROUGHPUT_P95_MS", "5000"))
CONCURRENT_USERS = int(os.getenv("THROUGHPUT_USERS", os.getenv("MARK_USERS", "100")))


@events.test_start.add_listener
def _on_test_start(environment=None, **kwargs) -> None:
    if isinstance(environment.runner, (MasterRunner, WorkerRunner)):
        return
    if BREAKPOINT_FILE.is_file():
        BREAKPOINT_FILE.unlink()
    print(f"\n[throughput] {CONCURRENT_USERS} concurrent users (flat, no ramp)\n")


@events.test_stop.add_listener
def _on_test_stop(environment=None, **kwargs) -> None:
    if environment is None or isinstance(environment.runner, WorkerRunner):
        return

    total = environment.stats.total
    requests = total.num_requests or 0
    failures = total.num_failures or 0
    fail_pct = (failures / requests * 100) if requests else 0.0
    p95 = total.get_response_time_percentile(0.95) or 0
    rps = total.total_rps or 0

    degraded = fail_pct >= FAIL_PCT or p95 >= P95_MS
    breakpoint = {
        "concurrent_users": CONCURRENT_USERS,
        "total_requests": requests,
        "total_failures": failures,
        "failure_pct": round(fail_pct, 2),
        "p95_ms": round(p95, 1),
        "avg_rps": round(rps, 2),
        "fail_threshold_pct": FAIL_PCT,
        "p95_threshold_ms": P95_MS,
        "degraded": degraded,
        "host": os.getenv("LOCUST_HOST", ""),
    }
    BREAKPOINT_FILE.write_text(json.dumps(breakpoint, indent=2) + "\n")
    print(
        f"\n[throughput] done — users={CONCURRENT_USERS} "
        f"failures={fail_pct:.1f}% p95={p95:.0f}ms rps={rps:.1f} degraded={degraded}\n"
    )
