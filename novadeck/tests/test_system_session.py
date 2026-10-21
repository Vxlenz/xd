from pathlib import Path
from unittest.mock import Mock

import pytest

from novadeck.core.models import SystemAction
from novadeck.core.session_lease import SessionLease
from novadeck.core.system_session import RecoveryJournal, RecoveryState, SystemSession
from novadeck.integrations.dnd import NotificationState
from novadeck.integrations.errors import IntegrationError
from novadeck.integrations.volume import VolumeState


def setup_session(tmp_path):
    volume, dnd = Mock(), Mock()
    volume.capture.return_value = VolumeState(device_id='speakers', level=.37)
    dnd.capture.return_value = NotificationState(present=True, value=1)
    session = SystemSession(tmp_path/'system_recovery.json', volume=volume, dnd=dnd)
    session.begin('profile')
    return session, volume, dnd


def test_journal_is_durable_before_each_system_change_and_restores_exact_originals(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    def set_volume(*args, **kwargs):
        state = session.journal.load()
        assert state.volumes == [VolumeState(device_id='speakers', level=.37)]
    def set_dnd(*args):
        assert session.journal.load().notifications == NotificationState(present=True, value=1)
    volume.set.side_effect = set_volume
    dnd.set.side_effect = set_dnd
    try:
        session.apply(SystemAction(volume=20, do_not_disturb=True))
        assert session.journal.path.exists()
        volume.restore.assert_not_called()  # A completed action does not end the profile.
        session.end()
        volume.restore.assert_called_once_with(VolumeState(device_id='speakers', level=.37))
        dnd.restore.assert_called_once_with(NotificationState(present=True, value=1))
        assert not session.journal.path.exists()
    finally:
        session.close()


def test_disabled_restore_keeps_volume_and_always_restores_dnd(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    try:
        session.apply(SystemAction(volume=80, restore_volume=False, do_not_disturb=True))
        assert session.journal.load().volumes == []
        session.end()
        volume.restore.assert_not_called()
        dnd.restore.assert_called_once()
    finally:
        session.close()


def test_repeated_actions_keep_first_snapshot_and_opt_in_never_forgets_it(tmp_path):
    session, volume, _ = setup_session(tmp_path)
    try:
        session.apply(SystemAction(volume=80, restore_volume=False))
        volume.capture.return_value = VolumeState(device_id='speakers', level=.8)
        session.apply(SystemAction(volume=40, restore_volume=True))
        session.apply(SystemAction(volume=10, restore_volume=False))
        session.end()
        volume.restore.assert_called_once_with(VolumeState(device_id='speakers', level=.37))
    finally:
        session.close()


def test_endpoint_changes_preserve_each_affected_device(tmp_path):
    session, volume, _ = setup_session(tmp_path)
    try:
        session.apply(SystemAction(volume=80))
        volume.capture.return_value = VolumeState(device_id='headphones', level=.2)
        session.apply(SystemAction(volume=40))
        assert {v.device_id for v in session.journal.load().volumes} == {'speakers', 'headphones'}
        session.end()
        assert [call.args[0].device_id for call in volume.restore.call_args_list] == ['speakers', 'headphones']
    finally:
        session.close()


def test_begin_new_profile_restores_old_before_changing_new_state(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    try:
        session.apply(SystemAction(volume=10, do_not_disturb=True))
        session.begin('next')
        volume.restore.assert_called_once()
        dnd.restore.assert_called_once()
        assert not session.journal.path.exists()
        session.apply(SystemAction(do_not_disturb=False))
        assert session.journal.load().profile_id == 'next'
    finally:
        session.close()


def test_failed_journal_write_prevents_system_mutation(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    try:
        session.journal.save = Mock(side_effect=IntegrationError('system_recovery_write_failed'))
        with pytest.raises(IntegrationError, match='system_recovery_write_failed'):
            session.apply(SystemAction(volume=20, do_not_disturb=True))
        volume.set.assert_not_called()
        dnd.set.assert_not_called()
    finally:
        session.lease.close()


def test_volume_failure_does_not_skip_dnd_and_failed_restore_remains_recoverable(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    try:
        volume.set.side_effect = IntegrationError('volume_write_failed')
        with pytest.raises(IntegrationError, match='volume_write_failed'):
            session.apply(SystemAction(volume=20, do_not_disturb=True))
        dnd.set.assert_called_once_with(True)
        volume.restore.side_effect = IntegrationError('volume_device_missing')
        with pytest.raises(IntegrationError, match='system_restore_failed'):
            session.end()
        assert session.journal.load().volumes
        assert session.journal.load().notifications is None
        dnd.restore.assert_called_once()
        volume.restore.side_effect = None
        session.recover()
        assert not session.journal.path.exists()
    finally:
        session.close()


def test_crash_recovery_uses_persisted_state_and_is_idempotent(tmp_path):
    session, volume, dnd = setup_session(tmp_path)
    session.apply(SystemAction(volume=20, do_not_disturb=True))
    session.lease.close()  # Emulate OS closing handles after a killed process; no end().
    recovered = SystemSession(session.journal.path, volume=volume, dnd=dnd)
    try:
        recovered.recover()
        assert not recovered.journal.path.exists()
        volume.restore.assert_called_once_with(VolumeState(device_id='speakers', level=.37))
        dnd.restore.assert_called_once_with(NotificationState(present=True, value=1))
        recovered.recover()
        assert volume.restore.call_count == dnd.restore.call_count == 1
    finally:
        recovered.close()


def test_corrupt_journal_is_preserved_even_on_close(tmp_path):
    path = tmp_path/'system_recovery.json'
    path.write_text('{broken')
    session = SystemSession(path, volume=Mock(), dnd=Mock())
    with pytest.raises(IntegrationError, match='system_recovery_invalid'):
        session.recover()
    with pytest.raises(IntegrationError, match='system_recovery_invalid'):
        session.close()
    assert path.read_text() == '{broken'
    session.volume.restore.assert_not_called()
    session.dnd.restore.assert_not_called()


def test_second_instance_cannot_restore_an_active_sessions_journal(tmp_path):
    first, volume, dnd = setup_session(tmp_path)
    first.apply(SystemAction(do_not_disturb=True))
    second = SystemSession(first.journal.path, volume=volume, dnd=dnd)
    try:
        with pytest.raises(IntegrationError, match='system_session_in_use'):
            second.recover()
        second.close()
        dnd.restore.assert_not_called()
        assert first.journal.path.exists()
    finally:
        first.close()


def test_missing_original_registry_value_survives_recovery(tmp_path):
    session, _, dnd = setup_session(tmp_path)
    try:
        dnd.capture.return_value = NotificationState(present=False)
        session.apply(SystemAction(do_not_disturb=True))
        session.end()
        dnd.restore.assert_called_once_with(NotificationState(present=False))
    finally:
        session.close()
