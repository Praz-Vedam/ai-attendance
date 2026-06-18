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
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


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
