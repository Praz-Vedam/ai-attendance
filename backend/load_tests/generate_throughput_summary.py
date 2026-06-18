#!/usr/bin/env python3
"""Build throughput_summary.html from Locust CSV + breakpoint JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BREAKPOINT_FILE = LOAD_TESTS_DIR / "throughput_breakpoint.json"
HISTORY_CSV = LOAD_TESTS_DIR / "throughput_data_stats_history.csv"
SUMMARY_HTML = LOAD_TESTS_DIR / "throughput_summary.html"
LOCUST_HTML = LOAD_TESTS_DIR / "throughput_report.html"


def _read_breakpoint() -> dict:
    if not BREAKPOINT_FILE.is_file():
        return {}
    return json.loads(BREAKPOINT_FILE.read_text())


def _read_history() -> list[dict]:
    if not HISTORY_CSV.is_file():
        return []
    with HISTORY_CSV.open() as f:
        return list(csv.DictReader(f))


def main() -> None:
    bp = _read_breakpoint()
    history = _read_history()

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    degraded = bp.get("degraded", False)
    status_class = "bad" if degraded else "ok"
    status_text = "DEGRADED / near crash" if degraded else "Stable at 100 concurrent users"
    users = bp.get("concurrent_users", 100)

    hist_rows = ""
    for row in history[-20:]:
        hist_rows += f"""
        <tr>
          <td>{row.get('Timestamp', '—')}</td>
          <td>{row.get('User Count', '—')}</td>
          <td>{row.get('Requests/s', '—')}</td>
          <td>{row.get('Failures/s', '—')}</td>
          <td>{row.get('Total Average Response Time', '—')}</td>
        </tr>"""

    locust_link = (
        '<a class="btn" href="throughput_report.html">Open Locust report</a>'
        if LOCUST_HTML.is_file()
        else '<span class="muted">throughput_report.html not found</span>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Throughput Test Summary</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .sub {{ color: #666; margin-bottom: 1.5rem; }}
    .status {{ padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; max-width: 720px; }}
    .status.ok {{ background: #ecfdf5; border: 1px solid #6ee7b7; }}
    .status.bad {{ background: #fef2f2; border: 1px solid #fca5a5; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 960px; margin-bottom: 2rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.55rem 0.75rem; text-align: left; font-size: 0.9rem; }}
    th {{ background: #f5f5f5; }}
    .btn {{ display: inline-block; padding: 0.35rem 0.75rem; background: #2563eb;
            color: #fff; text-decoration: none; border-radius: 4px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                gap: 1rem; max-width: 800px; margin-bottom: 1.5rem; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.75rem 1rem; }}
    .card .val {{ font-size: 1.4rem; font-weight: 600; }}
    .card .lbl {{ color: #666; font-size: 0.8rem; }}
    .muted {{ color: #888; }}
  </style>
</head>
<body>
  <h1>Throughput Test Summary</h1>
  <p class="sub">Generated {generated} — <strong>{users} concurrent users</strong> (flat, no ramp)</p>

  <div class="status {status_class}"><strong>{status_text}</strong></div>

  <div class="metrics">
    <div class="card"><div class="val">{users}</div><div class="lbl">Concurrent users</div></div>
    <div class="card"><div class="val">{bp.get('total_requests', '—')}</div><div class="lbl">Total requests</div></div>
    <div class="card"><div class="val">{bp.get('avg_rps', '—')}</div><div class="lbl">Avg RPS</div></div>
    <div class="card"><div class="val">{bp.get('failure_pct', '—')}%</div><div class="lbl">Failure rate</div></div>
    <div class="card"><div class="val">{bp.get('p95_ms', '—')} ms</div><div class="lbl">p95 latency</div></div>
  </div>

  <p>{locust_link} &nbsp; <a class="btn" href="index.html">All reports</a></p>

  <h2>Stats over time</h2>
  <table>
    <thead><tr><th>Time</th><th>Users</th><th>RPS</th><th>Failures/s</th><th>Avg RT (ms)</th></tr></thead>
    <tbody>{hist_rows or '<tr><td colspan="5" class="muted">No CSV history</td></tr>'}</tbody>
  </table>
</body>
</html>
"""
    SUMMARY_HTML.write_text(html)
    print(f"[throughput] Wrote {SUMMARY_HTML}")


if __name__ == "__main__":
    main()
