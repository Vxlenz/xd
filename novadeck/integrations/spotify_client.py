"""Spotify operations. All public methods run on workers, never on Tk's thread."""
from collections.abc import Callable
from dataclasses import dataclass
import csv
import io
import math
import os
import platform
import subprocess
from threading import Event, RLock
import time
import webbrowser

import requests
import spotipy
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from ..core.models import SpotifyAction
from ..core.settings_store import AppSettings, SettingsStore
from .errors import IntegrationError
from .spotify_auth import CachedPKCE, REDIRECT_URI, SCOPES, TokenCache, authorize


@dataclass(frozen=True)
class Playback:
    name: str = ''
    artists: str = ''
    playing: bool = False
    volume: int | None = None


@dataclass(frozen=True)
class Playlist:
    name: str
    uri: str


def _desktop_running() -> bool | None:
    if os.name != 'nt':
        return None
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Spotify.exe', '/FO', 'CSV', '/NH'],
                                capture_output=True, text=True, timeout=5,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode != 0:
            return None
        return any(row and row[0].casefold() == 'spotify.exe' for row in csv.reader(io.StringIO(result.stdout)))
    except (OSError, subprocess.TimeoutExpired):
        return None


def _open_desktop() -> None:
    try:
        os.startfile('spotify:')
    except (AttributeError, OSError) as exc:
        raise IntegrationError('spotify_desktop_failed') from exc


def _open_uri(uri: str) -> None:
    try:
        if hasattr(os, 'startfile'):
            os.startfile(uri)
        else:
            _, kind, identifier = uri.split(':')
            if not webbrowser.open(f'https://open.spotify.com/{kind}/{identifier}', new=2):
                raise OSError()
    except (OSError, webbrowser.Error) as exc:
        raise IntegrationError('spotify_fallback_failed') from exc


