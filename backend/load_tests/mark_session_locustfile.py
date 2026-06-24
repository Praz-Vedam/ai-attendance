"""
Mark-attendance burst test — one POST per marking user.

Default: 300 users (200 polling + 100 marking) / 15s burst / 2m run.
Run via: ./load_tests/run_mark_session_test.sh
"""

from __future__ import annotations

import gevent
from locust import HttpUser, between, constant, events, task

from locust_common import (
    CLASS_SESSION_ID,
    LOCUST_USERS,
    MARK_USERS,
    POLL_USERS,
    MARK_STUDENT_TOKENS_FILE,
    POLL_STUDENT_TOKENS_FILE,
    TokenPool,
    auth_headers,
    build_mark_form_data,
    class_session_query,
    face_image_bytes,
    load_mark_tokens,
    load_poll_tokens,
    load_token_embeddings,
    mark_delay_seconds,
    record_mark_response,
    validate_mark_prerequisites,
)

MARK_TOKENS = load_mark_tokens()
POLL_TOKENS = load_poll_tokens()
MARK_TOKEN_POOL = TokenPool(MARK_TOKENS)
POLL_TOKEN_POOL = TokenPool(POLL_TOKENS)


@events.init.add_listener
def on_locust_init(environment=None, **_kwargs) -> None:
    for message in validate_mark_prerequisites(MARK_TOKENS, label="[mark_session]"):
        print(f"\n{message}\n")
    if MARK_TOKENS:
        embeddings = load_token_embeddings(MARK_TOKENS)
        print(
            f"\n[mark_session] Ready — session={CLASS_SESSION_ID}, "
            f"total_users={LOCUST_USERS} (poll={POLL_USERS}, mark={MARK_USERS}), "
            f"mark_tokens={len(MARK_TOKENS)} ({len(dict.fromkeys(MARK_TOKENS))} unique), "
            f"poll_tokens={len(POLL_TOKENS)}, embeddings={len(embeddings)}\n"
        )


class SessionPoller(HttpUser):
    weight = max(POLL_USERS, 0)
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.token = POLL_TOKEN_POOL.next()

    @task
    def student_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/student-status?{class_session_query()}",
            headers=auth_headers(self.token),
            name="GET /lms/attendance/student-status",
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"HTTP {response.status_code}")
            elif response.status_code == 401:
                response.failure("HTTP 401")


class ConcurrentMarkStudent(HttpUser):
    weight = max(MARK_USERS, 0)
    wait_time = constant(3600)

    def on_start(self) -> None:
        token = MARK_TOKEN_POOL.next()
        if not token or CLASS_SESSION_ID <= 0:
            return

        form_data = build_mark_form_data(token)
        if not form_data:
            return

        try:
            image_bytes = face_image_bytes()
        except FileNotFoundError:
            return

        gevent.sleep(mark_delay_seconds())

        with self.client.post(
            "/lms/attendance/mark",
            headers=auth_headers(token),
            data=form_data,
            files={"file": ("attendance.jpg", image_bytes, "image/jpeg")},
            name="POST /lms/attendance/mark",
            catch_response=True,
        ) as response:
            record_mark_response(response)

    @task
    def idle(self) -> None:
        pass
