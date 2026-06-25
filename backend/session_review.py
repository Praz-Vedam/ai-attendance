"""Background deferred spoof + location review after session submit (not IP checks)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from lms_redis_store import (
    dequeue_session_review,
    enqueue_session_review,
    get_session,
    get_snapshot,
    list_marks,
    release_review_lock,
    reset_session_for_review,
    set_session_review_status,
    try_acquire_review_lock,
    update_mark,
)
from ml_config import REVIEW_CONCURRENCY

logger = logging.getLogger(__name__)

_poller_task: Optional[asyncio.Task] = None
_review_snapshots_batch: Optional[
    Callable[[List[bytes], Optional[str]], List[Dict[str, Any]]]
] = None


def init_review_worker(
    review_snapshots_batch: Callable[[List[bytes], Optional[str]], List[Dict[str, Any]]],
) -> None:
    global _review_snapshots_batch
    _review_snapshots_batch = review_snapshots_batch
    logger.info("[review] concurrency=%s", REVIEW_CONCURRENCY)


async def start_review_poller() -> None:
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        return
    _poller_task = asyncio.create_task(_review_poller_loop())


async def shutdown_review_poller() -> None:
    global _poller_task
    if _poller_task is None:
        return
    _poller_task.cancel()
    try:
        await _poller_task
    except asyncio.CancelledError:
        pass
    _poller_task = None


def schedule_session_review(class_session_id: int, *, force: bool = False) -> None:
    if force:
        reset_session_for_review(class_session_id)
    enqueue_session_review(class_session_id)
    asyncio.create_task(review_session(class_session_id, force=force))


async def review_session(class_session_id: int, *, force: bool = False) -> None:
    session = get_session(class_session_id)
    if not session:
        return

    review_status = session.get("review_status")
    if not force and review_status in ("in_progress", "complete"):
        return

    if not try_acquire_review_lock(class_session_id):
        return

    if _review_snapshots_batch is None:
        logger.error("[review] Worker not initialized for session %s", class_session_id)
        release_review_lock(class_session_id)
        return

    try:
        await _run_review(class_session_id, session, force=force)
    finally:
        release_review_lock(class_session_id)


def _collect_marks_to_review(
    class_session_id: int,
    marks: List[Dict[str, Any]],
    *,
    force: bool,
) -> Tuple[List[Tuple[Dict[str, Any], bytes]], int, int]:
    pending: List[Tuple[Dict[str, Any], bytes]] = []
    flagged_count = 0
    rejected_count = 0

    for mark in marks:
        email = (mark.get("email") or "").lower()
        if not email:
            continue

        if not force and mark.get("review_status") == "complete":
            if mark.get("status") == "Flagged":
                flagged_count += 1
            elif mark.get("status") == "Rejected":
                rejected_count += 1
            continue

        snapshot = get_snapshot(class_session_id, email)
        if not snapshot:
            update_mark(
                class_session_id,
                email,
                {
                    "review_status": "complete",
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "reason": mark.get("reason") or "Snapshot missing for review",
                },
            )
            continue

        pending.append((mark, snapshot))

    return pending, flagged_count, rejected_count


def _apply_review_result(
    class_session_id: int,
    mark: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    email = (mark.get("email") or "").lower()
    status = result.get("status", "Present")
    update_mark(
        class_session_id,
        email,
        {
            "spoof_confidence": result.get("spoof_confidence"),
            "location": result.get("location"),
            "location_confidence": result.get("location_confidence"),
            "status": status,
            "reason": result.get("reason"),
            "review_status": "complete",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    logger.info(
        "[review] mark complete session=%s email=%s status=%s",
        class_session_id,
        email,
        status,
    )
    return status


async def _run_review(
    class_session_id: int,
    session: Dict[str, Any],
    *,
    force: bool = False,
) -> None:
    set_session_review_status(class_session_id, "in_progress")
    expected_classroom = session.get("classroom")
    marks = list_marks(class_session_id)
    pending, flagged_count, rejected_count = _collect_marks_to_review(
        class_session_id,
        marks,
        force=force,
    )

    try:
        for start in range(0, len(pending), REVIEW_CONCURRENCY):
            chunk = pending[start : start + REVIEW_CONCURRENCY]
            snapshots = [snapshot for _, snapshot in chunk]
            results = await asyncio.to_thread(
                _review_snapshots_batch,
                snapshots,
                expected_classroom,
            )

            for (mark, _), result in zip(chunk, results):
                status = _apply_review_result(class_session_id, mark, result)
                if status == "Flagged":
                    flagged_count += 1
                elif status == "Rejected":
                    rejected_count += 1

        set_session_review_status(
            class_session_id,
            "complete",
            flagged_count=flagged_count,
            rejected_count=rejected_count,
        )
        logger.info(
            "[review] finished session=%s flagged=%s rejected=%s",
            class_session_id,
            flagged_count,
            rejected_count,
        )
    except Exception as exc:
        logger.exception("[review] failed session=%s", class_session_id)
        set_session_review_status(
            class_session_id,
            "failed",
            review_error=str(exc),
        )


async def _review_poller_loop() -> None:
    while True:
        try:
            class_session_id = await asyncio.to_thread(dequeue_session_review, 5)
            if class_session_id is not None:
                await review_session(class_session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[review] Poller error")