class SpotifyClient:
    def __init__(self, settings: SettingsStore | None = None, *, api=None, auth=None,
                 launch_desktop: Callable = _open_desktop, open_uri: Callable = _open_uri,
                 sleep: Callable = time.sleep, clock: Callable = time.monotonic, desktop_running: Callable = _desktop_running):
        self.settings = settings if settings is not None else SettingsStore()
        self._api = api
        self._auth = auth
        self._client_id: str | None = None
        self._desktop_running = desktop_running
        self._launch_desktop = launch_desktop
        self._open_uri = open_uri
        self._sleep = sleep
        self._clock = clock
        self._retry_at = 0.0
        self._lock = RLock()

    def _prepare(self):
        if self._api is not None:
            return self._api
        settings = self.settings.load()
        if not settings.spotify_client_id:
            raise IntegrationError('spotify_client_id_missing')
        self._client_id = settings.spotify_client_id
        self._auth = CachedPKCE(client_id=self._client_id, redirect_uri=REDIRECT_URI,
                                scope=SCOPES, cache_handler=TokenCache(
                                    self.settings.path.parent / '.spotify_cache', self._client_id),
                                open_browser=False, requests_timeout=(3, 5))
        self._api = spotipy.Spotify(auth_manager=self._auth, requests_timeout=(3, 5),
                                    retries=0, status_retries=0, backoff_factor=0)
        return self._api

    def _call(self, name: str, *args, **kwargs):
        if self._clock() < self._retry_at:
            raise IntegrationError('spotify_rate_limited')
        api = self._prepare()
        for attempt in range(2):
            try:
                return getattr(api, name)(*args, **kwargs)
            except SpotifyException as exc:
                if exc.http_status == 401 and attempt == 0 and self._auth is not None:
                    try:
                        self._auth.force_refresh()
                    except (SpotifyOauthError, requests.RequestException) as refresh_error:
                        raise IntegrationError('spotify_auth_required') from refresh_error
                    continue
                if exc.http_status == 429:
                    try:
                        delay = float((exc.headers or {}).get('Retry-After', 5))
                        if not math.isfinite(delay):
                            delay = 5
                    except (TypeError, ValueError):
                        delay = 5
                    self._retry_at = self._clock() + max(1, delay)
                    raise IntegrationError('spotify_rate_limited') from exc
                key = {401: 'spotify_auth_required', 403: 'spotify_premium_required',
                       404: 'spotify_no_device'}.get(exc.http_status, 'spotify_api_failed')
                raise IntegrationError(key) from exc
            except SpotifyOauthError as exc:
                raise IntegrationError('spotify_auth_required') from exc
            except requests.RequestException as exc:
                raise IntegrationError('spotify_network_failed') from exc

    def _exclusive(self):
        if not self._lock.acquire(blocking=False):
            raise IntegrationError('spotify_busy')

    def connect(self, client_id: str, cancel: Event, messages: dict[str, str]) -> None:
        validated = AppSettings(spotify_client_id=client_id)
        if not validated.spotify_client_id:
            raise IntegrationError('spotify_client_id_missing')
        self._exclusive()
        try:
            self.settings.update(spotify_client_id=validated.spotify_client_id)
            self._api = self._auth = None
            self._prepare()
            try:
                authorize(self._auth, cancel, messages)
            except SpotifyOauthError as exc:
                raise IntegrationError('spotify_auth_required') from exc
            except requests.RequestException as exc:
                raise IntegrationError('spotify_network_failed') from exc
        finally:
            self._lock.release()

    def play(self, action: SpotifyAction) -> None:
        action = SpotifyAction.model_validate_json(action.model_dump_json())
        self._exclusive()
        try:
            try:
                device = self._desktop_device()
                device_id = device['id']
                self._call('transfer_playback', device_id, force_play=False)
                if action.volume is not None:
                    self._call('volume', action.volume, device_id=device_id)
                if action.shuffle is not None:
                    self._call('shuffle', action.shuffle, device_id=device_id)
                arguments = {'uris': [action.uri]} if action.uri.startswith('spotify:track:') else {'context_uri': action.uri}
                self._call('start_playback', device_id=device_id, **arguments)
            except IntegrationError as exc:
                self._open_uri(action.uri)
                # Opening a URI is a fallback, not a successful API playback result.
                raise IntegrationError(exc.key + '_fallback') from exc
        finally:
            self._lock.release()

    def _desktop_device(self):
        deadline = self._clock() + 20
        delay = .5
        launched = False
        check_process = True
        previous_ids: set[str] = set()
        while True:
            devices = (self._call('devices') or {}).get('devices', [])
            computers = [d for d in devices if d.get('type') == 'Computer' and d.get('id') and not d.get('is_restricted')]
            host = platform.node().casefold()
            if check_process and self._desktop_running() is False:
                # Existing devices can belong to other PCs. Wait for this desktop.
                previous_ids = {device['id'] for device in computers}
                self._launch_desktop()
                launched = True
                check_process = False
                computers = []
            elif launched and previous_ids:
                computers = [device for device in computers if device['id'] not in previous_ids
                             or device.get('name', '').casefold() == host]
            check_process = False
            if computers:
                return next((d for d in computers if d.get('name', '').casefold() == host),
                            next((d for d in computers if d.get('is_active')), computers[0]))
            if not launched:
                self._launch_desktop()
                launched = True
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise IntegrationError('spotify_no_device')
            self._sleep(min(delay, remaining))
            delay = min(delay * 2, 4)

    def playback(self) -> Playback:
        self._exclusive()
        try:
            state = self._call('current_playback') or {}
            item = state.get('item') or {}
            return Playback(item.get('name', ''), ', '.join(a.get('name', '') for a in item.get('artists', [])),
                            bool(state.get('is_playing')), (state.get('device') or {}).get('volume_percent'))
        finally:
            self._lock.release()

    def control(self, operation: str, volume: int | None = None) -> None:
        if operation not in ('toggle', 'pause', 'resume', 'next', 'previous', 'volume'):
            raise ValueError('invalid_spotify_control')
        if operation == 'volume' and (type(volume) is not int or not 0 <= volume <= 100):
            raise ValueError('invalid_volume')
        self._exclusive()
        try:
            state = self._call('current_playback') or {}
            device_id = (state.get('device') or {}).get('id')
            if not device_id:
                raise IntegrationError('spotify_no_device')
            if operation == 'toggle':
                self._call('pause_playback' if state.get('is_playing') else 'start_playback', device_id=device_id)
            elif operation == 'pause':
                if state.get('is_playing'):
                    self._call('pause_playback', device_id=device_id)
            elif operation == 'resume':
                if not state.get('is_playing'):
                    self._call('start_playback', device_id=device_id)
            elif operation == 'volume':
                self._call('volume', volume, device_id=device_id)
            else:
                self._call('next_track' if operation == 'next' else 'previous_track', device_id=device_id)
        finally:
            self._lock.release()

    def playlists(self) -> list[Playlist]:
        self._exclusive()
        try:
            user_id = self._call('current_user')['id']
            result = []
            offset = 0
            while True:
                page = self._call('current_user_playlists', limit=50, offset=offset) or {}
                items = page.get('items') or []
                for item in items:
                    if item and (item.get('owner') or {}).get('id') == user_id:
                        uri = item.get('uri', '')
                        try:
                            validated = SpotifyAction(uri=uri)
                        except ValueError:
                            continue
                        result.append(Playlist(item.get('name', ''), validated.uri))
                if not page.get('next') or not items:
                    return result
                offset += len(items)
        finally:
            self._lock.release()
