import json
import logging
import sys

from .core.config import configure_logging, data_directory


def show_startup_error(key: str) -> None:
    """Display a translated error even if CustomTkinter cannot be imported."""
    from .i18n import translations

    language = 'es'
    try:
        language = json.loads((data_directory() / 'settings.json').read_text(encoding='utf-8')).get('language', 'es')
    except (OSError, ValueError, AttributeError):
        pass
    strings = translations(language if language in ('es', 'en') else 'es')
    message = strings[key]
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            show = ctypes.windll.user32.MessageBoxW
            show.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            show.restype = ctypes.c_int
            if show(None, message, strings['app_name'], 0x10):
                return
        except (OSError, AttributeError):
            pass
    try:
        from tkinter import messagebox
        messagebox.showerror(strings['app_name'], message)
    except Exception:
        if sys.stderr is not None:
            sys.stderr.write(message + '\n')


def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="NovaDeck")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--self-test", metavar="REPORT.json", help="Check bundled resources without loading user settings")
    args = parser.parse_args(argv)
    if args.self_test:
        from .diagnostics import write_report
        raise SystemExit(write_report(args.self_test))
    try:
        configure_logging()
    except OSError:
        show_startup_error('startup_logging_failed')
        raise SystemExit(1) from None
    window = None
    try:
        import customtkinter as ctk
        from .ui.main_window import MainWindow

        ctk.set_appearance_mode('dark')
        window = MainWindow(minimized=args.minimized, login=args.login)
        window.mainloop()
    except Exception as error:
        # Exception messages and tracebacks can contain private paths or commands.
        logging.getLogger('novadeck').error('startup_failed (%s)', type(error).__name__)
        if window is not None:
            try:
                window.destroy()
            except Exception:
                logging.getLogger('novadeck').error('startup_cleanup_failed')
        show_startup_error('startup_failed')
        raise SystemExit(1) from None
