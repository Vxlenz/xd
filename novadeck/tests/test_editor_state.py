import pytest

from novadeck.core.models import Profile, SteamAction
from novadeck.ui.editor_state import action_from_fields, move_action


def test_reorder_preserves_identity_and_draft_isolation():
    original = Profile(name='A', actions=[SteamAction(app_id=str(i), display_name=str(i)) for i in (10, 20, 30)])
    draft = original.model_copy(deep=True)
    move_action(draft, 0, 2)
    assert [a.app_id for a in draft.actions] == ['20', '30', '10']
    assert [a.app_id for a in original.actions] == ['10', '20', '30']
    move_action(draft, 2, 0)
    assert draft == original
    with pytest.raises(IndexError):
        move_action(draft, 0, -1)


def test_action_form_builds_typed_models():
    steam = action_from_fields('steam', {'app_id': '570', 'display_name': 'Dota', 'delay_seconds': '1.5'}, 'existing')
    assert steam.id == 'existing'
    assert steam.delay_seconds == 1.5
    app = action_from_fields('launch', {'target': r'C:\My App.exe', 'arguments': 'a b\n--next'})
    assert app.arguments == ['a b', '--next']
    spotify = action_from_fields('spotify', {'uri': 'spotify:track:' + 'a'*22, 'shuffle': 'false', 'volume': '0'})
    assert spotify.shuffle is False and spotify.volume == 0
    system = action_from_fields('system', {'do_not_disturb': 'true'})
    assert system.do_not_disturb is True and system.restore_volume is True


@pytest.mark.parametrize('kind,fields', [
    ('steam', {'app_id': '570', 'display_name': 'Dota', 'delay_seconds': 'nan'}),
    ('launch', {'target': 'cmd.exe'}),
    ('spotify', {'uri': 'bad'}),
    ('system', {'do_not_disturb': 'yes'}),
    ('system', {}),
    ('unknown', {}),
])
def test_invalid_form_not_saved(kind, fields):
    with pytest.raises(ValueError):
        action_from_fields(kind, fields)
