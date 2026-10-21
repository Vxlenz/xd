"""Serial worker bridge for launches, persistent profile sessions and restoration."""
from dataclasses import dataclass
import logging
from queue import Queue
from threading import Event, RLock, Thread
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from .models import Profile, SystemAction
from .runner import ActionResult, Runner
from .system_session import SystemSession
from ..integrations.errors import IntegrationError


@dataclass(frozen=True)
class RunFinished:
    results: tuple[ActionResult, ...]
    error_key: str | None = None


@dataclass(frozen=True)
class LifecycleFinished:
    operation: Literal['recover', 'end', 'close']
    error_key: str | None = None


@dataclass(frozen=True)
class ControlFinished:
    operation: str
    error_key: str | None = None


class Execution:
    def __init__(self, runner: Runner | None = None, *, sessions: SystemSession | None = None):
        self.runner = runner if runner is not None else Runner()
        self.sessions = sessions
        if sessions is not None:
            self.runner.handlers.setdefault('system', sessions.apply)
        self.events: Queue[ActionResult | RunFinished | LifecycleFinished | ControlFinished] = Queue()
        self.current_profile: Profile | None = None
        self.recovery_required = sessions is not None
        self.closed = False
        self.close_attempted = False
        self._thread: Thread | None = None
        self._cancel = Event()
        self._lock = RLock()
        self._busy = False
        self._end_requested = False
        self._close_requested = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def _launch(self, function, *args) -> None:
        self._busy = True
        self._thread = Thread(target=self._work, args=(function, args),
                              daemon=self.sessions is None, name='novadeck-runner')
        self._thread.start()

    def start(self, profile: Profile, *, test: bool = False) -> bool:
        with self._lock:
            if self._busy or self.closed or self._close_requested:
                return False
            if test and self.current_profile is not None:
                return False
            try:
                snapshot = Profile.model_validate_json(profile.model_dump_json(warnings=False))
            except ValidationError as exc:
                raise IntegrationError('invalid_profile') from exc
            if test:
                for action in snapshot.actions:
                    if isinstance(action, SystemAction):
                        action.restore_volume = True
            self._cancel = Event()
            self._launch(self._run, snapshot, test)
            return True

    def _run(self, profile: Profile, test: bool) -> None:
        results: list[ActionResult] = []
        error = None
        try:
            if self.sessions is not None:
                self.sessions.begin(profile.id)
                self.recovery_required = False
            self.current_profile = profile
            results = self.runner.run(profile, self.events.put, self._cancel)
        except IntegrationError as exc:
            error = exc.key
            self.recovery_required = True
        except Exception:
            logging.getLogger('novadeck.runner').warning('run_failed')
            error = 'run_failed'
        finally:
            if test:
                try:
                    if self.sessions is not None:
                        self.sessions.end()
                    self.current_profile = None
                except Exception as exc:
                    error = exc.key if isinstance(exc, IntegrationError) else 'system_restore_failed'
                    self.recovery_required = True
            self.events.put(RunFinished(tuple(results), error))

    def change_system(self, name: str, *, volume_delta: int | None = None, dnd: bool | None = None) -> bool:
        if (volume_delta is None) == (dnd is None):
            raise ValueError('one_system_operation_required')
        with self._lock:
            if self._busy or self.closed or self._close_requested or self.recovery_required:
                return False
            self._launch(self._change_system, name, volume_delta, dnd)
            return True

    def _change_system(self, name: str, volume_delta: int | None, dnd: bool | None) -> None:
        operation = 'voice_master_volume' if volume_delta is not None else 'voice_dnd_on' if dnd else 'voice_dnd_off'
        error = None
        try:
            if self.sessions is None:
                raise IntegrationError('windows_required')
            if self.current_profile is None:
                identifier = str(uuid4())
                self.sessions.begin(identifier)
                self.current_profile = Profile(id=identifier, name=name)
            if volume_delta is not None:
                self.sessions.adjust_volume(volume_delta)
            else:
                self.sessions.apply(SystemAction(do_not_disturb=dnd))
        except IntegrationError as exc:
            error = exc.key
        except Exception:
            error = 'voice_failed'
        self.events.put(ControlFinished(operation, error))

    def _lifecycle(self, operation: Literal['recover', 'end', 'close']) -> None:
        error = None
        try:
            if self.sessions is not None:
                {'recover': self.sessions.recover, 'end': self.sessions.end,
                 'close': self.sessions.close}[operation]()
            self.current_profile = None
            self.recovery_required = False
            if operation == 'close':
                self.closed = True
        except IntegrationError as exc:
            error = exc.key
            self.recovery_required = True
        except Exception:
            error = 'system_restore_failed'
            self.recovery_required = True
        if operation == 'close':
            self.close_attempted = True
        self.events.put(LifecycleFinished(operation, error))

    def _work(self, function, args) -> None:
        try:
            function(*args)
        except Exception:
            self.recovery_required = True
            self.events.put(LifecycleFinished('end', 'system_restore_failed'))
        while True:
            with self._lock:
                if self._close_requested:
                    self._close_requested = False
                    self._end_requested = False
                    operation = 'close'
                elif self._end_requested:
                    self._end_requested = False
                    operation = 'end'
                else:
                    # This is the final write by this worker. A new worker may start now.
                    self._busy = False
                    return
            self._lifecycle(operation)

    def recover(self) -> bool:
        with self._lock:
            if self._busy or self._close_requested or self.closed:
                return False
            self._launch(self._lifecycle, 'recover')
            return True

    def end_profile(self) -> None:
        with self._lock:
            if self.closed or self._close_requested:
                return
            self._cancel.set()
            if self._busy:
                self._end_requested = True
            else:
                self._launch(self._lifecycle, 'end')

    def request_close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self._cancel.set()
            if self._busy:
                self._close_requested = True
            else:
                self._launch(self._lifecycle, 'close')

    def cancel(self) -> None:
        self._cancel.set()
