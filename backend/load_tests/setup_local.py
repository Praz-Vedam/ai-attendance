#!/usr/bin/env python3
"""Prepare load-test config from secrets.env and local Redis state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = LOAD_TESTS_DIR.parent
sys.path.insert(0, str(LOAD_TESTS_DIR))

from env_util import (  # noqa: E402
    BACKEND_DIR as _BACKEND_DIR,
    LOCAL_ENV,
    SECRETS_ENV,
    FACE_FIXTURE,
    auth_detail,
    find_active_class_session_id,
    load_dotenv,
    load_secrets_env,
    parse_env_file,
    read_token_lines,
    resolve_valid_access_token,
    write_env_file,
)

STUDENT_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens.txt"
DEFAULT_STUDENT_TOKEN_COPIES = 100


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
    return str(person.get("personType") or person.get("type") or "").lower() == "student"


def _write_student_tokens(tokens: Iterable[str], *, copies: int) -> None:
    unique = [t for t in dict.fromkeys(tokens) if t]
    if not unique:
        return
    lines = unique if len(unique) > 1 else unique * max(copies, 1)
    STUDENT_TOKENS_FILE.write_text("\n".join(lines) + "\n")


def _export_face_fixture(class_session_id: int) -> bool:
    try:
        sys.path.insert(0, str(_BACKEND_DIR))
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
    subprocess.run(
        [sys.executable, str(LOAD_TESTS_DIR / "generate_fixture.py")],
        check=True,
    )


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_secrets_env(SECRETS_ENV)

    existing = parse_env_file(LOCAL_ENV)
    class_session_id = int(
        os.getenv("CLASS_SESSION_ID") or existing.get("CLASS_SESSION_ID") or 0
    )
    if class_session_id <= 0:
        class_session_id = find_active_class_session_id()

    student_token = resolve_valid_access_token(
        os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", "").strip() or None,
        os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip() or None,
        class_session_id=class_session_id,
        student=True,
    )
    teacher_token = resolve_valid_access_token(
        os.getenv("LOAD_TEST_TEACHER_ACCESS_TOKEN", "").strip() or None,
        os.getenv("LOAD_TEST_TEACHER_REFRESH_TOKEN", "").strip() or None,
        class_session_id=class_session_id,
        student=False,
    )

    if not student_token and not teacher_token:
        browser = _read_browser_cookies()
        resolved = resolve_valid_access_token(
            browser.get("accessToken"),
            browser.get("refreshToken"),
            class_session_id=class_session_id,
        )
        if resolved:
            detail = auth_detail(resolved)
            if detail and _is_student_auth(detail):
                student_token = resolved
            else:
                teacher_token = resolved

    if not student_token:
        existing_student = read_token_lines(STUDENT_TOKENS_FILE)
        for candidate in existing_student:
            if resolve_valid_access_token(
                candidate, None, class_session_id=class_session_id, student=True
            ):
                student_token = candidate
                break

    if not teacher_token:
        existing_teacher = existing.get("TEACHER_TOKEN", "").strip() or None
        teacher_token = resolve_valid_access_token(
            existing_teacher,
            None,
            class_session_id=class_session_id,
            student=False,
        )

    copies = int(os.getenv("LOAD_TEST_STUDENT_TOKEN_COPIES", str(DEFAULT_STUDENT_TOKEN_COPIES)))
    if student_token:
        _write_student_tokens([student_token], copies=copies)

    if _export_face_fixture(class_session_id):
        print(f"[setup_local] Face fixture from Redis → {FACE_FIXTURE}")
    else:
        _ensure_placeholder_face()

    env_values = {
        "CLASS_SESSION_ID": str(class_session_id or 0),
        "STUDENT_TOKENS_FILE": str(STUDENT_TOKENS_FILE),
        "FACE_IMAGE_PATH": str(FACE_FIXTURE),
        "ENABLE_MARK_TASK": os.getenv("ENABLE_MARK_TASK", "1").strip(),
        "LOCUST_HOST": os.getenv("LOCUST_HOST", existing.get("LOCUST_HOST", "http://127.0.0.1:8000")),
    }
    if teacher_token:
        env_values["TEACHER_TOKEN"] = teacher_token
    write_env_file(LOCAL_ENV, env_values)

    print(f"[setup_local] Wrote {LOCAL_ENV}")
    if class_session_id:
        print(f"[setup_local] CLASS_SESSION_ID={class_session_id}")
    if student_token:
        print(f"[setup_local] Student token OK ({copies} copies for polling)")
    else:
        print("[setup_local] Set LOAD_TEST_STUDENT_ACCESS_TOKEN in secrets.env")
    if teacher_token:
        print("[setup_local] Teacher token OK")
    else:
        print("[setup_local] Set LOAD_TEST_TEACHER_ACCESS_TOKEN in secrets.env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
