from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from local_db import (
    ensure_dirs,
    load_students_index,
    save_students_index,
    session_path,
    student_path,
)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_student(email: str) -> Optional[Dict[str, Any]]:
    path = student_path(normalize_email(email))
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_student(student: Dict[str, Any]) -> None:
    email = normalize_email(student["email"])
    student["email"] = email
    ensure_dirs()
    path = student_path(email)
    path.write_text(json.dumps(student, indent=2), encoding="utf-8")

    index = load_students_index()
    if email not in index:
        index.append(email)
        save_students_index(index)


def list_students() -> List[Dict[str, Any]]:
    students: List[Dict[str, Any]] = []
    for email in load_students_index():
        student = get_student(email)
        if student:
            students.append(student)
    return students


def upsert_face(
    email: str,
    embedding: List[float],
    name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    student = get_student(email)
    if student is None:
        return None

    if name is not None:
        trimmed = name.strip()
        if trimmed:
            student["name"] = trimmed

    student["embedding"] = embedding
    student["face_registered_at"] = datetime.now(timezone.utc).isoformat()
    save_student(student)
    return student


def student_has_face(student: Dict[str, Any]) -> bool:
    embedding = student.get("embedding")
    return isinstance(embedding, list) and len(embedding) > 0


def create_student_with_face(name: str, embedding: List[float]) -> Dict[str, Any]:
    student_id = str(uuid.uuid4())
    email = f"{student_id}@student.local"
    created_at = datetime.now(timezone.utc).isoformat()
    student = {
        "email": email,
        "student_id": student_id,
        "name": name.strip(),
        "embedding": embedding,
        "face_registered_at": created_at,
        "created_at": created_at,
    }
    save_student(student)
    return student


def create_session(email: str, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    ensure_dirs()
    path = session_path(token)
    path.write_text(
        json.dumps(
            {
                "email": normalize_email(email),
                "expires_at": time.time() + ttl_seconds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return token


def get_session_email(token: str) -> Optional[str]:
    if not token:
        return None

    path = session_path(token)
    if not path.is_file():
        return None

    record = json.loads(path.read_text(encoding="utf-8"))
    expires_at = record.get("expires_at")
    if expires_at is not None and time.time() > float(expires_at):
        path.unlink(missing_ok=True)
        return None

    email = record.get("email")
    return normalize_email(email) if email else None
