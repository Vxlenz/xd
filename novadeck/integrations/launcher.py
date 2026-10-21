"""Launch only explicitly supplied targets, without command-shell interpolation."""
from pathlib import Path
import subprocess
import sys
import webbrowser
from urllib.parse import urlsplit

from ..core.models import LaunchAction
from .errors import IntegrationError


def launch(action: LaunchAction) -> None:
    action = LaunchAction.model_validate_json(action.model_dump_json())
    if urlsplit(action.target).scheme in ('https', 'http'):
        try:
            if not webbrowser.open(action.target, new=2):
                raise IntegrationError('browser_launch_failed')
        except (OSError, webbrowser.Error) as exc:
            raise IntegrationError('browser_launch_failed') from exc
        return
    if sys.platform != 'win32':
        raise IntegrationError('windows_required')
    path = Path(action.target)
    try:
        if not path.is_file():
            raise IntegrationError('executable_missing')
        subprocess.Popen([str(path), *action.arguments], shell=False, cwd=str(path.parent))
    except OSError as exc:
        raise IntegrationError('app_launch_failed') from exc
