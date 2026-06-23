from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
STUDENTS_DIR = DATA_DIR / "students"
SESSIONS_DIR = DATA_DIR / "sessions"
STUDENTS_INDEX_FILE = DATA_DIR / "students_index.json"


def ensure_dirs() -> None:
    for path in (DATA_DIR, STUDENTS_DIR, SESSIONS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    ensure_dirs()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def email_to_filename(email: str) -> str:
    return (
        email.strip()
        .lower()
        .replace("@", "_at_")
        .replace(".", "_")
    )


def student_path(email: str) -> Path:
    return STUDENTS_DIR / f"{email_to_filename(email)}.json"


def session_path(token: str) -> Path:
    safe = token.replace("/", "_")
    return SESSIONS_DIR / f"{safe}.json"


def load_students_index() -> list[str]:
    ensure_dirs()
    data = _read_json(STUDENTS_INDEX_FILE)
    if not isinstance(data, list):
        return []
    return sorted({str(email).lower() for email in data})


def save_students_index(emails: list[str]) -> None:
    _write_json(STUDENTS_INDEX_FILE, sorted({e.lower() for e in emails}))


ensure_dirs()
