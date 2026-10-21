"""Offline Vosk/PortAudio worker. PCM exists only in a bounded memory queue."""
from dataclasses import dataclass
import json
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from ..core.settings_store import VoiceOptions
from ..integrations.errors import IntegrationError
from .models import ModelManager


@dataclass(frozen=True)
class Microphone:
    key: str
    name: str
    index: int
    rate: int


@dataclass(frozen=True)
class VoiceEvent:
    generation: int
    kind: str
    text: str = ''
    key: str | None = None


def audio_backend():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as exc:
        raise IntegrationError('voice_audio_missing') from exc


def microphones(audio=None) -> list[Microphone]:
    audio = audio if audio is not None else audio_backend()
    try:
        hosts = audio.query_hostapis()
        return [Microphone(f"{hosts[d['hostapi']]['name']}:{d['name']}", d['name'], index,
                           int(d['default_samplerate']))
                for index, d in enumerate(audio.query_devices()) if d['max_input_channels'] > 0]
    except Exception as exc:
        raise IntegrationError('voice_microphone_failed') from exc


class SpeechService:
    def __init__(self, models: ModelManager, *, audio=None, vosk=None):
        self.models, self.audio, self.vosk = models, audio, vosk
        self.events: Queue[VoiceEvent] = Queue(maxsize=64)
        self.generation = 0
        self.options = VoiceOptions()
        self._thread: Thread | None = None
        self._stop = Event()
        self._pressed = False
        self._epoch = 0
        self._released = 0
        self._lock = Lock()
        self._pending: VoiceOptions | None = None

    def _emit(self, generation, kind, text='', key=None):
        event = VoiceEvent(generation, kind, text[:500], key)
        try:
            self.events.put_nowait(event)
        except Full:
            # Never accumulate an unbounded transcript history.
            try:
                self.events.get_nowait()
            except Empty:
                pass
            try:
                self.events.put_nowait(event)
            except Full:
                pass

    def configure(self, options: VoiceOptions) -> None:
        self.generation += 1
        self._stop.set()
        self.release()
        self.options = VoiceOptions.model_validate_json(options.model_dump_json())
        self._pending = self.options if options.enabled else None
        self._emit(self.generation, 'status', key='voice_preparing' if options.enabled else 'voice_disabled')

    def tick(self) -> None:
        if self._pending is not None and (self._thread is None or not self._thread.is_alive()):
            options, self._pending = self._pending, None
            self._stop = Event()
            self._thread = Thread(target=self._run, args=(self.generation, options, self._stop), daemon=True,
                                  name='novadeck-speech')
            self._thread.start()

    def press(self) -> None:
        with self._lock:
            if not self._pressed:
                self._epoch += 1
                self._pressed = True
        self._emit(self.generation, 'status', key='voice_listening')

    def release(self) -> None:
        with self._lock:
            self._pressed = False
            self._released = self._epoch

    def stop(self) -> None:
        self.generation += 1
        self._pending = None
        self._stop.set()
        self.release()

    def _run(self, generation: int, options: VoiceOptions, stop: Event) -> None:
        try:
            self._emit(generation, 'status', key='voice_downloading')
            path = self.models.ensure(options.language, stop)
            if stop.is_set():
                return
            if self.vosk is None:
                import vosk
            else:
                vosk = self.vosk
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(path))  # Explicit path: Vosk's own network downloader is never used.
            if stop.is_set():
                return
            audio = self.audio if self.audio is not None else audio_backend()
            devices = microphones(audio)
            if options.microphone is None:
                try:
                    default = audio.query_devices(None, 'input')
                    index, rate = None, int(default['default_samplerate'])
                except Exception as exc:
                    raise IntegrationError('voice_microphone_failed') from exc
            else:
                matching = [device for device in devices if device.key == options.microphone]
                if len(matching) != 1:
                    raise IntegrationError('voice_microphone_missing')
                index, rate = matching[0].index, matching[0].rate
            if not 8000 <= rate <= 192000:
                raise IntegrationError('voice_microphone_failed')
            self._capture(generation, options, stop, audio, vosk, model, index, rate)
        except IntegrationError as exc:
            if not stop.is_set():
                self._emit(generation, 'error', key=exc.key)
        except Exception:
            if not stop.is_set():
                self._emit(generation, 'error', key='voice_failed')
        finally:
            self._emit(generation, 'stopped')

    def _capture(self, generation, options, stop, audio, vosk, model, index, rate):
        chunks: Queue[tuple[int, bytes]] = Queue(maxsize=16)
        overflow = Event()
        def callback(data, frames, timing, status):
            if stop.is_set():
                return
            with self._lock:
                if not options.always_listening and not self._pressed:
                    return
                if status:
                    overflow.set()
                    return
                epoch = 0 if options.always_listening else self._epoch
                try:
                    chunks.put_nowait((epoch, bytes(data)))
                except Full:
                    overflow.set()
        recognizer = vosk.KaldiRecognizer(model, rate)
        current_epoch = None
        fragments = []
        def final():
            text = json.loads(recognizer.FinalResult()).get('text', '')
            joined = ' '.join([*fragments, text]).strip()
            if joined:
                self._emit(generation, 'final', joined)
            fragments.clear()
            recognizer.Reset()
        try:
            with audio.RawInputStream(samplerate=rate, blocksize=max(800, rate//10), dtype='int16',
                                       channels=1, device=index, callback=callback):
                self._emit(generation, 'status', key='voice_wake_listening' if options.always_listening else 'voice_ready')
                while not stop.is_set():
                    if overflow.is_set():
                        raise IntegrationError('voice_audio_overflow')
                    try:
                        epoch, data = chunks.get(timeout=.05)
                    except Empty:
                        with self._lock:
                            released = self._released
                        if not options.always_listening and current_epoch is not None and released >= current_epoch:
                            final()
                            current_epoch = None
                            self._emit(generation, 'status', key='voice_ready')
                        continue
                    if current_epoch is not None and epoch != current_epoch:
                        final()
                    current_epoch = epoch
                    if recognizer.AcceptWaveform(data):
                        text = json.loads(recognizer.Result()).get('text', '')
                        if options.always_listening:
                            if text:
                                self._emit(generation, 'final', text)
                        else:
                            fragments.append(text)
                            if sum(map(len, fragments)) > 500:
                                raise IntegrationError('voice_utterance_too_long')
                    # No partial transcript is retained or written to a log.
        except IntegrationError:
            raise
        except Exception as exc:
            raise IntegrationError('voice_microphone_failed') from exc
        finally:
            while not chunks.empty():
                try:
                    chunks.get_nowait()
                except Empty:
                    break
