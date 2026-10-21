"""Atomic writes with a durable backup of the exact previous contents."""
import os
from pathlib import Path
import tempfile
from threading import RLock

from pydantic import ValidationError

from .config import data_directory
from .models import Profile, ProfileDocument


class ProfileStoreError(Exception):
    """The UI should translate this exception's message key."""


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else data_directory() / "profiles.json"
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self._lock = RLock()

    def load(self) -> ProfileDocument:
        with self._lock:
            try:
                return ProfileDocument.model_validate_json(self.path.read_bytes())
            except FileNotFoundError:
                return ProfileDocument()
            except (OSError, ValidationError) as exc:
                raise ProfileStoreError("profiles_read_failed") from exc

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".novadeck-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, document: ProfileDocument) -> None:
        with self._lock:
            # Revalidate even if callers mutated a nested list after construction.
            validated = ProfileDocument.model_validate_json(document.model_dump_json())
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists():
                    self._atomic_write(self.backup_path, self.path.read_bytes())
                self._atomic_write(self.path, validated.model_dump_json(indent=2).encode("utf-8"))
            except OSError as exc:
                raise ProfileStoreError("profiles_write_failed") from exc

    def upsert(self, profile: Profile) -> None:
        with self._lock:
            document = self.load()
            for index, existing in enumerate(document.profiles):
                if existing.id == profile.id:
                    document.profiles[index] = profile
                    break
            else:
                document.profiles.append(profile)
            self.save(document)

    def delete(self, profile_id: str) -> None:
        with self._lock:
            document = self.load()
            document.profiles = [p for p in document.profiles if p.id != profile_id]
            self.save(document)

    def import_profile(self, path: Path) -> Profile:
        try:
            profile = Profile.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise ProfileStoreError("profile_import_failed") from exc
        self.upsert(profile)
        return profile

    def export_profile(self, profile_id: str, path: Path) -> None:
        with self._lock:
            profile = next((p for p in self.load().profiles if p.id == profile_id), None)
            if profile is None:
                raise ProfileStoreError("profile_not_found")
            # Exporting must never overwrite the store or its recovery backup.
            if path.resolve() in (self.path.resolve(), self.backup_path.resolve()):
                raise ProfileStoreError("invalid_export_path")
            try:
                self._atomic_write(path, profile.model_dump_json(indent=2).encode("utf-8"))
            except OSError as exc:
                raise ProfileStoreError("profile_export_failed") from exc
