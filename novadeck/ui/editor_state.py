"""Pure editor transformations, testable without a desktop session."""
from collections.abc import Mapping

from ..core.models import (LaunchAction, Profile, ProfileAction, SpotifyAction,
                           SteamAction, SystemAction)


def move_action(profile: Profile, source: int, destination: int) -> None:
    if not 0 <= source < len(profile.actions) or not 0 <= destination < len(profile.actions):
        raise IndexError('invalid_action_index')
    profile.actions.insert(destination, profile.actions.pop(source))


def action_from_fields(kind: str, fields: Mapping[str, str], action_id: str | None = None) -> ProfileAction:
    common = {'delay_seconds': float(fields.get('delay_seconds', '0'))}
    if action_id is not None:
        common['id'] = action_id
    if kind == 'steam':
        return SteamAction(**common, app_id=fields['app_id'].strip(), display_name=fields['display_name'].strip())
    if kind == 'launch':
        return LaunchAction(**common, target=fields['target'].strip(),
                            arguments=fields.get('arguments', '').splitlines())
    if kind == 'spotify':
        return SpotifyAction(**common, uri=fields['uri'].strip(),
                             volume=int(fields['volume']) if fields.get('volume', '').strip() else None,
                             shuffle=_optional_bool(fields.get('shuffle', '')))
    if kind == 'system':
        return SystemAction(**common,
                            volume=int(fields['volume']) if fields.get('volume', '').strip() else None,
                            do_not_disturb=_optional_bool(fields.get('do_not_disturb', '')),
                            restore_volume=fields.get('restore_volume', 'true') == 'true')
    raise ValueError('invalid_action_type')


def _optional_bool(value: str) -> bool | None:
    if value == '':
        return None
    if value not in ('true', 'false'):
        raise ValueError('invalid_boolean')
    return value == 'true'
