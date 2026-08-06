"""LMS API client for face enrollment and attendance sync."""

from __future__ import annotations

import json
import logging
import os
import ssl
from typing import Any, Dict, List, Optional

import certifi
import httpx

from face_matching import parse_embedding_payload

logger = logging.getLogger(__name__)


class LmsApiError(Exception):
    """Raised when an outbound LMS API call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        lms_status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.lms_status = lms_status

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_DEFAULT_LMS_API_BASE = "https://unmixed-virtual-chihuahua.ngrok-free.dev"
_DEFAULT_LMS_LOCAL_FALLBACK = "http://localhost:9090"

_lms_client: Optional[httpx.AsyncClient] = None


def _lms_api_base() -> str:
    return os.getenv("LMS_API_BASE", _DEFAULT_LMS_API_BASE).rstrip("/")


def _lms_local_fallback() -> Optional[str]:
    """Same-machine Java (:9090) — avoids ngrok HTTPS + large Bearer token issues on LibreSSL."""
    raw = os.getenv("LMS_API_LOCAL_FALLBACK", _DEFAULT_LMS_LOCAL_FALLBACK).strip()
    return raw.rstrip("/") if raw else None


def _lms_request_bases() -> List[str]:
    primary = _lms_api_base()
    fallback = _lms_local_fallback()
    bases: List[str] = []
    # Prefer direct localhost when ngrok is configured — tokens from browser login are large.
    if fallback and "ngrok" in primary and primary.startswith("https://"):
        bases.append(fallback)
    if primary not in bases:
        bases.append(primary)
    if fallback and fallback not in bases:
        bases.append(fallback)
    return bases


def _lms_ssl_context() -> ssl.SSLContext:
    """Explicit CA bundle — macOS system Python uses LibreSSL and needs certifi."""
    return ssl.create_default_context(cafile=certifi.where())


def get_lms_client() -> httpx.AsyncClient:
    global _lms_client
    if _lms_client is None or _lms_client.is_closed:
        _lms_client = httpx.AsyncClient(
            verify=_lms_ssl_context(),
            http2=False,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _lms_client


async def close_lms_client() -> None:
    global _lms_client
    if _lms_client is not None:
        await _lms_client.aclose()
        _lms_client = None


def _auth_headers(token: str, base: str) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    return headers


async def _lms_request(
    method: str,
    path: str,
    token: str,
    *,
    timeout: float = 30.0,
    **kwargs: Any,
) -> httpx.Response:
    extra_headers = kwargs.pop("headers", {})
    params = kwargs.get("params")
    last_error: Optional[httpx.RequestError] = None

    for base in _lms_request_bases():
        url = f"{base}{path}"
        headers = {**_auth_headers(token, base), **extra_headers}
        logger.info(
            "[LMS API →] %s %s | accessToken=%s | params=%s | json=%s",
            method,
            url,
            token,
            params,
            kwargs.get("json"),
        )
        for attempt in range(2):
            try:
                client = get_lms_client()
                response = await client.request(
                    method, url, headers=headers, timeout=timeout, **kwargs
                )
                body_preview = response.text[:500] if response.text else ""
                logger.info(
                    "[LMS API ←] %s %s -> %s | body=%s",
                    method,
                    path,
                    response.status_code,
                    body_preview,
                )
                return response
            except httpx.RequestError as exc:
                last_error = exc
                detail = str(exc) or repr(exc)
                logger.warning(
                    "[LMS API ✗] %s %s via %s (attempt %s): %s",
                    method,
                    path,
                    base,
                    attempt + 1,
                    detail,
                )
                await close_lms_client()
                if attempt == 0:
                    continue
                break

    detail = str(last_error) or repr(last_error) if last_error else "unknown error"
    logger.error("[LMS API ✗] %s %s all bases failed: %s", method, path, detail)
    raise LmsApiError(
        f"LMS API unreachable ({path}): {detail}",
        status_code=503,
    ) from last_error


def _raise_for_lms_response(response: httpx.Response, path: str) -> None:
    if response.status_code == 401:
        raise LmsApiError(
            "LMS rejected access token",
            status_code=401,
            lms_status=401,
        )
    if response.status_code >= 400:
        raise LmsApiError(
            f"LMS {path} failed: HTTP {response.status_code}",
            status_code=502,
            lms_status=response.status_code,
        )


def _unwrap_lms_response(payload: Dict[str, Any]) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


async def validate_lms_token(token: str) -> Dict[str, Any]:
    response = await _lms_request("GET", "/auth/detail", token)
    _raise_for_lms_response(response, "/auth/detail")
    try:
        return _unwrap_lms_response(response.json())
    except (TypeError, ValueError) as exc:
        raise LmsApiError(
            f"Invalid LMS auth/detail response: {exc}",
            status_code=502,
        ) from exc


def parse_face_embedding(face_json: Optional[str]) -> List[float]:
    if not face_json:
        return []
    try:
        payload = json.loads(face_json)
    except (TypeError, ValueError):
        return []
    return parse_embedding_payload(payload)


async def get_face_embedding(token: str) -> Dict[str, Any]:
    response = await _lms_request("GET", "/person/face", token)
    _raise_for_lms_response(response, "/person/face")
    return _unwrap_lms_response(response.json())


async def get_face_status_by_email(token: str, email: str) -> Dict[str, Any]:
    response = await _lms_request(
        "GET",
        "/person/face/status",
        token,
        params={"email": email},
    )
    _raise_for_lms_response(response, "/person/face/status")
    return _unwrap_lms_response(response.json())


async def register_face_embedding(
    token: str,
    embedding: List[float],
    *,
    face_image: Optional[bytes] = None,
    face_image_filename: str = "onboarding.jpg",
    face_image_content_type: str = "image/jpeg",
) -> None:
    """Register face embedding with LMS; optionally persist onboarding photo.

    LMS expects multipart/form-data with ``faceJson`` (+ optional ``faceImage``).
    """
    face_json = json.dumps({"embedding": embedding})
    # Use files= so httpx always sends multipart (LMS @RequestPart), even without image.
    files: Dict[str, Any] = {
        "faceJson": (None, face_json),
    }
    if face_image:
        files["faceImage"] = (
            face_image_filename,
            face_image,
            face_image_content_type or "image/jpeg",
        )

    response = await _lms_request(
        "PUT",
        "/person/face",
        token,
        files=files,
    )
    if response.status_code == 400:
        detail = response.json()
        message = detail.get("message") or "Face registration failed"
        raise ValueError(message)
    _raise_for_lms_response(response, "/person/face")


async def get_bulk_face_embeddings(token: str, class_session_id: int) -> Dict[str, Any]:
    """Fetch enrolled students' face data for a class session from LMS."""
    response = await _lms_request(
        "GET",
        "/person/face/bulk",
        token,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={"classSessionId": class_session_id},
    )
    _raise_for_lms_response(response, "/person/face/bulk")
    data = _unwrap_lms_response(response.json())
    return data if isinstance(data, dict) else {}


