# AI Attendance — Load Tests (main branch)

Locust-based load tests matching **LMS-integrated routes** used by admin-portal and student-portal.

## Quick start

```bash
cd backend
cp load_tests/secrets.example.env load_tests/secrets.env
# Edit secrets.env: teacher + student tokens, CLASS_SESSION_ID, optional LOCUST_HOST

./load_tests/run_all.sh               # ALL tests → HTML reports + index.html
./load_tests/run.sh                   # polling → report.html
./load_tests/run_mark_session_test.sh # 150-user mark burst (30s) → mark_report.html
./load_tests/run_throughput_test.sh   # 100 flat concurrent → throughput_summary.html
```

## HTML reports

| File | Test |
|------|------|
| `load_tests/index.html` | Dashboard linking all reports |
| `load_tests/report.html` | Polling test (**100 concurrent users**) |
| `load_tests/mark_report.html` | Mark burst (150 users / 30s window) |
| `load_tests/throughput_summary.html` | Throughput — **100 flat users** |
| `load_tests/throughput_report.html` | Throughput — Locust detail |

Open the index after any run: `file://.../backend/load_tests/index.html`

| Script | Simulates | Endpoints |
|--------|-----------|-----------|
| `run.sh` | Live class polling + **mark attendance** | `GET /lms/attendance/*`, `POST /lms/attendance/mark` |
| `run_mark_session_test.sh` | **150 users mark in 30s** | `POST /lms/attendance/start` (setup), `POST /lms/attendance/mark` × 150 |
| `run_throughput_test.sh` | **100 concurrent users** (flat) | Same polling mix, sustained load |

## Config (`load_tests/secrets.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `LOAD_TEST_TEACHER_ACCESS_TOKEN` | Yes | Admin portal LMS token |
| `LOAD_TEST_STUDENT_ACCESS_TOKEN` | Yes | Student portal LMS token |
| `CLASS_SESSION_ID` | Yes | Class session id |
| `LOCUST_HOST` | No | Default `http://127.0.0.1:8000` — set to hosted URL to test remote |
| `LMS_API_BASE` | No | Override backend `.env` for token refresh/validation (optional if `LOCUST_HOST` is set) |

## Hosted URL

```bash
LOCUST_HOST=https://attendance.vedam.org ./load_tests/run.sh
```

Use tokens from the **same environment** as the hosted server. Tokens are validated against `LOCUST_HOST` when local LMS (`localhost:9090`) is unreachable.

## What gets tested

- Redis running (LMS attendance state)
- LMS API reachable from the target server
- For mark tests: student face registered, active session
