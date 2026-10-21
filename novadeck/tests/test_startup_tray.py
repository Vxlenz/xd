from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from novadeck.core.models import Profile
from novadeck.i18n import translations
from novadeck.integrations.errors import IntegrationError
from novadeck.integrations.startup import WindowsStartup, RUN_KEY, VALUE_NAME
from novadeck.ui.tray import Tray


def test_startup_command_quotes_paths_and_marks_login(tmp_path):
    executable = tmp_path / 'Python Installation' / 'python.exe'
    executable.parent.mkdir()
    windowless = executable.with_name('pythonw.exe')
    windowless.touch()
    service = WindowsStartup(executable=executable, entrypoint=tmp_path / 'My App' / 'app.py', frozen=False)
    command = service.command()
    assert command.startswith('"' + str(windowless) + '"')
    assert '"' + str(tmp_path / 'My App' / 'app.py') + '"' in command
    assert command.endswith('--minimized --login')
    frozen = WindowsStartup(executable=tmp_path / 'NovaDeck.exe', frozen=True)
    assert frozen.command() == str(tmp_path / 'NovaDeck.exe') + ' --minimized --login'


def test_startup_registry_touches_only_current_user_app_value():
    registry = MagicMock()
    service = WindowsStartup(registry=registry, executable=Path('python.exe'), entrypoint=Path('app.py'), frozen=False)
    registry.QueryValueEx.return_value = ('existing command', registry.REG_SZ)
    assert service.enabled()
    registry.OpenKey.assert_called_once_with(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_READ)
    registry.QueryValueEx.assert_called_once_with(registry.OpenKey.return_value.__enter__.return_value, VALUE_NAME)
    service.set_enabled(True)
    registry.SetValueEx.assert_called_once_with(registry.CreateKeyEx.return_value.__enter__.return_value,
                                              VALUE_NAME, 0, registry.REG_SZ, service.command())
    service.set_enabled(False)
    registry.DeleteValue.assert_called_once_with(registry.CreateKeyEx.return_value.__enter__.return_value, VALUE_NAME)


def test_startup_missing_value_and_permission_errors():
    registry = MagicMock()
    service = WindowsStartup(registry=registry)
    registry.OpenKey.side_effect = FileNotFoundError
    assert not service.enabled()
    registry.OpenKey.side_effect = PermissionError
    with pytest.raises(IntegrationError, match='startup_read_failed'):
        service.enabled()
    registry.CreateKeyEx.side_effect = PermissionError
    with pytest.raises(IntegrationError, match='startup_write_failed'):
        service.set_enabled(True)
    registry.CreateKeyEx.side_effect = None
    registry.DeleteValue.side_effect = FileNotFoundError
    service.set_enabled(False)  # Disabling twice is safe.


def test_startup_is_explicitly_unsupported_outside_windows():
    with patch('novadeck.integrations.startup.sys.platform', 'linux'):
        service = WindowsStartup()
        assert not service.supported
        assert not service.enabled()
        with pytest.raises(IntegrationError, match='windows_required'):
            service.set_enabled(True)


class MenuItem:
    def __init__(self, text, action, **kwargs):
        self.text, self.action, self.options = text, action, kwargs


class Icon:
    def __init__(self, name, image, title, menu):
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.visible = False
        self.stopped = False
    def run_detached(self, setup):
        setup(self)
    def update_menu(self):
        return
    def stop(self):
        self.stopped = True


def fake_tray():
    return Tray(backend=SimpleNamespace(MenuItem=MenuItem, Menu=lambda *items: items, Icon=Icon))


def test_tray_profile_actions_only_enqueue_commands_and_menu_can_refresh():
    tray = fake_tray()
    profile = Profile(name='Gaming')
    tray.start([profile], translations())
    assert tray.ready
    assert tray.events.get_nowait().operation == 'ready'
    menu = tray.icon.menu
    menu[1].action[0].action(tray.icon, menu[1].action[0])
    command = tray.events.get_nowait()
    assert command.operation == 'run' and command.profile_id == profile.id
    menu[0].action(tray.icon, menu[0])
    assert tray.events.get_nowait().operation == 'open'
    menu[2].action(tray.icon, menu[2])
    assert tray.events.get_nowait().operation == 'pause'
    tray.update([], translations('en'), True)
    assert tray.icon.menu[2].text == 'Resume scheduler'
    assert tray.icon.menu[1].action[0].options['enabled'] is False
    icon = tray.icon
    tray.stop()
    assert icon.stopped and not tray.ready


def test_tray_failure_and_unsupported_backend_leave_recovery_command():
    tray = fake_tray()
    tray.backend.Icon = Mock(side_effect=RuntimeError('backend failed'))
    tray.start([], translations())
    assert tray.events.get_nowait().operation == 'unavailable'
    assert not tray.ready
    with patch('novadeck.ui.tray.sys.platform', 'linux'):
        tray = Tray()
        tray.start([], translations())
        assert tray.events.get_nowait().operation == 'unavailable'


def test_entrypoint_passes_login_and_minimized_flags_without_side_effects():
    from novadeck.app import main
    with patch('novadeck.app.configure_logging'), patch('customtkinter.set_appearance_mode'), patch(
            'novadeck.ui.main_window.MainWindow') as window:
        main(['--minimized', '--login'])
        window.assert_called_once_with(minimized=True, login=True)
        window.return_value.mainloop.assert_called_once()
