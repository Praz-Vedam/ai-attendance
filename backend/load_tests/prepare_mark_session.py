#!/usr/bin/env python3
"""Start class session and prepare tokens for concurrent mark-attendance test."""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOAD_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LOAD_TESTS_DIR))

from env_util import (  # noqa: E402
    BACKEND_DIR,
    LOCAL_ENV,
    SECRETS_ENV,
    ai_attendance_base,
    find_active_class_session_id,
    load_dotenv,
    load_secrets_env,
    parse_env_file,
    resolve_student_tokens,
    resolve_teacher_token,
    start_attendance_session,
    write_env_file,
    write_token_lines,
)

STUDENT_MARK_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens_mark.txt"
DEFAULT_MARK_USERS = 150


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_secrets_env(SECRETS_ENV)
    load_dotenv(LOCAL_ENV)

    existing = parse_env_file(LOCAL_ENV)
    mark_users = int(os.getenv("MARK_USERS", str(DEFAULT_MARK_USERS)))
    class_session_id = int(
        os.getenv("CLASS_SESSION_ID") or existing.get("CLASS_SESSION_ID") or 0
    )
    if class_session_id <= 0:
        class_session_id = find_active_class_session_id()
    if class_session_id <= 0:
        print("[prepare_mark_session] Set CLASS_SESSION_ID in secrets.env", file=sys.stderr)
        return 1

    teacher_token = resolve_teacher_token(existing, class_session_id=class_session_id)
    if not teacher_token:
        print(
            "[prepare_mark_session] No valid teacher token — check TEACHER_TOKEN in "
            "local.env or LOAD_TEST_TEACHER_* in secrets.env",
            file=sys.stderr,
        )
        return 1

    try:
        result = start_attendance_session(teacher_token, class_session_id)
        print(f"[prepare_mark_session] Session {class_session_id}: {result.get('message', 'ok')}")
    except Exception as exc:
        print(f"[prepare_mark_session] start failed: {exc}", file=sys.stderr)
        return 1

    access_tokens = resolve_student_tokens(
        LOAD_TESTS_DIR / "student_tokens.txt",
        class_session_id=class_session_id,
    )
    if not access_tokens:
        print(
            "[prepare_mark_session] No valid student token — check LOAD_TEST_STUDENT_* "
            "in secrets.env",
            file=sys.stderr,
        )
        return 1

    if len(access_tokens) == 1:
        print(
            f"[prepare_mark_session] 1 student × {mark_users} concurrent marks — "
            "expect ~1 success; rest exercises ML/auth under load."
        )

    unique = len(access_tokens)
    final = (access_tokens * ((mark_users // unique) + 1))[:mark_users]
    write_token_lines(STUDENT_MARK_TOKENS_FILE, final)

    write_env_file(
        LOCAL_ENV,
        {
            **existing,
            "CLASS_SESSION_ID": str(class_session_id),
            "STUDENT_TOKENS_FILE": str(STUDENT_MARK_TOKENS_FILE),
            "FACE_IMAGE_PATH": existing.get(
                "FACE_IMAGE_PATH", str(LOAD_TESTS_DIR / "fixtures" / "sample.jpg")
            ),
            "MARK_USERS": str(mark_users),
            "LOCUST_HOST": existing.get("LOCUST_HOST", ai_attendance_base()),
            "TEACHER_TOKEN": teacher_token,
            "ENABLE_MARK_TASK": existing.get("ENABLE_MARK_TASK", "1"),
        },
    )
    print(f"[prepare_mark_session] {len(final)} token slots → {STUDENT_MARK_TOKENS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
