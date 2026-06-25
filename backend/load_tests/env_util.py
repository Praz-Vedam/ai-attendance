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
STUDENT_REFRESH_TOKENS_FILE = LOAD_TESTS_DIR / "student_refresh_tokens.txt"
DEFAULT_MARK_STUDENT_TOKENS = LOAD_TESTS_DIR / "student_tokens_mark.txt"
DEFAULT_POLL_STUDENT_TOKENS = LOAD_TESTS_DIR / "student_tokens_poll.txt"

DEFAULT_LMS_BASE = "http://localhost:9090"
FACE_API_DIM = 128

# Keys set in the parent shell (e.g. MARK_USERS=0 from run_ml_review_test.sh) must
# not be overwritten when secrets.env is loaded.
_SHELL_ENV_KEYS = frozenset(os.environ)


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
        key = key.strip()
        if key in _SHELL_ENV_KEYS:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


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


def parse_bulk_tokens(raw: str) -> list[str]:
    """Split comma- or newline-separated token lists from env vars."""
    if not raw.strip():
        return []
    parts = raw.replace("\n", ",").split(",")
    return [part.strip().removeprefix("Bearer ").strip() for part in parts if part.strip()]


def read_refresh_token_lines(path: Optional[Path] = None) -> list[str]:
    path = path or STUDENT_REFRESH_TOKENS_FILE
    tokens = read_token_lines(path)
    if tokens:
        return tokens

    bulk = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKENS", "").strip()
    if bulk:
        return parse_bulk_tokens(bulk)

    single = os.getenv("LOAD_TEST_STUDENT_REFRESH_TOKEN", "").strip()
    return [single] if single else []


