"""Explicit PKCE consent with a bounded, state-checked loopback callback."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
import secrets
from threading import Event
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyPKCE

from ..core.profile_store import ProfileStore
from .errors import IntegrationError

REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPES = ' '.join(('user-read-playback-state', 'user-modify-playback-state',
                   'user-read-currently-playing', 'playlist-read-private', 'user-library-read'))

# Spotipy debug messages can include credentials; keep this library's logs private.
_library_logger = logging.getLogger('spotipy')
_library_logger.addHandler(logging.NullHandler())
_library_logger.propagate = False


class TokenCache(CacheHandler):
    def __init__(self, path: Path, client_id: str):
        self.path = path
        self.client_id = client_id

    def get_cached_token(self):
        try:
            content = json.loads(self.path.read_bytes())
            if content.get('client_id') != self.client_id:
                return None
            token = content['token']
            if not isinstance(token, dict) or not all(key in token for key in
                    ('access_token', 'refresh_token', 'expires_at', 'scope')):
                return None
            if (not isinstance(token['expires_at'], (int, float)) or
                    not all(isinstance(token[key], str) for key in ('access_token', 'refresh_token', 'scope'))):
                return None
            return token
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, AttributeError, TypeError):
            return None
        except OSError as exc:
            raise IntegrationError('spotify_cache_failed') from exc

    def save_token_to_cache(self, token_info):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ProfileStore._atomic_write(self.path, json.dumps(
                {'client_id': self.client_id, 'token': token_info}).encode('utf-8'))
            self.path.chmod(0o600)
        except OSError as exc:
            raise IntegrationError('spotify_cache_failed') from exc


class CachedPKCE(SpotifyPKCE):
    """API calls may refresh a token, but must never prompt on stdin or open consent."""
    def get_access_token(self, code=None, check_cache=True, **kwargs):
        if code is None:
            token = self.validate_token(self.cache_handler.get_cached_token())
            if not token:
                raise IntegrationError('spotify_auth_required')
            return token['access_token']
        return super().get_access_token(code=code, check_cache=False)

    def force_refresh(self) -> None:
        token = self.cache_handler.get_cached_token()
        if not token:
            raise IntegrationError('spotify_auth_required')
        self.refresh_access_token(token['refresh_token'])


def authorize(auth: CachedPKCE, cancel: Event, messages: dict[str, str],
              browser=webbrowser.open, timeout: float = 120) -> None:
    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(2)
            super().setup()

        def log_message(self, *args):
            # HTTP request paths contain authorization codes. Never log them.
            return

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != '/callback':
                self.send_response(404)
                self.end_headers()
                return
            received = query.get('state', [])
            if len(received) != 1 or not hmac.compare_digest(received[0], state):
                self.send_response(400)
                self.end_headers()
                return
            if len(query.get('code', [])) == 1 and 'error' not in query:
                result['code'] = query['code'][0]
            else:
                result['error'] = 'spotify_auth_denied'
            body = messages['spotify_browser_done'].encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = HTTPServer(('127.0.0.1', 8888), Callback)
    except OSError as exc:
        raise IntegrationError('spotify_callback_busy') from exc
    with server:
        server.timeout = .2
        # Reset verifier for every new consent attempt, including retries after denial.
        auth.get_pkce_handshake_parameters()
        try:
            if not browser(auth.get_authorize_url(state=state)):
                raise IntegrationError('browser_launch_failed')
        except webbrowser.Error as exc:
            raise IntegrationError('browser_launch_failed') from exc
        deadline = time.monotonic() + timeout
        while not result and not cancel.is_set() and time.monotonic() < deadline:
            server.handle_request()
    if cancel.is_set():
        raise IntegrationError('spotify_auth_cancelled')
    if not result:
        raise IntegrationError('spotify_auth_timeout')
    if 'error' in result:
        raise IntegrationError(result['error'])
    auth.get_access_token(code=result['code'], check_cache=False)
