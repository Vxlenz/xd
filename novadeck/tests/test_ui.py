"""GUI smoke tests: use a desktop or xvfb-run on Linux; no real apps are launched."""
import os
import sys
import time
from threading import Event
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != 'win32' and not os.environ.get('DISPLAY'), reason='A graphical display is required')


@pytest.fixture(autouse=True)
def isolated_native_ui():
    """GUI checks must not create real tray icons or read the startup registry."""
    from queue import Queue
    from unittest.mock import Mock
    def tray():
        instance = Mock()
        instance.ready = False
        instance.events = Queue()
        return instance
    with patch('novadeck.ui.main_window.Tray', side_effect=tray), patch(
            'novadeck.ui.main_window.WindowsStartup') as startup:
        startup.return_value.supported = False
        yield


@pytest.fixture
def window(tmp_path):
    from novadeck.core.execution import Execution
    from novadeck.core.profile_store import ProfileStore
    from novadeck.core.runner import Runner
    from novadeck.core.settings_store import SettingsStore
    from novadeck.integrations.spotify_client import SpotifyClient
    from novadeck.ui.main_window import MainWindow
    app = MainWindow(ProfileStore(tmp_path / 'profiles.json'), Execution(Runner({'steam': lambda action: None})),
                     SpotifyClient(SettingsStore(tmp_path / 'settings.json')))
    callback_errors = []
    app.report_callback_exception = lambda *args: callback_errors.append(args)
    app.update()
    yield app
    app.execution.request_close()
    if app.execution._thread:
        app.execution._thread.join(2)
    assert not app.execution.busy
    if not app._closing:
        app.after_cancel(app.poll_id)
        app.destroy()
    assert not callback_errors


