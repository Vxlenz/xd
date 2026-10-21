"""Per-user Windows startup registration, without admin privileges or a shell."""
from pathlib import Path
import subprocess
import sys

from .errors import IntegrationError

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'NovaDeck'


class WindowsStartup:
    def __init__(self, *, registry=None, executable: Path | None = None,
                 entrypoint: Path | None = None, frozen: bool | None = None):
        self.registry = registry
        self.executable = executable if executable is not None else Path(sys.executable)
        self.entrypoint = entrypoint if entrypoint is not None else Path(__file__).resolve().parents[2] / 'app.py'
        self.frozen = bool(getattr(sys, 'frozen', False)) if frozen is None else frozen

    @property
    def supported(self) -> bool:
        return self.registry is not None or sys.platform == 'win32'

    def command(self) -> str:
        executable = self.executable
        if not self.frozen and executable.name.lower() == 'python.exe':
            windowless = executable.with_name('pythonw.exe')
            if windowless.is_file():
                executable = windowless
        arguments = [str(executable)]
        if not self.frozen:
            arguments.append(str(self.entrypoint))
        return subprocess.list2cmdline([*arguments, '--minimized', '--login'])

    def _registry(self):
        if not self.supported:
            raise IntegrationError('windows_required')
        if self.registry is not None:
            return self.registry
        import winreg
        return winreg

    def enabled(self) -> bool:
        if not self.supported:
            return False
        registry = self._registry()
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ) as key:
                value, _ = registry.QueryValueEx(key, VALUE_NAME)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise IntegrationError('startup_read_failed') from exc

    def set_enabled(self, enabled: bool) -> None:
        registry = self._registry()
        try:
            with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                if enabled:
                    registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, self.command())
                else:
                    try:
                        registry.DeleteValue(key, VALUE_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            raise IntegrationError('startup_write_failed') from exc
