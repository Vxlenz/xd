"""Submit a user-configured game to the registered Windows Steam handler."""
import os
import sys

from ..core.models import SteamAction
from .errors import IntegrationError


def launch_game(action: SteamAction) -> None:
    action = SteamAction.model_validate_json(action.model_dump_json())
    if sys.platform != 'win32':
        raise IntegrationError('windows_required')
    try:
        os.startfile(f'steam://rungameid/{action.app_id}')
    except OSError as exc:
        raise IntegrationError('steam_launch_failed') from exc
