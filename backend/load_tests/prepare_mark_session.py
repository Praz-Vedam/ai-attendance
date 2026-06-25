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
    DEFAULT_MARK_STUDENT_TOKENS,
    DEFAULT_POLL_STUDENT_TOKENS,
    LOCAL_ENV,
    SECRETS_ENV,
    STUDENT_REFRESH_TOKENS_FILE,
    ai_attendance_base,
    allow_duplicate_mark_tokens,
    assign_mark_and_poll_tokens,
    find_active_class_session_id,
    load_dotenv,
    load_secrets_env,
    parse_env_file,
    read_token_lines,
    resolve_distinct_student_tokens,
    resolve_mark_embeddings,
    resolve_teacher_token,
    start_attendance_session,
    write_env_file,
    write_token_lines,
)

STUDENT_MARK_TOKENS_FILE = DEFAULT_MARK_STUDENT_TOKENS
STUDENT_POLL_TOKENS_FILE = DEFAULT_POLL_STUDENT_TOKENS
STUDENT_EMBEDDINGS_FILE = LOAD_TESTS_DIR / "student_embeddings.json"
DEFAULT_MARK_USERS = 150
DEFAULT_POLL_USERS = 150


def _resolve_student_tokens(class_session_id: int) -> list[str]:
    return resolve_distinct_student_tokens(
        class_session_id=class_session_id,
        refresh_tokens_file=STUDENT_REFRESH_TOKENS_FILE,
    )


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    load_secrets_env(SECRETS_ENV)
    load_dotenv(LOCAL_ENV)

    existing = parse_env_file(LOCAL_ENV)
    mark_users = int(os.getenv("MARK_USERS", str(DEFAULT_MARK_USERS)))
    poll_users = int(os.getenv("POLL_USERS", str(DEFAULT_POLL_USERS)))

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

    if mark_users == 0 and poll_users == 0:
        face_path = existing.get("FACE_IMAGE_PATH") or str(
            LOAD_TESTS_DIR / "fixtures" / "sample.jpg"
        )
        env_values = {
            **existing,
            "CLASS_SESSION_ID": str(class_session_id),
            "FACE_IMAGE_PATH": face_path,
            "MARK_USERS": "0",
            "POLL_USERS": "0",
            "LOCUST_USERS": "0",
            "LOCUST_HOST": existing.get("LOCUST_HOST", ai_attendance_base()),
            "TEACHER_TOKEN": teacher_token,
        }
        write_env_file(LOCAL_ENV, env_values)
        print(
            f"[prepare_mark_session] Session {class_session_id} ready "
            "(no student tokens — mark/poll users are 0)"
        )
        return 0

    access_tokens = _resolve_student_tokens(class_session_id)
    if not access_tokens:
        print(
            "[prepare_mark_session] No valid student token — check LOAD_TEST_STUDENT_* "
            f"in load_tests/secrets.env or add refresh tokens to {STUDENT_REFRESH_TOKENS_FILE.name}",
            file=sys.stderr,
        )
        return 1

    unique_count = len(access_tokens)
    try:
        mark_tokens, poll_tokens = assign_mark_and_poll_tokens(
            access_tokens,
            mark_users=mark_users,
            poll_users=poll_users,
            allow_duplicate_marks=allow_duplicate_mark_tokens(),
        )
    except ValueError as exc:
        print(f"[prepare_mark_session] {exc}", file=sys.stderr)
        return 1

    if unique_count < mark_users and not allow_duplicate_mark_tokens():
        print(
            f"[prepare_mark_session] {unique_count} distinct student(s) for "
            f"{mark_users} mark users — each mark user gets a unique token "
            f"(face verification under load)."
        )
    elif unique_count == 1 and allow_duplicate_mark_tokens():
        print(
            f"[prepare_mark_session] 1 student token — {mark_users} mark requests; "
            "only the first mark per student runs face verification."
        )

    write_token_lines(STUDENT_MARK_TOKENS_FILE, mark_tokens)
    write_token_lines(STUDENT_POLL_TOKENS_FILE, poll_tokens)

    embeddings = resolve_mark_embeddings(
        mark_tokens,
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
        "STUDENT_TOKENS_FILE": str(STUDENT_POLL_TOKENS_FILE),
        "MARK_STUDENT_TOKENS_FILE": str(STUDENT_MARK_TOKENS_FILE),
        "POLL_STUDENT_TOKENS_FILE": str(STUDENT_POLL_TOKENS_FILE),
        "STUDENT_EMBEDDINGS_FILE": str(STUDENT_EMBEDDINGS_FILE),
        "FACE_IMAGE_PATH": face_path,
        "MARK_USERS": str(mark_users),
        "POLL_USERS": str(poll_users),
        "LOCUST_USERS": str(mark_users + poll_users),
        "MARK_WINDOW_SECONDS": os.getenv("MARK_WINDOW_SECONDS", "15").strip(),
        "MARK_DISTRIBUTION": os.getenv("MARK_DISTRIBUTION", "burst").strip(),
        "MARK_BURST_SECONDS": os.getenv("MARK_BURST_SECONDS", "3").strip(),
        "LOCUST_HOST": existing.get("LOCUST_HOST", ai_attendance_base()),
        "TEACHER_TOKEN": teacher_token,
    }
    write_env_file(LOCAL_ENV, env_values)

    print(
        f"[prepare_mark_session] Wrote {len(mark_tokens)} mark token(s) → {STUDENT_MARK_TOKENS_FILE}"
    )
    if poll_tokens:
        print(
            f"[prepare_mark_session] Wrote {len(poll_tokens)} poll token(s) → "
            f"{STUDENT_POLL_TOKENS_FILE}"
        )
    print(
        f"[prepare_mark_session] Resolved {len(embeddings)} face-api embedding(s) → "
        f"{STUDENT_EMBEDDINGS_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
