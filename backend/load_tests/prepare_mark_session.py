#!/usr/bin/env python3
"""
Prepare a single class session for concurrent mark-attendance load testing.

Works with 1 teacher + 1 student token (replicated for concurrent users).

Steps:
  1. Resolve CLASS_SESSION_ID and teacher token
  2. POST /lms/attendance/start (clears prior marks in Redis)
  3. Resolve student access token from secrets.env
  4. Write student_tokens_mark.txt (replicated to MARK_USERS lines)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOAD_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LOAD_TESTS_DIR))

from env_util import (
    BACKEND_DIR,
    LOCAL_ENV,
    SECRETS_ENV,
    ai_attendance_base,
    auth_detail,
    find_active_class_session_id,
    load_dotenv,
    parse_env_file,
    read_token_lines,
    refresh_access_token,
    resolve_access_token,
    start_attendance_session,
    write_env_file,
    write_token_lines,
)

STUDENT_REFRESH_TOKENS_FILE = LOAD_TESTS_DIR / "student_refresh_tokens.txt"
STUDENT_MARK_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens_mark.txt"
DEFAULT_MARK_USERS = 100


def _read_refresh_tokens() -> list[str]:
    tokens = read_token_lines(STUDENT_REFRESH_TOKENS_FILE)
    if tokens:
        return tokens

    bulk = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKENS", "").strip()
    if bulk:
        return [part.strip() for part in bulk.replace("\n", ",").split(",") if part.strip()]

    single = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip()
    if single:
        return [single]

    return []


def _resolve_teacher_token(existing: dict[str, str]) -> str | None:
    token = os.getenv("LOAD_TEST_TEACHER_ACCESS_TOKEN", "").strip() or existing.get(
        "TEACHER_TOKEN", ""
    ).strip()
    if token and auth_detail(token):
        return token

    refresh = os.getenv("LOAD_TEST_TEACHER_REFRESH_TOKEN", "").strip()
    resolved = resolve_access_token(None, refresh or None)
    if resolved and auth_detail(resolved):
        return resolved
    return None


def _resolve_student_access_tokens() -> list[str]:
    """One student token is enough — it is replicated for concurrent mark requests."""
    direct = os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", "").strip()
    if direct and auth_detail(direct):
        return [direct]

    access_tokens: list[str] = []
    for refresh in _read_refresh_tokens():
        token = refresh_access_token(refresh)
        if token and auth_detail(token):
            access_tokens.append(token)
    if access_tokens:
        return list(dict.fromkeys(access_tokens))

    fallback = read_token_lines(LOAD_TESTS_DIR / "student_tokens.txt")
    return [token for token in dict.fromkeys(fallback) if auth_detail(token)]


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_dotenv(SECRETS_ENV)
    load_dotenv(LOCAL_ENV)

    existing = parse_env_file(LOCAL_ENV)
    mark_users = int(os.getenv("MARK_USERS", str(DEFAULT_MARK_USERS)))

    class_session_id = int(
        os.getenv("CLASS_SESSION_ID") or existing.get("CLASS_SESSION_ID") or 0
    )
    if class_session_id <= 0:
        class_session_id = find_active_class_session_id()
    if class_session_id <= 0:
        print(
            "[prepare_mark_session] Set CLASS_SESSION_ID in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    teacher_token = _resolve_teacher_token(existing)
    if not teacher_token:
        print(
            "[prepare_mark_session] Set LOAD_TEST_TEACHER_ACCESS_TOKEN in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    try:
        result = start_attendance_session(teacher_token, class_session_id)
        print(
            f"[prepare_mark_session] Started session {class_session_id}: "
            f"{result.get('message', 'ok')}"
        )
    except Exception as exc:
        print(f"[prepare_mark_session] Failed to start attendance session: {exc}", file=sys.stderr)
        return 1

    access_tokens = _resolve_student_access_tokens()
    if not access_tokens:
        print(
            "[prepare_mark_session] Set LOAD_TEST_STUDENT_ACCESS_TOKEN in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    unique_count = len(access_tokens)
    if unique_count == 1:
        print(
            f"[prepare_mark_session] 1 student token × {mark_users} concurrent requests — "
            "expect 1 successful mark; others stress ML/auth under load."
        )
    elif unique_count < mark_users:
        print(
            f"[prepare_mark_session] {unique_count} student token(s) for {mark_users} users."
        )

    final_tokens = (access_tokens * ((mark_users // unique_count) + 1))[:mark_users]
    write_token_lines(STUDENT_MARK_TOKENS_FILE, final_tokens)

    face_path = existing.get("FACE_IMAGE_PATH") or str(LOAD_TESTS_DIR / "fixtures" / "sample.jpg")
    env_values = {
        **existing,
        "CLASS_SESSION_ID": str(class_session_id),
        "STUDENT_TOKENS_FILE": str(STUDENT_MARK_TOKENS_FILE),
        "FACE_IMAGE_PATH": face_path,
        "MARK_USERS": str(mark_users),
        "LOCUST_HOST": existing.get("LOCUST_HOST", ai_attendance_base()),
        "TEACHER_TOKEN": teacher_token,
    }
    write_env_file(LOCAL_ENV, env_values)

    print(
        f"[prepare_mark_session] Wrote {len(final_tokens)} token slot(s) → {STUDENT_MARK_TOKENS_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
