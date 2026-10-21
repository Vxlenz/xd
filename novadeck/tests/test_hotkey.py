"""Late native events must not reactivate capture after changing or removing a hook."""
from types import SimpleNamespace
from unittest.mock import Mock

from novadeck.voice.hotkey import GlobalHotkey


class Listener:
    def __init__(self, on_press, on_release):
        self.on_press, self.on_release = on_press, on_release
        self.on_stop = lambda: None

    def canonical(self, key):
        return key

    def start(self):
        pass

    def stop(self):
        self.on_stop()


def hotkey():
    backend = SimpleNamespace(
        Listener=Listener,
        HotKey=SimpleNamespace(parse=lambda value: value.replace('<', '').replace('>', '').split('+')),
    )
    press, release = Mock(), Mock()
    return GlobalHotkey(press, release, backend=backend), press, release


def test_replaced_hook_cannot_activate_or_contaminate_current_shortcut():
    shortcut, press, release = hotkey()
    assert shortcut.start('ctrl+a')
    old = shortcut.listener
    assert shortcut.start('ctrl+b')
    current = shortcut.listener
    try:
        old.on_press('ctrl')
        old.on_press('a')
        press.assert_not_called()
        # The old Ctrl event must not combine with B from the new listener.
        current.on_press('b')
        press.assert_not_called()
        current.on_press('ctrl')
        press.assert_called_once()
        current.on_release('b')
        release.assert_called_once()
    finally:
        shortcut.stop()


def test_replaced_hook_cannot_release_new_capture():
    shortcut, press, release = hotkey()
    assert shortcut.start('ctrl+a')
    old = shortcut.listener
    assert shortcut.start('ctrl+b')
    current = shortcut.listener
    try:
        current.on_press('ctrl')
        current.on_press('b')
        press.assert_called_once()
        old.on_release('a')
        release.assert_not_called()
        current.on_release('b')
        release.assert_called_once()
    finally:
        shortcut.stop()


def test_stop_invalidates_callbacks_before_calling_native_backend():
    shortcut, press, release = hotkey()
    assert shortcut.start('ctrl+a')
    listener = shortcut.listener
    def during_stop():
        listener.on_press('ctrl')
        listener.on_press('a')
    listener.on_stop = during_stop
    shortcut.stop()
    press.assert_not_called()
    release.assert_not_called()
    assert shortcut.listener is None


def test_stop_failure_still_releases_capture_and_allows_reconfiguration(caplog):
    shortcut, press, release = hotkey()
    assert shortcut.start('ctrl+a')
    listener = shortcut.listener
    listener.on_press('ctrl')
    listener.on_press('a')
    def fail():
        raise OSError('private native details')
    listener.on_stop = fail
    shortcut.stop()
    release.assert_called_once()
    assert shortcut.listener is None
    listener.on_press('ctrl')
    listener.on_press('a')
    assert press.call_count == 1
    assert 'private native details' not in caplog.text
    assert shortcut.start('ctrl+b')
    shortcut.stop()
