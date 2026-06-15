"""LMS API client for face enrollment and attendance sync."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_DEFAULT_LMS_API_BASE = "https://unmixed-virtual-chihuahua.ngrok-free.dev"


def _lms_api_base() -> str:
    return os.getenv("LMS_API_BASE", _DEFAULT_LMS_API_BASE).rstrip("/")


def _auth_headers(token: str) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if "ngrok" in _lms_api_base():
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
    url = f"{_lms_api_base()}{path}"
    extra_headers = kwargs.pop("headers", {})
    headers = {**_auth_headers(token), **extra_headers}
    params = kwargs.get("params")
    logger.info(
        "[LMS API →] %s %s | accessToken=%s | params=%s | json=%s",
        method,
        url,
        token,
        params,
        kwargs.get("json"),
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
    body_preview = response.text[:500] if response.text else ""
    logger.info(
        "[LMS API ←] %s %s -> %s | body=%s",
        method,
        path,
        response.status_code,
        body_preview,
    )
    return response


def _unwrap_lms_response(payload: Dict[str, Any]) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


async def validate_lms_token(token: str) -> Dict[str, Any]:
    response = await _lms_request("GET", "/auth/detail", token)
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


async def get_face_embedding(token: str) -> Dict[str, Any]:
    response = await _lms_request("GET", "/person/face", token)
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


async def get_face_status_by_email(token: str, email: str) -> Dict[str, Any]:
    response = await _lms_request(
        "GET",
        "/person/face/status/by-email",
        token,
        params={"email": email},
    )
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


async def register_face_embedding(token: str, embedding: List[float]) -> None:
    response = await _lms_request(
        "PUT",
        "/person/face",
        token,
        headers={"Content-Type": "application/json"},
        json={"embedding": embedding},
    )
    if response.status_code == 400:
        detail = response.json()
        message = detail.get("message") or "Face registration failed"
        raise ValueError(message)
    response.raise_for_status()


async def start_face_session(
    token: str, class_session_id: int, classroom: Optional[str] = None
) -> Dict[str, Any]:
    response = await _lms_request(
        "POST",
        "/attendance/face-session/start",
        token,
        headers={"Content-Type": "application/json"},
        json={"classSessionId": class_session_id, "classroom": classroom},
    )
    if response.status_code == 400:
        detail = response.json()
        raise ValueError(detail.get("message") or "Could not start session")
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


async def stop_face_session(token: str, class_session_id: int) -> Dict[str, Any]:
    response = await _lms_request(
        "POST",
        "/attendance/face-session/stop",
        token,
        headers={"Content-Type": "application/json"},
        json={"classSessionId": class_session_id},
    )
    if response.status_code in (400, 404):
        detail = response.json()
        raise ValueError(detail.get("message") or "Could not stop session")
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


async def get_active_face_session(token: str) -> Dict[str, Any]:
    response = await _lms_request("GET", "/attendance/face-session/active", token)
    response.raise_for_status()
    return _unwrap_lms_response(response.json())


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
    response.raise_for_status()
    data = _unwrap_lms_response(response.json())
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


async def bulk_update_attendance(
    token: str, updates: List[Dict[str, Any]]
) -> None:
    response = await _lms_request(
        "PUT",
        "/attendance/bulk",
        token,
        timeout=60.0,
        headers={"Content-Type": "application/json"},
        json=updates,
    )
    if response.status_code == 400:
        detail = response.json()
        raise ValueError(detail.get("message") or "Bulk update failed")
    response.raise_for_status()
