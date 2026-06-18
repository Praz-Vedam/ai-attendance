#!/usr/bin/env python3
"""Stepped POST /lms/attendance/mark load to find max stable concurrency."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = LOAD_TESTS_DIR.parent
sys.path.insert(0, str(LOAD_TESTS_DIR))

from env_util import (  # noqa: E402
    LOCAL_ENV,
    SECRETS_ENV,
    ai_attendance_base,
    load_dotenv,
    load_secrets_env,
    parse_env_file,
    resolve_student_tokens,
    resolve_teacher_token,
    start_attendance_session,
    write_token_lines,
)

STUDENT_MARK_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens_mark.txt"
LOCUSTFILE = LOAD_TESTS_DIR / "mark_session_locustfile.py"
RESULTS_JSON = LOAD_TESTS_DIR / "mark_breakpoint.json"
SUMMARY_HTML = LOAD_TESTS_DIR / "mark_breakpoint_summary.html"

DEFAULT_STEPS = [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]
MARK_ENDPOINT = "POST /lms/attendance/mark"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _parse_steps() -> list[int]:
    raw = os.getenv("BREAKPOINT_STEPS", "").strip()
    if not raw:
        return DEFAULT_STEPS
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _read_stats_row(csv_path: Path) -> dict | None:
    if not csv_path.is_file():
        return None
    with csv_path.open() as handle:
        for row in csv.DictReader(handle):
            if row.get("Name") == MARK_ENDPOINT:
                return row
            if row.get("Type") == "POST" and "attendance/mark" in (row.get("Name") or ""):
                return row
    return None


def _float(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _int(value: str | None) -> int:
    return int(_float(value))


def _is_degraded(stats: dict, *, fail_pct_limit: float, p95_limit_ms: float) -> tuple[bool, str]:
    requests = _int(stats.get("Request Count"))
    failures = _int(stats.get("Failure Count"))
    fail_pct = (failures / requests * 100) if requests else 100.0
    p95 = _float(stats.get("95%"))

    if requests == 0:
        return True, "no requests completed"
    if fail_pct >= fail_pct_limit:
        return True, f"failure rate {fail_pct:.1f}% >= {fail_pct_limit}%"
    if p95 >= p95_limit_ms:
        return True, f"p95 {p95:.0f}ms >= {p95_limit_ms:.0f}ms"
    return False, ""


def _prepare_tokens(users: int, class_session_id: int) -> None:
    tokens = resolve_student_tokens(
        LOAD_TESTS_DIR / "student_tokens.txt",
        class_session_id=class_session_id,
    )
    if not tokens:
        raise RuntimeError("No valid student tokens")
    final = (tokens * ((users // len(tokens)) + 1))[:users]
    write_token_lines(STUDENT_MARK_TOKENS_FILE, final)


def _run_locust_step(users: int, host: str, run_time: str, csv_prefix: Path) -> int:
    for suffix in ("", "_stats", "_stats_history", "_failures", "_exceptions"):
        path = Path(f"{csv_prefix}{suffix}.csv")
        if path.is_file():
            path.unlink()

    env = os.environ.copy()
    env["MARK_USERS"] = str(users)
    env["CLASS_SESSION_ID"] = env.get("CLASS_SESSION_ID", "0")

    cmd = [
        "locust",
        "-f",
        str(LOCUSTFILE),
        f"--host={host}",
        "--headless",
        "-u",
        str(users),
        "-r",
        str(users),
        "--run-time",
        run_time,
        "--csv",
        str(csv_prefix),
        "--only-summary",
    ]
    return subprocess.run(cmd, env=env, cwd=str(BACKEND_DIR)).returncode


def _write_summary(payload: dict) -> None:
    max_stable = payload.get("max_stable_concurrent_marks", 0)
    host = payload.get("host", "")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = ""
    for step in payload.get("steps", []):
        degraded = step.get("degraded", False)
        badge = "bad" if degraded else "ok"
        rows += f"""
        <tr class="{badge}">
          <td>{step.get('users')}</td>
          <td>{step.get('requests', '—')}</td>
          <td>{step.get('failures', '—')}</td>
          <td>{step.get('failure_pct', '—')}%</td>
          <td>{step.get('avg_ms', '—')}</td>
          <td>{step.get('p95_ms', '—')}</td>
          <td>{step.get('rps', '—')}</td>
          <td>{'yes' if degraded else 'no'}</td>
          <td>{step.get('reason', '')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Mark Breakpoint Summary</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .sub {{ color: #666; margin-bottom: 1.5rem; }}
    .hero {{ font-size: 2rem; font-weight: 700; margin: 1rem 0; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 1100px; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.65rem; text-align: left; font-size: 0.9rem; }}
    th {{ background: #f5f5f5; }}
    tr.ok td {{ background: #f0fdf4; }}
    tr.bad td {{ background: #fef2f2; }}
  </style>
</head>
<body>
  <h1>POST /mark breakpoint</h1>
  <p class="sub">Generated {generated} — target <strong>{host}</strong></p>
  <p class="hero">Max stable concurrent marks: <strong>{max_stable}</strong></p>
  <p>Degraded when failure rate ≥ {payload.get('fail_pct_limit')}% or p95 ≥ {payload.get('p95_limit_ms')}ms.</p>
  <table>
    <thead>
      <tr>
        <th>Users</th><th>Requests</th><th>Failures</th><th>Fail %</th>
        <th>Avg ms</th><th>p95 ms</th><th>RPS</th><th>Degraded</th><th>Reason</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
"""
    SUMMARY_HTML.write_text(html)


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_secrets_env(SECRETS_ENV)
    load_dotenv(LOCAL_ENV)

    existing = parse_env_file(LOCAL_ENV)
    host = os.getenv("LOCUST_HOST", existing.get("LOCUST_HOST", ai_attendance_base())).rstrip("/")
    class_session_id = int(os.getenv("CLASS_SESSION_ID") or existing.get("CLASS_SESSION_ID") or 0)
    if class_session_id <= 0:
        print("[breakpoint] Set CLASS_SESSION_ID", file=sys.stderr)
        return 1

    teacher_token = resolve_teacher_token(existing, class_session_id=class_session_id)
    if not teacher_token:
        print("[breakpoint] No valid teacher token", file=sys.stderr)
        return 1

    steps = _parse_steps()
    run_time = os.getenv("BREAKPOINT_RUN_TIME", "90s")
    cooldown = float(os.getenv("BREAKPOINT_COOLDOWN_SEC", "5"))
    fail_pct_limit = _env_float("BREAKPOINT_FAIL_PCT", 10.0)
    p95_limit_ms = _env_float("BREAKPOINT_P95_MS", 15000.0)

    os.environ["LOCUST_HOST"] = host
    os.environ["CLASS_SESSION_ID"] = str(class_session_id)
    os.environ["STUDENT_TOKENS_FILE"] = str(STUDENT_MARK_TOKENS_FILE)

    print(f"\n[breakpoint] target={host} session={class_session_id}")
    print(f"[breakpoint] steps={steps} run_time={run_time} limits fail>={fail_pct_limit}% p95>={p95_limit_ms}ms\n")

    results: list[dict] = []
    max_stable = 0
    first_degraded: int | None = None

    for users in steps:
        print(f"[breakpoint] --- {users} concurrent POST /mark ---")
        try:
            start_attendance_session(teacher_token, class_session_id)
            _prepare_tokens(users, class_session_id)
        except Exception as exc:
            print(f"[breakpoint] setup failed at {users}: {exc}", file=sys.stderr)
            results.append({"users": users, "degraded": True, "reason": f"setup failed: {exc}"})
            first_degraded = first_degraded or users
            break

        csv_prefix = LOAD_TESTS_DIR / f"breakpoint_{users}"
        exit_code = _run_locust_step(users, host, run_time, csv_prefix)
        stats = _read_stats_row(Path(f"{csv_prefix}_stats.csv")) or {}

        requests = _int(stats.get("Request Count"))
        failures = _int(stats.get("Failure Count"))
        fail_pct = round((failures / requests * 100) if requests else 100.0, 2)
        avg_ms = round(_float(stats.get("Average Response Time")), 1)
        p95_ms = round(_float(stats.get("95%")), 1)
        rps = round(_float(stats.get("Requests/s")), 2)
        degraded, reason = _is_degraded(stats, fail_pct_limit=fail_pct_limit, p95_limit_ms=p95_limit_ms)
        if exit_code != 0 and not degraded:
            degraded = True
            reason = reason or f"locust exit code {exit_code}"

        step = {
            "users": users,
            "requests": requests,
            "failures": failures,
            "failure_pct": fail_pct,
            "avg_ms": avg_ms,
            "p95_ms": p95_ms,
            "rps": rps,
            "degraded": degraded,
            "reason": reason,
        }
        results.append(step)
        print(
            f"[breakpoint] users={users} reqs={requests} fail={fail_pct}% "
            f"avg={avg_ms}ms p95={p95_ms}ms rps={rps} degraded={degraded}"
        )

        if not degraded:
            max_stable = users
        else:
            first_degraded = first_degraded or users
            print(f"[breakpoint] stop at {users}: {reason}")
            break

        if cooldown > 0:
            time.sleep(cooldown)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "class_session_id": class_session_id,
        "endpoint": MARK_ENDPOINT,
        "max_stable_concurrent_marks": max_stable,
        "first_degraded_at": first_degraded,
        "fail_pct_limit": fail_pct_limit,
        "p95_limit_ms": p95_limit_ms,
        "steps": results,
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    _write_summary(payload)

    print(f"\n[breakpoint] max stable concurrent POST /mark: {max_stable}")
    if first_degraded:
        print(f"[breakpoint] first degraded at: {first_degraded}")
    print(f"[breakpoint] wrote {RESULTS_JSON}")
    print(f"[breakpoint] wrote {SUMMARY_HTML}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
