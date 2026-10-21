"""Let sounddevice find the bundled PortAudio without a system ldconfig entry."""
import ctypes.util
from pathlib import Path
import sys

_system_find_library = ctypes.util.find_library


def _find_library(name):
    if name == 'portaudio':
        library = Path(sys._MEIPASS) / 'libportaudio.so.2'
        if library.is_file():
            return str(library)
    return _system_find_library(name)


ctypes.util.find_library = _find_library