def pump_until(window, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.update()
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail('UI operation timed out')


def test_editor_create_reorder_save_and_reopen(window):
    from novadeck.core.models import Profile, SteamAction
    from novadeck.ui.profile_editor import ActionDialog
    profile = Profile(name='Gaming')
    window.open_editor(profile)
    editor = window.editor
    window.update()
    dialog = ActionDialog(editor, window.s, lambda action: editor.draft.actions.append(action))
    window.update()
    dialog.inputs['app_id'].insert(0, '570')
    dialog.inputs['display_name'].insert(0, 'Dota')
    dialog.save()
    editor.draft.actions.append(SteamAction(app_id='730', display_name='Counter Strike'))
    editor.render_actions()
    editor.move(0, 1)
    editor.fields['name'].delete(0, 'end')
    editor.fields['name'].insert(0, 'Jugar')
    editor.save()
    saved = window.store.load().profiles[0]
    assert saved.name == 'Jugar'
    assert [a.app_id for a in saved.actions] == ['730', '570']
    assert profile.actions == []
    window.open_editor(saved)
    window.update()
    assert window.editor.fields['name'].get() == 'Jugar'
    assert len(window.editor.rows) == 2


def test_invalid_action_and_profile_stay_open(window):
    from novadeck.core.models import Profile
    from novadeck.ui.profile_editor import ActionDialog
    window.open_editor(Profile(name='New'))
    editor = window.editor
    dialog = ActionDialog(editor, window.s, lambda action: pytest.fail('invalid action saved'))
    window.update()
    dialog.save()
    assert dialog.winfo_exists()
    assert dialog.error.cget('text') == window.s['invalid_action']
    dialog.destroy()
    editor.fields['name'].delete(0, 'end')
    editor.save()
    assert editor.winfo_exists()
    assert not window.store.load().profiles


def test_run_shows_partial_failures_without_blocking_ui(window):
    from novadeck.core.models import Profile, SteamAction
    from novadeck.integrations.errors import IntegrationError
    release = Event()
    def handler(action):
        if action.app_id == '570':
            assert release.wait(2)
            raise IntegrationError('steam_launch_failed')
    window.execution.runner.handlers['steam'] = handler
    profile = Profile(name='Gaming', actions=[SteamAction(app_id='570', display_name='Dota'),
                                             SteamAction(app_id='730', display_name='CS')])
    assert window.start_run(profile)
    window.update()
    assert window.active_profile is not None
    # The GUI is responsive while the launch worker is blocked.
    assert window.run_title.cget('text') == window.s['running_profile'].format(name='Gaming')
    release.set()
    pump_until(window, lambda: window.active_profile is None)
    assert window.s['status_failed'] in window.result_labels[profile.actions[0].id].cget('text')
    assert window.s['status_succeeded'] in window.result_labels[profile.actions[1].id].cget('text')
    assert window.run_title.cget('text') == window.s['run_summary'].format(succeeded=1, failed=1, cancelled=0)


def test_action_test_reports_to_editor(window):
    from novadeck.core.models import Profile, SteamAction
    action = SteamAction(app_id='570', display_name='Dota', delay_seconds=60)
    window.open_editor(Profile(name='Gaming', actions=[action]))
    with patch('novadeck.ui.profile_editor.messagebox.askyesno', return_value=True):
        window.editor.test_action(0)
    pump_until(window, lambda: window.active_profile is None)
    assert window.editor.test_status.cget('text') == window.s['status_succeeded']
    assert window.editor.draft.actions[0].delay_seconds == 60


def test_language_switch_and_card_import_export_delete(window, tmp_path):
    from novadeck.core.models import Profile
    profile = Profile(name='A')
    source = tmp_path / 'import.json'
    source.write_text(profile.model_dump_json())
    with patch('novadeck.ui.main_window.filedialog.askopenfilename', return_value=str(source)), patch(
            'novadeck.ui.main_window.messagebox.askyesno', return_value=True):
        window.import_profile()
    assert window.store.load().profiles == [profile]
    target = tmp_path / 'export.json'
    with patch('novadeck.ui.main_window.filedialog.asksaveasfilename', return_value=str(target)):
        window.export_profile(profile)
    assert Profile.model_validate_json(target.read_bytes()) == profile
    window.change_language('English')
    window.update()
    assert window.s['run'] == 'Run'
    with patch('novadeck.ui.main_window.messagebox.askyesno', return_value=True):
        window.delete_profile(profile)
    assert not window.store.load().profiles


def test_language_persists_across_windows_without_dropping_settings(window):
    from novadeck.core.execution import Execution
    from novadeck.core.runner import Runner
    from novadeck.ui.main_window import MainWindow
    window.spotify.settings.update(spotify_client_id='a'*32)
    window.change_language('English')
    assert window.spotify.settings.load().language == 'en'
    assert window.spotify.settings.load().spotify_client_id == 'a'*32
    other = MainWindow(window.store, Execution(Runner({})), window.spotify)
    try:
        other.update()
        assert other.s['run'] == 'Run'
        assert other.language_menu.get() == 'English'
    finally:
        other.destroy()


def test_language_write_failure_keeps_current_language_and_settings(window):
    from novadeck.integrations.errors import IntegrationError
    window.spotify.settings.update(spotify_client_id='a'*32)
    original = window.spotify.settings.path.read_bytes()
    with patch.object(window.spotify.settings, 'save', side_effect=IntegrationError('settings_write_failed')), patch.object(
            window, 'show_error') as show_error:
        window.change_language('English')
    assert window.s['run'] == 'Ejecutar'
    assert window.language_menu.get() == 'Español'
    assert window.spotify.settings.path.read_bytes() == original
    show_error.assert_called_once_with('settings_write_failed')


def test_unexpected_ui_exception_never_displays_or_logs_private_details(window, caplog):
    from novadeck.ui.main_window import MainWindow
    with patch.object(window, 'show_error') as show_error:
        MainWindow.report_callback_exception(window, RuntimeError, RuntimeError('private-token-or-transcript'), None)
    show_error.assert_called_once_with('unexpected_error')
    assert 'RuntimeError' in caplog.text
    assert 'private-token-or-transcript' not in caplog.text


def test_drag_binding_and_keyboard_button_activation(window):
    from novadeck.core.models import Profile, SteamAction
    window.open_editor(Profile(name='A', actions=[SteamAction(app_id=str(i), display_name=str(i)) for i in (10, 20)]))
    editor = window.editor
    window.update()
    handle = editor.rows[0].winfo_children()[0]
    bottom = editor.rows[1].winfo_rooty() + editor.rows[1].winfo_height() // 2
    handle._label.event_generate('<ButtonPress-1>', x=5, y=5)
    handle._label.event_generate('<ButtonRelease-1>', x=5, y=5, rooty=bottom)
    window.update()
    assert [a.app_id for a in editor.draft.actions] == ['20', '10']
    # Focusable CTkButton canvas responds to Return, rather than requiring a mouse.
    down = editor.rows[0].winfo_children()[3]
    down._canvas.focus_force()
    window.update()
    down._canvas.event_generate('<Return>')
    window.update()
    assert [a.app_id for a in editor.draft.actions] == ['10', '20']


def test_spotify_mini_player_refresh_controls_and_debounced_volume(window):
    from unittest.mock import Mock
    from novadeck.integrations.spotify_client import Playback
    window.spotify.playback = Mock(return_value=Playback('Song', 'Artist', True, 35))
    window.spotify.control = Mock()
    window.player.refresh()
    pump_until(window, lambda: window.player.current.name == 'Song')
    assert window.player.track.cget('text') == 'Song · Artist'
    assert round(window.player.volume.get()) == 35
    window.player.control('next')
    pump_until(window, lambda: not window.tasks.pending)
    window.spotify.control.assert_called_once_with('next')
    window.player.volume_changed(40)
    window.player.volume_changed(80)
    pump_until(window, lambda: window.spotify.control.call_count == 2 and not window.tasks.pending)
    assert window.spotify.control.call_args.args == ('volume', 80)


def test_spotify_picker_search_and_profile_uri_selection(window):
    from unittest.mock import Mock
    from novadeck.integrations.spotify_client import Playlist
    from novadeck.ui.profile_editor import ActionDialog
    from novadeck.core.models import Profile, SpotifyAction
    uri = 'spotify:playlist:' + 'a'*22
    window.spotify.playlists = Mock(return_value=[Playlist('Música', uri), Playlist('Study', uri)])
    selected = []
    picker = window.open_playlist_picker(window, selected.append)
    pump_until(window, lambda: len(picker.items) == 2)
    picker.query.set('musica')
    window.update()
    assert len(picker.rows.winfo_children()) == 1
    picker.select(picker.items[0])
    assert selected == [Playlist('Música', uri)]
    assert window.active_profile is None  # Choosing for an editor never starts playback.
    window.open_editor(Profile(name='A'))
    def choose(parent, on_pick):
        on_pick(Playlist('Música', uri))
    dialog = ActionDialog(window.editor, window.s, selected.append,
                          SpotifyAction(uri='spotify:track:'+'b'*22), choose)
    dialog.pick_playlist()
    assert dialog.inputs['uri'].get() == uri
    dialog.save()
    assert selected[-1].uri == uri


def test_spotify_settings_client_id_validation_and_async_connect(window):
    from unittest.mock import Mock
    window.spotify.connect = Mock()
    window.open_settings()
    settings = window.settings_window
    settings.connect()
    assert settings.status.cget('text') == window.s['spotify_invalid_client_id']
    settings.client_id.insert(0, 'a'*32)
    settings.connect()
    pump_until(window, lambda: not window.tasks.pending)
    assert settings.status.cget('text') == window.s['spotify_connected']
    assert window.spotify.connect.call_args.args[0] == 'a'*32
    settings.destroy()
    assert settings.cancel_auth.is_set()


def test_spotify_player_reports_friendly_errors(window):
    from unittest.mock import Mock
    from novadeck.integrations.errors import IntegrationError
    window.spotify.playback = Mock(side_effect=IntegrationError('spotify_premium_required'))
    window.player.refresh()
    pump_until(window, lambda: not window.tasks.pending)
    assert window.player.status.cget('text') == window.s['spotify_premium_required']


class NoticeClock:
    now = 0.0
    def __call__(self):
        return self.now


def advance_notice(notice, clock, seconds):
    for _ in range(seconds):
        if notice.timer:
            notice.after_cancel(notice.timer)
        clock.now += 1
        notice.tick()


def test_scheduled_toast_has_full_five_second_cancel_window(window):
    from unittest.mock import Mock
    from novadeck.ui.scheduled_notice import ScheduledNotice
    clock = NoticeClock()
    run, cancel = Mock(), Mock()
    notice = ScheduledNotice(window, window.s, 'Gaming', run, cancel, clock=clock)
    advance_notice(notice, clock, 4)
    run.assert_not_called()
    advance_notice(notice, clock, 1)
    run.assert_called_once()
    cancel.assert_not_called()
    notice = ScheduledNotice(window, window.s, 'Gaming', run, cancel, clock=clock)
    notice.cancel()
    assert run.call_count == 1
    cancel.assert_called_once()


def test_missed_toast_requires_consent_and_sleep_during_countdown_requires_new_consent(window):
    from unittest.mock import Mock
    from novadeck.ui.scheduled_notice import ScheduledNotice
    clock = NoticeClock()
    run = Mock()
    notice = ScheduledNotice(window, window.s, 'Gaming', run, Mock(), missed=True, clock=clock)
    assert notice.deadline is None and notice.timer is None
    notice.begin_countdown()
    if notice.timer:
        notice.after_cancel(notice.timer)
    clock.now += 60
    notice.tick()
    run.assert_not_called()
    assert notice.deadline is None
    notice.begin_countdown()
    advance_notice(notice, clock, 5)
    run.assert_called_once()


def test_trigger_editor_validates_days_and_preserves_multiple_schedules(window):
    from novadeck.core.models import Profile, Trigger
    window.open_editor(Profile(name='A', triggers=[Trigger(type='login'),
                                                  Trigger(type='schedule', time='12:30', weekdays=[0, 4]),
                                                  Trigger(type='schedule', time='16:00', weekdays=[1])]))
    editor = window.editor
    assert len(editor.trigger_editor.get_triggers()) == 3
    editor.trigger_editor.add_schedule()
    editor.save()
    assert editor.error.cget('text') == window.s['invalid_schedule']
    editor.trigger_editor.rows[-1]['days'][6].set(True)
    editor.save()
    saved = window.store.load().profiles[0]
    assert len(saved.triggers) == 4
    assert saved.triggers[-1].weekdays == [6]
    assert window.s['schedule_next'].split('{')[0] in window.schedule_labels[saved.id].cget('text')


def test_scheduled_intents_queue_deduplicate_and_execute_after_notice(window):
    from datetime import datetime, timezone
    from unittest.mock import Mock
    from novadeck.core.models import Profile, SteamAction, Trigger
    from novadeck.core.scheduler import ScheduledRun
    handler = Mock()
    window.execution.runner.handlers['steam'] = handler
    profile = Profile(name='Gaming', actions=[SteamAction(app_id='570', display_name='Dota')],
                      triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    window.save_profile(profile)
    now = datetime.now(timezone.utc)
    window.scheduler.clock = lambda: now
    request = ScheduledRun(profile.id, now, window.scheduler._revisions[profile.id])
    window.active_profile = Profile(name='Busy')
    window.scheduler.events.put(request)
    window.scheduler.events.put(request)
    window.poll_automation()
    assert len(window.scheduled_pending) == 1
    assert window.notice is None
    window.active_profile = None
    window.poll_automation()
    assert window.notice is not None
    handler.assert_not_called()
    notice, clock = window.notice, NoticeClock()
    notice.clock = clock
    notice.begin_countdown()
    advance_notice(notice, clock, 5)
    pump_until(window, lambda: window.active_profile is None)
    handler.assert_called_once()
    assert window.notice is None


def test_pause_and_profile_edits_cancel_pending_automation(window):
    from datetime import datetime, timezone, timedelta
    from novadeck.core.models import Profile, Trigger
    from novadeck.core.scheduler import ScheduledRun
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    window.save_profile(profile)
    now = datetime.now(timezone.utc)
    window.scheduler.clock = lambda: now
    request = ScheduledRun(profile.id, now-timedelta(minutes=2), window.scheduler._revisions[profile.id])
    window.scheduler.events.put(request)
    window.poll_automation()
    assert window.notice.deadline is None  # Missed schedule requires approval.
    window.toggle_scheduler()
    assert window.notice is None and window.scheduler.paused
    window.toggle_scheduler()
    assert not window.scheduler.is_current(request)
    request = ScheduledRun(profile.id, now, window.scheduler._revisions[profile.id])
    window.scheduler.events.put(request)
    window.poll_automation()
    assert window.notice is not None
    profile.name = 'Edited'
    window.save_profile(profile)
    window.poll_automation()
    assert window.notice is None


def test_tray_close_open_pause_and_quit_are_dispatched_on_ui_thread(window):
    from queue import Queue
    from unittest.mock import Mock
    from novadeck.ui.tray import TrayCommand
    tray = Mock()
    tray.ready = True
    tray.events = Queue()
    window.tray = tray
    window.close()
    assert window.state() == 'withdrawn'
    tray.events.put(TrayCommand('open'))
    window.poll_automation()
    assert window.state() == 'normal'
    tray.events.put(TrayCommand('pause'))
    window.poll_automation()
    assert window.scheduler.paused
    # The explicit Quit menu action calls quit_app, while the X button only hides.
    with patch.object(window, 'quit_app') as quit_app:
        tray.events.put(TrayCommand('quit'))
        window.poll_automation()
        quit_app.assert_called_once()


def test_startup_switch_reverts_when_registry_write_fails(window):
    from unittest.mock import Mock
    from novadeck.integrations.errors import IntegrationError
    startup = Mock()
    startup.supported = True
    startup.enabled.return_value = False
    window.startup = startup
    window.open_settings()
    settings = window.settings_window
    settings.startup_value.set(True)
    settings.toggle_startup()
    startup.set_enabled.assert_called_once_with(True)
    startup.set_enabled.side_effect = IntegrationError('startup_write_failed')
    settings.startup_value.set(False)
    settings.toggle_startup()
    assert settings.startup_value.get() is True
    assert settings.startup_status.cget('text') == window.s['startup_write_failed']


def test_clock_moving_back_during_notice_never_executes_early(window):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import Mock
    from novadeck.core.models import Profile, SteamAction, Trigger
    from novadeck.core.scheduler import ScheduledRun
    handler = Mock()
    window.execution.runner.handlers['steam'] = handler
    profile = Profile(name='A', actions=[SteamAction(app_id='570', display_name='Dota')],
                      triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    window.save_profile(profile)
    now = datetime.now(timezone.utc)
    window.scheduler.clock = lambda: now
    request = ScheduledRun(profile.id, now, window.scheduler._revisions[profile.id])
    window.scheduler.events.put(request)
    window.poll_automation()
    notice, clock = window.notice, NoticeClock()
    notice.clock = clock
    notice.begin_countdown()
    window.scheduler.clock = lambda: now-timedelta(minutes=5)
    advance_notice(notice, clock, 5)
    handler.assert_not_called()
    assert window.notice is None
    assert list(window.scheduled_pending) == [request]


def install_system_sessions(window, tmp_path):
    from unittest.mock import Mock
    from novadeck.core.execution import Execution
    from novadeck.core.runner import Runner
    from novadeck.core.system_session import SystemSession
    from novadeck.integrations.volume import VolumeState
    from novadeck.integrations.dnd import NotificationState
    volume, dnd = Mock(), Mock()
    volume.capture.return_value = VolumeState(device_id='speakers', level=.35)
    dnd.capture.return_value = NotificationState(present=True, value=1)
    sessions = SystemSession(tmp_path/'system_recovery.json', volume=volume, dnd=dnd)
    window.execution = Execution(Runner({'steam': Mock()}), sessions=sessions)
    window.execution.recover()
    pump_until(window, lambda: not window.execution.busy)
    return sessions, volume, dnd


def test_system_profile_stays_active_until_end_button_then_restores(window, tmp_path):
    from novadeck.core.models import Profile, SystemAction
    sessions, volume, dnd = install_system_sessions(window, tmp_path)
    target = Profile(name='Gaming', actions=[SystemAction(volume=20, do_not_disturb=True)])
    assert window.start_run(target)
    pump_until(window, lambda: window.active_profile is None and not window.execution.busy)
    assert window.execution.current_profile.name == 'Gaming'
    assert window.session_label.cget('text') == window.s['system_profile_active'].format(name='Gaming')
    assert window.end_button.cget('state') == 'normal'
    volume.restore.assert_not_called()
    dnd.restore.assert_not_called()
    window.end_button.invoke()
    pump_until(window, lambda: not window._ending and not window.execution.busy)
    assert window.execution.current_profile is None
    assert window.session_label.cget('text') == window.s['system_no_profile']
    volume.restore.assert_called_once()
    dnd.restore.assert_called_once()
    assert not sessions.journal.path.exists()


def test_system_restore_failure_keeps_app_open_and_retry_clears_recovery(window, tmp_path):
    from novadeck.core.models import Profile, SystemAction
    from novadeck.integrations.errors import IntegrationError
    sessions, volume, dnd = install_system_sessions(window, tmp_path)
    window.start_run(Profile(name='Gaming', actions=[SystemAction(volume=20, do_not_disturb=True)]))
    pump_until(window, lambda: window.active_profile is None and not window.execution.busy)
    volume.restore.side_effect = IntegrationError('volume_restore_failed')
    window.end_profile()
    pump_until(window, lambda: not window._ending and not window.execution.busy)
    assert sessions.journal.path.exists()
    assert window.recovery_button.cget('state') == 'normal'
    dnd.restore.assert_called_once()
    volume.restore.side_effect = None
    window.retry_recovery()
    pump_until(window, lambda: not window.execution.busy and not window.execution.recovery_required)
    assert not sessions.journal.path.exists()
    assert window.execution.current_profile is None


def test_system_action_test_restores_and_preserves_configured_false_option(window, tmp_path):
    from novadeck.core.models import Profile, SystemAction
    sessions, volume, dnd = install_system_sessions(window, tmp_path)
    action = SystemAction(volume=20, restore_volume=False, do_not_disturb=True)
    assert window.test_action(action)
    pump_until(window, lambda: window.active_profile is None and not window.execution.busy)
    volume.restore.assert_called_once()
    dnd.restore.assert_called_once()
    assert action.restore_volume is False
    assert window.execution.current_profile is None
    assert not sessions.journal.path.exists()


def test_quit_restores_before_destroy_and_failed_quit_can_be_cancelled(window, tmp_path):
    from novadeck.core.models import Profile, SystemAction
    from novadeck.integrations.errors import IntegrationError
    sessions, volume, _ = install_system_sessions(window, tmp_path)
    window.start_run(Profile(name='Gaming', actions=[SystemAction(volume=20)]))
    pump_until(window, lambda: window.active_profile is None and not window.execution.busy)
    volume.restore.side_effect = IntegrationError('volume_restore_failed')
    with patch('novadeck.ui.main_window.messagebox.askyesno', return_value=False):
        window.quit_app()
        pump_until(window, lambda: not window._quit_requested and not window.execution.busy)
    assert not window._closing
    assert sessions.journal.path.exists()
    volume.restore.side_effect = None
    window.quit_app()
    pump_until(window, lambda: window._closing)
    assert window.execution.closed
    assert not sessions.journal.path.exists()


def test_corrupt_system_recovery_blocks_automation_and_preserves_file(window, tmp_path):
    from datetime import datetime, timezone
    from novadeck.core.models import Profile, Trigger
    from novadeck.core.scheduler import ScheduledRun
    path = tmp_path/'system_recovery.json'
    path.write_text('{broken')
    sessions, volume, dnd = install_system_sessions(window, tmp_path)
    assert window.execution.recovery_required
    assert path.read_text() == '{broken'
    profile = Profile(name='Scheduled', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    window.save_profile(profile)
    window.scheduler.events.put(ScheduledRun(profile.id, datetime.now(timezone.utc), window.scheduler._revisions[profile.id]))
    window.poll_automation()
    assert window.notice is None
    volume.restore.assert_not_called()
    dnd.restore.assert_not_called()
    # Repair is an explicit external change, followed by the existing retry action.
    path.write_text('{"schema_version": 1, "volumes": [], "notifications": null}')
    window.retry_recovery()
    pump_until(window, lambda: not window.execution.busy and not window.execution.recovery_required)
    assert not path.exists()
    window.toggle_scheduler()  # Cancel the now-unblocked queued notice before teardown.


def test_default_application_recovers_before_enabling_profiles(tmp_path):
    from unittest.mock import Mock
    from novadeck.core.models import Profile, SystemAction
    from novadeck.core.profile_store import ProfileStore
    from novadeck.core.settings_store import SettingsStore
    from novadeck.core.system_session import RecoveryJournal, RecoveryState, SystemSession
    from novadeck.integrations.dnd import NotificationState
    from novadeck.integrations.spotify_client import SpotifyClient
    from novadeck.ui.main_window import MainWindow
    path = tmp_path/'system_recovery.json'
    RecoveryJournal(path).save(RecoveryState(profile_id='crashed', notifications=NotificationState(present=False)))
    dnd = Mock()
    session = SystemSession(path, volume=Mock(), dnd=dnd)
    with patch('novadeck.ui.main_window.SystemSession', return_value=session):
        app = MainWindow(ProfileStore(tmp_path/'profiles.json'),
                         spotify=SpotifyClient(SettingsStore(tmp_path/'settings.json')))
    callback_errors = []
    app.report_callback_exception = lambda *args: callback_errors.append(args)
    try:
        pump_until(app, lambda: not app.execution.busy and not app.execution.recovery_required)
        dnd.restore.assert_called_once_with(NotificationState(present=False))
        assert not path.exists()
        assert app.execution.sessions is session
        dnd.capture.return_value = NotificationState(present=True, value=1)
        assert app.start_run(Profile(name='DND', actions=[SystemAction(do_not_disturb=True)]))
        pump_until(app, lambda: app.active_profile is None and not app.execution.busy)
        assert path.exists()
        app.quit_app()
        pump_until(app, lambda: app._closing)
        assert app.execution.closed
        assert not path.exists()
        assert not callback_errors
    finally:
        app.execution.request_close()
        app.execution._thread.join(2)
        if not app._closing:
            app.destroy()


def test_voice_commands_select_only_existing_profiles_and_require_wake_word_in_continuous_mode(window):
    from novadeck.core.models import Profile, SteamAction
    from novadeck.core.settings_store import VoiceOptions
    profile=Profile(name='Gaming',actions=[SteamAction(app_id='570',display_name='Dota')])
    window.save_profile(profile)
    window.speech.options=VoiceOptions(enabled=True,always_listening=True)
    window.dispatch_voice('start gaming profile')
    assert window.active_profile is None
    window.dispatch_voice('nova start gaming profile')
    pump_until(window,lambda:window.active_profile is None and not window.execution.busy)
    assert window.execution.current_profile.id==profile.id
    assert window.voice_overlay.winfo_exists()
    window.dispatch_voice('nova abre calc.exe')
    assert window.voice_overlay.result.cget('text')==window.s['voice_unknown']


def test_voice_master_volume_and_dnd_reuse_system_session(window,tmp_path):
    sessions,volume,dnd=install_system_sessions(window,tmp_path)
    window.dispatch_voice('sube el volumen')
    pump_until(window,lambda:not window.execution.busy)
    volume.set.assert_called_once_with(45,device_id='speakers')
    identifier=window.execution.current_profile.id
    window.dispatch_voice('activa no molestar')
    pump_until(window,lambda:not window.execution.busy)
    dnd.set.assert_called_once_with(True)
    assert window.execution.current_profile.id==identifier
    window.end_profile()
    pump_until(window,lambda:not window._ending and not window.execution.busy)
    volume.restore.assert_called_once()
    dnd.restore.assert_called_once()


def test_voice_stop_ends_profile_pauses_scheduler_and_reports_spotify_failure(window,tmp_path):
    from unittest.mock import Mock
    from novadeck.core.models import Profile,SystemAction
    from novadeck.integrations.errors import IntegrationError
    sessions,volume,dnd=install_system_sessions(window,tmp_path)
    window.start_run(Profile(name='Gaming',actions=[SystemAction(volume=20,do_not_disturb=True)]))
    pump_until(window,lambda:window.active_profile is None and not window.execution.busy)
    window.spotify.control=Mock(side_effect=IntegrationError('spotify_auth_required'))
    window.dispatch_voice('deten todo')
    pump_until(window,lambda:not window.execution.busy and not window.voice_tasks.pending)
    assert window.execution.current_profile is None and window.scheduler.paused
    window.spotify.control.assert_called_once_with('pause')
    assert window.s['spotify_auth_required'] in window.voice_overlay.result.cget('text')
    volume.restore.assert_called_once()
    dnd.restore.assert_called_once()


def test_voice_settings_save_selects_microphone_without_enabling_capture_implicitly(window):
    from novadeck.voice.recognizer import Microphone
    from novadeck.core.background import TaskResult
    window.open_settings()
    panel=window.settings_window.voice_panel
    panel.handle_task_result(TaskResult(panel,'microphones',[Microphone('api:Mic','Mic',1,16000)]))
    panel.microphone.set('api:Mic')
    panel.language.set(window.s['voice_english'])
    panel.shortcut.delete(0,'end');panel.shortcut.insert(0,'ctrl+shift+space')
    panel.save()
    pump_until(window,lambda:not window.voice_tasks.pending)
    saved=window.spotify.settings.load().voice
    assert not saved.enabled and saved.microphone=='api:Mic' and saved.language=='en'
    assert saved.hotkey=='ctrl+shift+space'
    assert window.speech._thread is None
    panel.shortcut.delete(0,'end');panel.shortcut.insert(0,'wrong')
    panel.save()
    assert panel.status.cget('text')==window.s['voice_invalid_settings']


def test_voice_disable_discards_stale_recognition_events(window):
    from novadeck.voice.recognizer import VoiceEvent
    from novadeck.core.settings_store import VoiceOptions
    old=window.speech.generation
    window.apply_voice_options(VoiceOptions(enabled=False))
    window.speech.events.put(VoiceEvent(old,'final','deten todo'))
    window.poll_voice()
    assert not window.scheduler.paused
    assert window.voice_overlay is None
    assert window.voice_button.cget('state')=='disabled'


def test_voice_controls_stay_inside_window_at_minimum_height(window):
    window.geometry('900x650')
    window.update()
    root_bottom=window.winfo_rooty()+window.winfo_height()
    button_bottom=window.voice_button.winfo_rooty()+window.voice_button.winfo_height()
    assert button_bottom<=root_bottom
    assert window.player.winfo_height()>90


def test_repeated_model_download_click_keeps_original_cancellation_token(window):
    from threading import Event
    from unittest.mock import Mock
    from novadeck.integrations.errors import IntegrationError
    entered=Event()
    tokens=[]
    def download(language,cancel):
        tokens.append(cancel)
        entered.set()
        assert cancel.wait(2)
        raise IntegrationError('voice_cancelled')
    window.speech.models.ensure=Mock(side_effect=download)
    window.open_settings()
    panel=window.settings_window.voice_panel
    panel.download_models()
    assert entered.wait(2)
    panel.download_models()
    panel.destroy()
    window.voice_tasks._thread.join(2)
    assert tokens[0].is_set()
    pump_until(window,lambda:not window.voice_tasks.pending)
