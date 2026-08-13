"""Single-process Chapter 15 worker for durable schedule occurrences."""

from __future__ import annotations

import os
import threading
from uuid import uuid4

from apps.api.services.run_service import RunService
from klara.scheduler import Schedule, ScheduleNotification, ScheduleOccurrence, SchedulerService
from klara.tasks import TaskScope


class SchedulerRunner:
    """Poll the durable scheduler without executing work on the API main thread."""

    def __init__(
        self,
        *,
        service: SchedulerService,
        scope: TaskScope,
        run_service: RunService,
        poll_seconds: float | None = None,
    ) -> None:
        self.service = service
        self.scope = scope
        self.run_service = run_service
        self.poll_seconds = max(
            0.2, poll_seconds or float(os.getenv("KLARA_SCHEDULER_POLL_SECONDS", "1"))
        )
        self.worker_id = f"scheduler:{uuid4().hex}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="klara-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(2.0, self.poll_seconds * 2))
        self._thread = None

    def tick_once(self):
        with self._tick_lock:
            result = self.service.tick(
                scope=self.scope,
                worker_id=self.worker_id,
                dispatcher=self.dispatch,
                notifier=self.notify,
            )
            self.last_error = None
            return result

    def dispatch(self, schedule: Schedule, occurrence: ScheduleOccurrence) -> None:
        if occurrence.task_id is None or schedule.session_id is None:
            raise RuntimeError("scheduled_chat_run_requires_session")
        self.run_service.create_scheduled_run(
            session_id=schedule.session_id,
            task_id=occurrence.task_id,
            question=schedule.task_description or schedule.title,
            schedule_title=schedule.title,
        )

    def notify(self, notification: ScheduleNotification) -> None:
        self.run_service.inject_schedule_notification(
            notification_id=notification.notification_id,
            session_id=notification.session_id,
            message=notification.message,
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as exc:  # scheduler remains live for the next durable poll
                self.last_error = f"{type(exc).__name__}:{str(exc)[:240]}"
            self._stop.wait(self.poll_seconds)
