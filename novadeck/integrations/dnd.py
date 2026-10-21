"""Reversible toast-notification preference. This is not the Focus Assist API."""
from collections.abc import Callable
import sys

from pydantic import Field, model_validator

from ..core.models import Model
from .errors import IntegrationError

SETTINGS_KEY = r'Software\Microsoft\Windows\CurrentVersion\Notifications\Settings'
VALUE_NAME = 'NOC_GLOBAL_SETTING_TOASTS_ENABLED'


class NotificationState(Model):
    present: bool
    value: int | None = Field(default=None, ge=0, le=4294967295)

    @model_validator(mode='after')
    def validate_presence(self) -> 'NotificationState':
        if self.present != (self.value is not None):
            raise ValueError('invalid_notification_state')
        return self


def _broadcast_change() -> None:
    if sys.platform != 'win32':
        return
    import ctypes
    from ctypes import wintypes
    try:
        result = ctypes.c_size_t()
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send.restype = wintypes.LPARAM
        send(0xFFFF, 0x001A, 0, SETTINGS_KEY, 0x0002, 1000, ctypes.byref(result))
    except (OSError, AttributeError):
        # The stored preference is authoritative; Windows may ignore the broadcast.
        pass


class DoNotDisturb:
    def __init__(self, *, registry=None, notify: Callable = _broadcast_change):
        self.registry = registry
        self.notify = notify

    def _registry(self):
        if self.registry is not None:
            return self.registry
        if sys.platform != 'win32':
            raise IntegrationError('windows_required')
        import winreg
        return winreg

    def capture(self) -> NotificationState:
        registry = self._registry()
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, SETTINGS_KEY, 0, registry.KEY_READ) as key:
                value, value_type = registry.QueryValueEx(key, VALUE_NAME)
                if value_type != registry.REG_DWORD or type(value) is not int:
                    raise IntegrationError('dnd_unsupported_value')
                return NotificationState(present=True, value=value)
        except FileNotFoundError:
            return NotificationState(present=False)
        except OSError as exc:
            raise IntegrationError('dnd_read_failed') from exc

    def set(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError('invalid_dnd')
        self._write(NotificationState(present=True, value=0 if enabled else 1))

    def restore(self, state: NotificationState) -> None:
        self._write(NotificationState.model_validate_json(state.model_dump_json()))

    def _write(self, state: NotificationState) -> None:
        registry = self._registry()
        try:
            if state.present:
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, SETTINGS_KEY, 0, registry.KEY_SET_VALUE) as key:
                    registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_DWORD, state.value)
            else:
                try:
                    with registry.OpenKey(registry.HKEY_CURRENT_USER, SETTINGS_KEY, 0, registry.KEY_SET_VALUE) as key:
                        registry.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise IntegrationError('dnd_write_failed') from exc
        self.notify()
