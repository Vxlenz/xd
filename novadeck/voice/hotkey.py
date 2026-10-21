"""Global push-to-talk via pynput. Importing this module never installs a hook."""
from dataclasses import dataclass
import logging
import re
import sys
from threading import Lock


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: tuple[str, ...]
    key: str

    @property
    def pynput(self) -> str:
        parts = [f'<{modifier}>' for modifier in self.modifiers]
        parts.append(f'<{self.key}>' if self.key == 'space' or self.key.startswith('f') and len(self.key)>1 else self.key)
        return '+'.join(parts)


def parse_hotkey(value: str) -> HotkeySpec:
    parts = [part.strip().lower() for part in value.split('+')]
    if len(parts) < 2 or len(set(parts)) != len(parts):
        raise ValueError('invalid_hotkey')
    modifiers, key = parts[:-1], parts[-1]
    if (not all(part in ('ctrl', 'alt', 'shift') for part in modifiers)
            or not re.fullmatch(r'(?:space|[a-z0-9]|f[1-9]|f1[0-2])', key)):
        raise ValueError('invalid_hotkey')
    return HotkeySpec(tuple(sorted(modifiers)), key)


class GlobalHotkey:
    def __init__(self, press, release, *, backend=None):
        self.press, self.release = press, release
        self.backend = backend
        self.listener = None
        self.pressed = set()
        self.held = False
        self._lock = Lock()

    def start(self, shortcut: str) -> bool:
        self.stop()
        spec = parse_hotkey(shortcut)
        if self.backend is None:
            if sys.platform != 'win32':
                return False
            try:
                from pynput import keyboard
                self.backend = keyboard
            except (ImportError, OSError):
                return False
        try:
            expected = set(self.backend.HotKey.parse(spec.pynput))
            listener = None
            def on_press(key):
                with self._lock:
                    if listener is None or listener is not self.listener:
                        return
                    self.pressed.add(listener.canonical(key))
                    if expected <= self.pressed and not self.held:
                        self.held = True
                        self.press()
            def on_release(key):
                with self._lock:
                    if listener is None or listener is not self.listener:
                        return
                    canonical = listener.canonical(key)
                    self.pressed.discard(canonical)
                    if canonical in expected and self.held:
                        self.held = False
                        self.release()
            listener = self.backend.Listener(on_press=on_press, on_release=on_release)
            with self._lock:
                self.listener = listener
            listener.start()
            return True
        except Exception:
            self.stop()
            return False

    def stop(self) -> None:
        with self._lock:
            listener = self.listener
            self.listener = None
            if self.held:
                self.release()
            self.held = False
            self.pressed.clear()
        # Native shutdown may deliver a final event or fail. Callbacks are already
        # detached, and a pressed shortcut has been released before either case.
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                logging.getLogger('novadeck.voice').warning('hotkey_stop_failed')
