"""pystray callbacks only enqueue commands; they never access Tk widgets."""
from dataclasses import dataclass
from importlib.resources import files
from queue import Queue
import sys

from PIL import Image

from ..core.models import Profile


@dataclass(frozen=True)
class TrayCommand:
    operation: str
    profile_id: str | None = None


class Tray:
    def __init__(self, *, backend=None):
        self.backend = backend
        self.events: Queue[TrayCommand] = Queue()
        self.ready = False
        self.icon = None

    def _action(self, operation: str, profile_id: str | None = None):
        def callback(icon, item):
            self.events.put(TrayCommand(operation, profile_id))
        return callback

    def _menu(self, profiles: list[Profile], strings: dict[str, str], paused: bool):
        backend = self.backend
        profile_items = [backend.MenuItem(profile.name, self._action('run', profile.id)) for profile in profiles]
        if not profile_items:
            profile_items = [backend.MenuItem(strings['tray_no_profiles'], None, enabled=False)]
        return backend.Menu(
            backend.MenuItem(strings['tray_open'], self._action('open'), default=True),
            backend.MenuItem(strings['profiles_heading'], backend.Menu(*profile_items)),
            backend.MenuItem(strings['scheduler_resume' if paused else 'scheduler_pause'], self._action('pause')),
            backend.MenuItem(strings['quit'], self._action('quit')),
        )

    def start(self, profiles: list[Profile], strings: dict[str, str], paused: bool = False) -> None:
        if self.backend is None and sys.platform != 'win32':
            self.events.put(TrayCommand('unavailable'))
            return
        try:
            if self.backend is None:
                import pystray
                self.backend = pystray
            with Image.open(files('novadeck').joinpath('assets/novadeck.png')) as image:
                self.icon = self.backend.Icon('NovaDeck', image.copy(), strings['app_name'],
                                              self._menu(profiles, strings, paused))
            def setup(icon):
                try:
                    icon.visible = True
                    self.ready = True
                    self.events.put(TrayCommand('ready'))
                except Exception:
                    self.events.put(TrayCommand('unavailable'))
            self.icon.run_detached(setup=setup)
        except Exception:
            self.ready = False
            self.events.put(TrayCommand('unavailable'))

    def update(self, profiles: list[Profile], strings: dict[str, str], paused: bool) -> None:
        if self.icon is None:
            return
        try:
            self.icon.menu = self._menu(profiles, strings, paused)
            self.icon.update_menu()
        except Exception:
            self.ready = False
            self.events.put(TrayCommand('unavailable'))

    def stop(self) -> None:
        self.ready = False
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
