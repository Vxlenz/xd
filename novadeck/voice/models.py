"""First-use downloads from Vosk's official HTTPS host; no audio is sent."""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
from threading import Event
import tempfile
import time
from zipfile import BadZipFile, ZipFile

import requests

from ..integrations.errors import IntegrationError

MODEL_NAMES = {'es': 'vosk-model-small-es-0.42', 'en': 'vosk-model-small-en-us-0.15'}
MODEL_BASE = 'https://alphacephei.com/vosk/models/'
REQUIRED_FILES = ('am/final.mdl', 'conf/mfcc.conf', 'conf/model.conf')
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


class ModelManager:
    def __init__(self, directory: Path, *, get=requests.get):
        self.directory = directory
        self.get = get

    def ensure(self, language: str, cancel: Event, progress=lambda received, total: None) -> Path:
        if language not in MODEL_NAMES:
            raise ValueError('invalid_voice_language')
        if cancel.is_set():
            raise IntegrationError('voice_cancelled')
        name = MODEL_NAMES[language]
        target = self.directory / name
        if target.exists():
            try:
                marker = json.loads((target/'.novadeck-ready.json').read_text())
                if marker['name'] == name and all((target/file).is_file() and (target/file).stat().st_size > 0 for file in REQUIRED_FILES):
                    return target
            except (OSError, ValueError, KeyError, TypeError):
                pass
            raise IntegrationError('voice_model_invalid')
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.download-', dir=self.directory) as temporary:
                temporary = Path(temporary)
                archive = temporary/'model.zip'
                received, digest = 0, sha256()
                deadline = time.monotonic()+300
                with self.get(MODEL_BASE+name+'.zip', stream=True, timeout=(5, 15), allow_redirects=False) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise IntegrationError('voice_model_download_failed')
                    total = int(response.headers.get('Content-Length', 0))
                    if total < 0 or total > MAX_ARCHIVE:
                        raise IntegrationError('voice_model_invalid')
                    with archive.open('wb') as output:
                        for chunk in response.iter_content(1024*256):
                            if cancel.is_set():
                                raise IntegrationError('voice_cancelled')
                            if time.monotonic()>deadline:
                                raise IntegrationError('voice_model_download_failed')
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > MAX_ARCHIVE:
                                raise IntegrationError('voice_model_invalid')
                            digest.update(chunk)
                            output.write(chunk)
                            progress(received, total)
                        output.flush()
                        os.fsync(output.fileno())
                    if total and received != total:
                        raise IntegrationError('voice_model_invalid')
                if cancel.is_set():
                    raise IntegrationError('voice_cancelled')
                extracted = temporary/'extracted'
                with ZipFile(archive) as zipped:
                    members = zipped.infolist()
                    if len(members) > 10000 or sum(item.file_size for item in members)>MAX_EXPANDED:
                        raise IntegrationError('voice_model_invalid')
                    for item in members:
                        path = PurePosixPath(item.filename)
                        if (path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != name
                                or '\\' in item.filename or ':' in item.filename or stat.S_ISLNK(item.external_attr>>16)):
                            raise IntegrationError('voice_model_invalid')
                    for item in members:
                        if cancel.is_set():
                            raise IntegrationError('voice_cancelled')
                        zipped.extract(item, extracted)  # ZipFile verifies each member's CRC.
                model = extracted/name
                if not all((model/file).is_file() and (model/file).stat().st_size > 0 for file in REQUIRED_FILES):
                    raise IntegrationError('voice_model_invalid')
                (model/'.novadeck-ready.json').write_text(json.dumps({'name': name, 'archive_sha256': digest.hexdigest()}))
                try:
                    os.replace(model, target)
                except OSError:
                    if target.exists():
                        return self.ensure(language, cancel, progress)
                    raise
            return target
        except IntegrationError:
            raise
        except requests.RequestException as exc:
            raise IntegrationError('voice_model_download_failed') from exc
        except (OSError, ValueError, BadZipFile) as exc:
            raise IntegrationError('voice_model_invalid') from exc
