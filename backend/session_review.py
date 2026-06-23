"""Background deferred spoof + location review after session submit (not IP checks)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

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

logger = logging.getLogger(__name__)

REVIEW_CONCURRENCY = 4
_poller_task: Optional[asyncio.Task] = None
_run_post_mark_review: Optional[Callable[..., Dict[str, Any]]] = None


def init_review_worker(run_post_mark_review: Callable[..., Dict[str, Any]]) -> None:
    global _run_post_mark_review
    _run_post_mark_review = run_post_mark_review


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

    if _run_post_mark_review is None:
        logger.error("[review] Worker not initialized for session %s", class_session_id)
        release_review_lock(class_session_id)
        return

    try:
        await _run_review(class_session_id, session, force=force)
    finally:
        release_review_lock(class_session_id)


async def _run_review(
    class_session_id: int,
    session: Dict[str, Any],
    *,
    force: bool = False,
) -> None:
    set_session_review_status(class_session_id, "in_progress")
    expected_classroom = session.get("classroom")
    marks = list_marks(class_session_id)
    flagged_count = 0
    rejected_count = 0
    semaphore = asyncio.Semaphore(REVIEW_CONCURRENCY)

    async def review_one_mark(mark: Dict[str, Any]) -> None:
        nonlocal flagged_count, rejected_count
        email = (mark.get("email") or "").lower()
        if not email:
            return

        if not force and mark.get("review_status") == "complete":
            if mark.get("status") == "Flagged":
                flagged_count += 1
            elif mark.get("status") == "Rejected":
                rejected_count += 1
            return

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
            return

        async with semaphore:
            result = await asyncio.to_thread(
                _run_post_mark_review,
                snapshot,
                expected_classroom,
            )

        status = result.get("status", "Present")
        if status == "Flagged":
            flagged_count += 1
        elif status == "Rejected":
            rejected_count += 1

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

    try:
        await asyncio.gather(*(review_one_mark(mark) for mark in marks))
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
