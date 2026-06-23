#!/usr/bin/env python3
"""
Prepare a single class session for concurrent mark-attendance load testing.

Works with 1 teacher + 1 student token (replicated for concurrent users).

Steps:
  1. Resolve CLASS_SESSION_ID and teacher token
  2. POST /lms/attendance/start — imports LMS roster, bulk-loads face-api embeddings to Redis
  3. Resolve student access token + 128-d face_embedding JSON from LMS
  4. Write student_tokens_mark.txt (replicated to MARK_USERS lines)
"""

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
    read_token_lines,
    resolve_mark_embeddings,
    resolve_student_access_tokens,
    resolve_teacher_token,
    start_attendance_session,
    write_env_file,
    write_token_lines,
)

STUDENT_REFRESH_TOKENS_FILE = LOAD_TESTS_DIR / "student_refresh_tokens.txt"
STUDENT_MARK_TOKENS_FILE = LOAD_TESTS_DIR / "student_tokens_mark.txt"
STUDENT_EMBEDDINGS_FILE = LOAD_TESTS_DIR / "student_embeddings.json"
DEFAULT_MARK_USERS = 100
DEFAULT_LOCUST_USERS = 300


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


def _resolve_student_tokens(class_session_id: int) -> list[str]:
    tokens = resolve_student_access_tokens(class_session_id=class_session_id)
    if tokens:
        return tokens

    access_tokens: list[str] = []
    for refresh in _read_refresh_tokens():
        from env_util import is_valid_token, refresh_access_token

        token = refresh_access_token(refresh)
        if token and is_valid_token(token, class_session_id=class_session_id, student=True):
            access_tokens.append(token)
    return list(dict.fromkeys(access_tokens))


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_secrets_env(SECRETS_ENV)
    load_dotenv(LOCAL_ENV)

    existing = parse_env_file(LOCAL_ENV)
    mark_users = int(os.getenv("MARK_USERS", str(DEFAULT_MARK_USERS)))
    locust_users = int(os.getenv("LOCUST_USERS", str(DEFAULT_LOCUST_USERS)))
    if locust_users < mark_users:
        locust_users = mark_users

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

    teacher_token = resolve_teacher_token(existing, class_session_id=class_session_id)
    if not teacher_token:
        print(
            "[prepare_mark_session] No valid teacher token — check LOAD_TEST_TEACHER_* "
            "in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    try:
        result = start_attendance_session(teacher_token, class_session_id)
        if not result.get("success"):
            print(
                f"[prepare_mark_session] Failed to start session: {result.get('message')}",
                file=sys.stderr,
            )
            return 1
        face_loaded = int(result.get("face_embeddings_loaded") or 0)
        students_with_face = int(result.get("students_with_face_data") or 0)
        print(
            f"[prepare_mark_session] Started session {class_session_id}: "
            f"{result.get('message', 'ok')} — "
            f"{face_loaded} embedding(s) cached, "
            f"{students_with_face} enrolled student(s) with face data"
        )
        if face_loaded == 0:
            print(
                "[prepare_mark_session] WARNING: No face embeddings cached for this session. "
                "Ensure students are enrolled and have face-api data in LMS.",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"[prepare_mark_session] Failed to start attendance session: {exc}", file=sys.stderr)
        return 1

    access_tokens = _resolve_student_tokens(class_session_id)
    if not access_tokens:
        print(
            "[prepare_mark_session] No valid student token — check LOAD_TEST_STUDENT_* "
            "in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    unique_count = len(access_tokens)
    if unique_count == 1:
        print(
            f"[prepare_mark_session] 1 student token — {locust_users} virtual users "
            f"({mark_users} mark requests); expect ≤1 successful mark per enrolled student."
        )
    elif unique_count < mark_users:
        print(
            f"[prepare_mark_session] {unique_count} student token(s) for {mark_users} mark users."
        )

    final_tokens = (access_tokens * ((locust_users // unique_count) + 1))[:locust_users]
    write_token_lines(STUDENT_MARK_TOKENS_FILE, final_tokens)

    embeddings = resolve_mark_embeddings(
        dict.fromkeys(final_tokens),
        embeddings_file=STUDENT_EMBEDDINGS_FILE,
        fallback_embedding_json=os.getenv("FACE_EMBEDDING_JSON", "").strip(),
    )
    if not embeddings:
        print(
            "[prepare_mark_session] No face-api embeddings — enroll the student in the "
            "student portal or set FACE_EMBEDDING_JSON in load_tests/secrets.env",
            file=sys.stderr,
        )
        return 1

    face_path = existing.get("FACE_IMAGE_PATH") or str(LOAD_TESTS_DIR / "fixtures" / "sample.jpg")
    env_values = {
        **existing,
        "CLASS_SESSION_ID": str(class_session_id),
        "STUDENT_TOKENS_FILE": str(STUDENT_MARK_TOKENS_FILE),
        "STUDENT_EMBEDDINGS_FILE": str(STUDENT_EMBEDDINGS_FILE),
        "FACE_IMAGE_PATH": face_path,
        "MARK_USERS": str(mark_users),
        "LOCUST_USERS": str(locust_users),
        "POLL_USERS": str(max(locust_users - mark_users, 0)),
        "MARK_WINDOW_SECONDS": os.getenv("MARK_WINDOW_SECONDS", "15").strip(),
        "MARK_DISTRIBUTION": os.getenv("MARK_DISTRIBUTION", "burst").strip(),
        "MARK_BURST_SECONDS": os.getenv("MARK_BURST_SECONDS", "3").strip(),
        "LOCUST_HOST": existing.get("LOCUST_HOST", ai_attendance_base()),
        "TEACHER_TOKEN": teacher_token,
    }
    write_env_file(LOCAL_ENV, env_values)

    print(
        f"[prepare_mark_session] Wrote {len(final_tokens)} token slot(s) → {STUDENT_MARK_TOKENS_FILE}"
    )
    print(
        f"[prepare_mark_session] Resolved {len(embeddings)} face-api embedding(s) → "
        f"{STUDENT_EMBEDDINGS_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
