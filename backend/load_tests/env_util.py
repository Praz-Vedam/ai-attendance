"""Shared helpers for load-test setup scripts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = LOAD_TESTS_DIR.parent
LOCAL_ENV = LOAD_TESTS_DIR / "local.env"
SECRETS_ENV = LOAD_TESTS_DIR / "secrets.env"
FACE_FIXTURE = LOAD_TESTS_DIR / "fixtures" / "sample.jpg"

DEFAULT_LMS_BASE = "http://localhost:9090"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_secrets_env(path: Path = SECRETS_ENV) -> None:
    """Load secrets.env, overriding backend .env (e.g. LMS_API_BASE for hosted tests)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    values: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env_file(path: Path, values: Dict[str, str]) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")


def lms_bases() -> list[str]:
    primary = os.getenv("LMS_API_BASE", DEFAULT_LMS_BASE).rstrip("/")
    fallback = os.getenv("LMS_API_LOCAL_FALLBACK", DEFAULT_LMS_BASE).rstrip("/")
    bases: list[str] = []
    if "ngrok" in primary and primary.startswith("https://") and fallback:
        bases.append(fallback)
    if primary not in bases:
        bases.append(primary)
    if fallback and fallback not in bases:
        bases.append(fallback)
    return bases


def lms_headers(base: str) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    return headers


def refresh_access_token(refresh_token: str) -> Optional[str]:
    for base in lms_bases():
        try:
            response = httpx.post(
                f"{base}/auth/refresh",
                headers={
                    **lms_headers(base),
                    "Authorization": f"Bearer {refresh_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            token = (response.json().get("data") or {}).get("accessToken")
            if token:
                return token
        except httpx.HTTPError:
            continue
    return None


def resolve_access_token(
    access_token: Optional[str],
    refresh_token: Optional[str],
) -> Optional[str]:
    if access_token:
        return access_token
    if refresh_token:
        return refresh_access_token(refresh_token)
    return None


def auth_detail(access_token: str) -> Optional[Dict[str, Any]]:
    for base in lms_bases():
        try:
            response = httpx.get(
                f"{base}/auth/detail",
                headers={
                    **lms_headers(base),
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            return response.json().get("data")
        except httpx.HTTPError:
            continue
    return None


def token_accepted_by_host(
    access_token: str,
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> bool:
    """Validate token against the attendance API (works when LMS is not on localhost)."""
    host = ai_attendance_base()
    path = "/lms/attendance/student-status" if student else "/lms/attendance/roster"
    params: Dict[str, Any] = {}
    if class_session_id > 0:
        params["class_session_id"] = class_session_id
    try:
        response = httpx.get(
            f"{host}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=30.0,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def is_valid_token(
    access_token: str,
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> bool:
    if auth_detail(access_token):
        return True
    return token_accepted_by_host(
        access_token, class_session_id=class_session_id, student=student
    )


def resolve_valid_access_token(
    access_token: Optional[str],
    refresh_token: Optional[str],
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> Optional[str]:
    candidates: list[str] = []
    if access_token and access_token not in candidates:
        candidates.append(access_token)
    if refresh_token:
        refreshed = refresh_access_token(refresh_token)
        if refreshed and refreshed not in candidates:
            candidates.append(refreshed)
    for token in candidates:
        if is_valid_token(token, class_session_id=class_session_id, student=student):
            return token
    return None


def read_token_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tokens: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tokens.append(stripped.removeprefix("Bearer ").strip())
    return tokens


def write_token_lines(path: Path, tokens: Iterable[str]) -> None:
    unique = [token for token in dict.fromkeys(tokens) if token]
    path.write_text("\n".join(unique) + ("\n" if unique else ""))


def find_active_class_session_id() -> int:
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from redis_client import redis_client

        for key in redis_client.scan_iter(match="lms:attendance:session:*"):
            raw = redis_client.get(key)
            if not raw:
                continue
            session = json.loads(raw.decode("utf-8"))
            if session.get("active"):
                return int(session["class_session_id"])
    except Exception:
        pass
    return 0


def ai_attendance_base() -> str:
    return os.getenv("LOCUST_HOST", "http://127.0.0.1:8000").rstrip("/")


def resolve_teacher_token(
    existing_local: Optional[Dict[str, str]] = None,
    *,
    class_session_id: int = 0,
) -> Optional[str]:
    """Pick first valid teacher token — prefers TEACHER_TOKEN from local.env (setup_local)."""
    existing_local = existing_local or {}
    if class_session_id <= 0:
        class_session_id = int(
            os.getenv("CLASS_SESSION_ID") or existing_local.get("CLASS_SESSION_ID") or 0
        )
    candidates: list[str] = []

    for raw in (
        existing_local.get("TEACHER_TOKEN", "").strip(),
        os.getenv("LOAD_TEST_TEACHER_ACCESS_TOKEN", "").strip(),
    ):
        if raw and raw not in candidates:
            candidates.append(raw)

    refresh = os.getenv("LOAD_TEST_TEACHER_REFRESH_TOKEN", "").strip()
    if refresh:
        resolved = refresh_access_token(refresh)
        if resolved and resolved not in candidates:
            candidates.append(resolved)

    for token in candidates:
        if is_valid_token(token, class_session_id=class_session_id, student=False):
            return token
    return None


def resolve_student_tokens(
    student_tokens_file: Optional[Path] = None,
    *,
    class_session_id: int = 0,
) -> list[str]:
    """Pick valid student token(s) for mark-attendance."""
    path = student_tokens_file or (LOAD_TESTS_DIR / "student_tokens.txt")
    if class_session_id <= 0:
        class_session_id = int(os.getenv("CLASS_SESSION_ID") or 0)
    candidates: list[str] = []

    for raw in (
        os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", "").strip(),
    ):
        if raw and raw not in candidates:
            candidates.append(raw)

    refresh = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip()
    if refresh:
        resolved = refresh_access_token(refresh)
        if resolved and resolved not in candidates:
            candidates.append(resolved)

    for token in read_token_lines(path):
        if token not in candidates:
            candidates.append(token)

    return [
        t
        for t in candidates
        if is_valid_token(t, class_session_id=class_session_id, student=True)
    ]


def start_attendance_session(
    teacher_token: str,
    class_session_id: int,
    *,
    classroom: str = "Load Test Classroom",
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/start",
        headers={
            "Authorization": f"Bearer {teacher_token}",
            "Content-Type": "application/json",
        },
        json={"class_session_id": class_session_id, "classroom": classroom},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()
