"""Feature flags for optional ML pipelines (anti-spoof, location).

Anti-spoof and background/location classifiers operate on raw JPEG snapshots only.
They do not depend on face embeddings (browser face-api.js 128-dim descriptors).
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, value)


ENABLE_ANTI_SPOOF = env_bool("ENABLE_ANTI_SPOOF", True)
ENABLE_LOCATION_DETECTION = env_bool("ENABLE_LOCATION_DETECTION", True)
DEFER_ML_REVIEW = env_bool("DEFER_ML_REVIEW", True)
REVIEW_CONCURRENCY = env_int("REVIEW_CONCURRENCY", 4)
# Load-test routes: seed N synthetic marks (same JPEG) for deferred spoof + DINO review benchmarks.
ENABLE_LOAD_TEST_SEED = env_bool("ENABLE_LOAD_TEST_SEED", False)


IP_MISMATCH_REASON = "IP mismatch"


def ip_mark_fields(
    teacher_ip: Optional[str],
    student_ip: Optional[str],
) -> Tuple[bool, bool, Optional[str]]:
    """Return (ip_match, ip_flagged, reason). Missing IPs are not flagged."""
    if not teacher_ip or not student_ip:
        return True, False, None
    if teacher_ip == student_ip:
        return True, False, None
    return False, True, IP_MISMATCH_REASON


def apply_ip_flag_to_status(
    status: str,
    reason: Optional[str],
    *,
    ip_flagged: bool,
) -> Tuple[str, Optional[str]]:
    """Apply IP mismatch flag at mark time or after deferred ML review."""
    if not ip_flagged:
        return status, reason
    if status == "Rejected":
        return status, reason
    if status == "Flagged":
        return status, reason
    return "Flagged", IP_MISMATCH_REASON


def location_attendance_status(
    detected_location: Optional[str],
    expected_classroom: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Map detected location to attendance status; skips checks when disabled."""
    if not ENABLE_LOCATION_DETECTION:
        return "Present", None

    if detected_location == "Non-Classroom":
        return "Flagged", "Outside Classroom"

    if expected_classroom and detected_location != expected_classroom:
        return "Flagged", "Wrong Classroom"

    return "Present", None


def post_mark_review_status(
    is_real: bool,
    detected_location: Optional[str],
    expected_classroom: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Deferred review status from anti-spoof + background location models only (not IP)."""
    if ENABLE_ANTI_SPOOF and not is_real:
        return "Rejected", "Spoof detected"

    return location_attendance_status(detected_location, expected_classroom)
