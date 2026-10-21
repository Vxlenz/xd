from pathlib import Path
from threading import Event
from unittest.mock import Mock
import subprocess
import sys

import pytest

from novadeck.core.execution import Execution, LifecycleFinished, RunFinished
from novadeck.core.models import Profile, SteamAction, SystemAction
from novadeck.core.runner import Runner
from novadeck.core.system_session import SystemSession
from novadeck.integrations.dnd import NotificationState
from novadeck.integrations.errors import IntegrationError
from novadeck.integrations.volume import VolumeState


def create_execution(tmp_path):
    volume, dnd = Mock(), Mock()
    volume.capture.return_value = VolumeState(device_id='original', level=.35)
    dnd.capture.return_value = NotificationState(present=True, value=1)
    session = SystemSession(tmp_path/'system_recovery.json', volume=volume, dnd=dnd)
    runner = Runner({'steam': Mock()})
    return Execution(runner, sessions=session), session, volume, dnd


def settle(execution):
    execution._thread.join(2)
    assert not execution.busy
    events = []
    while not execution.events.empty():
        events.append(execution.events.get_nowait())
    return events


def profile():
    return Profile(name='Gaming', actions=[SystemAction(volume=15, do_not_disturb=True),
                                            SteamAction(app_id='570', display_name='Dota')])


