from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from novadeck.integrations.dnd import DoNotDisturb, NotificationState, SETTINGS_KEY, VALUE_NAME
from novadeck.integrations.errors import IntegrationError
from novadeck.integrations.volume import VolumeState, WindowsVolume


def volume_backend():
    device = Mock()
    device.id = 'speakers'
    device.EndpointVolume.GetMasterVolumeLevelScalar.return_value = .375
    audio, com = Mock(), Mock()
    audio.GetSpeakers.return_value = device
    audio.CreateDevice.return_value = device
    return WindowsVolume(audio=audio, com=com), device, audio, com


def test_master_volume_uses_scalar_preserves_precision_and_targets_original_endpoint():
    volume, device, audio, com = volume_backend()
    original = volume.capture()
    assert original == VolumeState(device_id='speakers', level=.375)
    volume.set(0, device_id=original.device_id)
    volume.restore(original)
    assert [call.args[0] for call in audio.GetDeviceEnumerator.return_value.GetDevice.call_args_list] == ['speakers', 'speakers']
    assert device.EndpointVolume.SetMasterVolumeLevelScalar.call_args_list[0].args == (0.0, None)
    assert device.EndpointVolume.SetMasterVolumeLevelScalar.call_args_list[1].args == (.375, None)
    assert com.CoInitialize.call_count == com.CoUninitialize.call_count == 3
    device.EndpointVolume.SetMute.assert_not_called()


@pytest.mark.parametrize('value', [-1, 101, True, 3.5, '20'])
def test_master_volume_rejects_invalid_input_before_com(value):
    volume, _, _, com = volume_backend()
    with pytest.raises(ValueError):
        volume.set(value, device_id='speakers')
    com.CoInitialize.assert_not_called()


def test_com_failure_is_friendly_and_always_balanced():
    volume, device, _, com = volume_backend()
    device.EndpointVolume.SetMasterVolumeLevelScalar.side_effect = RuntimeError('native detail')
    with pytest.raises(IntegrationError, match='volume_write_failed'):
        volume.set(50, device_id='speakers')
    com.CoUninitialize.assert_called_once()
    volume, _, _, com = volume_backend()
    com.CoInitialize.side_effect = RuntimeError('initialization failure')
    with pytest.raises(IntegrationError, match='volume_read_failed'):
        volume.capture()
    com.CoUninitialize.assert_not_called()


def test_unplugged_endpoint_does_not_restore_to_new_default():
    volume, _, audio, com = volume_backend()
    audio.GetDeviceEnumerator.return_value.GetDevice.side_effect = RuntimeError('not found')
    with pytest.raises(IntegrationError, match='volume_restore_failed'):
        volume.restore(VolumeState(device_id='unplugged', level=.25))
    audio.GetSpeakers.assert_not_called()
    com.CoUninitialize.assert_called_once()


def test_dnd_reads_writes_and_restores_exact_hkcu_dword():
    registry, notify = MagicMock(), Mock()
    registry.REG_DWORD = 4
    registry.QueryValueEx.return_value = (1, 4)
    dnd = DoNotDisturb(registry=registry, notify=notify)
    original = dnd.capture()
    assert original == NotificationState(present=True, value=1)
    dnd.set(True)
    dnd.set(False)
    dnd.restore(original)
    assert [call.args[-1] for call in registry.SetValueEx.call_args_list] == [0, 1, 1]
    for call in registry.SetValueEx.call_args_list:
        assert call.args[1:4] == (VALUE_NAME, 0, 4)
    registry.CreateKeyEx.assert_called_with(registry.HKEY_CURRENT_USER, SETTINGS_KEY, 0, registry.KEY_SET_VALUE)
    assert notify.call_count == 3


def test_dnd_restores_absence_and_preserves_unrelated_registry_values():
    registry, notify = MagicMock(), Mock()
    registry.QueryValueEx.side_effect = FileNotFoundError
    dnd = DoNotDisturb(registry=registry, notify=notify)
    original = dnd.capture()
    assert not original.present
    dnd.set(True)
    dnd.restore(original)
    registry.DeleteValue.assert_called_once_with(registry.OpenKey.return_value.__enter__.return_value, VALUE_NAME)
    registry.DeleteKey.assert_not_called()
    registry.DeleteKeyEx.assert_not_called()


def test_dnd_unknown_registry_type_is_never_overwritten():
    registry = MagicMock()
    registry.REG_DWORD = 4
    registry.QueryValueEx.return_value = ('unexpected', 1)
    dnd = DoNotDisturb(registry=registry, notify=Mock())
    with pytest.raises(IntegrationError, match='dnd_unsupported_value'):
        dnd.capture()
    registry.SetValueEx.assert_not_called()


def test_dnd_permission_failure_is_friendly():
    registry = MagicMock()
    dnd = DoNotDisturb(registry=registry, notify=Mock())
    registry.OpenKey.side_effect = PermissionError
    with pytest.raises(IntegrationError, match='dnd_read_failed'):
        dnd.capture()
    registry.CreateKeyEx.side_effect = PermissionError
    with pytest.raises(IntegrationError, match='dnd_write_failed'):
        dnd.set(True)


def test_windows_only_integrations_import_without_com_on_linux():
    with patch('novadeck.integrations.volume.sys.platform', 'linux'):
        with pytest.raises(IntegrationError, match='windows_required'):
            WindowsVolume().capture()
        with pytest.raises(IntegrationError, match='windows_required'):
            DoNotDisturb().capture()
