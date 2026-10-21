from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import Mock, patch
import json
import time

import pytest
import requests
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from novadeck.core.background import Background
from novadeck.core.models import SpotifyAction
from novadeck.core.settings_store import AppSettings, SettingsStore
from novadeck.i18n import translations
from novadeck.integrations.errors import IntegrationError
from novadeck.integrations.spotify_auth import CachedPKCE, REDIRECT_URI, SCOPES, TokenCache, authorize
from novadeck.integrations.spotify_client import Playlist, SpotifyClient
from novadeck.ui.playlist_picker import filter_playlists

URI = 'spotify:playlist:' + 'a' * 22
TRACK = 'spotify:track:' + 'b' * 22
DEVICE = {'id': 'desktop', 'type': 'Computer', 'name': 'PC', 'is_active': True}


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []
    def __call__(self):
        return self.now
    def sleep(self, delay):
        self.waits.append(delay)
        self.now += delay


def client():
    api = Mock()
    api.devices.return_value = {'devices': [DEVICE]}
    clock = Clock()
    open_uri, desktop = Mock(), Mock()
    return SpotifyClient(api=api, open_uri=open_uri, launch_desktop=desktop,
                         clock=clock, sleep=clock.sleep), api, clock, open_uri, desktop


def test_playback_context_order_and_options():
    spotify, api, _, fallback, desktop = client()
    spotify.play(SpotifyAction(uri=URI, volume=0, shuffle=False))
    assert [call[0] for call in api.mock_calls] == ['devices', 'transfer_playback', 'volume', 'shuffle', 'start_playback']
    api.transfer_playback.assert_called_once_with('desktop', force_play=False)
    api.volume.assert_called_once_with(0, device_id='desktop')
    api.shuffle.assert_called_once_with(False, device_id='desktop')
    api.start_playback.assert_called_once_with(device_id='desktop', context_uri=URI)
    fallback.assert_not_called()
    desktop.assert_not_called()


def test_track_uses_uris_not_context_and_optional_values_are_untouched():
    spotify, api, *_ = client()
    spotify.play(SpotifyAction(uri=TRACK))
    api.start_playback.assert_called_once_with(device_id='desktop', uris=[TRACK])
    api.volume.assert_not_called()
    api.shuffle.assert_not_called()


def test_wait_for_desktop_device_with_backoff():
    spotify, api, clock, fallback, desktop = client()
    api.devices.side_effect = [{'devices': []}, {'devices': []}, {'devices': [DEVICE]}]
    spotify.play(SpotifyAction(uri=URI))
    desktop.assert_called_once()
    assert clock.waits == [.5, 1]
    fallback.assert_not_called()


def test_device_timeout_is_bounded_and_falls_back():
    spotify, api, clock, fallback, desktop = client()
    api.devices.return_value = {'devices': []}
    with pytest.raises(IntegrationError, match='spotify_no_device_fallback'):
        spotify.play(SpotifyAction(uri=URI))
    assert clock.now == 20
    assert max(clock.waits) <= 4
    desktop.assert_called_once()
    fallback.assert_called_once_with(URI)
    api.start_playback.assert_not_called()


def test_restricted_device_is_not_selected_and_local_computer_is_preferred():
    spotify, api, *_ = client()
    api.devices.return_value = {'devices': [dict(DEVICE, id='blocked', is_restricted=True),
                                           dict(DEVICE, id='remote'), dict(DEVICE, id='local', name='ThisPC')]}
    with patch('novadeck.integrations.spotify_client.platform.node', return_value='thispc'):
        spotify.play(SpotifyAction(uri=URI))
    api.transfer_playback.assert_called_once_with('local', force_play=False)


@pytest.mark.parametrize('status,key', [(403, 'spotify_premium_required'), (404, 'spotify_no_device'),
                                        (401, 'spotify_auth_required'), (500, 'spotify_api_failed')])
def test_http_failures_are_friendly_and_open_only_configured_uri(status, key):
    spotify, api, _, fallback, _ = client()
    api.start_playback.side_effect = SpotifyException(status, -1, 'sensitive-response')
    with pytest.raises(IntegrationError) as error:
        spotify.play(SpotifyAction(uri=URI))
    assert error.value.key == key + '_fallback'
    assert 'sensitive' not in str(error.value)
    fallback.assert_called_once_with(URI)


