from threading import Thread
from unittest.mock import patch

from novadeck.core.settings_store import AppSettings, SettingsStore, VoiceOptions
from novadeck.integrations.spotify_client import SpotifyClient


def test_old_settings_load_with_voice_disabled_and_updates_preserve_other_fields(tmp_path):
 store=SettingsStore(tmp_path/'settings.json')
 store.path.write_text('{"spotify_client_id":"'+'a'*32+'"}')
 assert not store.load().voice.enabled
 voice=VoiceOptions(enabled=True,language='en',microphone='api:Mic',always_listening=True)
 store.update(voice=voice)
 store.update(language='en')
 assert store.load().spotify_client_id=='a'*32
 client=SpotifyClient(store)
 with patch('novadeck.integrations.spotify_client.authorize'):
  from threading import Event
  client.connect('b'*32,Event(),{})
 assert store.load().voice==voice
 assert store.load().spotify_client_id=='b'*32
 assert store.load().language=='en'


def test_concurrent_settings_updates_do_not_drop_independent_fields(tmp_path):
 store=SettingsStore(tmp_path/'settings.json')
 voice=VoiceOptions(enabled=True)
 threads=[Thread(target=lambda:store.update(voice=voice)),
          Thread(target=lambda:store.update(spotify_client_id='c'*32))]
 for thread in threads:thread.start()
 for thread in threads:thread.join(2)
 assert store.load()==AppSettings(spotify_client_id='c'*32,voice=voice)
