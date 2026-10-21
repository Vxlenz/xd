"""Master endpoint volume. COM interfaces never leave the calling worker thread."""
from collections.abc import Callable
import sys
from typing import TypeVar

from pydantic import Field

from ..core.models import Model
from .errors import IntegrationError

T = TypeVar('T')


class VolumeState(Model):
    device_id: str = Field(min_length=1)
    level: float = Field(ge=0, le=1)


class WindowsVolume:
    def __init__(self, *, audio=None, com=None):
        self.audio = audio
        self.com = com

    def _perform(self, device_id: str | None, operation: Callable, error_key: str) -> T:
        if self.audio is None or self.com is None:
            if sys.platform != 'win32':
                raise IntegrationError('windows_required')
            try:
                import comtypes
                from pycaw.pycaw import AudioUtilities
            except ImportError as exc:
                raise IntegrationError('volume_dependencies_missing') from exc
            audio, com = AudioUtilities, comtypes
        else:
            audio, com = self.audio, self.com
        initialized = False
        device = None
        try:
            com.CoInitialize()
            initialized = True
            if device_id is None:
                device = audio.GetSpeakers()
            else:
                native = audio.GetDeviceEnumerator().GetDevice(device_id)
                try:
                    device = audio.CreateDevice(native)
                finally:
                    native = None
            if device is None:
                raise IntegrationError('volume_device_missing')
            return operation(device)
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError(error_key) from exc
        finally:
            # Release all endpoint interfaces before uninitializing COM.
            device = None
            if initialized:
                com.CoUninitialize()

    def capture(self) -> VolumeState:
        return self._perform(None, lambda device: VolumeState(
            device_id=device.id, level=float(device.EndpointVolume.GetMasterVolumeLevelScalar())), 'volume_read_failed')

    def set(self, percent: int, *, device_id: str) -> None:
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError('invalid_volume')
        self._perform(device_id, lambda device: device.EndpointVolume.SetMasterVolumeLevelScalar(
            percent / 100, None), 'volume_write_failed')

    def restore(self, state: VolumeState) -> None:
        validated = VolumeState.model_validate_json(state.model_dump_json())
        self._perform(validated.device_id, lambda device: device.EndpointVolume.SetMasterVolumeLevelScalar(
            validated.level, None), 'volume_restore_failed')
