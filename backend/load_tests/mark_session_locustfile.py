"""
100-concurrent mark-attendance simulation for one class session.

Each virtual user marks attendance once on spawn (burst concurrency).
Run via: ./load_tests/run_mark_session_test.sh
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
MARK_USERS = int(os.getenv("MARK_USERS", "100"))

FACE_IMAGE_BYTES: bytes | None = None


def _load_tokens(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tokens: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tokens.append(stripped.removeprefix("Bearer ").strip())
    return tokens


STUDENT_TOKENS = _load_tokens(STUDENT_TOKENS_FILE)


class _TokenPool:
    def __init__(self, tokens: list[str]) -> None:
        self._cycle = itertools.cycle(tokens)
        self._lock = threading.Lock()

    def next(self) -> str | None:
        if not STUDENT_TOKENS:
            return None
        with self._lock:
            return next(self._cycle)


TOKEN_POOL = _TokenPool(STUDENT_TOKENS)


def _face_image_bytes() -> bytes:
    global FACE_IMAGE_BYTES
    if FACE_IMAGE_BYTES is not None:
        return FACE_IMAGE_BYTES
    if not FACE_IMAGE_PATH.is_file():
        raise FileNotFoundError(f"Face image not found: {FACE_IMAGE_PATH}")
    FACE_IMAGE_BYTES = FACE_IMAGE_PATH.read_bytes()
    return FACE_IMAGE_BYTES


@events.init.add_listener
def on_locust_init(_environment, **_kwargs) -> None:
    if CLASS_SESSION_ID <= 0:
        print("\n[mark_session] ERROR: CLASS_SESSION_ID is required.\n")
    if not STUDENT_TOKENS:
        print(f"\n[mark_session] ERROR: No tokens in {STUDENT_TOKENS_FILE}\n")
    try:
        _face_image_bytes()
    except FileNotFoundError as exc:
        print(f"\n[mark_session] ERROR: {exc}\n")
    else:
        print(
            f"\n[mark_session] Ready — session={CLASS_SESSION_ID}, "
            f"tokens={len(STUDENT_TOKENS)}, target_users={MARK_USERS}\n"
        )


class ConcurrentMarkStudent(HttpUser):
    """One mark per user when spawned — simulates a class-wide attendance burst."""

    wait_time = constant(3600)

    def on_start(self) -> None:
        token = TOKEN_POOL.next()
        if not token or CLASS_SESSION_ID <= 0:
            return

        try:
            image_bytes = _face_image_bytes()
        except FileNotFoundError:
            return

        with self.client.post(
            "/lms/attendance/mark",
            headers={"Authorization": f"Bearer {token}"},
            data={"class_session_id": str(CLASS_SESSION_ID)},
            files={"file": ("attendance.jpg", image_bytes, "image/jpeg")},
            name="POST /lms/attendance/mark",
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"HTTP {response.status_code}")
            elif response.status_code == 401:
                response.failure("HTTP 401 — invalid or expired LMS token")
            elif response.status_code >= 400:
                response.failure(f"HTTP {response.status_code}")

    @task
    def idle(self) -> None:
        pass