def parse_bulk_face_data_response(bulk: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse LMS bulk face response into Redis-ready session data.

    LMS payload:
      { "classSessionId": 1, "students": [{ "email", "hasFaceData", "faceJson", "photoUrl?" }] }
    """
    students = bulk.get("students") or []
    embeddings_by_email: Dict[str, List[float]] = {}
    roster: List[Dict[str, Any]] = []
    students_with_face_data = 0

    for student in students:
        if not isinstance(student, dict):
            continue
        email = (student.get("email") or "").strip()
        if not email:
            continue

        has_face_data = bool(student.get("hasFaceData"))
        photo_url = student.get("photoUrl") or student.get("photo_url")
        entry: Dict[str, Any] = {
            "email": email,
            "hasFaceData": has_face_data,
        }
        if isinstance(photo_url, str) and photo_url.strip():
            entry["photoUrl"] = photo_url.strip()
        roster.append(entry)

        if not has_face_data:
            continue

        embedding = parse_face_embedding(student.get("faceJson"))
        if embedding:
            embeddings_by_email[email.lower()] = embedding
            students_with_face_data += 1

    return {
        "class_session_id": bulk.get("classSessionId"),
        "embeddings_by_email": embeddings_by_email,
        "roster": roster,
        "students_enrolled": len(roster),
        "students_with_face_data": students_with_face_data,
    }


def embeddings_from_bulk_response(bulk: Dict[str, Any]) -> Dict[str, List[float]]:
    return parse_bulk_face_data_response(bulk)["embeddings_by_email"]


async def import_attendance(token: str, class_session_id: int) -> None:
    """Seed LMS attendance rows for a class session (no-op if already imported)."""
    response = await _lms_request(
        "POST",
        "/attendance/import",
        token,
        headers={"Content-Type": "application/json"},
        json={"classSessionId": class_session_id},
    )
    if response.status_code == 400:
        detail = response.json()
        message = (detail.get("message") or "").lower()
        if "already been imported" in message:
            return
        raise ValueError(detail.get("message") or "Could not import attendance")
    _raise_for_lms_response(response, "/attendance/import")


async def get_attendance_records(
    token: str,
    campus_id: int,
    class_session_id: int,
    *,
    scope: str = "ALL",
) -> List[Dict[str, Any]]:
    response = await _lms_request(
        "GET",
        "/attendance",
        token,
        timeout=60.0,
        params={
            "campusId": campus_id,
            "classSessionId": class_session_id,
            "scope": scope,
            "page": 0,
            "size": 1000,
        },
    )
    _raise_for_lms_response(response, "/attendance")
    data = _unwrap_lms_response(response.json())
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def _prepare_bulk_attendance_payload(
    updates: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Normalize bulk attendance updates to LMS emailId + status format."""
    prepared: List[Dict[str, str]] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        email = (update.get("emailId") or update.get("email") or "").strip()
        status = (update.get("status") or "").strip().upper()
        if not email or not status:
            continue
        prepared.append({"emailId": email, "status": status})
    return prepared


async def bulk_update_attendance(
    token: str, class_session_id: int, updates: List[Dict[str, Any]]
) -> None:
    payload = _prepare_bulk_attendance_payload(updates)
    if not payload:
        raise ValueError("No valid attendance updates to submit")

    response = await _lms_request(
        "PUT",
        "/attendance/bulk",
        token,
        timeout=60.0,
        params={"classSessionId": class_session_id},
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    if response.status_code == 400:
        detail = response.json()
        raise ValueError(detail.get("message") or "Bulk update failed")
    _raise_for_lms_response(response, "/attendance/bulk")
