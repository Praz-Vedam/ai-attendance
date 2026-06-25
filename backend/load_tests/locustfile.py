"""
Sustained throughput load test — mixed student + teacher traffic.

Default scenario (150 polling + 150 marking / 2 min):
  - 150 students poll GET /lms/attendance/student-status continuously
  - 150 students POST /lms/attendance/mark in a 15s burst (face-api + JPEG)
  - 1 teacher polls roster + session status

Run via: ./load_tests/run_throughput_test.sh
"""

from __future__ import annotations

import gevent
from locust import HttpUser, between, constant, events, task

from locust_common import (
    CLASS_SESSION_ID,
    MARK_USERS,
    POLL_USERS,
    TEACHER_TOKEN,
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
    validate_polling_prerequisites,
)

MARK_TOKENS = load_mark_tokens()
POLL_TOKENS = load_poll_tokens()
MARK_TOKEN_POOL = TokenPool(MARK_TOKENS)
POLL_TOKEN_POOL = TokenPool(POLL_TOKENS)


@events.init.add_listener
def on_locust_init(environment=None, **_kwargs) -> None:
    for message in validate_polling_prerequisites(POLL_TOKENS, label="[throughput]"):
        print(f"\n{message}\n")
    if MARK_USERS > 0:
        for message in validate_mark_prerequisites(MARK_TOKENS, label="[throughput]"):
            print(f"\n{message}\n")
        if MARK_TOKENS:
            load_token_embeddings(MARK_TOKENS)
    if not TEACHER_TOKEN:
        print(
            "\n[throughput] WARNING: TEACHER_TOKEN is not set. "
            "Teacher polling will be skipped.\n"
        )


class _BaseUser(HttpUser):
    abstract = True

    def _fail_unless_ok(self, response) -> None:
        if response.status_code >= 500:
            response.failure(f"HTTP {response.status_code}")
        elif response.status_code == 401:
            response.failure("HTTP 401 — invalid or expired LMS token")
        elif response.status_code >= 400:
            response.failure(f"HTTP {response.status_code}")


class LmsStudentPoller(_BaseUser):
    """Background polling for the full run duration."""

    weight = max(POLL_USERS, 0)
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.token = POLL_TOKEN_POOL.next()

    @task(5)
    def student_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/student-status?{class_session_query()}",
            headers=auth_headers(self.token),
            name="GET /lms/attendance/student-status",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)

    @task(2)
    def session_status(self) -> None:
        if not self.token or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{class_session_query()}",
            headers=auth_headers(self.token),
            name="GET /lms/attendance/status",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)


class LmsBurstMarker(_BaseUser):
    """Mark once in the opening burst window, then idle for the rest of the run."""

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


class LmsTeacherPoller(_BaseUser):
    """Admin portal polling during the live session."""

    weight = 1 if TEACHER_TOKEN else 0
    wait_time = between(2, 5)

    @task(3)
    def attendance_status(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/status?{class_session_query()}",
            headers=auth_headers(TEACHER_TOKEN),
            name="GET /lms/attendance/status [teacher]",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)

    @task(1)
    def roster(self) -> None:
        if not TEACHER_TOKEN or CLASS_SESSION_ID <= 0:
            return
        with self.client.get(
            f"/lms/attendance/roster?{class_session_query()}",
            headers=auth_headers(TEACHER_TOKEN),
            name="GET /lms/attendance/roster",
            catch_response=True,
        ) as response:
            self._fail_unless_ok(response)
