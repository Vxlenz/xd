"""Versioned, strict JSON schema. Models have no platform dependencies."""
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class Action(Model):
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    delay_seconds: float = Field(default=0, ge=0, le=86400)


class SpotifyAction(Action):
    type: Literal["spotify"] = "spotify"
    uri: str
    shuffle: bool | None = None
    volume: int | None = Field(default=None, ge=0, le=100)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        if re.fullmatch(r"spotify:(playlist|album|track|artist):[A-Za-z0-9]{22}", value):
            return value
        parsed = urlsplit(value)
        match = re.fullmatch(r"/(?:intl-[A-Za-z-]+/)?(playlist|album|track|artist)/([A-Za-z0-9]{22})/?", parsed.path)
        if parsed.scheme == "https" and parsed.netloc == "open.spotify.com" and match:
            kind, identifier = match.groups()
            return f"spotify:{kind}:{identifier}"
        raise ValueError("invalid_spotify_uri")


class SteamAction(Action):
    type: Literal["steam"] = "steam"
    app_id: str = Field(pattern=r"^[1-9][0-9]{0,9}$")
    display_name: str = Field(min_length=1, max_length=120)


class LaunchAction(Action):
    type: Literal["launch"] = "launch"
    target: str = Field(min_length=1)
    arguments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> "LaunchAction":
        if any("\x00" in item for item in [self.target, *self.arguments]):
            raise ValueError("invalid_launch_target")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.target):
            raise ValueError("invalid_launch_target")
        parsed = urlsplit(self.target)
        if parsed.scheme in ("http", "https"):
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("invalid_url") from exc
            if (not parsed.hostname or parsed.username or parsed.password or self.arguments
                    or any(char.isspace() for char in self.target) or "\\" in self.target):
                raise ValueError("invalid_url")
        else:
            from pathlib import PureWindowsPath
            path = PureWindowsPath(self.target)
            if not path.is_absolute() or path.suffix.lower() != ".exe":
                raise ValueError("executable_must_be_absolute")
        return self


class SystemAction(Action):
    type: Literal["system"] = "system"
    volume: int | None = Field(default=None, ge=0, le=100)
    do_not_disturb: bool | None = None
    restore_volume: bool = True

    @model_validator(mode="after")
    def require_operation(self) -> "SystemAction":
        if self.volume is None and self.do_not_disturb is None:
            raise ValueError("missing_system_operation")
        return self


ProfileAction = Annotated[SpotifyAction | SteamAction | LaunchAction | SystemAction, Field(discriminator="type")]


class Trigger(Model):
    type: Literal["manual", "login", "schedule"] = "manual"
    time: str | None = None
    weekdays: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_schedule(self) -> "Trigger":
        if self.type == "schedule":
            if not self.time or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", self.time):
                raise ValueError("invalid_schedule_time")
            if not self.weekdays or len(set(self.weekdays)) != len(self.weekdays) or any(d < 0 or d > 6 for d in self.weekdays):
                raise ValueError("invalid_weekdays")
        elif self.time is not None or self.weekdays:
            raise ValueError("unexpected_schedule_fields")
        return self


class Profile(Model):
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    name: str = Field(min_length=1, max_length=80)
    icon: str = Field(default="✨", min_length=1, max_length=32)
    color: str = Field(default="#7C5CFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    actions: list[ProfileAction] = Field(default_factory=list)
    triggers: list[Trigger] = Field(default_factory=lambda: [Trigger()])

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty_profile_name")
        return value

    @model_validator(mode="after")
    def unique_actions(self) -> "Profile":
        if len({a.id for a in self.actions}) != len(self.actions):
            raise ValueError("duplicate_action_id")
        return self


class ProfileDocument(Model):
    schema_version: Literal[1] = 1
    profiles: list[Profile] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_profiles(self) -> "ProfileDocument":
        if len({p.id for p in self.profiles}) != len(self.profiles):
            raise ValueError("duplicate_profile_id")
        return self