def test_session_remains_after_launches_and_explicit_end_restores(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    try:
        assert execution.start(profile())
        events = settle(execution)
        assert isinstance(events[-1], RunFinished)
        assert [r.status for r in events[-1].results] == ['succeeded', 'succeeded']
        assert execution.current_profile.name == 'Gaming'
        volume.restore.assert_not_called()
        dnd.restore.assert_not_called()
        execution.end_profile()
        events = settle(execution)
        assert events[-1] == LifecycleFinished('end')
        assert execution.current_profile is None
        volume.restore.assert_called_once()
        dnd.restore.assert_called_once()
    finally:
        execution.request_close()
        settle(execution)


def test_switch_restores_before_next_profile_launch(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    try:
        execution.start(profile())
        settle(execution)
        def verify_restored(action):
            volume.restore.assert_called_once()
            dnd.restore.assert_called_once()
        execution.runner.handlers['steam'] = verify_restored
        execution.start(Profile(name='Next', actions=[SteamAction(app_id='730', display_name='CS')]))
        events = settle(execution)
        assert events[-1].results[0].status == 'succeeded'
        assert execution.current_profile.name == 'Next'
    finally:
        execution.request_close()
        settle(execution)


def test_failed_system_action_still_runs_following_game(tmp_path):
    execution, _, volume, dnd = create_execution(tmp_path)
    try:
        volume.set.side_effect = IntegrationError('volume_write_failed')
        execution.start(profile())
        events = settle(execution)
        assert [r.status for r in events[-1].results] == ['failed', 'succeeded']
        execution.runner.handlers['steam'].assert_called_once()
        dnd.set.assert_called_once_with(True)
    finally:
        execution.request_close()
        settle(execution)


def test_end_during_delay_cancels_remaining_actions_then_restores(tmp_path):
    execution, _, volume, dnd = create_execution(tmp_path)
    applied = Event()
    dnd.set.side_effect = lambda value: applied.set()
    target = profile()
    target.actions[1].delay_seconds = 60.0
    try:
        execution.start(target)
        assert applied.wait(2)
        execution.end_profile()
        events = settle(execution)
        run = next(event for event in events if isinstance(event, RunFinished))
        assert [r.status for r in run.results] == ['succeeded', 'cancelled']
        assert events[-1] == LifecycleFinished('end')
        volume.restore.assert_called_once()
        dnd.restore.assert_called_once()
    finally:
        execution.request_close()
        settle(execution)


def test_close_during_action_waits_for_worker_and_releases_lease(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    entered, release = Event(), Event()
    def game(action):
        entered.set()
        assert release.wait(2)
    execution.runner.handlers['steam'] = game
    execution.start(profile())
    assert entered.wait(2)
    execution.request_close()
    assert execution.busy  # request_close never blocks the UI while an operation finishes.
    assert not execution.closed
    release.set()
    events = settle(execution)
    assert events[-1] == LifecycleFinished('close')
    assert execution.closed
    assert execution.current_profile is None
    volume.restore.assert_called_once()
    dnd.restore.assert_called_once()
    other = SystemSession(session.journal.path, volume=volume, dnd=dnd)
    other.recover()
    other.close()  # The old process no longer owns the lease.


def test_restore_failure_on_exit_preserves_journal_and_supports_retry(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    execution.start(profile())
    settle(execution)
    volume.restore.side_effect = IntegrationError('volume_restore_failed')
    execution.request_close()
    events = settle(execution)
    assert events[-1] == LifecycleFinished('close', 'system_restore_failed')
    assert not execution.closed and execution.recovery_required
    assert session.journal.path.exists()
    dnd.restore.assert_called_once()
    volume.restore.side_effect = None
    assert execution.recover()
    events = settle(execution)
    assert events[-1] == LifecycleFinished('recover')
    assert not execution.recovery_required
    assert not session.journal.path.exists()
    execution.request_close()
    settle(execution)
    assert execution.closed


def test_individual_system_test_restores_even_when_action_disables_restore(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    try:
        target = Profile(name='Test', actions=[SystemAction(volume=80, restore_volume=False, do_not_disturb=True)])
        assert execution.start(target, test=True)
        events = settle(execution)
        assert events[-1].error_key is None
        assert execution.current_profile is None
        assert target.actions[0].restore_volume is False
        volume.restore.assert_called_once()
        dnd.restore.assert_called_once()
        assert not session.journal.path.exists()
        execution.start(profile())
        settle(execution)
        assert not execution.start(target, test=True)
    finally:
        execution.request_close()
        settle(execution)


def test_real_killed_process_leaves_recovery_and_os_releases_lease(tmp_path):
    path = tmp_path/'system_recovery.json'
    code = '''
import os, sys
from pathlib import Path
from unittest.mock import Mock
from novadeck.core.system_session import SystemSession
from novadeck.core.models import SystemAction
from novadeck.integrations.volume import VolumeState
from novadeck.integrations.dnd import NotificationState
volume, dnd = Mock(), Mock()
volume.capture.return_value = VolumeState(device_id='original', level=.35)
dnd.capture.return_value = NotificationState(present=False)
session = SystemSession(Path(sys.argv[1]), volume=volume, dnd=dnd)
session.begin('crash')
session.apply(SystemAction(volume=10, do_not_disturb=True))
os._exit(7)
'''
    result = subprocess.run([sys.executable, '-c', code, str(path)],
                            cwd=Path(__file__).resolve().parents[2], timeout=5, capture_output=True)
    assert result.returncode == 7
    assert path.exists()
    volume, dnd = Mock(), Mock()
    session = SystemSession(path, volume=volume, dnd=dnd)
    try:
        session.recover()
        volume.restore.assert_called_once_with(VolumeState(device_id='original', level=.35))
        dnd.restore.assert_called_once_with(NotificationState(present=False))
        assert not path.exists()
    finally:
        session.close()


def test_invalid_replacement_never_ends_current_profile(tmp_path):
    execution, _, volume, dnd = create_execution(tmp_path)
    try:
        execution.start(profile())
        settle(execution)
        replacement = profile()
        replacement.actions.append({'type': 'steam', 'app_id': 'not-valid'})
        with pytest.raises(IntegrationError, match='invalid_profile'):
            execution.start(replacement)
        assert execution.current_profile.name == 'Gaming'
        volume.restore.assert_not_called()
        dnd.restore.assert_not_called()
    finally:
        execution.request_close()
        settle(execution)


def test_retrying_exit_directly_reloads_and_restores_pending_journal(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    execution.start(profile())
    settle(execution)
    volume.restore.side_effect = IntegrationError('volume_restore_failed')
    execution.request_close()
    first = settle(execution)
    assert first[-1].error_key == 'system_restore_failed'
    assert session.journal.path.exists()
    volume.restore.side_effect = None
    execution.request_close()
    second = settle(execution)
    assert second[-1] == LifecycleFinished('close')
    assert execution.closed
    assert not session.journal.path.exists()
    assert volume.restore.call_count == 2
    assert dnd.restore.call_count == 1


def test_end_after_cancelled_failed_exit_still_restores_pending_journal(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    execution.start(profile())
    settle(execution)
    volume.restore.side_effect = IntegrationError('volume_restore_failed')
    execution.request_close()
    settle(execution)
    assert execution.recovery_required
    volume.restore.side_effect = None
    execution.end_profile()
    events = settle(execution)
    assert events[-1] == LifecycleFinished('end')
    assert not execution.recovery_required
    assert not session.journal.path.exists()
    execution.request_close()
    settle(execution)


def test_voice_system_adjustment_reuses_active_profile_and_original_restore(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    try:
        execution.start(profile())
        settle(execution)
        identifier=execution.current_profile.id
        volume.capture.return_value=VolumeState(device_id='original',level=.95)
        assert execution.change_system('Voice',volume_delta=10)
        events=settle(execution)
        assert events[-1].operation=='voice_master_volume' and events[-1].error_key is None
        assert execution.current_profile.id==identifier
        volume.set.assert_called_with(100,device_id='original')
        execution.end_profile();settle(execution)
        volume.restore.assert_called_once_with(VolumeState(device_id='original',level=.35))
    finally:
        execution.request_close();settle(execution)


def test_voice_system_control_without_profile_creates_restorable_manual_session(tmp_path):
    execution, session, volume, dnd = create_execution(tmp_path)
    try:
        execution.recover();settle(execution)
        assert execution.change_system('Voice control',dnd=True)
        events=settle(execution)
        assert events[-1].error_key is None
        assert execution.current_profile.name=='Voice control'
        dnd.set.assert_called_once_with(True)
        execution.end_profile();settle(execution)
        dnd.restore.assert_called_once()
    finally:
        execution.request_close();settle(execution)
