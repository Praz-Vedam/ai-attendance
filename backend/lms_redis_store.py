"""Redis-backed live attendance marks for LMS-integrated face sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from redis_client import redis_client

SESSION_TTL_SECONDS = 24 * 60 * 60


def _session_key(class_session_id: int) -> str:
    return f"lms:attendance:session:{class_session_id}"


def _marks_key(class_session_id: int) -> str:
    return f"lms:attendance:marks:{class_session_id}"


def _snapshot_key(class_session_id: int, email: str) -> str:
    safe_email = email.replace("@", "_at_").replace(".", "_")
    return f"lms:attendance:snapshot:{class_session_id}:{safe_email}"


def init_session(
    class_session_id: int,
    *,
    classroom: Optional[str],
    teacher_ip: Optional[str],
    campus_id: Optional[int],
) -> Dict[str, Any]:
    payload = {
        "class_session_id": class_session_id,
        "active": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "classroom": classroom,
        "teacher_ip": teacher_ip,
        "campus_id": campus_id,
    }
    pipe = redis_client.pipeline()
    pipe.set(_session_key(class_session_id), json.dumps(payload).encode("utf-8"))
    pipe.expire(_session_key(class_session_id), SESSION_TTL_SECONDS)
    pipe.delete(_marks_key(class_session_id))
    pipe.execute()
    return payload


def get_session(class_session_id: int) -> Optional[Dict[str, Any]]:
    raw = redis_client.get(_session_key(class_session_id))
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def is_session_active(class_session_id: int) -> bool:
    session = get_session(class_session_id)
    return bool(session and session.get("active"))


def has_mark(class_session_id: int, email: str) -> bool:
    return redis_client.hexists(_marks_key(class_session_id), email)


def add_mark(
    class_session_id: int,
    email: str,
    record: Dict[str, Any],
    snapshot_bytes: Optional[bytes] = None,
) -> None:
    marks_key = _marks_key(class_session_id)
    pipe = redis_client.pipeline()
    pipe.hset(marks_key, email, json.dumps(record).encode("utf-8"))
    pipe.expire(marks_key, SESSION_TTL_SECONDS)
    if snapshot_bytes:
        snap_key = _snapshot_key(class_session_id, email)
        pipe.set(snap_key, snapshot_bytes)
        pipe.expire(snap_key, SESSION_TTL_SECONDS)
    pipe.execute()


def get_mark(class_session_id: int, email: str) -> Optional[Dict[str, Any]]:
    raw = redis_client.hget(_marks_key(class_session_id), email)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def list_marks(class_session_id: int) -> List[Dict[str, Any]]:
    raw_map = redis_client.hgetall(_marks_key(class_session_id))
    marks: List[Dict[str, Any]] = []
    for raw in raw_map.values():
        record = json.loads(raw.decode("utf-8"))
        marks.append(record)
    marks.sort(key=lambda item: item.get("marked_at", ""))
    return marks


def get_snapshot(class_session_id: int, email: str) -> Optional[bytes]:
    return redis_client.get(_snapshot_key(class_session_id, email))


def clear_session(class_session_id: int) -> None:
    marks_key = _marks_key(class_session_id)
    emails = [
        key.decode("utf-8") if isinstance(key, bytes) else key
        for key in redis_client.hkeys(marks_key)
    ]
    pipe = redis_client.pipeline()
    pipe.delete(_session_key(class_session_id))
    pipe.delete(marks_key)
    for email in emails:
        pipe.delete(_snapshot_key(class_session_id, email))
    pipe.execute()


def deactivate_session(class_session_id: int) -> None:
    session = get_session(class_session_id)
    if not session:
        return
    session["active"] = False
    session["ended_at"] = datetime.now(timezone.utc).isoformat()
    redis_client.set(
        _session_key(class_session_id),
        json.dumps(session).encode("utf-8"),
        ex=SESSION_TTL_SECONDS,
    )
