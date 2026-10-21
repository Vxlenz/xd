from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from novadeck.core.models import LaunchAction, SteamAction
from novadeck.integrations import launcher, steam
from novadeck.integrations.errors import IntegrationError


def test_steam_uses_exact_validated_protocol():
    with patch.object(steam.sys, 'platform', 'win32'), patch.object(steam.os, 'startfile', create=True) as start:
        steam.launch_game(SteamAction(app_id='570', display_name='Dota'))
        start.assert_called_once_with('steam://rungameid/570')


def test_steam_missing_handler_is_friendly():
    with patch.object(steam.sys, 'platform', 'win32'), patch.object(steam.os, 'startfile', create=True, side_effect=OSError):
        with pytest.raises(IntegrationError, match='steam_launch_failed'):
            steam.launch_game(SteamAction(app_id='570', display_name='Dota'))


def test_windows_requirement():
    with patch.object(steam.sys, 'platform', 'linux'):
        with pytest.raises(IntegrationError, match='windows_required'):
            steam.launch_game(SteamAction(app_id='570', display_name='Dota'))
        with pytest.raises(IntegrationError, match='windows_required'):
            launcher.launch(LaunchAction(target=r'C:\Game.exe'))


def test_browser_receives_configured_url_only():
    with patch.object(launcher.webbrowser, 'open', return_value=True) as browser:
        launcher.launch(LaunchAction(target='https://example.com/path?q=1&tab=2'))
        browser.assert_called_once_with('https://example.com/path?q=1&tab=2', new=2)


@pytest.mark.parametrize('result', [False, OSError('missing')])
def test_browser_failure(result):
    browser = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    with patch.object(launcher.webbrowser, 'open', browser):
        with pytest.raises(IntegrationError, match='browser_launch_failed'):
            launcher.launch(LaunchAction(target='https://example.com'))


def test_executable_arguments_are_not_interpreted_by_shell():
    action = LaunchAction(target=r'C:\Apps\My App.exe', arguments=['a b', '& calc', '$(whoami)'])
    fake_path = Mock()
    fake_path.is_file.return_value = True
    fake_path.parent = 'configured-parent'
    fake_path.__str__ = Mock(return_value=action.target)
    with patch.object(launcher.sys, 'platform', 'win32'), patch.object(launcher, 'Path', return_value=fake_path), patch.object(launcher.subprocess, 'Popen') as popen:
        launcher.launch(action)
        popen.assert_called_once_with([action.target, *action.arguments], shell=False, cwd='configured-parent')


def test_missing_executable_does_not_launch():
    with patch.object(launcher.sys, 'platform', 'win32'), patch.object(launcher.Path, 'is_file', return_value=False), patch.object(launcher.subprocess, 'Popen') as popen:
        with pytest.raises(IntegrationError, match='executable_missing'):
            launcher.launch(LaunchAction(target=r'C:\Missing.exe'))
        popen.assert_not_called()


def test_launch_permission_denied():
    with patch.object(launcher.sys, 'platform', 'win32'), patch.object(launcher.Path, 'is_file', return_value=True), patch.object(launcher.subprocess, 'Popen', side_effect=PermissionError):
        with pytest.raises(IntegrationError, match='app_launch_failed'):
            launcher.launch(LaunchAction(target=r'C:\App.exe'))


@pytest.mark.parametrize('target', [
    'file:///C:/test.exe', 'javascript:alert(1)', 'https://example.com\ncalc',
    'https://ex ample.com', 'https://example.com:invalid', 'https://example.com\\evil',
    'https://user:secret@example.com', r'.\relative.exe', r'C:\test.bat',
])
def test_invalid_targets(target):
    with pytest.raises(ValidationError):
        LaunchAction(target=target)
