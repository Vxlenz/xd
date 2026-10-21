"""Pure bilingual command parsing. Speech can only select existing profile IDs."""
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata


@dataclass(frozen=True)
class Command:
    kind: str
    profile_id: str | None = None


def normalize(text: str) -> str:
    text = ''.join(char for char in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(char))
    return ' '.join(re.findall(r'\w+', text, flags=re.UNICODE))


COMMANDS = {
    'pause': {'pausa', 'pausar', 'pausa la musica', 'pause', 'pause music'},
    'resume': {'continua', 'reanuda', 'reanuda la musica', 'resume', 'resume music', 'play music'},
    'next': {'siguiente', 'siguiente cancion', 'next', 'next song', 'next track'},
    'previous': {'anterior', 'cancion anterior', 'previous', 'previous song', 'previous track'},
    'volume_up': {'sube el volumen', 'sube volumen', 'aumenta el volumen', 'volume up', 'turn up the volume'},
    'volume_down': {'baja el volumen', 'baja volumen', 'reduce el volumen', 'volume down', 'turn down the volume'},
    'dnd_on': {'activa no molestar', 'activa el modo no molestar', 'no molestar', 'enable do not disturb', 'turn on do not disturb'},
    'dnd_off': {'desactiva no molestar', 'desactiva el modo no molestar', 'disable do not disturb', 'turn off do not disturb'},
    'stop': {'deten todo', 'para todo', 'stop everything', 'stop all'},
}


def parse_command(text: str, profiles: Mapping[str, str], *, require_wake: bool = False) -> Command:
    if not isinstance(text, str) or len(text) > 500:
        return Command('unknown')
    heard = normalize(text)
    words = heard.split()
    if words and words[0] == 'nova':
        heard = ' '.join(words[1:])
    elif require_wake:
        return Command('wake_missing')
    if not heard:
        return Command('unknown')
    for kind, phrases in COMMANDS.items():
        if heard in phrases:
            return Command(kind)
    match = re.fullmatch(r'(?:activa|activar|inicia|iniciar|ejecuta|ejecutar)(?: el)?(?: perfil)? (.+)', heard)
    if match is None:
        match = re.fullmatch(r'(?:start|activate|run)(?: the)?(?: profile)? (.+?)(?: profile)?', heard)
    if match is None:
        return Command('unknown')
    target = match.group(1).strip()
    candidates = [(identifier, normalize(name)) for identifier, name in profiles.items()]
    exact = [identifier for identifier, name in candidates if name == target]
    if len(exact) == 1:
        return Command('activate', exact[0])
    if len(exact) > 1:
        return Command('ambiguous')
    if len(target) <= 3:
        return Command('unknown')
    scored = sorted(((SequenceMatcher(None, target, name).ratio(), identifier)
                     for identifier, name in candidates if len(name) > 3), reverse=True)
    if not scored or scored[0][0] < .78:
        return Command('unknown')
    if len(scored) > 1 and scored[0][0] - scored[1][0] < .12:
        return Command('ambiguous')
    return Command('activate', scored[0][1])
