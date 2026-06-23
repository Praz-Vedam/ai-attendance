"""Shared helpers for load-test setup scripts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx

LOAD_TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = LOAD_TESTS_DIR.parent
LOCAL_ENV = LOAD_TESTS_DIR / "local.env"
SECRETS_ENV = LOAD_TESTS_DIR / "secrets.env"
FACE_FIXTURE = LOAD_TESTS_DIR / "fixtures" / "sample.jpg"
STUDENT_EMBEDDINGS_FILE = LOAD_TESTS_DIR / "student_embeddings.json"

DEFAULT_LMS_BASE = "http://localhost:9090"
FACE_API_DIM = 128


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_secrets_env(path: Path = SECRETS_ENV) -> None:
    """Load secrets.env, overriding backend .env (e.g. LOCUST_HOST, LMS_API_BASE)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def format_env_value(value: str) -> str:
    """Shell-safe value for local.env (bash `source` compatible)."""
    if value == "":
        return '""'
    if any(ch in value for ch in " \t\n\"'$\\`&|;<>()*,[]"):
        escaped = value.replace("'", "'\"'\"'")
        return f"'{escaped}'"
    return value


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    values: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env_file(path: Path, values: Dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{k}={format_env_value(v)}" for k, v in values.items()) + "\n"
    )


def lms_bases() -> list[str]:
    primary = os.getenv("LMS_API_BASE", DEFAULT_LMS_BASE).rstrip("/")
    fallback = os.getenv("LMS_API_LOCAL_FALLBACK", DEFAULT_LMS_BASE).rstrip("/")
    bases: list[str] = []
    if "ngrok" in primary and primary.startswith("https://") and fallback:
        bases.append(fallback)
    if primary not in bases:
        bases.append(primary)
    if fallback and fallback not in bases:
        bases.append(fallback)
    return bases


def lms_headers(base: str) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    return headers


