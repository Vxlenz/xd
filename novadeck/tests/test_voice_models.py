import io
from pathlib import Path
from threading import Event
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
import requests

from novadeck.integrations.errors import IntegrationError
from novadeck.voice.models import ModelManager, MODEL_NAMES, REQUIRED_FILES


def archive(language='es',extra=None):
 output=io.BytesIO()
 with ZipFile(output,'w') as zipped:
  for file in REQUIRED_FILES:
   zipped.writestr(MODEL_NAMES[language]+'/'+file,b'model-data')
  if extra:
   zipped.writestr(extra,b'evil')
 return output.getvalue()


def getter(data):
 response=Mock()
 response.status_code=200
 response.headers={'Content-Length':str(len(data))}
 response.iter_content.return_value=[data]
 response.__enter__=Mock(return_value=response)
 response.__exit__=Mock(return_value=False)
 return Mock(return_value=response)


def test_first_use_download_then_offline_cache(tmp_path):
 get=getter(archive())
 manager=ModelManager(tmp_path,get=get)
 path=manager.ensure('es',Event())
 assert all((path/file).is_file() for file in REQUIRED_FILES)
 assert path==tmp_path/MODEL_NAMES['es']
 assert get.call_args.args==('https://alphacephei.com/vosk/models/'+MODEL_NAMES['es']+'.zip',)
 assert get.call_args.kwargs['allow_redirects'] is False
 assert get.call_args.kwargs.get('verify',True) is True
 assert manager.ensure('es',Event())==path
 assert get.call_count==1
 assert not list(tmp_path.glob('.download-*'))


@pytest.mark.parametrize('entry',['../escape','/absolute',MODEL_NAMES['es']+'/../../escape',
 MODEL_NAMES['es']+'/C:/escape',MODEL_NAMES['es']+'\\escape'])
def test_model_extraction_rejects_unsafe_paths(tmp_path,entry):
 with pytest.raises(IntegrationError,match='voice_model_invalid'):
  ModelManager(tmp_path,get=getter(archive(extra=entry))).ensure('es',Event())
 assert not (tmp_path/MODEL_NAMES['es']).exists()
 assert not list(tmp_path.glob('.download-*'))


def test_cancel_corrupt_and_failed_downloads_leave_no_partial_model(tmp_path):
 cancel=Event();cancel.set()
 get=getter(archive())
 with pytest.raises(IntegrationError,match='voice_cancelled'):
  ModelManager(tmp_path,get=get).ensure('es',cancel)
 get.assert_not_called()
 for data in [b'not-a-zip',archive()[:-40]]:
  with pytest.raises(IntegrationError,match='voice_model_invalid'):
   ModelManager(tmp_path,get=getter(data)).ensure('es',Event())
 get=Mock(side_effect=requests.ConnectionError('offline'))
 with pytest.raises(IntegrationError,match='voice_model_download_failed'):
  ModelManager(tmp_path,get=get).ensure('en',Event())
 assert not list(tmp_path.glob('.download-*'))


def test_corrupt_existing_model_is_preserved(tmp_path):
 target=tmp_path/MODEL_NAMES['es'];target.mkdir()
 (target/'user-file').write_text('preserve')
 with pytest.raises(IntegrationError,match='voice_model_invalid'):
  ModelManager(tmp_path,get=Mock()).ensure('es',Event())
 assert (target/'user-file').read_text()=='preserve'
