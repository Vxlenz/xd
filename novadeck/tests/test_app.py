"""Startup failures remain understandable in a windowless Windows distribution."""
from io import StringIO
from unittest.mock import Mock, patch

import pytest

from novadeck.app import main
from novadeck.i18n import translations


def test_unwritable_log_directory_shows_friendly_error_without_starting_ui():
    with patch('novadeck.app.configure_logging', side_effect=PermissionError('private-data-directory')), patch(
            'novadeck.app.show_startup_error', create=True) as show_error, patch(
            'novadeck.ui.main_window.MainWindow') as window:
        with pytest.raises(SystemExit) as error:
            main([])
    assert error.value.code == 1
    window.assert_not_called()
    show_error.assert_called_once_with('startup_logging_failed')


def test_missing_gui_dependency_is_reported_without_raw_details():
    with patch('novadeck.app.configure_logging'), patch.dict('sys.modules', {'customtkinter': None}), patch(
            'novadeck.app.show_startup_error', create=True) as show_error:
        with pytest.raises(SystemExit) as error:
            main([])
    assert error.value.code == 1
    show_error.assert_called_once_with('startup_failed')


def test_unexpected_mainloop_failure_requests_cleanup_and_hides_private_details(caplog):
    window = Mock()
    window.mainloop.side_effect = RuntimeError('private-token-or-command')
    with patch('novadeck.app.configure_logging'), patch('customtkinter.set_appearance_mode'), patch(
            'novadeck.ui.main_window.MainWindow', return_value=window), patch(
            'novadeck.app.show_startup_error', create=True) as show_error:
        with pytest.raises(SystemExit) as error:
            main([])
    assert error.value.code == 1
    window.destroy.assert_called_once()
    show_error.assert_called_once_with('startup_failed')
    assert 'RuntimeError' in caplog.text
    assert 'private-token-or-command' not in caplog.text


def test_cleanup_failure_still_reports_original_error_without_leaking_details(caplog):
    window = Mock()
    window.mainloop.side_effect = RuntimeError('private-token-or-command')
    window.destroy.side_effect = RuntimeError('private-cleanup-detail')
    with patch('novadeck.app.configure_logging'), patch('customtkinter.set_appearance_mode'), patch(
            'novadeck.ui.main_window.MainWindow', return_value=window), patch(
            'novadeck.app.show_startup_error', create=True) as show_error:
        with pytest.raises(SystemExit) as error:
            main([])
    assert error.value.code == 1
    show_error.assert_called_once_with('startup_failed')
    assert 'private-token-or-command' not in caplog.text
    assert 'private-cleanup-detail' not in caplog.text


def test_startup_error_uses_windows_native_dialog_without_initializing_tk(monkeypatch, tmp_path):
    from novadeck.app import show_startup_error
    import ctypes
    monkeypatch.setenv('APPDATA', str(tmp_path))
    native = Mock()
    native.user32.MessageBoxW.return_value = 1
    with patch('novadeck.app.sys.platform', 'win32'), patch.object(ctypes, 'windll', native, create=True), patch(
            'tkinter.messagebox.showerror') as tk_dialog:
        show_startup_error('startup_logging_failed')
    args = native.user32.MessageBoxW.call_args.args
    assert args == (None, translations()['startup_logging_failed'], translations()['app_name'], 0x10)
    tk_dialog.assert_not_called()


def test_startup_error_falls_back_to_text_when_graphical_dialogs_are_unavailable(monkeypatch, tmp_path):
    from novadeck.app import show_startup_error
    monkeypatch.setenv('APPDATA', str(tmp_path))
    output = StringIO()
    with patch('novadeck.app.sys.platform', 'linux'), patch('tkinter.messagebox.showerror', side_effect=RuntimeError(
            'private-display-detail')), patch('novadeck.app.sys.stderr', output):
        show_startup_error('startup_failed')
    assert output.getvalue().strip() == translations()['startup_failed']
    assert 'private-display-detail' not in output.getvalue()


def test_startup_error_uses_saved_language_without_changing_settings(monkeypatch, tmp_path):
    from novadeck.app import show_startup_error
    monkeypatch.setenv('APPDATA', str(tmp_path))
    directory = tmp_path / 'NovaDeck'
    directory.mkdir()
    settings = directory / 'settings.json'
    settings.write_text('{"language":"en"}', encoding='utf-8')
    original = settings.read_bytes()
    with patch('novadeck.app.sys.platform', 'linux'), patch('tkinter.messagebox.showerror') as show_error:
        show_startup_error('startup_failed')
    show_error.assert_called_once_with(translations('en')['app_name'], translations('en')['startup_failed'])
    assert settings.read_bytes() == original


@pytest.mark.parametrize('contents', ['{broken', '[]', '{"language":["en"]}'])
def test_invalid_settings_do_not_mask_the_original_startup_error(monkeypatch, tmp_path, contents):
    from novadeck.app import show_startup_error
    monkeypatch.setenv('APPDATA', str(tmp_path))
    directory = tmp_path / 'NovaDeck'
    directory.mkdir()
    settings = directory / 'settings.json'
    settings.write_text(contents, encoding='utf-8')
    with patch('novadeck.app.sys.platform', 'linux'), patch('tkinter.messagebox.showerror') as show_error:
        show_startup_error('startup_logging_failed')
    show_error.assert_called_once_with(translations()['app_name'], translations()['startup_logging_failed'])
    assert settings.read_text(encoding='utf-8') == contents


def test_failed_native_dialog_falls_back_to_tk(monkeypatch, tmp_path):
    from novadeck.app import show_startup_error
    import ctypes
    monkeypatch.setenv('APPDATA', str(tmp_path))
    native = Mock()
    native.user32.MessageBoxW.return_value = 0
    with patch('novadeck.app.sys.platform', 'win32'), patch.object(ctypes, 'windll', native, create=True), patch(
            'tkinter.messagebox.showerror') as tk_dialog:
        show_startup_error('startup_failed')
    tk_dialog.assert_called_once_with(translations()['app_name'], translations()['startup_failed'])
