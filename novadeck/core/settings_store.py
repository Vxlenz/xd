"""Persist public settings only; OAuth credentials live in a separate cache."""
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from .config import data_directory
from .models import Model
from .profile_store import ProfileStore
from ..integrations.errors import IntegrationError


class VoiceOptions(Model):
    enabled: bool = False
    language: Literal['es', 'en'] = 'es'
    microphone: str | None = Field(default=None, max_length=500)
    hotkey: str = 'ctrl+alt+space'
    always_listening: bool = False

    @field_validator('hotkey')
    @classmethod
    def validate_hotkey(cls, value: str) -> str:
        from ..voice.hotkey import parse_hotkey
        parse_hotkey(value)
        return value.lower().strip()


class AppSettings(Model):
    spotify_client_id: str = Field(default='', pattern=r'^(?:[0-9a-fA-F]{32})?$')
    language: Literal['es', 'en'] = 'es'
    voice: VoiceOptions = Field(default_factory=VoiceOptions)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else data_directory() / 'settings.json'
        self._lock = RLock()

    def load(self) -> AppSettings:
        try:
            return AppSettings.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValidationError) as exc:
            raise IntegrationError('settings_read_failed') from exc

    def save(self, settings: AppSettings) -> None:
        validated = AppSettings.model_validate_json(settings.model_dump_json())
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ProfileStore._atomic_write(self.path, validated.model_dump_json(indent=2).encode('utf-8'))
        except OSError as exc:
            raise IntegrationError('settings_write_failed') from exc

    def update(self, **changes) -> AppSettings:
        with self._lock:
            current = self.load().model_dump()
            current.update(changes)
            updated = AppSettings.model_validate(current)
            self.save(updated)
            return updated
