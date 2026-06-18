"""
150-concurrent mark-attendance burst for one class session (main branch).

Each user marks once on spawn via POST /lms/attendance/mark.

Run: ./load_tests/run_mark_session_test.sh
Report: load_tests/mark_report.html
"""

from __future__ import annotations

import itertools
import os
import threading
from pathlib import Path

from locust import HttpUser, constant, events, task

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
    os.getenv("STUDENT_TOKENS_FILE", str(LOAD_TESTS_DIR / "student_tokens_mark.txt"))
)
FACE_IMAGE_PATH = Path(
    os.getenv("FACE_IMAGE_PATH", str(LOAD_TESTS_DIR / "fixtures" / "sample.jpg"))
)
MARK_USERS = int(os.getenv("MARK_USERS", "150"))

_tokens: list[str] = []
_face_bytes: bytes | None = None


class _TokenPool:
    def __init__(self, tokens: list[str]) -> None:
        self._cycle = itertools.cycle(tokens)
        self._lock = threading.Lock()

    def next(self) -> str | None:
        if not _tokens:
            return None
        with self._lock:
            return next(self._cycle)


_pool = _TokenPool([])


@events.init.add_listener
def _on_init(environment=None, **kwargs) -> None:
    global _tokens, _pool
    if not STUDENT_TOKENS_FILE.is_file():
        return
    _tokens = [
        ln.strip().removeprefix("Bearer ").strip()
        for ln in STUDENT_TOKENS_FILE.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    _pool = _TokenPool(_tokens)
    print(
        f"\n[mark_session] session={CLASS_SESSION_ID} tokens={len(_tokens)} "
        f"target_users={MARK_USERS}\n"
    )


class ConcurrentMarkStudent(HttpUser):
    wait_time = constant(3600)

    def on_start(self) -> None:
        global _face_bytes
        token = _pool.next()
        if not token or CLASS_SESSION_ID <= 0:
            return
        if _face_bytes is None and FACE_IMAGE_PATH.is_file():
            _face_bytes = FACE_IMAGE_PATH.read_bytes()
        if not _face_bytes:
            return
        with self.client.post(
            "/lms/attendance/mark",
            headers={"Authorization": f"Bearer {token}"},
            data={"class_session_id": str(CLASS_SESSION_ID)},
            files={"file": ("attendance.jpg", _face_bytes, "image/jpeg")},
            name="POST /lms/attendance/mark",
            catch_response=True,
        ) as r:
            if r.status_code >= 500:
                r.failure(f"HTTP {r.status_code}")
            elif r.status_code == 401:
                r.failure("HTTP 401")

    @task
    def idle(self) -> None:
        pass
