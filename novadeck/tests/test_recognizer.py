from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import json
import time

import pytest

from novadeck.core.settings_store import VoiceOptions
from novadeck.integrations.errors import IntegrationError
from novadeck.voice.recognizer import SpeechService, microphones
from novadeck.voice.hotkey import GlobalHotkey, parse_hotkey


class FakeRecognizer:
    def __init__(self,model,rate):
        self.text=''
    def AcceptWaveform(self,data):
        self.text=data.decode()
        return True
    def Result(self):
        text,self.text=self.text,''
        return json.dumps({'text':text})
    def FinalResult(self):
        text,self.text=self.text,''
        return json.dumps({'text':text})
    def Reset(self):
        self.text=''


class FakeAudio:
    def __init__(self):
        self.callback=None
        self.opened=Event()
        self.closed=Event()
    def query_hostapis(self):
        return [{'name':'test-api'}]
    def query_devices(self,*args):
        device={'name':'Mic','hostapi':0,'max_input_channels':1,'default_samplerate':16000}
        return device if args else [device]
    def RawInputStream(self,**kwargs):
        audio=self
        class Stream:
            def __enter__(self):
                audio.callback=kwargs['callback'];audio.opened.set();return self
            def __exit__(self,*args):
                audio.closed.set()
        return Stream()


def make_service():
    models=Mock();models.ensure.return_value=Path('model')
    audio=FakeAudio()
    vosk=SimpleNamespace(Model=Mock(),KaldiRecognizer=FakeRecognizer,SetLogLevel=Mock())
    return SpeechService(models,audio=audio,vosk=vosk),audio


def next_event(service,kind,timeout=2):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        event=service.events.get(timeout=max(.01,deadline-time.monotonic()))
        if event.kind==kind:
            return event
    pytest.fail('Missing recognition event')


def test_push_to_talk_discards_idle_audio_and_emits_only_on_release():
    service,audio=make_service()
    service.configure(VoiceOptions(enabled=True))
    service.tick()
    assert audio.opened.wait(2)
    audio.callback(b'not recorded',1,None,False)
    service.press()
    audio.callback(b'activa perfil jugar',1,None,False)
    # Stream silence result must not execute before the key is released.
    time.sleep(.08)
    events=[]
    while not service.events.empty():
        events.append(service.events.get_nowait())
    assert not any(event.kind=='final' for event in events)
    service.release()
    event=next_event(service,'final')
    assert event.text=='activa perfil jugar'
    service.stop();service._thread.join(2)
    assert audio.closed.is_set()


def test_always_listening_emits_utterances_without_button_and_stops_cleanly():
    service,audio=make_service()
    service.configure(VoiceOptions(enabled=True,always_listening=True))
    service.tick();assert audio.opened.wait(2)
    audio.callback(b'nova pausa',1,None,False)
    assert next_event(service,'final').text=='nova pausa'
    service.stop();service._thread.join(2)
    assert audio.closed.is_set()


def test_missing_microphone_and_failed_model_are_friendly():
    service,audio=make_service()
    service.configure(VoiceOptions(enabled=True,microphone='removed'))
    service.tick()
    assert next_event(service,'error').key=='voice_microphone_missing'
    service._thread.join(2)
    assert not audio.opened.is_set()
    service.models.ensure.side_effect=IntegrationError('voice_model_download_failed')
    service.configure(VoiceOptions(enabled=True));service.tick()
    assert next_event(service,'error').key=='voice_model_download_failed'
    service._thread.join(2)


def test_overflow_stops_instead_of_executing_incomplete_audio():
    service,audio=make_service()
    service.configure(VoiceOptions(enabled=True,always_listening=True));service.tick()
    assert audio.opened.wait(2)
    audio.callback(b'corrupt audio',1,None,True)
    assert next_event(service,'error').key=='voice_audio_overflow'
    service._thread.join(2)
    assert audio.closed.is_set()


def test_disabling_while_downloading_never_opens_microphone():
    service,audio=make_service()
    entered,release=Event(),Event()
    def download(*args):
        entered.set();assert release.wait(2);return Path('model')
    service.models.ensure.side_effect=download
    service.configure(VoiceOptions(enabled=True));service.tick();assert entered.wait(2)
    service.configure(VoiceOptions(enabled=False));release.set();service._thread.join(2)
    assert not audio.opened.is_set()
    service.tick()
    assert not service._thread.is_alive()


@pytest.mark.parametrize('value',['space','ctrl+ctrl+a','ctrl+alt','win+x','ctrl+f13','ctrl+;'])
def test_invalid_hotkey(value):
    with pytest.raises(ValueError):
        parse_hotkey(value)


def test_hotkey_canonicalization_and_press_release_only_once():
    class Listener:
        def __init__(self,on_press,on_release):
            self.on_press,self.on_release=on_press,on_release
        def canonical(self,key):return key
        def start(self):return
        def stop(self):return
    backend=SimpleNamespace(Listener=Listener,HotKey=SimpleNamespace(parse=lambda shortcut:['ctrl','alt','space']))
    press,release=Mock(),Mock()
    hotkey=GlobalHotkey(press,release,backend=backend)
    assert hotkey.start('CTRL+ALT+SPACE')
    listener=hotkey.listener
    for key in ['ctrl','alt','space','space']:
        listener.on_press(key)
    press.assert_called_once()
    listener.on_release('space');listener.on_release('alt')
    release.assert_called_once()
    hotkey.stop()
    listener.on_press('space')  # A late OS callback after unhooking is harmless.
    assert press.call_count==1


def test_microphone_identity_is_stable_across_indices():
    devices=microphones(FakeAudio())
    assert devices[0].key=='test-api:Mic'
    assert devices[0].rate==16000


def test_disable_during_model_load_never_opens_microphone():
    service,audio=make_service()
    entered,release=Event(),Event()
    def model(path):
        entered.set();assert release.wait(2);return object()
    service.vosk.Model.side_effect=model
    service.configure(VoiceOptions(enabled=True));service.tick()
    assert entered.wait(2)
    service.configure(VoiceOptions(enabled=False));release.set();service._thread.join(2)
    assert not audio.opened.is_set()
