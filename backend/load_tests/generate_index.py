#!/usr/bin/env python3
"""Build index.html linking all load-test HTML reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

LOAD_TESTS_DIR = Path(__file__).resolve().parent
INDEX = LOAD_TESTS_DIR / "index.html"

REPORTS = [
    ("Polling test (student + teacher portals)", "report.html"),
    ("Mark burst test (concurrent attendance)", "mark_report.html"),
    ("Throughput test (100 concurrent users)", "throughput_summary.html"),
    ("Throughput Locust detail", "throughput_report.html"),
]


def main() -> None:
    rows = []
    for title, filename in REPORTS:
        path = LOAD_TESTS_DIR / filename
        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            size_kb = path.stat().st_size / 1024
            status = "Ready"
            link = filename
        else:
            mtime = None
            size_kb = 0
            status = "Not run yet"
            link = "#"
        rows.append((title, filename, status, mtime, size_kb, link))

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body_rows = ""
    for title, filename, status, mtime, size_kb, link in rows:
        when = mtime.strftime("%Y-%m-%d %H:%M:%S UTC") if mtime else "—"
        size = f"{size_kb:.1f} KB" if size_kb else "—"
        btn = (
            f'<a class="btn" href="{link}">Open report</a>'
            if link != "#"
            else '<span class="muted">Run test first</span>'
        )
        body_rows += f"""
        <tr>
          <td>{title}</td>
          <td><code>{filename}</code></td>
          <td>{status}</td>
          <td>{when}</td>
          <td>{size}</td>
          <td>{btn}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>AI Attendance Load Test Reports</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .sub {{ color: #666; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 960px; }}
    th, td {{ border: 1px solid #ddd; padding: 0.65rem 0.85rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .btn {{ display: inline-block; padding: 0.35rem 0.75rem; background: #2563eb;
            color: #fff; text-decoration: none; border-radius: 4px; }}
    .btn:hover {{ background: #1d4ed8; }}
    .muted {{ color: #888; }}
    code {{ background: #f0f0f0; padding: 0.1rem 0.35rem; border-radius: 3px; }}
    .cmds {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 1rem;
              border-radius: 6px; max-width: 960px; margin-top: 2rem; }}
    pre {{ margin: 0.5rem 0 0; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>AI Attendance Load Test Reports</h1>
  <p class="sub">Generated {generated}</p>
  <table>
    <thead>
      <tr>
        <th>Test</th>
        <th>Report file</th>
        <th>Status</th>
        <th>Last updated</th>
        <th>Size</th>
        <th></th>
      </tr>
    </thead>
    <tbody>{body_rows}
    </tbody>
  </table>
  <div class="cmds">
    <strong>Run all tests:</strong>
    <pre>cd backend && ./load_tests/run_all.sh</pre>
    <strong>Individual runs:</strong>
    <pre>./load_tests/run.sh
./load_tests/run_mark_session_test.sh
./load_tests/run_throughput_test.sh</pre>
  </div>
</body>
</html>
"""
    INDEX.write_text(html)
    print(f"[reports] Wrote {INDEX}")


if __name__ == "__main__":
    main()
