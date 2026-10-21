"""Sequential execution independent of the GUI. Call run() on a worker thread."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
from threading import Event, Lock
from typing import Literal

from .models import Profile, ProfileAction
from ..integrations.errors import IntegrationError
from ..integrations.launcher import launch
from ..integrations.steam import launch_game

Status = Literal['running', 'succeeded', 'failed', 'cancelled']
Handler = Callable[[ProfileAction], None]
logger = logging.getLogger('novadeck.runner')


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    index: int
    status: Status
    message_key: str | None = None


class RunnerBusy(Exception):
    pass


class Runner:
    def __init__(self, handlers: Mapping[str, Handler] | None = None):
        self.handlers = dict(handlers) if handlers is not None else {
            'steam': launch_game, 'launch': launch,
        }
        self._lock = Lock()

    def run(self, profile: Profile, emit: Callable[[ActionResult], None] | None = None,
            cancel: Event | None = None) -> list[ActionResult]:
        # An immutable-to-the-caller snapshot prevents edits changing a live run.
        snapshot = Profile.model_validate_json(profile.model_dump_json())
        if not self._lock.acquire(blocking=False):
            raise RunnerBusy('runner_busy')
        cancel = cancel if cancel is not None else Event()
        results: list[ActionResult] = []

        def report(result: ActionResult) -> None:
            if emit is not None:
                try:
                    emit(result)
                except Exception:
                    # A failed observer must not interrupt execution or leak secrets.
                    logger.warning('runner_observer_failed')

        try:
            for index, action in enumerate(snapshot.actions):
                # Delay is before this action, including the first one. It is cancellable.
                if cancel.is_set() or (action.delay_seconds > 0 and cancel.wait(action.delay_seconds)):
                    result = ActionResult(action.id, index, 'cancelled', 'run_cancelled')
                else:
                    report(ActionResult(action.id, index, 'running'))
                    try:
                        handler = self.handlers.get(action.type)
                        if handler is None:
                            raise IntegrationError('integration_pending')
                        handler(action)
                        result = ActionResult(action.id, index, 'succeeded')
                    except IntegrationError as exc:
                        result = ActionResult(action.id, index, 'failed', exc.key)
                    except Exception:
                        logger.warning('action_failed type=%s', action.type)
                        result = ActionResult(action.id, index, 'failed', 'action_failed')
                results.append(result)
                report(result)
            return results
        finally:
            self._lock.release()
