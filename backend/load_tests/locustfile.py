"""
Load tests for the AI attendance FastAPI backend (LMS-integrated routes).

Prerequisites:
  1. Backend running: uvicorn main:app --host 0.0.0.0 --port 8000  (no --reload)
  2. Redis running (required for /lms/attendance/* session state)
  3. LMS API reachable from the backend (LMS_API_BASE in backend/.env)
  4. An active attendance session for CLASS_SESSION_ID (teacher starts via admin portal)

Setup (automatic locally):
  ./load_tests/run.sh
  # run.sh calls setup_local.py which creates local.env, student_tokens.txt,
  # fixtures/sample.jpg, and enables mark-attendance by default.

Manual token fallback (if browser cookies unavailable):
  cp load_tests/secrets.example.env load_tests/secrets.env
  # Paste refresh tokens, then re-run ./load_tests/run.sh

Run (headless, 300 users):
  ./load_tests/run.sh --headless -u 300 -r 30 --run-time 5m --html load_tests/report.html

Environment variables (auto-written to load_tests/local.env by setup_local.py):
  LOCUST_HOST          Target base URL (default http://127.0.0.1:8000)
  CLASS_SESSION_ID     Active class session id (auto-detected from Redis when possible)
  TEACHER_TOKEN        Admin/teacher LMS token (from browser or secrets.env)
  STUDENT_TOKENS_FILE  Path to student tokens file (default load_tests/student_tokens.txt)
  FACE_IMAGE_PATH      JPEG used for mark-attendance uploads (Redis snapshot or placeholder)
  ENABLE_MARK_TASK     1 by default locally — POST /lms/attendance/mark in the mix
  MARK_TASK_WEIGHT     Locust task weight for mark-attendance (default 1)
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path

from locust import HttpUser, between, events, task

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

LOAD_TESTS_DIR = Path(__file__).resolve().parent
LOCAL_ENV = LOAD_TESTS_DIR / "local.env"

if load_dotenv is not None:
    load_dotenv(LOCAL_ENV, override=False)
DEFAULT_FIXTURE = LOAD_TESTS_DIR / "fixtures" / "sample.jpg"
DEFAULT_STUDENT_TOKENS = LOAD_TESTS_DIR / "student_tokens.txt"

LOCUST_HOST = os.getenv("LOCUST_HOST", "http://127.0.0.1:8000")
CLASS_SESSION_ID = int(os.getenv("CLASS_SESSION_ID", "0"))
STUDENT_TOKENS_FILE = Path(os.getenv("STUDENT_TOKENS_FILE", str(DEFAULT_STUDENT_TOKENS)))
TEACHER_TOKEN = os.getenv("TEACHER_TOKEN", "").strip()
FACE_IMAGE_PATH = Path(os.getenv("FACE_IMAGE_PATH", str(DEFAULT_FIXTURE)))
ENABLE_MARK_TASK = os.getenv(
    "ENABLE_MARK_TASK", "1" if LOCAL_ENV.is_file() else ""
).strip().lower() in {"1", "true", "yes"}
MARK_TASK_WEIGHT = int(os.getenv("MARK_TASK_WEIGHT", "1"))


def _load_tokens(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tokens: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens.append(stripped.removeprefix("Bearer ").strip())
    return tokens


STUDENT_TOKENS = _load_tokens(STUDENT_TOKENS_FILE)
STUDENT_TOKEN_CYCLE = itertools.cycle(STUDENT_TOKENS) if STUDENT_TOKENS else None
FACE_IMAGE_BYTES: bytes | None = None


def _face_image_bytes() -> bytes:
    global FACE_IMAGE_BYTES
    if FACE_IMAGE_BYTES is not None:
        return FACE_IMAGE_BYTES
    if FACE_IMAGE_PATH.is_file():
        FACE_IMAGE_BYTES = FACE_IMAGE_PATH.read_bytes()
        return FACE_IMAGE_BYTES
    raise FileNotFoundError(
        f"Face image not found at {FACE_IMAGE_PATH}. "
        "Run: python load_tests/generate_fixture.py"
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _class_session_query() -> str:
    return f"class_session_id={CLASS_SESSION_ID}"


@events.init.add_listener
def on_locust_init(environment, **_kwargs) -> None:
    if CLASS_SESSION_ID <= 0:
        print(
            "\n[load_tests] WARNING: CLASS_SESSION_ID is not set. "
            "Export CLASS_SESSION_ID before running LMS route tests.\n"
        )
    if not STUDENT_TOKENS:
        print(
            f"\n[load_tests] WARNING: No student tokens in {STUDENT_TOKENS_FILE}. "
            "Student tasks will be skipped.\n"
        )
    if not TEACHER_TOKEN:
        print(
            "\n[load_tests] WARNING: TEACHER_TOKEN is not set. "
            "Teacher roster polling will be skipped.\n"
        )
    try:
        _face_image_bytes()
    except FileNotFoundError as exc:
        print(f"\n[load_tests] WARNING: {exc}\n")


class _BaseUser(HttpUser):
    abstract = True
    wait_time = between(2, 5)

    def _next_student_token(self) -> str | None:
        if STUDENT_TOKEN_CYCLE is None:
            return None
        return next(STUDENT_TOKEN_CYCLE)

    def _fail_unless_ok(self, response, *, allow_success_false: bool = False) -> None:
        if response.status_code >= 500:
            response.failure(f"HTTP {response.status_code}")
            return
        if response.status_code == 401:
            response.failure("HTTP 401 — invalid or expired LMS token")
            return
        if response.status_code >= 400:
            response.failure(f"HTTP {response.status_code}")
            return
        if allow_success_false:
            return
        try:
            payload = response.json()
        except Exception:
            return
        if isinstance(payload, dict) and payload.get("success") is False:
            response.failure(payload.get("message") or "success=false")


class HealthUser(_BaseUser):
    """Lightweight baseline — no auth required."""

    weight = 1

    @task
    def health(self) -> None:
        with self.client.get("/", name="GET /", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")


class LmsStudentPoller(_BaseUser):
    """Simulates students polling attendance state during a live class."""

    weight = 9

    def on_start(self) -> None:
        self.token = self._next_student_token()

    @task(5)
    def student_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/student-status?{_class_session_query()}",
            headers=_auth_headers(self.token),
            name="GET /lms/attendance/student-status",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)

    @task(2)
    def session_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{_class_session_query()}",
            headers=_auth_headers(self.token),
            name="GET /lms/attendance/status",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)


class LmsTeacherPoller(_BaseUser):
    """Simulates admin portal polling roster + live status."""

    weight = 1

    @task(3)
    def attendance_status(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{_class_session_query()}",
            headers=_auth_headers(TEACHER_TOKEN),
            name="GET /lms/attendance/status [teacher]",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)

    @task(1)
    def roster(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/roster?{_class_session_query()}",
            headers=_auth_headers(TEACHER_TOKEN),
            name="GET /lms/attendance/roster",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)


if ENABLE_MARK_TASK:

    class LmsStudentMarker(_BaseUser):
        """ML-heavy: POST face image to mark attendance. Start with low user count."""

        weight = MARK_TASK_WEIGHT
        wait_time = between(5, 15)

        def on_start(self) -> None:
            self.token = self._next_student_token()

        @task
        def mark_attendance(self) -> None:
            if not self.token or CLASS_SESSION_ID <= 0:
                return
            try:
                image_bytes = _face_image_bytes()
            except FileNotFoundError:
                return

            with self.client.post(
                "/lms/attendance/mark",
                headers=_auth_headers(self.token),
                data={"class_session_id": str(CLASS_SESSION_ID)},
                files={"file": ("attendance.jpg", image_bytes, "image/jpeg")},
                name="POST /lms/attendance/mark",
                catch_response=True,
            ) as response:
                # Business failures (already marked, no face, not active) still mean the server handled the request.
                self._fail_unless_ok(response, allow_success_false=True)
