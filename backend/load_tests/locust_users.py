"""Shared Locust user classes for polling load tests."""

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

CLASS_SESSION_ID = int(os.getenv("CLASS_SESSION_ID", "0"))
STUDENT_TOKENS_FILE = Path(
    os.getenv("STUDENT_TOKENS_FILE", str(LOAD_TESTS_DIR / "student_tokens.txt"))
)
TEACHER_TOKEN = os.getenv("TEACHER_TOKEN", "").strip()
FACE_IMAGE_PATH = Path(
    os.getenv("FACE_IMAGE_PATH", str(LOAD_TESTS_DIR / "fixtures" / "sample.jpg"))
)
ENABLE_MARK_TASK = os.getenv("ENABLE_MARK_TASK", "1").strip().lower() in {
    "1", "true", "yes",
}

STUDENT_TOKENS: list[str] = []
_token_cycle = None
_face_bytes: bytes | None = None


def _load_tokens(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        ln.strip().removeprefix("Bearer ").strip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session_qs() -> str:
    return f"class_session_id={CLASS_SESSION_ID}"


@events.init.add_listener
def _bootstrap(environment=None, **kwargs) -> None:
    global STUDENT_TOKENS, _token_cycle
    STUDENT_TOKENS = _load_tokens(STUDENT_TOKENS_FILE)
    _token_cycle = itertools.cycle(STUDENT_TOKENS) if STUDENT_TOKENS else None


class _Base(HttpUser):
    abstract = True
    wait_time = between(1, 3)

    def _student_token(self) -> str | None:
        if _token_cycle is None:
            return None
        return next(_token_cycle)

    def _check(self, response) -> None:
        if response.status_code >= 500:
            response.failure(f"HTTP {response.status_code}")
        elif response.status_code == 401:
            response.failure("HTTP 401")
        elif response.status_code >= 400:
            response.failure(f"HTTP {response.status_code}")


class HealthUser(_Base):
    weight = 1

    @task
    def health(self) -> None:
        with self.client.get("/", name="GET /", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")


class StudentPoller(_Base):
    weight = 9

    def on_start(self) -> None:
        self.token = self._student_token()

    @task(5)
    def student_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/student-status?{_session_qs()}",
            headers=_auth(self.token),
            name="GET /lms/attendance/student-status",
            catch_response=True,
        ) as r:
            self._check(r)

    @task(2)
    def session_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{_session_qs()}",
            headers=_auth(self.token),
            name="GET /lms/attendance/status",
            catch_response=True,
        ) as r:
            self._check(r)


class TeacherPoller(_Base):
    weight = 1

    @task(3)
    def status(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{_session_qs()}",
            headers=_auth(TEACHER_TOKEN),
            name="GET /lms/attendance/status [teacher]",
            catch_response=True,
        ) as r:
            self._check(r)

    @task(1)
    def roster(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/roster?{_session_qs()}",
            headers=_auth(TEACHER_TOKEN),
            name="GET /lms/attendance/roster",
            catch_response=True,
        ) as r:
            self._check(r)


if ENABLE_MARK_TASK:

    class StudentMarker(_Base):
        weight = 1
        wait_time = between(5, 15)

        def on_start(self) -> None:
            self.token = self._student_token()

        @task
        def mark(self) -> None:
            global _face_bytes
            if not self.token or CLASS_SESSION_ID <= 0:
                return
            if _face_bytes is None:
                if not FACE_IMAGE_PATH.is_file():
                    return
                _face_bytes = FACE_IMAGE_PATH.read_bytes()
            with self.client.post(
                "/lms/attendance/mark",
                headers=_auth(self.token),
                data={"class_session_id": str(CLASS_SESSION_ID)},
                files={"file": ("attendance.jpg", _face_bytes, "image/jpeg")},
                name="POST /lms/attendance/mark",
                catch_response=True,
            ) as r:
                if r.status_code >= 500:
                    r.failure(f"HTTP {r.status_code}")
                elif r.status_code == 401:
                    r.failure("HTTP 401")
                elif r.status_code >= 400:
                    r.failure(f"HTTP {r.status_code}")
