import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from novadeck.core.config import data_directory
from novadeck.core.models import (LaunchAction, Profile, ProfileDocument, SpotifyAction,
                                  SteamAction, SystemAction, Trigger)
from novadeck.core.profile_store import ProfileStore, ProfileStoreError
from novadeck.i18n import translations


def test_crud_and_exact_backup(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    assert store.load().profiles == []
    profile = Profile(name='Jugar')
    store.upsert(profile)
    first = store.path.read_bytes()
    assert not store.backup_path.exists()
    profile.name = 'Gaming'
    store.upsert(profile)
    assert store.backup_path.read_bytes() == first
    assert store.load().profiles[0].name == 'Gaming'
    store.delete(profile.id)
    assert store.load().profiles == []
    assert json.loads(store.backup_path.read_bytes())['profiles'][0]['name'] == 'Gaming'


def test_import_export(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    profile = Profile(name='Study', actions=[SteamAction(app_id='570', display_name='Dota')])
    store.upsert(profile)
    export = tmp_path / 'export.json'
    store.export_profile(profile.id, export)
    other = ProfileStore(tmp_path / 'other.json')
    assert other.import_profile(export) == profile
    other.import_profile(export)
    assert len(other.load().profiles) == 1
    assert other.load().profiles == [profile]


def test_corrupt_store_is_preserved(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    store.path.write_text('{broken')
    with pytest.raises(ProfileStoreError):
        store.upsert(Profile(name='New'))
    assert store.path.read_text() == '{broken'


def test_failed_replace_preserves_original_and_cleans_temp(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    store.upsert(Profile(name='Original'))
    original = store.path.read_bytes()
    import os
    replace = os.replace
    def fail_final(source, target):
        if Path(target) == store.path:
            raise OSError('disk failure')
        return replace(source, target)
    with patch('novadeck.core.profile_store.os.replace', side_effect=fail_final):
        with pytest.raises(ProfileStoreError):
            store.upsert(Profile(name='New'))
    assert store.path.read_bytes() == original
    assert store.backup_path.read_bytes() == original
    assert not list(tmp_path.glob('.novadeck-*'))


@pytest.mark.parametrize('factory', [
    lambda: Profile(name='   '),
    lambda: Profile(name='A', color='red'),
    lambda: SteamAction(app_id='1;calc', display_name='bad'),
    lambda: SpotifyAction(uri='https://evil.test/track/123'),
    lambda: SpotifyAction(uri='spotify:track:bad'),
    lambda: SystemAction(volume=101),
    lambda: SystemAction(),
    lambda: LaunchAction(target='cmd.exe'),
    lambda: LaunchAction(target='javascript:alert(1)'),
    lambda: LaunchAction(target='https://example.com', arguments=['bad']),
    lambda: LaunchAction(target='https://user:pass@example.com'),
    lambda: Trigger(type='schedule', time='25:00', weekdays=[0]),
    lambda: Trigger(type='schedule', time='12:00', weekdays=[7]),
    lambda: Trigger(type='schedule', time='12:00', weekdays=[0, 0]),
    lambda: Trigger(type='manual', time='12:00'),
    lambda: ProfileDocument(schema_version=2),
    lambda: Profile(name='A', unexpected=True),
    lambda: SystemAction(volume='50'),
])
def test_invalid_inputs(factory):
    with pytest.raises(ValidationError):
        factory()


def test_valid_actions_and_order():
    actions = [SpotifyAction(uri='https://open.spotify.com/track/' + 'a'*22 + '?si=x'),
               SteamAction(app_id='570', display_name='Dota'),
               LaunchAction(target=r'C:\Program Files\Discord\Discord.exe', arguments=['--test']),
               LaunchAction(target='https://example.com'),
               SystemAction(volume=0, do_not_disturb=False)]
    profile = Profile(name=' A ', actions=actions)
    assert profile.name == 'A'
    restored = Profile.model_validate_json(profile.model_dump_json())
    assert restored.actions == actions
    assert restored.actions[0].uri == 'spotify:track:' + 'a'*22


def test_duplicate_ids_rejected():
    profile = Profile(name='A')
    with pytest.raises(ValidationError):
        ProfileDocument(profiles=[profile, profile])
    action = SteamAction(app_id='1', display_name='A')
    with pytest.raises(ValidationError):
        Profile(name='A', actions=[action, action])


def test_nested_mutation_revalidated_before_write(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    document = ProfileDocument(profiles=[Profile(name='A')])
    document.profiles.append(document.profiles[0])
    with pytest.raises(ValidationError):
        store.save(document)
    assert not store.path.exists()


def test_bad_import_and_protected_export(tmp_path):
    store = ProfileStore(tmp_path / 'profiles.json')
    profile = Profile(name='A')
    store.upsert(profile)
    bad = tmp_path / 'bad.json'
    bad.write_text('{}')
    with pytest.raises(ProfileStoreError):
        store.import_profile(bad)
    with pytest.raises(ProfileStoreError):
        store.export_profile(profile.id, store.path)
    with pytest.raises(ProfileStoreError):
        store.export_profile('missing', bad)
    assert store.load().profiles == [profile]


def test_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    assert data_directory() == tmp_path / 'NovaDeck'


def test_translations():
    assert translations('es').keys() == translations('en').keys()
    from string import Formatter
    for key, text in translations('es').items():
        placeholders = lambda value: {name for _, name, _, _ in Formatter().parse(value) if name is not None}
        assert placeholders(text) == placeholders(translations('en')[key]), key
    with pytest.raises(ValueError):
        translations('../es')


def test_example_document():
    document = ProfileDocument.model_validate_json(Path('profiles.example.json').read_bytes())
    assert len(document.profiles) == 2


def test_import_app_has_no_gui_side_effects():
    import novadeck.app
    assert callable(novadeck.app.main)
