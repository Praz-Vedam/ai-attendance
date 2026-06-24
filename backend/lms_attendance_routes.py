"""LMS-integrated face attendance routes backed by Redis."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import AliasChoices, BaseModel, Field

from lms_client import (
    LmsApiError,
    bulk_update_attendance,
    get_attendance_records,
    get_bulk_face_embeddings,
    get_face_embedding,
    get_face_status_by_email,
    import_attendance,
    parse_bulk_face_data_response,
    parse_face_embedding,
    register_face_embedding,
    validate_lms_token,
)
from face_matching import (
    FACE_API_ONLY_MESSAGE,
    embedding_format_mismatch_message,
    is_face_api_embedding,
    parse_client_embedding,
)
from ml_config import DEFER_ML_REVIEW, location_attendance_status
from lms_redis_store import (
    add_mark,
    add_mark_failure,
    cache_face_embedding,
    cache_session_face_embedding,
    cache_session_face_embeddings,
    cache_session_face_roster,
    clear_session,
    clear_mark_failure,
    get_cached_face_embedding,
    get_failure_snapshot,
    get_mark,
    get_mark_failure,
    get_session,
    get_session_face_embedding,
    get_session_face_roster_map,
    get_snapshot,
    has_mark,
    init_session,
    is_session_active,
    list_mark_failures,
    list_marks,
    mark_session_submitted,
)
from session_review import schedule_session_review

router = APIRouter(prefix="/lms", tags=["lms"])
logger = logging.getLogger(__name__)

FACE_MATCH_MAX_ATTEMPTS = 2
LEGACY_FACE_ENROLLMENT_MESSAGE = (
    "Face enrollment must be updated to browser face-api.js. "
    "Re-enroll in the student portal."
)
STUDENT_FACE_MISMATCH_MESSAGE = (
    "This face does not match your enrolled profile. "
    "Make sure you are the enrolled student, then try once more."
)
STUDENT_FACE_MISMATCH_FINAL_MESSAGE = (
    "Face verification failed. Attendance was not recorded. "
    "Contact your instructor if you need help."
)
STUDENT_FACE_MATCH_LOCKED_MESSAGE = (
    "Face verification failed. Attendance was not recorded. "
    "Contact your instructor."
)


class LmsAttendanceStartRequest(BaseModel):
    class_session_id: int = Field(
        validation_alias=AliasChoices("class_session_id", "classSessionId")
    )
    classroom: Optional[str] = None


class LmsAttendanceSessionRequest(BaseModel):
    class_session_id: int = Field(
        validation_alias=AliasChoices("class_session_id", "classSessionId")
    )


class LmsAttendanceReviewRequest(BaseModel):
    class_session_id: int = Field(
        validation_alias=AliasChoices("class_session_id", "classSessionId")
    )
    force: bool = False


def require_lms_token(
    authorization: Annotated[Optional[str], Header()] = None,
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("[FE →] Missing or invalid Authorization header: %s", authorization)
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    logger.info("[FE →] accessToken received: %s", token)
    return token


async def require_lms_auth(token: str = Depends(require_lms_token)) -> Dict[str, Any]:
    try:
        return await validate_lms_token(token)
    except LmsApiError as exc:
        logger.warning("[LMS auth] %s (lms_status=%s)", exc, exc.lms_status)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[LMS auth] Unexpected error validating token")
        raise HTTPException(
            status_code=502,
            detail="Could not verify LMS token",
        ) from exc


def _public_mark(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(record)
    payload["has_snapshot"] = bool(record.get("has_snapshot"))
    return payload


def _campus_id_from_auth(auth: Dict[str, Any]) -> Optional[int]:
    """LMS /auth/detail returns campus id on campusDetail.id (CampusDto), not campusId."""
    campus = auth.get("campusDetail") or auth.get("campusDto") or {}
    raw = campus.get("id") if campus else None
    if raw is None:
        raw = campus.get("campusId") if campus else None
    if raw is None:
        raw = auth.get("campusId")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _map_lms_status(_ai_status: str) -> str:
    return "PRESENT"


async def _resolve_stored_face_embedding(
    token: str,
    class_session_id: int,
    email: str,
) -> Optional[List[float]]:
    """
    Resolve enrolled face embedding for marking.

    Session Redis is populated when the teacher starts attendance. Fall back to
    the per-email cache (set on /face/register) and LMS when missing — e.g.
    student enrolled after the session started.
    """
    stored_embedding = get_session_face_embedding(class_session_id, email)
    if stored_embedding:
        return stored_embedding

    stored_embedding = get_cached_face_embedding(email)
    if stored_embedding:
        cache_session_face_embedding(class_session_id, email, stored_embedding)
        return stored_embedding

    try:
        face_data = await get_face_embedding(token)
    except Exception:
        logger.warning(
            "[LMS] Could not load face embedding for %s during mark",
            email,
            exc_info=True,
        )
        return None

    if not face_data.get("hasFaceData"):
        return None

    stored_embedding = parse_face_embedding(face_data.get("faceJson"))
    if not stored_embedding:
        return None

    cache_session_face_embedding(class_session_id, email, stored_embedding)
    cache_face_embedding(email, stored_embedding)
    return stored_embedding


async def _bootstrap_session_face_data(
    token: str,
    class_session_id: int,
) -> Dict[str, Any]:
    """
    Load enrolled students' face embeddings from LMS bulk API into Redis session.

    Admin portal -> POST /lms/attendance/start -> LMS GET /person/face/bulk
    """
    bulk_face_data = await get_bulk_face_embeddings(token, class_session_id)
    parsed = parse_bulk_face_data_response(bulk_face_data)

    cache_session_face_roster(class_session_id, parsed["roster"])
    face_embeddings_loaded = cache_session_face_embeddings(
        class_session_id,
        parsed["embeddings_by_email"],
    )

    return {
        "face_embeddings_loaded": face_embeddings_loaded,
        "students_enrolled": parsed["students_enrolled"],
        "students_with_face_data": parsed["students_with_face_data"],
    }


def _record_failed_mark_attempt(
    class_session_id: int,
    *,
    email: str,
    name: str,
    message: str,
    similarity: Optional[float] = None,
    image_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    return add_mark_failure(
        class_session_id,
        email,
        {
            "name": name,
            "message": message,
            "similarity": similarity,
        },
        image_bytes,
    )


def _face_match_retry_state(class_session_id: int, email: str) -> tuple[int, int]:
    failure = get_mark_failure(class_session_id, email)
    attempt_count = int(failure.get("attempt_count") or 0) if failure else 0
    next_attempt = attempt_count + 1
    retries_remaining = max(0, FACE_MATCH_MAX_ATTEMPTS - next_attempt)
    return next_attempt, retries_remaining


def _handle_face_match_failure(
    class_session_id: int,
    *,
    email: str,
    name: str,
    message: str,
    similarity: Optional[float],
    image_bytes: bytes,
    student_ip: Optional[str],
    teacher_ip: Optional[str],
    ips_match_fn,
) -> Dict[str, Any]:
    next_attempt, retries_remaining = _face_match_retry_state(class_session_id, email)
    _record_failed_mark_attempt(
        class_session_id,
        email=email,
        name=name,
        message=message,
        similarity=similarity,
        image_bytes=image_bytes,
    )

    if next_attempt < FACE_MATCH_MAX_ATTEMPTS:
        return {
            "success": False,
            "verified": False,
            "can_retry": True,
            "retries_remaining": retries_remaining,
            "similarity": similarity,
            "message": STUDENT_FACE_MISMATCH_MESSAGE,
        }

    return {
        "success": False,
        "verified": False,
        "can_retry": False,
        "retries_remaining": 0,
        "similarity": similarity,
        "message": STUDENT_FACE_MISMATCH_FINAL_MESSAGE,
    }


def register_routes(
    app_router: APIRouter,
    *,
    get_client_ip,
    verify_lms_face,
    verify_face_match_only,
    detect_location,
    ips_match,
    **_kwargs,
) -> None:
    """Bind route handlers that depend on ML helpers from main."""

    @app_router.post("/face/register")
    async def lms_register_face(
        face_json: str = Form(...),
        token: str = Depends(require_lms_token),
        _auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        try:
            embedding_list = parse_client_embedding(face_json)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        try:
            await register_face_embedding(token, embedding_list)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        except Exception:
            return {"success": False, "message": "Could not save face data to LMS"}

        person_detail = _auth.get("personDetail") or {}
        email = (person_detail.get("email") or "").lower()
        if email:
            cache_face_embedding(email, embedding_list)

        return {"success": True, "message": "Face registered successfully"}

    @app_router.post("/attendance/start")
    async def lms_start_attendance(
        request: Request,
        payload: LmsAttendanceStartRequest,
        token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        campus_id = _campus_id_from_auth(auth)

        try:
            await import_attendance(token, payload.class_session_id)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        existing = get_session(payload.class_session_id)
        already_active = bool(existing and existing.get("active"))

        session = init_session(
            payload.class_session_id,
            classroom=payload.classroom or (existing or {}).get("classroom"),
            teacher_ip=get_client_ip(request),
            campus_id=campus_id,
        )

        face_bootstrap = {
            "face_embeddings_loaded": 0,
            "students_enrolled": 0,
            "students_with_face_data": 0,
        }
        try:
            face_bootstrap = await _bootstrap_session_face_data(
                token,
                payload.class_session_id,
            )
        except LmsApiError as exc:
            logger.warning(
                "[LMS] bulk face load failed for class_session_id=%s: %s",
                payload.class_session_id,
                exc,
            )
            return {
                "success": False,
                "message": f"Could not load face data for this class session: {exc}",
            }
        except Exception:
            logger.exception(
                "[LMS] Failed to bulk load face embeddings for class_session_id=%s",
                payload.class_session_id,
            )
            return {
                "success": False,
                "message": "Could not load face data for this class session",
            }

        return {
            "success": True,
            "message": (
                "Attendance session already active for this class session"
                if already_active
                else "Attendance session started"
            ),
            "started_at": session.get("started_at"),
            "classroom": session.get("classroom"),
            "class_session_id": payload.class_session_id,
            **face_bootstrap,
        }

    @app_router.post("/attendance/stop")
    async def lms_stop_attendance(
        payload: LmsAttendanceSessionRequest,
        token: str = Depends(require_lms_token),
        _auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        marked = list_marks(payload.class_session_id)
        clear_session(payload.class_session_id)

        return {
            "success": True,
            "message": "Attendance session stopped without submitting to LMS",
            "marked_count": len(marked),
            "marked_students": [_public_mark(record) for record in marked],
        }

    @app_router.post("/attendance/submit")
    async def lms_submit_attendance(
        payload: LmsAttendanceSessionRequest,
        token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        class_session_id = payload.class_session_id
        session = get_session(class_session_id)
        if not session:
            return {"success": False, "message": "No attendance session found in Redis"}

        campus_id = session.get("campus_id") or _campus_id_from_auth(auth)
        if not campus_id:
            return {"success": False, "message": "Campus ID is required to submit attendance"}

        marks = list_marks(class_session_id)

        try:
            attendance_rows = await get_attendance_records(token, int(campus_id), class_session_id)
        except Exception:
            return {"success": False, "message": "Could not load attendance records from LMS"}

        marked_by_email = {
            (mark.get("email") or "").lower(): mark for mark in marks
        }

        roster_emails = {
            (row.get("email") or "").lower()
            for row in attendance_rows
            if row.get("email")
        }

        updates = []
        missing = []
        present_count = 0
        absent_count = 0

        for row in attendance_rows:
            email = row.get("email") or ""
            email_lower = email.lower()
            if not email:
                continue

            mark = marked_by_email.get(email_lower)
            if mark:
                updates.append(
                    {
                        "emailId": email,
                        "status": _map_lms_status(mark.get("status", "Present")),
                    }
                )
                present_count += 1
            else:
                updates.append(
                    {
                        "emailId": email,
                        "status": "ABSENT",
                    }
                )
                absent_count += 1

        missing = [email for email in marked_by_email if email not in roster_emails]

        if not updates:
            return {
                "success": False,
                "message": "No LMS attendance records found for this class session",
            }

        try:
            await bulk_update_attendance(token, class_session_id, updates)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        except Exception:
            return {"success": False, "message": "Failed to submit attendance to LMS"}

        mark_session_submitted(class_session_id)

        if DEFER_ML_REVIEW:
            schedule_session_review(class_session_id)

        return {
            "success": True,
            "message": (
                f"Submitted attendance to LMS — {present_count} present, {absent_count} absent"
            ),
            "marked_count": present_count,
            "absent_count": absent_count,
            "missing_emails": missing,
            "marked_students": [_public_mark(record) for record in marks],
            "review_status": "pending" if DEFER_ML_REVIEW else None,
        }

    @app_router.post("/attendance/review")
    async def lms_run_attendance_review(
        payload: LmsAttendanceReviewRequest,
        _token: str = Depends(require_lms_token),
        _auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        class_session_id = payload.class_session_id
        session = get_session(class_session_id)
        if not session:
            return {"success": False, "message": "No attendance session found in Redis"}

        if not session.get("submitted"):
            return {
                "success": False,
                "message": "Submit attendance to LMS before running spoof and location review",
            }

        marks = list_marks(class_session_id)
        if not marks:
            return {"success": False, "message": "No marked students to review"}

        review_status = session.get("review_status")
        if review_status == "in_progress":
            return {
                "success": True,
                "message": "Spoof and location review is already in progress",
                "review_status": "in_progress",
            }

        if review_status == "pending" and not payload.force:
            return {
                "success": True,
                "message": "Spoof and location review is already queued",
                "review_status": "pending",
            }

        if review_status == "complete" and not payload.force:
            return {
                "success": True,
                "message": "Spoof and location review already complete. Use force to re-run.",
                "review_status": "complete",
                "flagged_count": session.get("flagged_count"),
                "rejected_count": session.get("rejected_count"),
            }

        schedule_session_review(class_session_id, force=payload.force)
        return {
            "success": True,
            "message": "Spoof and location review started",
            "review_status": "pending",
            "marked_count": len(marks),
        }

    @app_router.get("/attendance/status")
    async def lms_attendance_status(
        class_session_id: int = Query(...),
        _token: str = Depends(require_lms_token),
    ):
        # Redis-only status — no LMS round-trip (avoids 401s during polling).
        session = get_session(class_session_id)
        marks = list_marks(class_session_id)
        failures = list_mark_failures(class_session_id)

        if not session:
            return {
                "active": False,
                "started_at": None,
                "teacher_ip": None,
                "expected_classroom": None,
                "class_session_id": class_session_id,
                "marked_count": 0,
                "marked_students": [],
                "failed_mark_count": 0,
                "failed_mark_attempts": [],
            }

        return {
            "active": bool(session.get("active")),
            "submitted": bool(session.get("submitted")),
            "review_status": session.get("review_status"),
            "review_error": session.get("review_error"),
            "flagged_count": session.get("flagged_count"),
            "rejected_count": session.get("rejected_count"),
            "started_at": session.get("started_at"),
            "teacher_ip": session.get("teacher_ip"),
            "expected_classroom": session.get("classroom"),
            "class_session_id": class_session_id,
            "marked_count": len(marks),
            "marked_students": [_public_mark(record) for record in marks],
            "failed_mark_count": len(failures),
            "failed_mark_attempts": failures,
        }

    @app_router.get("/attendance/student-status")
    async def lms_student_attendance_status(
        class_session_id: int = Query(...),
        _token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        # Redis-only — session id is always class_session_id; no LMS attendance round-trip.
        redis_session = get_session(class_session_id)
        session_active = bool(redis_session and redis_session.get("active"))
        session_submitted = bool(redis_session and redis_session.get("submitted"))

        person_detail = auth.get("personDetail") or {}
        email = (person_detail.get("email") or "").lower()

        mark = get_mark(class_session_id, email) if email else None
        already_marked = mark is not None

        return {
            "attendance_active": session_active,
            "class_session_id": class_session_id,
            "classroom": redis_session.get("classroom") if redis_session else None,
            "already_marked": already_marked,
            "session_submitted": session_submitted,
            "mark_status": mark.get("status") if mark else None,
            "review_status": mark.get("review_status") if mark else None,
            "marked_at": mark.get("marked_at") if mark else None,
        }

    @app_router.get("/attendance/roster")
    async def lms_attendance_roster(
        class_session_id: int = Query(...),
        token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        campus_id = _campus_id_from_auth(auth)
        if not campus_id:
            return {"success": False, "message": "Campus ID missing", "students": []}

        try:
            rows = await get_attendance_records(token, int(campus_id), class_session_id)
        except Exception:
            return {"success": False, "message": "Could not load roster", "students": []}

        marks_by_email = {
            (mark.get("email") or "").lower(): mark for mark in list_marks(class_session_id)
        }
        failures_by_email = {
            (failure.get("email") or "").lower(): failure
            for failure in list_mark_failures(class_session_id)
        }
        session_face_roster = get_session_face_roster_map(class_session_id)

        async def enrich(row: Dict[str, Any]) -> Dict[str, Any]:
            email = row.get("email") or ""
            email_lower = email.lower()
            face_meta = session_face_roster.get(email_lower)
            face_registered_at: Optional[str] = None
            if face_meta is not None:
                face_registered = bool(face_meta.get("hasFaceData"))
                if face_registered:
                    try:
                        face_status = await get_face_status_by_email(token, email)
                        face_registered_at = face_status.get("registeredAt")
                    except Exception:
                        pass
            else:
                face_status = {"hasFaceData": False}
                try:
                    face_status = await get_face_status_by_email(token, email)
                except Exception:
                    pass
                face_registered = bool(face_status.get("hasFaceData"))
                if face_registered:
                    face_registered_at = face_status.get("registeredAt")
            return {
                "email": email,
                "name": row.get("personName") or email,
                "attendance_id": row.get("attendanceId"),
                "face_registered": face_registered,
                "face_registered_at": face_registered_at,
                "lms_status": row.get("status"),
                "marked": email_lower in marks_by_email,
                "mark": marks_by_email.get(email_lower),
                "mark_failure": failures_by_email.get(email_lower),
            }

        if session_face_roster and not rows:
            students = [
                {
                    "email": meta.get("email") or email,
                    "name": meta.get("email") or email,
                    "attendance_id": None,
                    "face_registered": bool(meta.get("hasFaceData")),
                    "face_registered_at": None,
                    "lms_status": None,
                    "marked": email in marks_by_email,
                    "mark": marks_by_email.get(email),
                    "mark_failure": failures_by_email.get(email),
                }
                for email, meta in session_face_roster.items()
            ]
        else:
            students = await asyncio.gather(*(enrich(row) for row in rows))

        return {"success": True, "students": students}

    @app_router.get("/attendance/snapshot/{class_session_id}/{email}")
    async def lms_attendance_snapshot(class_session_id: int, email: str):
        snapshot = get_snapshot(class_session_id, email)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return Response(content=snapshot, media_type="image/jpeg")

    @app_router.get("/attendance/failure-snapshot/{class_session_id}/{email}")
    async def lms_attendance_failure_snapshot(class_session_id: int, email: str):
        snapshot = get_failure_snapshot(class_session_id, email)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Failure snapshot not found")
        return Response(content=snapshot, media_type="image/jpeg")

    @app_router.post("/attendance/mark")
    async def lms_mark_attendance(
        request: Request,
        file: UploadFile = File(...),
        class_session_id: int = Form(...),
        face_embedding: Optional[str] = Form(None),
        token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        if not is_session_active(class_session_id):
            return {"success": False, "message": "Attendance session is not active"}

        person_detail = auth.get("personDetail") or {}
        email = (person_detail.get("email") or "").lower()
        name = person_detail.get("name") or email

        if not email:
            return {"success": False, "message": "User email not found"}

        stored_embedding = await _resolve_stored_face_embedding(
            token,
            class_session_id,
            email,
        )
        if not stored_embedding:
            return {
                "success": False,
                "message": "Face not registered. Complete face enrollment first.",
            }

        if not is_face_api_embedding(stored_embedding):
            return {
                "success": False,
                "message": LEGACY_FACE_ENROLLMENT_MESSAGE,
            }

        if has_mark(class_session_id, email):
            return {"success": False, "message": "Attendance already marked for this session"}

        failure = get_mark_failure(class_session_id, email)
        if failure and int(failure.get("attempt_count") or 0) >= FACE_MATCH_MAX_ATTEMPTS:
            return {
                "success": False,
                "verified": False,
                "can_retry": False,
                "message": STUDENT_FACE_MATCH_LOCKED_MESSAGE,
            }

        image_bytes = await file.read()

        if not face_embedding:
            return {
                "success": False,
                "message": FACE_API_ONLY_MESSAGE,
            }

        try:
            live_embedding = parse_client_embedding(face_embedding)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        if len(stored_embedding) != len(live_embedding):
            mismatch_message = embedding_format_mismatch_message(
                stored_embedding, live_embedding
            )
            session = get_session(class_session_id) or {}
            return _handle_face_match_failure(
                class_session_id,
                email=email,
                name=name,
                message=mismatch_message,
                similarity=0.0,
                image_bytes=image_bytes,
                student_ip=get_client_ip(request),
                teacher_ip=session.get("teacher_ip"),
                ips_match_fn=ips_match,
            )

        if DEFER_ML_REVIEW:
            result = await asyncio.to_thread(
                verify_face_match_only,
                stored_embedding,
                image_bytes,
                live_embedding=live_embedding,
            )
        else:
            result = await asyncio.to_thread(
                verify_lms_face,
                stored_embedding,
                image_bytes,
                live_embedding=live_embedding,
            )

        if not result.get("success") or not result.get("verified"):
            if result.get("success") and not result.get("verified"):
                session = get_session(class_session_id) or {}
                return _handle_face_match_failure(
                    class_session_id,
                    email=email,
                    name=name,
                    message=result.get("message") or "Face verification failed",
                    similarity=result.get("similarity"),
                    image_bytes=image_bytes,
                    student_ip=get_client_ip(request),
                    teacher_ip=session.get("teacher_ip"),
                    ips_match_fn=ips_match,
                )
            return result

        session = get_session(class_session_id) or {}
        student_ip = get_client_ip(request)
        teacher_ip = session.get("teacher_ip")
        ip_match = ips_match(teacher_ip, student_ip)

        marked_at = datetime.now(timezone.utc).isoformat()

        if DEFER_ML_REVIEW:
            record = {
                "email": email,
                "name": name,
                "marked_at": marked_at,
                "similarity": result.get("similarity"),
                "student_ip": student_ip,
                "teacher_ip": teacher_ip,
                "ip_match": ip_match,
                "ip_flagged": bool(teacher_ip and student_ip and not ip_match),
                "status": "Present",
                "review_status": "pending",
                "reason": None,
                "has_snapshot": True,
            }
            add_mark(class_session_id, email, record, image_bytes)
            clear_mark_failure(class_session_id, email)

            return {
                "success": True,
                "verified": True,
                "message": "Attendance marked successfully",
                "similarity": result.get("similarity"),
                "marked_at": marked_at,
                "status": "Present",
                "review_status": "pending",
                "ip_match": ip_match,
            }

        location_result = detect_location(image_bytes)
        detected_location = location_result["location"]
        expected_classroom = session.get("classroom")

        status, reason = location_attendance_status(
            detected_location,
            expected_classroom,
        )

        record = {
            "email": email,
            "name": name,
            "marked_at": marked_at,
            "similarity": result.get("similarity"),
            "spoof_confidence": result.get("spoof_confidence"),
            "student_ip": student_ip,
            "teacher_ip": teacher_ip,
            "ip_match": ip_match,
            "ip_flagged": bool(teacher_ip and student_ip and not ip_match),
            "location": detected_location,
            "location_confidence": location_result.get("confidence"),
            "status": status,
            "reason": reason,
            "review_status": "complete",
            "has_snapshot": True,
        }

        add_mark(class_session_id, email, record, image_bytes)
        clear_mark_failure(class_session_id, email)

        return {
            "success": True,
            "verified": True,
            "message": "Attendance marked successfully",
            "similarity": result.get("similarity"),
            "spoof_confidence": result.get("spoof_confidence"),
            "marked_at": marked_at,
            "status": status,
            "reason": reason,
        }
