"""Opt-in distribution check. Never opens devices, credentials or user settings."""
from importlib import import_module
from importlib.resources import files
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def write_report(destination: str | Path) -> int:
    checks: dict[str, bool] = {}

    def check(name, operation):
        try:
            operation()
            checks[name] = True
        except Exception:
            # Dependency errors can contain local paths; the report only needs check names.
            checks[name] = False

    modules = [
        'novadeck.ui.main_window', 'novadeck.ui.profile_editor',
        'apscheduler.schedulers.background', 'apscheduler.triggers.cron',
        'spotipy', 'vosk', 'sounddevice',
    ]
    if sys.platform == 'win32':
        modules += ['pystray', 'pynput.keyboard', 'comtypes', 'pycaw.pycaw', 'winreg']
    for module in modules:
        check(module, lambda module=module: import_module(module))

    def catalogs():
        from .i18n import translations
        es, en = translations('es'), translations('en')
        assert es.keys() == en.keys()
        assert es['run'] != en['run']
    check('translations', catalogs)

    def icons():
        from PIL import Image
        for extension in ('png', 'ico'):
            with files('novadeck').joinpath('assets/novadeck.' + extension).open('rb') as source:
                with Image.open(source) as image:
                    image.load()
                    assert min(image.size) >= 32
    check('icons', icons)
    check('timezone_data', lambda: ZoneInfo('America/Bogota'))

    def tkinter():
        import customtkinter as ctk
        root = ctk.CTk()
        try:
            root.withdraw()
            ctk.CTkButton(root, text='').pack()
            root.update()
        finally:
            root.destroy()
    check('tkinter', tkinter)

    report = {'ok': all(checks.values()), 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': checks}
    Path(destination).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['ok'] else 1
