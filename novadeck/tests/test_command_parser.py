import pytest
from novadeck.voice.command_parser import Command, parse_command

PROFILES={'a':'Jugar','b':'Gaming','c':'Estudio','d':'Relax'}


@pytest.mark.parametrize('text,expected',[
 ('activa perfil jugar',Command('activate','a')), ('start gaming profile',Command('activate','b')),
 ('NOVA, activa el perfil Estúdio!',Command('activate','c')), ('activate profile relax',Command('activate','d')),
 ('start gamming profile',Command('activate','b')), ('pausa',Command('pause')),
 ('siguiente canción',Command('next')), ('sube el volumen',Command('volume_up')),
 ('baja volumen',Command('volume_down')), ('activa no molestar',Command('dnd_on')),
 ('desactiva no molestar',Command('dnd_off')), ('detén todo',Command('stop')),
 ('stop everything',Command('stop')), ('previous track',Command('previous')),
 ('resume music',Command('resume')), ('pause music',Command('pause')),
 ('turn up the volume',Command('volume_up')),
])
def test_bilingual_commands(text,expected):
 assert parse_command(text,PROFILES)==expected


@pytest.mark.parametrize('text',['pausa','supernova pausa','quiero nova pausa','novato pausa'])
def test_continuous_mode_requires_initial_whole_wake_word(text):
 assert parse_command(text,PROFILES,require_wake=True).kind=='wake_missing'


def test_wake_word_unknown_and_ambiguous_profiles_are_safe():
 assert parse_command('nova pausa',PROFILES,require_wake=True)==Command('pause')
 assert parse_command('nova',PROFILES,require_wake=True).kind=='unknown'
 assert parse_command('activa perfil estudio',{'a':'Estudio','b':'Estúdio'}).kind=='ambiguous'
 assert parse_command('start gamin profile',{'a':'Gaming','b':'Gaminq'}).kind=='ambiguous'
 assert parse_command('start tv profile',{'a':'TV','b':'AV'})==Command('activate','a')
 assert parse_command('start ts profile',{'a':'TV'}).kind=='unknown'


@pytest.mark.parametrize('text',['abre calc.exe','https://example.com','no activa perfil jugar',
 "don't start gaming profile",'jugar','x'*501,'activate nonexistent profile'])
def test_arbitrary_speech_never_becomes_a_launch_target(text):
 assert parse_command(text,PROFILES).kind=='unknown'