def test_rate_limit_respects_retry_after_without_hidden_retries():
    spotify, api, clock, fallback, _ = client()
    api.devices.side_effect = SpotifyException(429, -1, 'rate', headers={'Retry-After': '30'})
    with pytest.raises(IntegrationError, match='spotify_rate_limited_fallback'):
        spotify.play(SpotifyAction(uri=URI))
    with pytest.raises(IntegrationError, match='spotify_rate_limited'):
        spotify.playback()
    api.devices.assert_called_once()
    api.current_playback.assert_not_called()
    clock.now = 31
    api.current_playback.return_value = None
    assert spotify.playback().name == ''
    api.current_playback.assert_called_once()


def test_unauthorized_refreshes_once_then_retries():
    spotify, api, *_ = client()
    spotify._auth = Mock()
    api.current_playback.side_effect = [SpotifyException(401, -1, 'expired'), None]
    spotify.playback()
    spotify._auth.force_refresh.assert_called_once()
    assert api.current_playback.call_count == 2


def test_refresh_failure_is_safe():
    spotify, api, *_ = client()
    spotify._auth = Mock()
    spotify._auth.force_refresh.side_effect = SpotifyOauthError('secret-response')
    api.current_playback.side_effect = SpotifyException(401, -1, 'expired')
    with pytest.raises(IntegrationError, match='spotify_auth_required'):
        spotify.playback()
    assert api.current_playback.call_count == 1


def test_network_failure_and_fallback_failure():
    spotify, api, _, fallback, _ = client()
    api.devices.side_effect = requests.Timeout('secret')
    with pytest.raises(IntegrationError, match='spotify_network_failed_fallback'):
        spotify.play(SpotifyAction(uri=URI))
    fallback.side_effect = IntegrationError('spotify_fallback_failed')
    with pytest.raises(IntegrationError, match='^spotify_fallback_failed$'):
        spotify.play(SpotifyAction(uri=URI))


def test_playback_details_and_controls():
    spotify, api, *_ = client()
    api.current_playback.return_value = {'item': {'name': 'Song', 'artists': [{'name': 'Artist'}]},
                                        'is_playing': True, 'device': {'id': 'd', 'volume_percent': 50}}
    state = spotify.playback()
    assert (state.name, state.artists, state.playing, state.volume) == ('Song', 'Artist', True, 50)
    for operation in ('toggle', 'next', 'previous'):
        spotify.control(operation)
    spotify.control('volume', 75)
    api.pause_playback.assert_called_once_with(device_id='d')
    api.next_track.assert_called_once_with(device_id='d')
    api.previous_track.assert_called_once_with(device_id='d')
    api.volume.assert_called_once_with(75, device_id='d')
    api.current_playback.return_value['is_playing'] = False
    spotify.control('toggle')
    api.start_playback.assert_called_once_with(device_id='d')
    with pytest.raises(ValueError):
        spotify.control('volume', 101)
    api.current_playback.return_value = None
    with pytest.raises(IntegrationError, match='spotify_no_device'):
        spotify.control('next')


def test_playlist_pagination_owner_filter_and_search():
    spotify, api, *_ = client()
    api.current_user.return_value = {'id': 'me'}
    api.current_user_playlists.side_effect = [
        {'items': [{'name': 'Música española', 'owner': {'id': 'me'}, 'uri': URI},
                   {'name': 'Other', 'owner': {'id': 'other'}, 'uri': URI}, None], 'next': 'next'},
        {'items': [{'name': 'Study', 'owner': {'id': 'me'}, 'uri': URI},
                   {'name': 'Bad', 'owner': {'id': 'me'}, 'uri': 'bad'}], 'next': None}]
    playlists = spotify.playlists()
    assert [item.name for item in playlists] == ['Música española', 'Study']
    assert api.current_user_playlists.call_args_list[1].kwargs == {'limit': 50, 'offset': 3}
    assert filter_playlists(playlists, 'MUSICA ESPANOLA') == [playlists[0]]


