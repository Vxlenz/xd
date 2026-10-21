"""Spotify Client ID and explicit browser consent; no client secret is requested."""
from threading import Event
import webbrowser

import customtkinter as ctk
from pydantic import ValidationError

from ..core.background import Background, TaskResult
from ..core.settings_store import AppSettings
from ..integrations.errors import IntegrationError
from ..integrations.spotify_client import SpotifyClient
from ..integrations.startup import WindowsStartup
from . import theme
from .widgets import button, label
from .voice_settings import VoiceSettings


class Settings(ctk.CTkToplevel):
    def __init__(self, parent, strings: dict[str, str], spotify: SpotifyClient, tasks: Background, startup: WindowsStartup | None = None,
                 voice_service=None, voice_tasks=None, on_voice_change=None):
        super().__init__(parent)
        self.s, self.spotify, self.tasks = strings, spotify, tasks
        self.cancel_auth = Event()
        self.configure(fg_color=theme.BACKGROUND)
        self.title(strings['settings'])
        self.geometry('680x760')
        self.transient(parent)
        self.body = ctk.CTkScrollableFrame(self, fg_color=theme.BACKGROUND)
        self.body.pack(fill='both', expand=True)
        self.startup = startup if startup is not None else WindowsStartup()
        self.startup_enabled = False
        self.startup_value = ctk.BooleanVar(value=False)
        self.startup_switch = ctk.CTkSwitch(self.body, text=strings['start_with_windows'],
                                           variable=self.startup_value, command=self.toggle_startup)
        self.startup_switch.pack(anchor='w', padx=24, pady=(16, 4))
        label(self.body, strings['startup_hint'], wraplength=620).pack(fill='x', padx=24)
        self.startup_status = ctk.CTkLabel(self.body, text='', text_color=theme.WARNING, wraplength=620)
        self.startup_status.pack(fill='x', padx=24)
        if not self.startup.supported:
            self.startup_switch.configure(state='disabled')
            self.startup_status.configure(text=strings['windows_required'])
        else:
            try:
                self.startup_enabled = self.startup.enabled()
                self.startup_value.set(self.startup_enabled)
            except IntegrationError as exc:
                self.startup_status.configure(text=strings[exc.key])
        label(self.body, strings['spotify_setup_title'], font=('Segoe UI', 22, 'bold')).pack(anchor='w', padx=24, pady=20)
        guide = ctk.CTkTextbox(self.body, height=230, fg_color=theme.SURFACE, text_color=theme.TEXT, wrap='word')
        guide.pack(fill='x', padx=24)
        guide.insert('1.0', strings['spotify_setup_guide'])
        guide.configure(state='disabled')
        button(self.body, strings['spotify_dashboard'], self.open_dashboard, secondary=True).pack(anchor='w', padx=24, pady=10)
        label(self.body, strings['spotify_client_id']).pack(anchor='w', padx=24)
        self.client_id = ctk.CTkEntry(self.body, placeholder_text=strings['spotify_client_id'])
        self.client_id.pack(fill='x', padx=24, pady=8)
        self.status = ctk.CTkLabel(self.body, text='', text_color=theme.ACCENT, wraplength=620)
        self.status.pack(fill='x', padx=24, pady=8)
        try:
            self.client_id.insert(0, spotify.settings.load().spotify_client_id)
        except IntegrationError as exc:
            self.status.configure(text=strings[exc.key])
        self.connect_button = button(self.body, strings['spotify_connect'], self.connect)
        self.connect_button.pack(pady=8)
        button(self.body, strings['cancel'], self.cancel_auth.set, secondary=True).pack(pady=8)
        if voice_service is not None:
            self.voice_panel = VoiceSettings(self.body, strings, spotify.settings, voice_tasks, voice_service, on_voice_change)
            self.voice_panel.pack(fill='x', padx=24, pady=20)
        self.bind('<Escape>', lambda event: self.destroy())

    def toggle_startup(self) -> None:
        try:
            enabled = self.startup_value.get()
            self.startup.set_enabled(enabled)
            self.startup_enabled = enabled
            self.startup_status.configure(text=self.s['startup_enabled' if enabled else 'startup_disabled'])
        except IntegrationError as exc:
            self.startup_value.set(self.startup_enabled)
            self.startup_status.configure(text=self.s[exc.key])

    def open_dashboard(self) -> None:
        def open_page():
            if not webbrowser.open('https://developer.spotify.com/dashboard'):
                raise IntegrationError('browser_launch_failed')
        if not self.tasks.submit(self, 'dashboard', open_page):
            self.status.configure(text=self.s['spotify_busy'])

    def connect(self) -> None:
        try:
            client_id = AppSettings(spotify_client_id=self.client_id.get().strip()).spotify_client_id
            if not client_id:
                raise ValueError()
        except (ValueError, ValidationError):
            self.status.configure(text=self.s['spotify_invalid_client_id'])
            return
        self.cancel_auth = Event()
        if self.tasks.submit(self, 'connect', lambda: self.spotify.connect(client_id, self.cancel_auth, self.s)):
            self.status.configure(text=self.s['spotify_authorizing'])
            self.connect_button.configure(state='disabled')
        else:
            self.status.configure(text=self.s['spotify_busy'])

    def handle_task_result(self, result: TaskResult) -> None:
        if result.operation == 'connect':
            self.connect_button.configure(state='normal')
        self.status.configure(text=self.s.get(result.error_key, self.s['spotify_api_failed']) if result.error_key
                              else self.s['spotify_connected'] if result.operation == 'connect' else '')

    def destroy(self) -> None:
        self.cancel_auth.set()
        super().destroy()
