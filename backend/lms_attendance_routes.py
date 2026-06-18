"""LMS-integrated face attendance routes backed by Redis."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from lms_client import (
    LmsApiError,
    bulk_update_attendance,
    get_attendance_records,
    get_face_embedding,
    get_face_status_by_email,
    import_attendance,
    parse_face_embedding,
    register_face_embedding,
    validate_lms_token,
)
from ml_config import DEFER_ML_REVIEW, location_attendance_status
from lms_redis_store import (
    add_mark,
    cache_face_embedding,
    clear_session,
    get_cached_face_embedding,
    get_mark,
    get_session,
    get_snapshot,
    has_mark,
    init_session,
    is_session_active,
    list_marks,
    mark_session_submitted,
)
from session_review import schedule_session_review

router = APIRouter(prefix="/lms", tags=["lms"])
logger = logging.getLogger(__name__)

MIN_SIGNUP_SCANS = 1


class LmsAttendanceStartRequest(BaseModel):
    class_session_id: int
    classroom: Optional[str] = None


class LmsAttendanceSessionRequest(BaseModel):
    class_session_id: int


class LmsAttendanceReviewRequest(BaseModel):
    class_session_id: int
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


def register_routes(
    app_router: APIRouter,
    *,
    get_client_ip,
    verify_lms_face,
    verify_face_match_only,
    average_embedding_from_images,
    embedding_to_list,
    detect_location,
    ips_match,
    **_kwargs,
) -> None:
    """Bind route handlers that depend on ML helpers from main."""

    @app_router.post("/face/register")
    async def lms_register_face(
        files: List[UploadFile] = File(...),
        token: str = Depends(require_lms_token),
        _auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        if len(files) < MIN_SIGNUP_SCANS:
            return {
                "success": False,
                "message": f"At least {MIN_SIGNUP_SCANS} face scan is required",
            }

        image_bytes_list = [await upload.read() for upload in files]
        embedding = average_embedding_from_images(image_bytes_list)

        if embedding is None:
            return {
                "success": False,
                "message": "No face detected in the scans. Try better lighting.",
            }

        try:
            await register_face_embedding(token, embedding_to_list(embedding))
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        except Exception:
            return {"success": False, "message": "Could not save face data to LMS"}

        person_detail = _auth.get("personDetail") or {}
        email = (person_detail.get("email") or "").lower()
        if email:
            cache_face_embedding(email, embedding_to_list(embedding))

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
            if row.get("email") and row.get("attendanceId")
        }

        updates = []
        missing = []
        present_count = 0
        absent_count = 0

        for row in attendance_rows:
            email = (row.get("email") or "").lower()
            attendance_id = row.get("attendanceId")
            if not email or not attendance_id:
                continue

            mark = marked_by_email.get(email)
            if mark:
                updates.append(
                    {
                        "id": attendance_id,
                        "status": _map_lms_status(mark.get("status", "Present")),
                    }
                )
                present_count += 1
            else:
                updates.append(
                    {
                        "id": attendance_id,
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
            await bulk_update_attendance(token, updates)
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

        if not session:
            return {
                "active": False,
                "started_at": None,
                "teacher_ip": None,
                "expected_classroom": None,
                "class_session_id": class_session_id,
                "marked_count": 0,
                "marked_students": [],
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

        async def enrich(row: Dict[str, Any]) -> Dict[str, Any]:
            email = row.get("email") or ""
            face_status = {"hasFaceData": False}
            try:
                face_status = await get_face_status_by_email(token, email)
            except Exception:
                pass
            return {
                "email": email,
                "name": row.get("personName") or email,
                "attendance_id": row.get("attendanceId"),
                "face_registered": bool(face_status.get("hasFaceData")),
                "face_registered_at": face_status.get("registeredAt"),
                "lms_status": row.get("status"),
                "marked": (email.lower() in marks_by_email),
                "mark": marks_by_email.get(email.lower()),
            }

        students = await asyncio.gather(*(enrich(row) for row in rows))

        return {"success": True, "students": students}

    @app_router.get("/attendance/snapshot/{class_session_id}/{email}")
    async def lms_attendance_snapshot(class_session_id: int, email: str):
        snapshot = get_snapshot(class_session_id, email)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return Response(content=snapshot, media_type="image/jpeg")

    @app_router.post("/attendance/mark")
    async def lms_mark_attendance(
        request: Request,
        file: UploadFile = File(...),
        class_session_id: int = Form(...),
        token: str = Depends(require_lms_token),
        auth: Dict[str, Any] = Depends(require_lms_auth),
    ):
        if not is_session_active(class_session_id):
            return {"success": False, "message": "Attendance session is not active"}

        try:
            face_payload = await get_face_embedding(token)
        except LmsApiError as exc:
            logger.warning("[LMS] get_face_embedding failed: %s", exc)
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        person_detail = auth.get("personDetail") or {}
        email = (face_payload.get("email") or person_detail.get("email") or "").lower()
        name = person_detail.get("name") or email

        if not face_payload.get("hasFaceData"):
            return {
                "success": False,
                "message": "Face not registered. Complete face enrollment first.",
            }

        if has_mark(class_session_id, email):
            return {"success": False, "message": "Attendance already marked for this session"}

        image_bytes = await file.read()

        stored_embedding = get_cached_face_embedding(email)
        if stored_embedding is None:
            stored_embedding = parse_face_embedding(face_payload.get("faceJson"))
            if stored_embedding:
                cache_face_embedding(email, stored_embedding)

        if DEFER_ML_REVIEW:
            result = await asyncio.to_thread(
                verify_face_match_only,
                stored_embedding,
                image_bytes,
            )
        else:
            result = await asyncio.to_thread(
                verify_lms_face,
                stored_embedding,
                image_bytes,
            )

        if not result.get("success") or not result.get("verified"):
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