def test_cached_pkce_never_prompts_when_missing_and_refreshes_expired(tmp_path):
    cache = TokenCache(tmp_path / '.spotify_cache', 'a' * 32)
    auth = CachedPKCE(client_id='a'*32, redirect_uri=REDIRECT_URI, scope=SCOPES,
                      cache_handler=cache, open_browser=False)
    with patch.object(auth, 'get_authorization_code', side_effect=AssertionError('interactive prompt')):
        with pytest.raises(IntegrationError, match='spotify_auth_required'):
            auth.get_access_token()
    cache.save_token_to_cache({'access_token': 'old', 'refresh_token': 'refresh', 'expires_at': 0, 'scope': SCOPES})
    with patch.object(auth, 'refresh_access_token', return_value={'access_token': 'new'}) as refresh:
        assert auth.get_access_token() == 'new'
        refresh.assert_called_once_with('refresh')
    assert TokenCache(cache.path, 'b'*32).get_cached_token() is None
    if __import__('os').name != 'nt':
        assert cache.path.stat().st_mode & 0o777 == 0o600
    cache.path.write_text('[]')
    assert cache.get_cached_token() is None


def test_auth_loopback_checks_state_and_uses_pkce_without_secret(tmp_path):
    cache = TokenCache(tmp_path / '.spotify_cache', 'a' * 32)
    auth = CachedPKCE(client_id='a'*32, redirect_uri=REDIRECT_URI, scope=SCOPES,
                      cache_handler=cache, open_browser=False)
    response = Mock()
    response.json.return_value = {'access_token': 'access', 'refresh_token': 'refresh', 'expires_in': 3600, 'scope': SCOPES}
    errors = []
    threads = []
    def browser(url):
        query = parse_qs(urlsplit(url).query)
        assert query['code_challenge_method'] == ['S256']
        assert 'client_secret' not in query
        assert query['redirect_uri'] == [REDIRECT_URI]
        def callback():
            try:
                try:
                    urlopen(REDIRECT_URI + '?code=untrusted&state=wrong', timeout=2)
                    errors.append('invalid state accepted')
                except HTTPError as error:
                    assert error.code == 400
                with urlopen(REDIRECT_URI + '?code=approved&state=' + query['state'][0], timeout=2) as result:
                    assert result.status == 200
            except Exception as error:
                errors.append(error)
        thread = Thread(target=callback)
        thread.start()
        threads.append(thread)
        return True
    with patch.object(auth._session, 'post', return_value=response) as post:
        authorize(auth, Event(), translations(), browser=browser, timeout=2)
        for thread in threads:
            thread.join(2)
        assert not errors
        payload = post.call_args.kwargs['data']
        assert payload['code'] == 'approved'
        assert payload['code_verifier'] == auth.code_verifier
        assert 'client_secret' not in payload
        assert post.call_args.kwargs['verify'] is True
    assert cache.get_cached_token()['access_token'] == 'access'


def test_auth_cancel_timeout_and_browser_failure(tmp_path):
    auth = CachedPKCE(client_id='a'*32, redirect_uri=REDIRECT_URI,
                      cache_handler=TokenCache(tmp_path / '.spotify_cache', 'a'*32))
    cancel = Event()
    cancel.set()
    with pytest.raises(IntegrationError, match='spotify_auth_cancelled'):
        authorize(auth, cancel, translations(), browser=lambda url: True)
    with pytest.raises(IntegrationError, match='spotify_auth_timeout'):
        authorize(auth, Event(), translations(), browser=lambda url: True, timeout=0)
    with pytest.raises(IntegrationError, match='browser_launch_failed'):
        authorize(auth, Event(), translations(), browser=lambda url: False)