def refresh_access_token(refresh_token: str) -> Optional[str]:
    for base in lms_bases():
        try:
            response = httpx.post(
                f"{base}/auth/refresh",
                headers={
                    **lms_headers(base),
                    "Authorization": f"Bearer {refresh_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            token = (response.json().get("data") or {}).get("accessToken")
            if token:
                return token
        except httpx.HTTPError:
            continue
    return None


def resolve_access_token(
    access_token: Optional[str],
    refresh_token: Optional[str],
) -> Optional[str]:
    if access_token:
        return access_token
    if refresh_token:
        return refresh_access_token(refresh_token)
    return None


def auth_detail(access_token: str) -> Optional[Dict[str, Any]]:
    for base in lms_bases():
        try:
            response = httpx.get(
                f"{base}/auth/detail",
                headers={
                    **lms_headers(base),
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            return response.json().get("data")
        except httpx.HTTPError:
            continue
    return None


def token_accepted_by_host(
    access_token: str,
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> bool:
    """Validate token against the attendance API when local LMS is unreachable."""
    host = ai_attendance_base()
    path = "/lms/attendance/student-status" if student else "/lms/attendance/roster"
    params: Dict[str, Any] = {}
    if class_session_id > 0:
        params["class_session_id"] = class_session_id
    try:
        response = httpx.get(
            f"{host}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=30.0,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def is_valid_token(
    access_token: str,
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> bool:
    if auth_detail(access_token):
        return True
    return token_accepted_by_host(
        access_token, class_session_id=class_session_id, student=student
    )


def resolve_valid_access_token(
    access_token: Optional[str],
    refresh_token: Optional[str],
    *,
    class_session_id: int = 0,
    student: bool = False,
) -> Optional[str]:
    candidates: list[str] = []
    if access_token and access_token not in candidates:
        candidates.append(access_token)
    if refresh_token:
        refreshed = refresh_access_token(refresh_token)
        if refreshed and refreshed not in candidates:
            candidates.append(refreshed)
    for token in candidates:
        if is_valid_token(token, class_session_id=class_session_id, student=student):
            return token
    return None


def resolve_teacher_token(
    existing_local: Optional[Dict[str, str]] = None,
    *,
    class_session_id: int = 0,
) -> Optional[str]:
    existing_local = existing_local or {}
    if class_session_id <= 0:
        class_session_id = int(
            os.getenv("CLASS_SESSION_ID") or existing_local.get("CLASS_SESSION_ID") or 0
        )
    candidates: list[str] = []
    for raw in (
        existing_local.get("TEACHER_TOKEN", "").strip(),
        os.getenv("LOAD_TEST_TEACHER_ACCESS_TOKEN", "").strip(),
    ):
        if raw and raw not in candidates:
            candidates.append(raw)
    refresh = os.getenv("LOAD_TEST_TEACHER_REFRESH_TOKEN", "").strip()
    if refresh:
        resolved = refresh_access_token(refresh)
        if resolved and resolved not in candidates:
            candidates.append(resolved)
    for token in candidates:
        if is_valid_token(token, class_session_id=class_session_id, student=False):
            return token
    return None


def resolve_student_access_tokens(
    *,
    class_session_id: int = 0,
    student_tokens_file: Optional[Path] = None,
) -> list[str]:
    path = student_tokens_file or (LOAD_TESTS_DIR / "student_tokens.txt")
    if class_session_id <= 0:
        class_session_id = int(os.getenv("CLASS_SESSION_ID") or 0)
    candidates: list[str] = []
    for raw in (os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", "").strip(),):
        if raw and raw not in candidates:
            candidates.append(raw)
    refresh = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip()
    if refresh:
        resolved = refresh_access_token(refresh)
        if resolved and resolved not in candidates:
            candidates.append(resolved)
    for token in read_token_lines(path):
        if token not in candidates:
            candidates.append(token)
    return [
        t
        for t in candidates
        if is_valid_token(t, class_session_id=class_session_id, student=True)
    ]


def read_token_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tokens: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tokens.append(stripped.removeprefix("Bearer ").strip())
    return tokens


def write_token_lines(path: Path, tokens: Iterable[str]) -> None:
    unique = [token for token in dict.fromkeys(tokens) if token]
    path.write_text("\n".join(unique) + ("\n" if unique else ""))


def find_active_class_session_id() -> int:
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from redis_client import redis_client

        for key in redis_client.scan_iter(match="lms:attendance:session:*"):
            raw = redis_client.get(key)
            if not raw:
                continue
            session = json.loads(raw.decode("utf-8"))
            if session.get("active"):
                return int(session["class_session_id"])
    except Exception:
        pass
    return 0


def ai_attendance_base() -> str:
    return os.getenv("LOCUST_HOST", "http://127.0.0.1:8000").rstrip("/")


def _parse_embedding_from_face_json(face_json: str) -> list[float]:
    try:
        payload = json.loads(face_json)
    except (TypeError, ValueError):
        return []

    sys.path.insert(0, str(BACKEND_DIR))
    from face_matching import parse_embedding_payload

    return parse_embedding_payload(payload)


def fetch_face_embedding_json(access_token: str) -> Optional[str]:
    """Fetch enrolled face-api embedding from LMS as a JSON array (mark form field)."""
    for base in lms_bases():
        try:
            response = httpx.get(
                f"{base}/person/face",
                headers={
                    **lms_headers(base),
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=15.0,
            )
            if response.status_code != 200:
                continue
            data = (response.json().get("data") or {})
            face_json = data.get("faceJson")
            if not face_json:
                continue
            embedding = _parse_embedding_from_face_json(face_json)
            if len(embedding) != FACE_API_DIM:
                continue
            return json.dumps(embedding)
        except httpx.HTTPError:
            continue
    return None


def fetch_token_embeddings(tokens: Iterable[str]) -> Dict[str, str]:
    """Map each student access token to its face_embedding JSON payload."""
    mapping: Dict[str, str] = {}
    for token in dict.fromkeys(tokens):
        if not token:
            continue
        embedding_json = fetch_face_embedding_json(token)
        if embedding_json:
            mapping[token] = embedding_json
    return mapping


def write_token_embeddings(path: Path, embeddings: Dict[str, str]) -> None:
    path.write_text(json.dumps(embeddings, indent=2) + "\n")


def read_token_embeddings(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(token): str(embedding)
        for token, embedding in payload.items()
        if token and embedding
    }


def resolve_mark_embeddings(
    tokens: Iterable[str],
    *,
    embeddings_file: Optional[Path] = None,
    fallback_embedding_json: str = "",
) -> Dict[str, str]:
    """Build token→embedding map from file, LMS, or a shared fallback."""
    path = embeddings_file or STUDENT_EMBEDDINGS_FILE
    mapping = read_token_embeddings(path)
    unique_tokens = [token for token in dict.fromkeys(tokens) if token]

    for token in unique_tokens:
        if token in mapping:
            continue
        fetched = fetch_face_embedding_json(token)
        if fetched:
            mapping[token] = fetched

    if fallback_embedding_json.strip():
        for token in unique_tokens:
            mapping.setdefault(token, fallback_embedding_json.strip())

    if mapping:
        write_token_embeddings(path, mapping)
    return mapping


def start_attendance_session(
    teacher_token: str,
    class_session_id: int,
    *,
    classroom: str = "Load Test Classroom",
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/start",
        headers={
            "Authorization": f"Bearer {teacher_token}",
            "Content-Type": "application/json",
        },
        json={"class_session_id": class_session_id, "classroom": classroom},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def submit_attendance_session(teacher_token: str, class_session_id: int) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/submit",
        headers={
            "Authorization": f"Bearer {teacher_token}",
            "Content-Type": "application/json",
        },
        json={"class_session_id": class_session_id},
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()


def trigger_deferred_review(
    teacher_token: str,
    class_session_id: int,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/review",
        headers={
            "Authorization": f"Bearer {teacher_token}",
            "Content-Type": "application/json",
        },
        json={"class_session_id": class_session_id, "force": force},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def poll_review_status(
    teacher_token: str,
    class_session_id: int,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 2.0,
) -> Dict[str, Any]:
    """Poll teacher status until review_status is terminal or timeout."""
    import time

    deadline = time.monotonic() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = httpx.get(
            f"{ai_attendance_base()}/lms/attendance/status",
            headers={"Authorization": f"Bearer {teacher_token}"},
            params={"class_session_id": class_session_id},
            timeout=30.0,
        )
        response.raise_for_status()
        last = response.json()
        review_status = last.get("review_status")
        if review_status in ("complete", "failed"):
            return last
        time.sleep(interval_seconds)
    return last
