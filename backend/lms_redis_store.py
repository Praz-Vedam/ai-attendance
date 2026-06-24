"""Redis-backed live attendance marks for LMS-integrated face sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from redis_client import redis_client
from face_matching import parse_embedding_payload

SESSION_TTL_SECONDS = 24 * 60 * 60
EMBEDDING_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
REVIEW_QUEUE_KEY = "lms:attendance:review_queue"


def _session_key(class_session_id: int) -> str:
    return f"lms:attendance:session:{class_session_id}"


def _marks_key(class_session_id: int) -> str:
    return f"lms:attendance:marks:{class_session_id}"


def _snapshot_key(class_session_id: int, email: str) -> str:
    safe_email = email.replace("@", "_at_").replace(".", "_")
    return f"lms:attendance:snapshot:{class_session_id}:{safe_email}"


def _embedding_cache_key(email: str) -> str:
    safe_email = email.lower().replace("@", "_at_").replace(".", "_")
    return f"lms:face:embedding:{safe_email}"


def _session_embeddings_key(class_session_id: int) -> str:
    return f"lms:attendance:face_embeddings:{class_session_id}"


def _session_roster_key(class_session_id: int) -> str:
    return f"lms:attendance:face_roster:{class_session_id}"


def _mark_failures_key(class_session_id: int) -> str:
    return f"lms:attendance:mark_failures:{class_session_id}"


def _failure_snapshot_key(class_session_id: int, email: str) -> str:
    safe_email = email.replace("@", "_at_").replace(".", "_")
    return f"lms:attendance:failure_snapshot:{class_session_id}:{safe_email}"


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
        "submitted": False,
        "review_status": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "classroom": classroom,
        "teacher_ip": teacher_ip,
        "campus_id": campus_id,
    }
    pipe = redis_client.pipeline()
    pipe.set(_session_key(class_session_id), json.dumps(payload).encode("utf-8"))
    pipe.expire(_session_key(class_session_id), SESSION_TTL_SECONDS)
    pipe.delete(_marks_key(class_session_id))
    pipe.delete(_session_embeddings_key(class_session_id))
    pipe.delete(_session_roster_key(class_session_id))
    _delete_failure_snapshots(pipe, class_session_id)
    pipe.delete(_mark_failures_key(class_session_id))
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


def update_mark(
    class_session_id: int,
    email: str,
    patch: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    marks_key = _marks_key(class_session_id)
    raw = redis_client.hget(marks_key, email)
    if not raw:
        return None
    record = json.loads(raw.decode("utf-8"))
    record.update(patch)
    redis_client.hset(marks_key, email, json.dumps(record).encode("utf-8"))
    redis_client.expire(marks_key, SESSION_TTL_SECONDS)
    return record


def get_mark(class_session_id: int, email: str) -> Optional[Dict[str, Any]]:
    raw = redis_client.hget(_marks_key(class_session_id), email)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def mark_risk_sort_key(mark: Dict[str, Any]) -> tuple:
    """Sort marks by deferred AI review risk (spoof + location only, not IP)."""
    review = mark.get("review_status")
    if review != "complete":
        return (1, 9, 9, 0.0, 0.0, mark.get("marked_at", ""))

    status = mark.get("status") or "Present"
    status_order = {"Rejected": 0, "Flagged": 1, "Present": 2}.get(status, 3)
    reason_order = {
        "Spoof detected": 0,
        "Outside Classroom": 1,
        "Wrong Classroom": 2,
    }.get(mark.get("reason") or "", 3)

    spoof = mark.get("spoof_confidence")
    spoof_risk = float(spoof) if spoof is not None else 0.0

    location = mark.get("location_confidence")
    location_risk = float(location) if location is not None else 0.0

    return (0, status_order, reason_order, -spoof_risk, -location_risk, mark.get("marked_at", ""))


def list_marks(class_session_id: int) -> List[Dict[str, Any]]:
    raw_map = redis_client.hgetall(_marks_key(class_session_id))
    marks: List[Dict[str, Any]] = []
    for raw in raw_map.values():
        record = json.loads(raw.decode("utf-8"))
        marks.append(record)
    marks.sort(key=mark_risk_sort_key)
    return marks


def get_snapshot(class_session_id: int, email: str) -> Optional[bytes]:
    return redis_client.get(_snapshot_key(class_session_id, email))


def get_failure_snapshot(class_session_id: int, email: str) -> Optional[bytes]:
    return redis_client.get(_failure_snapshot_key(class_session_id, email))


def add_mark_failure(
    class_session_id: int,
    email: str,
    record: Dict[str, Any],
    snapshot_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    failures_key = _mark_failures_key(class_session_id)
    normalized_email = email.lower()
    attempt_count = 1
    existing_raw = redis_client.hget(failures_key, normalized_email)
    if existing_raw:
        try:
            existing = json.loads(existing_raw.decode("utf-8"))
            attempt_count = int(existing.get("attempt_count") or 0) + 1
        except (TypeError, ValueError):
            attempt_count = 1

    payload = {
        **record,
        "email": normalized_email,
        "attempt_count": attempt_count,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "has_snapshot": bool(snapshot_bytes),
    }

    pipe = redis_client.pipeline()
    pipe.hset(failures_key, normalized_email, json.dumps(payload).encode("utf-8"))
    pipe.expire(failures_key, SESSION_TTL_SECONDS)
    if snapshot_bytes:
        snap_key = _failure_snapshot_key(class_session_id, normalized_email)
        pipe.set(snap_key, snapshot_bytes)
        pipe.expire(snap_key, SESSION_TTL_SECONDS)
    pipe.execute()
    return payload


def get_mark_failure(class_session_id: int, email: str) -> Optional[Dict[str, Any]]:
    raw = redis_client.hget(_mark_failures_key(class_session_id), email.lower())
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def list_mark_failures(class_session_id: int) -> List[Dict[str, Any]]:
    raw_map = redis_client.hgetall(_mark_failures_key(class_session_id))
    failures: List[Dict[str, Any]] = []
    for raw in raw_map.values():
        failures.append(json.loads(raw.decode("utf-8")))
    failures.sort(key=lambda item: item.get("attempted_at") or "", reverse=True)
    return failures


def clear_mark_failure(class_session_id: int, email: str) -> None:
    normalized_email = email.lower()
    pipe = redis_client.pipeline()
    pipe.hdel(_mark_failures_key(class_session_id), normalized_email)
    pipe.delete(_failure_snapshot_key(class_session_id, normalized_email))
    pipe.execute()


def _delete_failure_snapshots(pipe, class_session_id: int) -> None:
    failure_emails = redis_client.hkeys(_mark_failures_key(class_session_id))
    for email_key in failure_emails:
        email = email_key.decode("utf-8") if isinstance(email_key, bytes) else email_key
        pipe.delete(_failure_snapshot_key(class_session_id, email))


def clear_session(class_session_id: int) -> None:
    marks_key = _marks_key(class_session_id)
    emails = [
        key.decode("utf-8") if isinstance(key, bytes) else key
        for key in redis_client.hkeys(marks_key)
    ]
    pipe = redis_client.pipeline()
    pipe.delete(_session_key(class_session_id))
    pipe.delete(marks_key)
    pipe.delete(_session_embeddings_key(class_session_id))
    pipe.delete(_session_roster_key(class_session_id))
    _delete_failure_snapshots(pipe, class_session_id)
    pipe.delete(_mark_failures_key(class_session_id))
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


def mark_session_submitted(class_session_id: int) -> None:
    """Close the live session but keep marks so students can still poll their status."""
    session = get_session(class_session_id)
    if not session:
        return
    session["active"] = False
    session["submitted"] = True
    session["submitted_at"] = datetime.now(timezone.utc).isoformat()
    session["ended_at"] = session.get("ended_at") or datetime.now(timezone.utc).isoformat()
    if session.get("review_status") is None:
        session["review_status"] = "pending"
    pipe = redis_client.pipeline()
    pipe.set(
        _session_key(class_session_id),
        json.dumps(session).encode("utf-8"),
        ex=SESSION_TTL_SECONDS,
    )
    pipe.expire(_marks_key(class_session_id), SESSION_TTL_SECONDS)
    pipe.execute()


def set_session_review_status(
    class_session_id: int,
    review_status: str,
    *,
    flagged_count: Optional[int] = None,
    rejected_count: Optional[int] = None,
    review_error: Optional[str] = None,
) -> None:
    session = get_session(class_session_id)
    if not session:
        return
    session["review_status"] = review_status
    if review_status == "in_progress":
        session["review_started_at"] = datetime.now(timezone.utc).isoformat()
    if review_status == "complete":
        session["review_completed_at"] = datetime.now(timezone.utc).isoformat()
    if flagged_count is not None:
        session["flagged_count"] = flagged_count
    if rejected_count is not None:
        session["rejected_count"] = rejected_count
    if review_error is not None:
        session["review_error"] = review_error
    redis_client.set(
        _session_key(class_session_id),
        json.dumps(session).encode("utf-8"),
        ex=SESSION_TTL_SECONDS,
    )


def cache_face_embedding(email: str, embedding: List[float]) -> None:
    payload = json.dumps({"embedding": embedding}).encode("utf-8")
    redis_client.set(_embedding_cache_key(email), payload, ex=EMBEDDING_CACHE_TTL_SECONDS)


def get_cached_face_embedding(email: str) -> Optional[List[float]]:
    raw = redis_client.get(_embedding_cache_key(email.lower()))
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (TypeError, ValueError):
        return None
    embedding = parse_embedding_payload(payload)
    return embedding or None


def invalidate_face_embedding_cache(email: str) -> None:
    redis_client.delete(_embedding_cache_key(email.lower()))


def cache_session_face_embeddings(
    class_session_id: int,
    embeddings_by_email: Dict[str, List[float]],
) -> int:
    key = _session_embeddings_key(class_session_id)
    pipe = redis_client.pipeline()
    pipe.delete(key)
    stored_count = 0
    for email, embedding in embeddings_by_email.items():
        if not embedding:
            continue
        pipe.hset(
            key,
            email.lower(),
            json.dumps({"embedding": embedding}).encode("utf-8"),
        )
        stored_count += 1
    pipe.expire(key, SESSION_TTL_SECONDS)
    pipe.execute()
    return stored_count


def get_session_face_embedding(
    class_session_id: int,
    email: str,
) -> Optional[List[float]]:
    raw = redis_client.hget(_session_embeddings_key(class_session_id), email.lower())
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (TypeError, ValueError):
        return None
    embedding = parse_embedding_payload(payload)
    return embedding or None


def cache_session_face_embedding(
    class_session_id: int,
    email: str,
    embedding: List[float],
) -> None:
    if not embedding:
        return
    key = _session_embeddings_key(class_session_id)
    redis_client.hset(
        key,
        email.lower(),
        json.dumps({"embedding": embedding}).encode("utf-8"),
    )
    redis_client.expire(key, SESSION_TTL_SECONDS)


def has_session_face_embedding(class_session_id: int, email: str) -> bool:
    return redis_client.hexists(
        _session_embeddings_key(class_session_id),
        email.lower(),
    )


def cache_session_face_roster(
    class_session_id: int,
    students: List[Dict[str, Any]],
) -> None:
    key = _session_roster_key(class_session_id)
    pipe = redis_client.pipeline()
    pipe.delete(key)
    for student in students:
        email = (student.get("email") or "").lower()
        if not email:
            continue
        pipe.hset(
            key,
            email,
            json.dumps(
                {
                    "email": student.get("email"),
                    "hasFaceData": bool(student.get("hasFaceData")),
                }
            ).encode("utf-8"),
        )
    pipe.expire(key, SESSION_TTL_SECONDS)
    pipe.execute()


def get_session_face_roster_map(class_session_id: int) -> Dict[str, Dict[str, Any]]:
    raw_map = redis_client.hgetall(_session_roster_key(class_session_id))
    roster: Dict[str, Dict[str, Any]] = {}
    for raw in raw_map.values():
        try:
            student = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError):
            continue
        email = (student.get("email") or "").lower()
        if email:
            roster[email] = student
    return roster


def enqueue_session_review(class_session_id: int) -> None:
    redis_client.rpush(REVIEW_QUEUE_KEY, str(class_session_id))


def try_acquire_review_lock(class_session_id: int) -> bool:
    key = f"lms:attendance:review_lock:{class_session_id}"
    return bool(redis_client.set(key, "1", nx=True, ex=SESSION_TTL_SECONDS))


def release_review_lock(class_session_id: int) -> None:
    redis_client.delete(f"lms:attendance:review_lock:{class_session_id}")


def reset_session_for_review(class_session_id: int) -> None:
    """Clear prior review results so spoof/location checks can run again."""
    session = get_session(class_session_id)
    if session:
        session["review_status"] = "pending"
        session.pop("review_started_at", None)
        session.pop("review_completed_at", None)
        session.pop("flagged_count", None)
        session.pop("rejected_count", None)
        session.pop("review_error", None)
        redis_client.set(
            _session_key(class_session_id),
            json.dumps(session).encode("utf-8"),
            ex=SESSION_TTL_SECONDS,
        )

    marks_key = _marks_key(class_session_id)
    emails = [
        key.decode("utf-8") if isinstance(key, bytes) else key
        for key in redis_client.hkeys(marks_key)
    ]
    for email in emails:
        raw = redis_client.hget(marks_key, email)
        if not raw:
            continue
        record = json.loads(raw.decode("utf-8"))
        record["status"] = "Present"
        record["review_status"] = "pending"
        record.pop("reason", None)
        record.pop("spoof_confidence", None)
        record.pop("location", None)
        record.pop("location_confidence", None)
        record.pop("reviewed_at", None)
        redis_client.hset(marks_key, email, json.dumps(record).encode("utf-8"))


def dequeue_session_review(timeout_seconds: int = 5) -> Optional[int]:
    result = redis_client.brpop(REVIEW_QUEUE_KEY, timeout=timeout_seconds)
    if not result:
        return None
    _, raw = result
    try:
        return int(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (TypeError, ValueError):
        return None