def test_settings_and_missing_configuration(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    assert store.load().spotify_client_id == ''
    store.save(AppSettings(spotify_client_id='a'*32))
    assert store.load().spotify_client_id == 'a'*32
    store.path.unlink()
    with pytest.raises(IntegrationError, match='spotify_client_id_missing'):
        SpotifyClient(store).playback()
    store.path.write_text('{broken')
    with pytest.raises(IntegrationError, match='settings_read_failed'):
        store.load()


def test_background_errors_are_keys_and_busy_operations_are_not_queued():
    tasks = Background()
    entered, release = Event(), Event()
    def work():
        entered.set()
        assert release.wait(2)
        raise RuntimeError('sensitive-value')
    assert tasks.submit('owner', 'operation', work)
    assert entered.wait(2)
    assert not tasks.submit('other', 'operation', lambda: None)
    release.set()
    result = tasks.events.get(timeout=2)
    assert result.error_key == 'spotify_api_failed'
    assert tasks.pending  # Busy until the GUI acknowledges the result.
    tasks.finish()
    assert not tasks.pending


def test_runner_continues_after_spotify_fallback():
    from novadeck.core.models import Profile, SteamAction
    from novadeck.core.runner import Runner
    spotify, api, _, fallback, _ = client()
    api.start_playback.side_effect = SpotifyException(403, -1, 'premium')
    steam = Mock()
    results = Runner({'spotify': spotify.play, 'steam': steam}).run(Profile(name='A', actions=[
        SpotifyAction(uri=URI), SteamAction(app_id='570', display_name='Dota')]))
    assert [result.status for result in results] == ['failed', 'succeeded']
    assert results[0].message_key == 'spotify_premium_required_fallback'
    fallback.assert_called_once_with(URI)
    steam.assert_called_once()


def test_auth_denial_and_occupied_port_are_reported(tmp_path):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    auth = CachedPKCE(client_id='a'*32, redirect_uri=REDIRECT_URI,
                      cache_handler=TokenCache(tmp_path / '.spotify_cache', 'a'*32))
    threads = []
    def browser(url):
        state = parse_qs(urlsplit(url).query)['state'][0]
        def callback():
            with urlopen(REDIRECT_URI + '?error=access_denied&state='+state, timeout=2):
                pass
        thread = Thread(target=callback)
        thread.start()
        threads.append(thread)
        return True
    with pytest.raises(IntegrationError, match='spotify_auth_denied'):
        authorize(auth, Event(), translations(), browser=browser, timeout=2)
    for thread in threads:
        thread.join(2)
    with HTTPServer(('127.0.0.1', 8888), BaseHTTPRequestHandler):
        with pytest.raises(IntegrationError, match='spotify_callback_busy'):
            authorize(auth, Event(), translations(), browser=Mock())


def test_spotipy_debug_logs_do_not_expose_tokens(caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        logging.getLogger('spotipy.oauth2').debug('access_token=private-test-value')
    assert 'private-test-value' not in caplog.text


def test_configured_pkce_has_required_scopes_and_disables_api_retries(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    store.save(AppSettings(spotify_client_id='a'*32))
    spotify = SpotifyClient(store)
    with patch('novadeck.integrations.spotify_client.spotipy.Spotify') as factory:
        spotify._prepare()
    auth = factory.call_args.kwargs['auth_manager']
    assert isinstance(auth, CachedPKCE)
    assert set(auth.scope.split()) == set(SCOPES.split())
    assert auth.redirect_uri == REDIRECT_URI
    assert factory.call_args.kwargs['retries'] == 0
    assert factory.call_args.kwargs['status_retries'] == 0
    assert auth.cache_handler.path == tmp_path / '.spotify_cache'


def test_missing_local_process_launches_desktop_and_ignores_remote_computer():
    spotify, api, clock, fallback, desktop = client()
    spotify._desktop_running = lambda: False
    api.devices.side_effect = [{'devices': [dict(DEVICE, id='other', name='OtherPC')]},
                               {'devices': [dict(DEVICE, id='other', name='OtherPC'),
                                            dict(DEVICE, id='local', name='ThisPC')]}]
    with patch('novadeck.integrations.spotify_client.platform.node', return_value='ThisPC'):
        spotify.play(SpotifyAction(uri=URI))
    desktop.assert_called_once()
    api.transfer_playback.assert_called_once_with('local', force_play=False)
    assert clock.waits == [.5]


@pytest.mark.parametrize('kind', ['playlist', 'album', 'track', 'artist'])
def test_localized_spotify_links_are_normalized(kind):
    action = SpotifyAction(uri=f'https://open.spotify.com/intl-es/{kind}/'+'a'*22+'?si=share')
    assert action.uri == f'spotify:{kind}:'+'a'*22
