"""One bounded background operation at a time; all results travel via a queue."""
from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
from threading import Thread
from typing import Any

from ..integrations.errors import IntegrationError


@dataclass(frozen=True)
class TaskResult:
    owner: object
    operation: str
    value: Any = None
    error_key: str | None = None


class Background:
    def __init__(self, default_error: str = 'spotify_api_failed'):
        self.default_error = default_error
        self.events: Queue[TaskResult] = Queue()
        self._thread: Thread | None = None
        self.pending = False

    def submit(self, owner: object, operation: str, function: Callable) -> bool:
        # submit and finish are UI-thread-only. Pending includes undisplayed results.
        if self.pending:
            return False
        self.pending = True
        self._thread = Thread(target=self._work, args=(owner, operation, function), daemon=True)
        self._thread.start()
        return True

    def _work(self, owner, operation, function) -> None:
        try:
            result = TaskResult(owner, operation, function())
        except IntegrationError as exc:
            result = TaskResult(owner, operation, error_key=exc.key)
        except Exception:
            result = TaskResult(owner, operation, error_key=self.default_error)
        self.events.put(result)

    def finish(self) -> None:
        self.pending = False
