"""Background task scheduler for netglance daemon mode.

Provides a simple cron-based scheduler that runs tasks in a background thread.
Supports standard 5-field cron expressions: minute, hour, day-of-month, month,
day-of-week.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


def _match_cron_field(field_expr: str, value: int) -> bool:
    """Check whether *value* matches a single cron field expression.

    Supported patterns:
    - ``*``      -- matches any value
    - ``*/N``    -- matches when value is divisible by N
    - ``N``      -- exact integer match
    """
    field_expr = field_expr.strip()
    if field_expr == "*":
        return True
    if field_expr.startswith("*/"):
        try:
            step = int(field_expr[2:])
        except ValueError:
            return False
        return step > 0 and value % step == 0
    try:
        return int(field_expr) == value
    except ValueError:
        return False


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Return ``True`` if *dt* matches the 5-field *cron_expr*.

    Fields: minute  hour  day-of-month  month  day-of-week (0=Mon .. 6=Sun).
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        logger.warning("Invalid cron expression (need 5 fields): %s", cron_expr)
        return False

    minute, hour, dom, month, dow = parts
    # Python weekday(): Monday=0 .. Sunday=6 (matches cron 0-6)
    return (
        _match_cron_field(minute, dt.minute)
        and _match_cron_field(hour, dt.hour)
        and _match_cron_field(dom, dt.day)
        and _match_cron_field(month, dt.month)
        and _match_cron_field(dow, dt.weekday())
    )


@dataclass
class ScheduledTask:
    """A task to run on a cron-like schedule."""

    name: str
    cron_expr: str  # e.g. "*/15 * * * *"
    callback: Callable[[], None]
    last_run: datetime | None = None
    enabled: bool = True


class Scheduler:
    """Simple scheduler that checks tasks once per minute.

    Parameters
    ----------
    _now_fn:
        Callable returning the current ``datetime``.  Defaults to
        ``datetime.now``.  Inject a fake for deterministic testing.
    _sleep_fn:
        Callable that sleeps for the given number of seconds.  Defaults
        to ``time.sleep``.  Inject a no-op or mock for fast tests.
    """

    def __init__(
        self,
        *,
        _now_fn: Callable[[], datetime] | None = None,
        _sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._now_fn = _now_fn or datetime.now
        self._sleep_fn = _sleep_fn or time.sleep
        self._lock = threading.Lock()

    # -- task management -----------------------------------------------------

    def add_task(self, task: ScheduledTask) -> None:
        """Register a new scheduled task."""
        with self._lock:
            self._tasks.append(task)

    def remove_task(self, name: str) -> None:
        """Remove a task by name.  Silently ignores unknown names."""
        with self._lock:
            self._tasks = [t for t in self._tasks if t.name != name]

    # -- lifecycle -----------------------------------------------------------

    def start(self, blocking: bool = True) -> None:
        """Start the scheduler loop.

        If *blocking* is ``True`` the calling thread runs the loop directly.
        Otherwise a daemon thread is spawned.
        """
        self._running = True
        if blocking:
            self._run_loop()
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Signal the scheduler to stop after the current iteration."""
        self._running = False
        if self._thread is not None:
            # Avoid joining from within the scheduler thread itself
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=5)
            self._thread = None

    # -- internals -----------------------------------------------------------

    def _run_loop(self) -> None:
        """Main scheduler loop -- runs until :meth:`stop` is called."""
        while self._running:
            now = self._now_fn()
            with self._lock:
                tasks_snapshot = list(self._tasks)
            for task in tasks_snapshot:
                if self._should_run(task, now):
                    logger.info("Running task: %s", task.name)
                    try:
                        task.callback()
                    except Exception:
                        logger.exception("Task %s raised an exception", task.name)
                    task.last_run = now
            self._sleep_fn(60)

    def _should_run(self, task: ScheduledTask, now: datetime) -> bool:
        """Decide whether *task* should execute at time *now*."""
        if not task.enabled:
            return False
        if not cron_matches(task.cron_expr, now):
            return False
        # Avoid running the same task twice in the same minute.
        if task.last_run is not None:
            if (
                task.last_run.year == now.year
                and task.last_run.month == now.month
                and task.last_run.day == now.day
                and task.last_run.hour == now.hour
                and task.last_run.minute == now.minute
            ):
                return False
        return True

    # -- status --------------------------------------------------------------

    def get_status(self) -> list[dict]:
        """Return a list of task-status dicts for display."""
        with self._lock:
            tasks_snapshot = list(self._tasks)
        result: list[dict] = []
        for task in tasks_snapshot:
            result.append(
                {
                    "name": task.name,
                    "cron_expr": task.cron_expr,
                    "enabled": task.enabled,
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                }
            )
        return result
