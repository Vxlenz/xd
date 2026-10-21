# Build on the target OS: PyInstaller does not cross-compile Windows executables.
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files('novadeck', includes=['i18n/*.json', 'assets/*.png', 'assets/*.ico'])
datas += collect_data_files('tzdata')
binaries = collect_dynamic_libs('vosk')
hiddenimports = ['vosk', 'sounddevice', 'apscheduler.triggers.cron']
runtime_hooks = []
if sys.platform.startswith('linux'):
    runtime_hooks.append(str(root / 'tools/hooks/portaudio_linux.py'))
if sys.platform == 'win32':
    hiddenimports += ['pystray._win32', 'pynput.keyboard._win32', 'pynput.mouse._win32']
    hiddenimports += collect_submodules('comtypes', filter=lambda name: '.test' not in name)
    hiddenimports += collect_submodules('pycaw')

analysis = Analysis(
    [str(root / 'app.py')], pathex=[str(root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=runtime_hooks, excludes=['pytest'], noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name='NovaDeck',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, icon=str(root / 'novadeck/assets/novadeck.ico'),
)
bundle = COLLECT(
    executable, analysis.binaries, analysis.datas, strip=False, upx=False, name='NovaDeck',
)