def collect_student_access_candidates(
    *,
    student_tokens_file: Optional[Path] = None,
) -> list[str]:
    """Ordered deduped access-token candidates (not yet validated)."""
    path = student_tokens_file or (LOAD_TESTS_DIR / "student_tokens.txt")
    candidates: list[str] = []

    def add(raw: str) -> None:
        token = raw.strip().removeprefix("Bearer ").strip()
        if token and token not in candidates:
            candidates.append(token)

    for token in read_token_lines(path):
        add(token)
    for token in parse_bulk_tokens(os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKENS", "")):
        add(token)
    add(os.getenv("LOAD_TEST_STUDENT_ACCESS_TOKEN", ""))
    return candidates


def student_email_from_token(access_token: str) -> Optional[str]:
    detail = auth_detail(access_token)
    if not detail:
        return None
    person = detail.get("personDetail") or {}
    email = (person.get("email") or "").strip().lower()
    return email or None


def resolve_distinct_student_tokens(
    *,
    class_session_id: int = 0,
    student_tokens_file: Optional[Path] = None,
    refresh_tokens_file: Optional[Path] = None,
    min_count: int = 0,
) -> list[str]:
    """
    Validated unique student access tokens — one entry per enrolled student email.

  Sources (first wins per email):
    - student_tokens.txt / student_tokens_file
    - LOAD_TEST_STUDENT_ACCESS_TOKENS / LOAD_TEST_STUDENT_ACCESS_TOKEN
    - student_refresh_tokens.txt / LOAD_TEST_STUDENT_REFRESH_TOKENS / LOAD_TEST_STUDENT_REFRESH_TOKEN
    """
    if class_session_id <= 0:
        class_session_id = int(os.getenv("CLASS_SESSION_ID") or 0)

    valid: list[str] = []
    seen_tokens: set[str] = set()
    seen_emails: set[str] = set()

    def accept(token: str) -> None:
        if not token or token in seen_tokens:
            return
        if not is_valid_token(token, class_session_id=class_session_id, student=True):
            return
        email = student_email_from_token(token)
        if email and email in seen_emails:
            return
        seen_tokens.add(token)
        if email:
            seen_emails.add(email)
        valid.append(token)

    for token in collect_student_access_candidates(student_tokens_file=student_tokens_file):
        accept(token)

    for refresh in read_refresh_token_lines(refresh_tokens_file):
        resolved = refresh_access_token(refresh)
        if resolved:
            accept(resolved)

    if min_count > 0 and len(valid) < min_count:
        return valid
    return valid


def resolve_student_access_tokens(
    *,
    class_session_id: int = 0,
    student_tokens_file: Optional[Path] = None,
) -> list[str]:
    return resolve_distinct_student_tokens(
        class_session_id=class_session_id,
        student_tokens_file=student_tokens_file,
    )


def resolve_student_tokens(
    student_tokens_file: Path,
    *,
    class_session_id: int = 0,
) -> list[str]:
    """Backward-compatible alias used by find_mark_breakpoint.py."""
    return resolve_distinct_student_tokens(
        class_session_id=class_session_id,
        student_tokens_file=student_tokens_file,
    )


def replicate_tokens(tokens: list[str], count: int) -> list[str]:
    """Repeat tokens in order until count lines (for polling load)."""
    unique = [token for token in dict.fromkeys(tokens) if token]
    if not unique or count <= 0:
        return []
    if len(unique) >= count:
        return unique[:count]
    return (unique * ((count // len(unique)) + 1))[:count]


def assign_mark_and_poll_tokens(
    access_tokens: list[str],
    *,
    mark_users: int,
    poll_users: int,
    allow_duplicate_marks: bool = False,
) -> tuple[list[str], list[str]]:
    """
    Build token lists for mark vs poll Locust users.

    Mark users get distinct tokens (one face-verification path per student).
    Poll users may reuse tokens.
    """
    unique = [token for token in dict.fromkeys(access_tokens) if token]
    if mark_users > 0 and not unique:
        raise ValueError("No student access tokens available for mark users")

    if mark_users > len(unique):
        if allow_duplicate_marks:
            mark_tokens = replicate_tokens(unique, mark_users)
        else:
            raise ValueError(
                f"Need {mark_users} distinct enrolled student token(s) for mark users, "
                f"but only {len(unique)} found. Add tokens to "
                f"{STUDENT_REFRESH_TOKENS_FILE.name} or LOAD_TEST_STUDENT_ACCESS_TOKENS, "
                "or set ALLOW_DUPLICATE_MARK_TOKENS=1 to allow repeated marks "
                "(skips face verification after the first mark per student)."
            )
    else:
        mark_tokens = unique[:mark_users]

    poll_tokens = replicate_tokens(unique, poll_users) if poll_users > 0 else []
    return mark_tokens, poll_tokens


def allow_duplicate_mark_tokens() -> bool:
    return os.getenv("ALLOW_DUPLICATE_MARK_TOKENS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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


def get_attendance_status(
    teacher_token: str,
    class_session_id: int,
) -> Dict[str, Any]:
    response = httpx.get(
        f"{ai_attendance_base()}/lms/attendance/status",
        headers={"Authorization": f"Bearer {teacher_token}"},
        params={"class_session_id": class_session_id},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def post_student_mark(
    student_token: str,
    class_session_id: int,
    *,
    embedding_json: str,
    image_bytes: bytes,
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/mark",
        headers={"Authorization": f"Bearer {student_token}"},
        data={
            "class_session_id": str(class_session_id),
            "face_embedding": embedding_json,
        },
        files={"file": ("attendance.jpg", image_bytes, "image/jpeg")},
        timeout=120.0,
    )
    if response.status_code >= 400:
        try:
            return response.json()
        except ValueError:
            response.raise_for_status()
    return response.json()


def seed_review_marks(
    class_session_id: int,
    student_tokens: list[str],
    *,
    embeddings: Dict[str, str],
    image_bytes: bytes,
    target_count: int,
    concurrency: int = 20,
) -> tuple[int, int, list[str]]:
    """
    POST /lms/attendance/mark for up to target_count distinct enrolled students.

    Each successful mark stores a JPEG snapshot for deferred spoof + DINO review.
    Returns (success_count, failure_count, sample_errors).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    unique_tokens = [token for token in dict.fromkeys(student_tokens) if token]
    tokens_to_mark = unique_tokens[: max(target_count, 0)]
    if not tokens_to_mark:
        return 0, 0, ["no student tokens available"]

    successes = 0
    failures = 0
    errors: list[str] = []

    def _mark_one(token: str) -> tuple[bool, str]:
        embedding_json = embeddings.get(token)
        if not embedding_json:
            return False, "missing embedding"
        try:
            result = post_student_mark(
                token,
                class_session_id,
                embedding_json=embedding_json,
                image_bytes=image_bytes,
            )
        except httpx.HTTPError as exc:
            return False, str(exc)
        if result.get("success"):
            return True, ""
        return False, str(result.get("message") or "mark failed")

    workers = max(1, min(concurrency, len(tokens_to_mark)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_mark_one, token): token for token in tokens_to_mark}
        for future in as_completed(futures):
            ok, message = future.result()
            if ok:
                successes += 1
            else:
                failures += 1
                if message and len(errors) < 5:
                    errors.append(message)

    return successes, failures, errors


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


def seed_synthetic_marks_via_api(
    teacher_token: str,
    class_session_id: int,
    *,
    count: int,
    image_bytes: bytes,
    replace: bool = True,
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/load-test/seed-marks",
        headers={"Authorization": f"Bearer {teacher_token}"},
        data={
            "class_session_id": str(class_session_id),
            "count": str(count),
            "replace": "true" if replace else "false",
        },
        files={"file": ("attendance.jpg", image_bytes, "image/jpeg")},
        timeout=180.0,
    )
    if response.status_code == 404:
        raise RuntimeError(
            "Load-test seed route not found — set ENABLE_LOAD_TEST_SEED=true on the server"
        )
    response.raise_for_status()
    return response.json()


def submit_session_for_review_load_test(
    teacher_token: str,
    class_session_id: int,
) -> Dict[str, Any]:
    response = httpx.post(
        f"{ai_attendance_base()}/lms/attendance/load-test/submit-for-review",
        headers={
            "Authorization": f"Bearer {teacher_token}",
            "Content-Type": "application/json",
        },
        json={"class_session_id": class_session_id},
        timeout=60.0,
    )
    if response.status_code == 404:
        raise RuntimeError(
            "Load-test submit route not found — set ENABLE_LOAD_TEST_SEED=true on the server"
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
