"""Durable before-change journal for the currently active profile's system state."""
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .config import data_directory
from .models import Model, SystemAction
from .profile_store import ProfileStore
from .session_lease import SessionLease
from ..integrations.dnd import DoNotDisturb, NotificationState
from ..integrations.errors import IntegrationError
from ..integrations.volume import VolumeState, WindowsVolume


class RecoveryState(Model):
    schema_version: Literal[1] = 1
    profile_id: str | None = None
    volumes: list[VolumeState] = Field(default_factory=list)
    notifications: NotificationState | None = None

    @model_validator(mode='after')
    def unique_endpoints(self) -> 'RecoveryState':
        if len({volume.device_id for volume in self.volumes}) != len(self.volumes):
            raise ValueError('duplicate_recovery_device')
        return self

    @property
    def pending(self) -> bool:
        return bool(self.volumes) or self.notifications is not None


class RecoveryJournal:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> RecoveryState:
        try:
            return RecoveryState.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return RecoveryState()
        except ValidationError as exc:
            raise IntegrationError('system_recovery_invalid') from exc
        except OSError as exc:
            raise IntegrationError('system_recovery_read_failed') from exc

    def save(self, state: RecoveryState) -> None:
        validated = RecoveryState.model_validate_json(state.model_dump_json())
        try:
            if validated.pending:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                ProfileStore._atomic_write(self.path, validated.model_dump_json(indent=2).encode('utf-8'))
            else:
                self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise IntegrationError('system_recovery_write_failed') from exc


class SystemSession:
    def __init__(self, path: Path | None = None, *, volume=None, dnd=None, journal=None, lease=None):
        path = path if path is not None else data_directory() / 'system_recovery.json'
        self.volume = volume if volume is not None else WindowsVolume()
        self.dnd = dnd if dnd is not None else DoNotDisturb()
        self.journal = journal if journal is not None else RecoveryJournal(path)
        self.lease = lease if lease is not None else SessionLease(path.with_name('.system-session.lock'))
        self._state = RecoveryState()
        self._original_volumes: dict[str, VolumeState] = {}
        self._lock = RLock()
        self._loaded = False
        self._owned_journal = False
        self._load_error: str | None = None
        self._active = False

    def recover(self) -> None:
        with self._lock:
            self.lease.acquire()
            if not self._loaded:
                self._load_journal()
            self._restore()

    def _load_journal(self) -> None:
        try:
            self._state = self.journal.load()
        except IntegrationError as exc:
            self._load_error = exc.key
            raise
        self._load_error = None
        self._loaded = True
        self._owned_journal = True

    def begin(self, profile_id: str) -> None:
        with self._lock:
            self.recover()  # Ends the previous profile before taking any new snapshots.
            self._state = RecoveryState(profile_id=profile_id)
            self._original_volumes = {}
            self._active = True

    def _commit(self, state: RecoveryState) -> None:
        self.journal.save(state)
        self._state = state

    def apply(self, action: SystemAction) -> None:
        action = SystemAction.model_validate_json(action.model_dump_json())
        with self._lock:
            if not self._active:
                raise IntegrationError('system_session_not_active')
            errors = []
            # Attempt independent operations even if one component fails.
            if action.volume is not None:
                try:
                    self._set_volume(self.volume.capture(), action.volume, action.restore_volume)
                except Exception as exc:
                    errors.append(exc if isinstance(exc, IntegrationError) else IntegrationError('volume_write_failed'))
            if action.do_not_disturb is not None:
                try:
                    if self._state.notifications is None:
                        original = self.dnd.capture()
                        changed = self._state.model_copy(deep=True)
                        changed.notifications = original
                        self._commit(changed)
                    self.dnd.set(action.do_not_disturb)
                except Exception as exc:
                    errors.append(exc if isinstance(exc, IntegrationError) else IntegrationError('dnd_write_failed'))
            if errors:
                raise errors[0]

    def _set_volume(self, current: VolumeState, percent: int, restore: bool) -> None:
        original = self._original_volumes.setdefault(current.device_id, current)
        if restore and not any(volume.device_id == current.device_id for volume in self._state.volumes):
            changed = self._state.model_copy(deep=True)
            changed.volumes.append(original)
            self._commit(changed)
        self.volume.set(percent, device_id=current.device_id)

    def adjust_volume(self, delta: int) -> None:
        with self._lock:
            if not self._active:
                raise IntegrationError('system_session_not_active')
            current = self.volume.capture()
            target = max(0, min(100, round(current.level*100)+delta))
            self._set_volume(current, target, True)

    def end(self) -> None:
        with self._lock:
            if self._load_error is not None:
                raise IntegrationError(self._load_error)
            if self._owned_journal and not self._loaded:
                self.lease.acquire()
                self._load_journal()
            if self._loaded:
                self.lease.acquire()
                self._restore()

    def _restore(self) -> None:
        errors = []
        for original in list(self._state.volumes):
            try:
                self.volume.restore(original)
                changed = self._state.model_copy(deep=True)
                changed.volumes = [volume for volume in changed.volumes if volume.device_id != original.device_id]
                self._commit(changed)
            except Exception as exc:
                errors.append(exc if isinstance(exc, IntegrationError) else IntegrationError('volume_restore_failed'))
        if self._state.notifications is not None:
            try:
                self.dnd.restore(self._state.notifications)
                changed = self._state.model_copy(deep=True)
                changed.notifications = None
                self._commit(changed)
            except Exception as exc:
                errors.append(exc if isinstance(exc, IntegrationError) else IntegrationError('dnd_write_failed'))
        if errors:
            raise IntegrationError('system_restore_failed') from errors[0]
        # Includes an empty journal left by an interrupted first write or older version.
        self._commit(RecoveryState())
        self._active = False
        self._original_volumes = {}

    def close(self) -> None:
        with self._lock:
            try:
                if self._load_error is not None:
                    raise IntegrationError(self._load_error)
                if self._owned_journal and not self._loaded:
                    self.lease.acquire()
                    self._load_journal()
                if self._loaded:
                    self.lease.acquire()
                    self._restore()
                    self._owned_journal = False
            finally:
                self.lease.close()
                self._loaded = False
                self._active = False
