#!/usr/bin/env python3
"""
Prepare load-test assets and config for local runs.

Creates/updates:
  - load_tests/local.env          (CLASS_SESSION_ID, tokens, paths, mark-task flags)
  - load_tests/student_tokens.txt (from browser cookies or refresh tokens)
  - load_tests/fixtures/sample.jpg (from Redis snapshot or placeholder)

Token sources (first match wins):
  1. load_tests/secrets.env — LOAD_TEST_STUDENT_REFRESH_TOKEN / LOAD_TEST_TEACHER_REFRESH_TOKEN
  2. Chrome cookies on localhost (admin or student portal login)
  3. Existing student_tokens.txt / local.env (left unchanged if still valid)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = LOAD_TESTS_DIR.parent
LOCAL_ENV = LOAD_TESTS_DIR / "local.env"
SECRETS_ENV = LOAD_TESTS_DIR / "secrets.env"
STUDENT_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens.txt"
FACE_FIXTURE = LOAD_TESTS_DIR / "fixtures" / "sample.jpg"

DEFAULT_LMS_BASE = "http://localhost:9090"
DEFAULT_STUDENT_TOKEN_COPIES = 300


def _load_dotenv(path: Path) -> None:
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


def _write_env(path: Path, values: Dict[str, str]) -> None:
    sys.path.insert(0, str(LOAD_TESTS_DIR))
    from env_util import write_env_file

    write_env_file(path, values)


def _lms_bases() -> list[str]:
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


def _lms_headers(base: str) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    return headers


def _refresh_access_token(refresh_token: str) -> Optional[str]:
    for base in _lms_bases():
        try:
            response = httpx.post(
                f"{base}/auth/refresh",
                headers={
                    **_lms_headers(base),
                    "Authorization": f"Bearer {refresh_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            token = (payload.get("data") or {}).get("accessToken")
            if token:
                return token
        except httpx.HTTPError:
            continue
    return None


def _resolve_access_token(
    access_token: Optional[str],
    refresh_token: Optional[str],
) -> Optional[str]:
    if access_token:
        return access_token
    if refresh_token:
        return _refresh_access_token(refresh_token)
    return None


def _auth_detail(access_token: str) -> Optional[Dict[str, Any]]:
    for base in _lms_bases():
        try:
            response = httpx.get(
                f"{base}/auth/detail",
                headers={
                    **_lms_headers(base),
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


def _is_student_auth(detail: Dict[str, Any]) -> bool:
    roles = detail.get("roles") or detail.get("roleList") or []
    if isinstance(roles, list):
        for role in roles:
            name = ""
            if isinstance(role, dict):
                name = str(role.get("roleName") or role.get("name") or "").lower()
            else:
                name = str(role).lower()
            if "student" in name:
                return True
    person = detail.get("personDetail") or {}
    person_type = str(person.get("personType") or person.get("type") or "").lower()
    return person_type == "student"


def _read_browser_cookies() -> Dict[str, str]:
    try:
        import browser_cookie3
    except ImportError:
        return {}

    cookies: Dict[str, str] = {}
    for loader_name in ("chrome", "chromium", "brave", "edge"):
        loader = getattr(browser_cookie3, loader_name, None)
        if loader is None:
            continue
        try:
            for cookie in loader(domain_name="localhost"):
                cookies[cookie.name] = cookie.value
        except Exception:
            continue
        if cookies:
            break
    return cookies


def _read_existing_tokens(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tokens: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tokens.append(stripped.removeprefix("Bearer ").strip())
    return tokens


def _write_student_tokens(tokens: Iterable[str], *, copies: int) -> None:
    unique = [token for token in dict.fromkeys(tokens) if token]
    if not unique:
        return
    base = unique if len(unique) > 1 else unique * max(copies, 1)
    STUDENT_TOKENS_FILE.write_text("\n".join(base) + "\n")


def _find_active_class_session_id() -> int:
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


def _export_face_fixture(class_session_id: int) -> bool:
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from redis_client import redis_client

        pattern = (
            f"lms:attendance:snapshot:{class_session_id}:*"
            if class_session_id > 0
            else "lms:attendance:snapshot:*"
        )
        for key in redis_client.scan_iter(match=pattern):
            raw = redis_client.get(key)
            if raw and len(raw) > 1024:
                FACE_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
                FACE_FIXTURE.write_bytes(raw)
                return True
    except Exception:
        pass
    return False


def _ensure_placeholder_face() -> None:
    if FACE_FIXTURE.is_file():
        return
    import subprocess

    subprocess.run(
        [sys.executable, str(LOAD_TESTS_DIR / "generate_fixture.py")],
        check=True,
    )


def _parse_local_env() -> Dict[str, str]:
    if not LOCAL_ENV.is_file():
        return {}
    values: Dict[str, str] = {}
    for line in LOCAL_ENV.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    _load_dotenv(BACKEND_DIR / ".env")
    _load_dotenv(SECRETS_ENV)

    existing = _parse_local_env()
    class_session_id = int(
        os.getenv("CLASS_SESSION_ID") or existing.get("CLASS_SESSION_ID") or 0
    )
    if class_session_id <= 0:
        class_session_id = _find_active_class_session_id()

    student_refresh = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip()
    teacher_refresh = os.getenv("LOAD_TEST_TEACHER_REFRESH_TOKEN", "").strip()
    browser = _read_browser_cookies()
    browser_access = browser.get("accessToken")
    browser_refresh = browser.get("refreshToken")

    student_token = _resolve_access_token(
        os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", "").strip() or None,
        student_refresh or None,
    )
    teacher_token = _resolve_access_token(
        os.getenv("LOAD_TEST_TEACHER_ACCESS_TOKEN", "").strip() or None,
        teacher_refresh or None,
    )

    if not student_token and not teacher_token and (browser_access or browser_refresh):
        resolved = _resolve_access_token(browser_access, browser_refresh)
        if resolved:
            detail = _auth_detail(resolved)
            if detail and _is_student_auth(detail):
                student_token = resolved
            else:
                teacher_token = resolved

    if not student_token:
        existing_student = _read_existing_tokens(STUDENT_TOKENS_FILE)
        if existing_student and _auth_detail(existing_student[0]):
            student_token = existing_student[0]

    if not teacher_token:
        teacher_token = existing.get("TEACHER_TOKEN", "").strip() or None
        if teacher_token and not _auth_detail(teacher_token):
            teacher_token = None

    copies = int(os.getenv("LOAD_TEST_STUDENT_TOKEN_COPIES", str(DEFAULT_STUDENT_TOKEN_COPIES)))
    if student_token:
        _write_student_tokens([student_token], copies=copies)
    elif _read_existing_tokens(STUDENT_TOKENS_FILE):
        print(f"[setup_local] Keeping existing {STUDENT_TOKENS_FILE}")

    if _export_face_fixture(class_session_id):
        print(f"[setup_local] Face fixture from Redis snapshot → {FACE_FIXTURE}")
    else:
        _ensure_placeholder_face()
        print(f"[setup_local] Placeholder face fixture → {FACE_FIXTURE}")

    enable_mark = os.getenv("ENABLE_MARK_TASK", "1").strip()
    mark_weight = os.getenv("MARK_TASK_WEIGHT", "1").strip()

    env_values = {
        "CLASS_SESSION_ID": str(class_session_id or 0),
        "STUDENT_TOKENS_FILE": str(STUDENT_TOKENS_FILE),
        "FACE_IMAGE_PATH": str(FACE_FIXTURE),
        "ENABLE_MARK_TASK": enable_mark,
        "MARK_TASK_WEIGHT": mark_weight,
        "LOCUST_HOST": os.getenv("LOCUST_HOST", existing.get("LOCUST_HOST", "http://127.0.0.1:8000")),
    }
    if teacher_token:
        env_values["TEACHER_TOKEN"] = teacher_token

    _write_env(LOCAL_ENV, env_values)

    print(f"[setup_local] Wrote {LOCAL_ENV}")
    if class_session_id:
        print(f"[setup_local] CLASS_SESSION_ID={class_session_id}")
    else:
        print("[setup_local] No active Redis session — start attendance in admin portal first.")
    if student_token:
        print(
            f"[setup_local] Student token ready "
            f"({copies} copies in student_tokens.txt for polling test)"
        )
    else:
        print(
            "[setup_local] No student token — set LOAD_TEST_STUDENT_ACCESS_TOKEN in "
            "load_tests/secrets.env"
        )
    if teacher_token:
        print("[setup_local] Teacher token ready")
    else:
        print(
            "[setup_local] No teacher token — set LOAD_TEST_TEACHER_ACCESS_TOKEN in "
            "load_tests/secrets.env"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
