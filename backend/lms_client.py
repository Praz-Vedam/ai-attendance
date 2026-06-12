"""LMS API client for face enrollment and attendance sync."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

LMS_API_BASE = os.getenv("LMS_API_BASE", "http://127.0.0.1:9090").rstrip("/")


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _unwrap_lms_response(payload: Dict[str, Any]) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


async def validate_lms_token(token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{LMS_API_BASE}/auth/detail",
            headers=_auth_headers(token),
        )
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def get_face_embedding(token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{LMS_API_BASE}/person/face",
            headers=_auth_headers(token),
        )
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def get_face_status_by_email(token: str, email: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{LMS_API_BASE}/person/face/status/by-email",
            params={"email": email},
            headers=_auth_headers(token),
        )
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def register_face_embedding(token: str, embedding: List[float]) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            f"{LMS_API_BASE}/person/face",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{LMS_API_BASE}/attendance/face-session/start",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json={"classSessionId": class_session_id, "classroom": classroom},
        )
        if response.status_code == 400:
            detail = response.json()
            raise ValueError(detail.get("message") or "Could not start session")
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def stop_face_session(token: str, class_session_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{LMS_API_BASE}/attendance/face-session/stop",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json={"classSessionId": class_session_id},
        )
        if response.status_code in (400, 404):
            detail = response.json()
            raise ValueError(detail.get("message") or "Could not stop session")
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def get_active_face_session(token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{LMS_API_BASE}/attendance/face-session/active",
            headers=_auth_headers(token),
        )
        response.raise_for_status()
        return _unwrap_lms_response(response.json())


async def get_attendance_records(
    token: str,
    campus_id: int,
    class_session_id: int,
    *,
    scope: str = "ALL",
) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{LMS_API_BASE}/attendance",
            params={
                "campusId": campus_id,
                "classSessionId": class_session_id,
                "scope": scope,
                "page": 0,
                "size": 1000,
            },
            headers=_auth_headers(token),
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.put(
            f"{LMS_API_BASE}/attendance/bulk",
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=updates,
        )
        if response.status_code == 400:
            detail = response.json()
            raise ValueError(detail.get("message") or "Bulk update failed")
        response.raise_for_status()
