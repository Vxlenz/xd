"""Profile cards and execution feedback. Tk is touched only on the main thread."""
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from importlib.resources import files
import logging
import sys
from queue import Empty
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..core.background import Background
from ..core.execution import ControlFinished, Execution, LifecycleFinished, RunFinished
from ..core.system_session import SystemSession
from ..core.settings_store import VoiceOptions
from ..voice.command_parser import parse_command
from ..voice.hotkey import GlobalHotkey
from ..voice.models import ModelManager
from ..voice.recognizer import SpeechService
from ..voice.overlay import VoiceOverlay
from ..core.models import Profile, ProfileAction, SpotifyAction
from ..integrations.spotify_client import SpotifyClient
from ..integrations.errors import IntegrationError
from .mini_player import MiniPlayer
from .playlist_picker import PlaylistPicker
from .settings import Settings
from ..core.profile_store import ProfileStore, ProfileStoreError
from ..core.runner import ActionResult
from ..core.scheduler import ProfileScheduler, ScheduledRun, classify_run
from ..integrations.startup import WindowsStartup
from .scheduled_notice import ScheduledNotice
from .tray import Tray
from ..i18n import translations
from . import theme
from .profile_editor import ProfileEditor
from .widgets import button, label


class MainWindow(ctk.CTk):
    def __init__(self, store: ProfileStore | None = None, execution: Execution | None = None,
                 spotify: SpotifyClient | None = None, *, scheduler: ProfileScheduler | None = None,
                 tray: Tray | None = None, startup: WindowsStartup | None = None,
                 minimized: bool = False, login: bool = False, speech=None, hotkey=None):
        theme.apply()
        super().__init__(fg_color=theme.BACKGROUND)
        self.store = store if store is not None else ProfileStore()
        self.execution = execution if execution is not None else Execution(
            sessions=SystemSession(self.store.path.parent / 'system_recovery.json'))
        self._ending = False
        self._quit_requested = False
        self.spotify = spotify if spotify is not None else SpotifyClient()
        self.tasks = Background()
        self.voice_tasks = Background(default_error='voice_failed')
        self.speech = speech if speech is not None else SpeechService(ModelManager(self.store.path.parent/'models'))
        self.voice_hotkey = hotkey if hotkey is not None else GlobalHotkey(self.speech.press, self.speech.release)
        self.voice_overlay = None
        self._voice_heard = ''
        self._voice_ready = False
        self._voice_hook_generation = -1
        self._voice_status_key = 'voice_disabled'
        self._voice_stop_pending = False
        self._voice_stop_music_pending = False
        self._voice_stop_music_error = None
        self._voice_stop_system_error = None
        if execution is None:
            self.execution.runner.handlers['spotify'] = self.spotify.play
        self.scheduler = scheduler if scheduler is not None else ProfileScheduler()
        self.tray = tray if tray is not None else Tray()
        self.startup = startup if startup is not None else WindowsStartup()
        self.profiles: list[Profile] = []
        self.scheduled_pending: deque[ScheduledRun] = deque()
        self.scheduled_seen: deque[tuple] = deque(maxlen=1024)
        self.notice: ScheduledNotice | None = None
        self.minimize_requested = minimized
        self._last_schedule_labels = 0.0
        self._closing = False
        self.scheduler.start([])
        self.settings_window = None
        self.language = 'es'
        try:
            self.language = self.spotify.settings.load().language
        except IntegrationError:
            pass  # The existing settings error is shown after the widgets are ready.
        self.s = translations(self.language)
        self.editor: ProfileEditor | None = None
        self.active_profile: Profile | None = None
        self.result_labels: dict[str, ctk.CTkLabel] = {}
        self.title(self.s['app_name'])
        if sys.platform == 'win32':
            self.iconbitmap(str(files('novadeck').joinpath('assets/novadeck.ico')))
        self.geometry('1120x800')
        self.minsize(900, 650)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.content = ctk.CTkFrame(self, fg_color='transparent')
        self.content.pack(fill='both', expand=True)
        self.render()
        self.tray.start(self.profiles, self.s, self.scheduler.paused)
        if login:
            self.scheduler.emit_login()
        self.poll_id = self.after(50, self.poll_events)
        if self.execution.sessions is not None:
            self.execution.recover()
            self.update_session_ui()
        try:
            self.apply_voice_options(self.spotify.settings.load().voice)
        except IntegrationError as exc:
            self._voice_status_key = exc.key
            self.voice_status.configure(text=self.text(exc.key))

    def text(self, key: str) -> str:
        return self.s.get(key, self.s['action_failed'])

    def render(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()
        self.content.grid_columnconfigure(0,weight=1)
        self.content.grid_rowconfigure(3,weight=1)
        header = ctk.CTkFrame(self.content, fg_color='transparent')
        header.grid(row=0,column=0,sticky='ew',padx=28,pady=(24,12))
        label(header, self.s['app_name'], font=('Segoe UI', 30, 'bold')).pack(side='left')
        self.language_menu = ctk.CTkOptionMenu(
            header, values=[self.s['language_es'], self.s['language_en']],
            command=self.change_language, width=120)
        self.language_menu.set(self.s['language_current'])
        self.language_menu.pack(side='right')
        button(header, self.s['import'], self.import_profile, secondary=True).pack(side='right', padx=12)
        button(header, self.s['settings'], self.open_settings, secondary=True, width=90).pack(side='right')
        toolbar = ctk.CTkFrame(self.content, fg_color='transparent')
        toolbar.grid(row=1,column=0,sticky='ew',padx=28,pady=4)
        self.automation_status = label(toolbar, self.s['scheduler_paused' if self.scheduler.paused else 'scheduler_active'], anchor='w')
        self.automation_status.pack(side='left')
        button(toolbar, self.s['quit'], self.quit_app, secondary=True, width=70).pack(side='right')
        self.pause_button = button(toolbar, self.s['scheduler_resume' if self.scheduler.paused else 'scheduler_pause'],
                                   self.toggle_scheduler, secondary=True, width=170)
        self.pause_button.pack(side='right', padx=8)
        label(self.content, self.s['profiles_heading'], anchor='w').grid(row=2,column=0,sticky='ew',padx=28)
        self.cards = ctk.CTkScrollableFrame(self.content, fg_color=theme.BACKGROUND)
        self.cards.grid(row=3,column=0,sticky='nsew',padx=20,pady=8)
        for column in range(2):
            self.cards.grid_columnconfigure(column, weight=1, uniform='cards')
        self.refresh_cards()
        panel = ctk.CTkFrame(self.content, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS)
        panel.grid(row=4,column=0,sticky='ew',padx=28,pady=(0,12))
        session_bar = ctk.CTkFrame(panel, fg_color='transparent')
        session_bar.pack(fill='x', padx=16, pady=(10, 0))
        self.session_label = ctk.CTkLabel(session_bar, text='', text_color=theme.ACCENT, wraplength=650, anchor='w')
        self.session_label.pack(side='left', fill='x', expand=True)
        self.end_button = button(session_bar, self.s['end_profile'], self.end_profile, secondary=True, width=135)
        self.end_button.pack(side='right', padx=4)
        self.recovery_button = button(session_bar, self.s['retry_recovery'], self.retry_recovery, secondary=True, width=145)
        self.recovery_button.pack(side='right', padx=4)
        self.run_title = label(panel, self.s['ready'], anchor='w')
        self.run_title.pack(fill='x', padx=16, pady=(12, 4))
        self.results_frame = ctk.CTkScrollableFrame(panel, height=64, fg_color=theme.SURFACE)
        # CTk gives the vertical scrollbar a 200px requested height by default.
        self.results_frame._scrollbar.configure(height=64)
        self.results_frame.pack(fill='x', padx=8)
        self.result_labels = {}
        self.cancel_button = button(panel, self.s['cancel_run'], self.execution.cancel, secondary=True)
        self.cancel_button.pack(anchor='e', padx=16, pady=12)
        self.cancel_button.configure(state='disabled')
        self.player = MiniPlayer(self.content, self.s, self.spotify, self.tasks, self.open_playlist_picker)
        self.player.grid(row=5,column=0,sticky='ew',padx=28,pady=(0,12))
        voice_bar = ctk.CTkFrame(self.content, fg_color='transparent')
        voice_bar.grid(row=6,column=0,sticky='ew',padx=28,pady=(0,12))
        self.voice_status = label(voice_bar, self.text(self._voice_status_key), anchor='w', wraplength=600)
        self.voice_status.pack(side='left', fill='x', expand=True)
        self.voice_button = ctk.CTkButton(voice_bar, text=self.s['voice_hold'], fg_color=theme.PRIMARY,
                                         corner_radius=theme.BUTTON_RADIUS, command=None)
        self.voice_button.pack(side='right')
        self.voice_button.bind('<ButtonPress-1>', lambda event: self.speech.press() if self._voice_ready else None)
        self.voice_button.bind('<ButtonRelease-1>', lambda event: self.speech.release())
        self.voice_button._canvas.configure(takefocus=1)
        self.voice_button._canvas.bind('<KeyPress-space>', lambda event: self.speech.press() if self._voice_ready else None)
        self.voice_button._canvas.bind('<KeyRelease-space>', lambda event: self.speech.release())
        self.voice_button._canvas.bind('<FocusOut>', lambda event: self.speech.release())
        self.voice_button.configure(state='normal' if self._voice_ready and not self.speech.options.always_listening else 'disabled')
        self.update_session_ui()

    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
        else:
            self.settings_window = Settings(self, self.s, self.spotify, self.tasks, self.startup, self.speech, self.voice_tasks, self.apply_voice_options)

    def open_playlist_picker(self, parent=None, on_pick=None):
        if on_pick is None:
            def on_pick(item):
                self.start_run(Profile(name=item.name, actions=[SpotifyAction(uri=item.uri)]))
        return PlaylistPicker(parent if parent is not None else self, self.s, self.spotify, self.tasks, on_pick)

    def change_language(self, value: str) -> None:
        if self.active_profile is not None:
            self.language_menu.set(self.s['language_current'])
            return
        language = 'es' if value == self.s['language_es'] else 'en'
        try:
            self.spotify.settings.update(language=language)
        except IntegrationError as exc:
            self.language_menu.set(self.s['language_current'])
            self.show_error(exc.key)
            return
        self.language = language
        self.s = translations(language)
        self.render()

    def show_error(self, key: str) -> None:
        messagebox.showerror(self.s['error_title'], self.text(key), parent=self.editor if
                             self.editor is not None and self.editor.winfo_exists() else self)

    def report_callback_exception(self, exception, value, traceback) -> None:
        # Exceptions can contain a URI, transcript or token. Keep only their type in logs.
        logging.getLogger('novadeck.ui').error('UI callback failed (%s)', exception.__name__)
        self.show_error('unexpected_error')

    def refresh_cards(self) -> None:
        for widget in self.cards.winfo_children():
            widget.destroy()
        try:
            profiles = self.store.load().profiles
        except ProfileStoreError as exc:
            self.profiles = []
            self.schedule_labels = {}
            self.scheduler.replace_profiles([])
            self.tray.update([], self.s, self.scheduler.paused)
            label(self.cards, self.text(str(exc)), wraplength=700).grid(row=0, column=0, columnspan=2, pady=20)
            return
        self.profiles = profiles
        self.scheduler.replace_profiles(profiles)
        self.tray.update(profiles, self.s, self.scheduler.paused)
        self.schedule_labels = {}
        for index, profile in enumerate(profiles):
            card = ctk.CTkFrame(self.cards, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS,
                                border_width=1, border_color=profile.color)
            card.grid(row=index // 2, column=index % 2, sticky='nsew', padx=8, pady=8)
            label(card, f'{profile.icon}  {profile.name}', font=('Segoe UI', 20, 'bold'), wraplength=360).pack(anchor='w', padx=18, pady=(16, 4))
            label(card, self.s['action_count'].format(count=len(profile.actions))).pack(anchor='w', padx=18)
            scheduled = label(card, self.next_run_text(profile.id), wraplength=350)
            scheduled.pack(anchor='w', padx=18)
            self.schedule_labels[profile.id] = scheduled
            controls = ctk.CTkFrame(card, fg_color='transparent')
            controls.pack(fill='x', padx=12, pady=14)
            for text, callback in [
                (self.s['run'], lambda p=profile: self.start_run(p)),
                (self.s['edit'], lambda p=profile: self.open_editor(p)),
                (self.s['export'], lambda p=profile: self.export_profile(p)),
                (self.s['delete'], lambda p=profile: self.delete_profile(p)),
            ]:
                button(controls, text, callback, secondary=text != self.s['run'], width=72).pack(side='left', padx=3)
        index = len(profiles)
        button(self.cards, self.s['new_profile'], lambda: self.open_editor(Profile(name=self.s['default_profile_name'])),
               secondary=True, height=120).grid(row=index // 2, column=index % 2, sticky='nsew', padx=8, pady=8)

    def open_editor(self, profile: Profile) -> None:
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift()
            return
        self.editor = ProfileEditor(self, self.s, profile, self.save_profile, self.test_action, self.open_playlist_picker)

    def save_profile(self, profile: Profile) -> bool:
        try:
            self.store.upsert(profile)
        except ProfileStoreError as exc:
            self.show_error(str(exc))
            return False
        self.refresh_cards()
        return True

    def delete_profile(self, profile: Profile) -> None:
        if not messagebox.askyesno(self.s['delete'], self.s['delete_confirmation'].format(name=profile.name), parent=self):
            return
        try:
            self.store.delete(profile.id)
            self.refresh_cards()
        except ProfileStoreError as exc:
            self.show_error(str(exc))

    def import_profile(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[(self.s['json_files'], '*.json')])
        if not path:
            return
        # Imports never execute actions. Confirm before any existing ID is replaced.
        if not messagebox.askyesno(self.s['import'], self.s['import_confirmation'], parent=self):
            return
        try:
            self.store.import_profile(Path(path))
            self.refresh_cards()
        except ProfileStoreError as exc:
            self.show_error(str(exc))

    def export_profile(self, profile: Profile) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.json',
                                          filetypes=[(self.s['json_files'], '*.json')])
        if path:
            try:
                self.store.export_profile(profile.id, Path(path))
            except ProfileStoreError as exc:
                self.show_error(str(exc))

    def test_action(self, action: ProfileAction) -> bool:
        if self.execution.current_profile is not None:
            self.show_error('system_test_requires_end')
            return False
        return self.start_run(Profile(name=self.s['test_action'], actions=[action]), test=True)

    def start_run(self, profile: Profile, *, test: bool = False) -> bool:
        if self._quit_requested or self._ending or self.execution.recovery_required:
            self.show_error('system_recovery_pending')
            return False
        # Wait for the previous completion event to be displayed before starting again.
        if self.active_profile is not None or self.execution.busy:
            self.show_error('runner_busy')
            return False
        if not profile.actions:
            self.show_error('empty_actions')
            return False
        self.active_profile = profile.model_copy(deep=True)
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        self.result_labels = {}
        for index, action in enumerate(profile.actions):
            row = label(self.results_frame, self.s['result_line'].format(
                index=index + 1, kind=self.s['type_' + action.type], status=self.s['status_waiting']), anchor='w', wraplength=900)
            row.pack(fill='x', padx=8, pady=2)
            self.result_labels[action.id] = row
        self.run_title.configure(text=self.s['running_profile'].format(name=profile.name))
        self.cancel_button.configure(state='normal')
        self.language_menu.configure(state='disabled')
        try:
            started = self.execution.start(profile, test=test)
        except IntegrationError as exc:
            started = False
            self.show_error(exc.key)
        if not started:
            self.active_profile = None
            self.cancel_button.configure(state='disabled')
            self.language_menu.configure(state='normal')
            return False
        self._system_error = None
        self.update_session_ui()
        return True

    def poll_events(self) -> None:
        try:
            while True:
                event = self.execution.events.get_nowait()
                if isinstance(event, ActionResult):
                    self.show_result(event)
                elif isinstance(event, ControlFinished):
                    self.voice_feedback(event.error_key or event.operation)
                elif isinstance(event, LifecycleFinished):
                    self.finish_lifecycle(event)
                    if self._closing:
                        return
                else:
                    self.finish_run(event)
        except Empty:
            pass
        for tasks in (self.tasks, self.voice_tasks):
            try:
                while True:
                    result = tasks.events.get_nowait()
                    tasks.finish()
                    if result.owner.winfo_exists():
                        result.owner.handle_task_result(result)
            except Empty:
                pass
        self.poll_voice()
        self.update_session_ui()
        self.poll_automation()
        if self._closing:
            return
        self.poll_id = self.after(50, self.poll_events)

    def show_result(self, result: ActionResult) -> None:
        row = self.result_labels.get(result.action_id)
        if row is None or self.active_profile is None:
            return
        action = self.active_profile.actions[result.index]
        status = self.s['status_' + result.status]
        if result.message_key:
            status += ' · ' + self.text(result.message_key)
        row.configure(text=self.s['result_line'].format(index=result.index + 1,
                      kind=self.s['type_' + action.type], status=status),
                      text_color={'succeeded': theme.SUCCESS, 'failed': theme.DANGER,
                                  'cancelled': theme.WARNING, 'running': theme.ACCENT}[result.status])
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.test_status.configure(text=status)

    def finish_run(self, event: RunFinished) -> None:
        if event.error_key:
            summary = self.text(event.error_key)
        else:
            counts = {status: sum(r.status == status for r in event.results)
                      for status in ('succeeded', 'failed', 'cancelled')}
            summary = self.s['run_summary'].format(**counts)
        self.run_title.configure(text=summary)
        self.cancel_button.configure(state='disabled')
        self.language_menu.configure(state='normal')
        self.active_profile = None

    def update_session_ui(self) -> None:
        current = self.execution.current_profile
        if self._quit_requested:
            text = self.s['system_closing']
        elif self._ending:
            text = self.s['system_ending']
        elif self.execution.recovery_required:
            text = self.s['system_recovery_pending']
        elif current is not None:
            text = self.s['system_profile_active'].format(name=current.name)
        else:
            text = self.s['system_no_profile']
        if getattr(self, '_system_error', None):
            text = self.text(self._system_error)
        self.session_label.configure(text=text)
        self.end_button.configure(state='normal' if (current is not None or self.active_profile is not None)
                                  and not self._ending and not self._quit_requested else 'disabled')
        self.recovery_button.configure(state='normal' if self.execution.recovery_required and
                                       not self.execution.busy and not self._quit_requested else 'disabled')

    def end_profile(self) -> None:
        self._ending = True
        self._system_error = None
        self.execution.end_profile()
        self.update_session_ui()

    def retry_recovery(self) -> None:
        if self.execution.recover():
            self._system_error = None
            self.update_session_ui()

    def finish_lifecycle(self, event: LifecycleFinished) -> None:
        self._ending = False
        self._system_error = event.error_key
        if event.operation == 'end' and self._voice_stop_pending:
            self._voice_stop_pending = False
            self._voice_stop_system_error = event.error_key
            self.finish_voice_stop()
        if event.operation == 'close' and self._quit_requested:
            if event.error_key:
                if not messagebox.askyesno(self.s['error_title'], self.s['system_exit_failed'], parent=self):
                    self._quit_requested = False
                    self.apply_voice_options(self.speech.options)
                    self.update_session_ui()
                    return
            self._force_exit = bool(event.error_key)
            self.destroy()
            return
        self.update_session_ui()

    def apply_voice_options(self, options: VoiceOptions) -> None:
        self.voice_hotkey.stop()
        self._voice_ready = False
        self._voice_hook_generation = -1
        self.speech.configure(options)
        self.voice_button.configure(state='disabled')
        self._voice_status_key = 'voice_preparing' if options.enabled else 'voice_disabled'
        self.voice_status.configure(text=self.text(self._voice_status_key))

    def poll_voice(self) -> None:
        if not self._quit_requested and not self.execution.recovery_required:
            self.speech.tick()
        try:
            while True:
                event = self.speech.events.get_nowait()
                if event.generation != self.speech.generation:
                    continue
                if event.kind == 'final' and not self._quit_requested:
                    self.dispatch_voice(event.text)
                elif event.kind == 'status':
                    self._voice_status_key = event.key
                    self.voice_status.configure(text=self.text(event.key))
                    if event.key == 'voice_listening':
                        self._voice_heard = ''
                        self.voice_feedback('voice_listening')
                    if event.key in ('voice_ready', 'voice_wake_listening'):
                        self._voice_ready = True
                        if not self.speech.options.always_listening and self._voice_hook_generation != event.generation:
                            self._voice_hook_generation = event.generation
                            if not self.voice_hotkey.start(self.speech.options.hotkey):
                                self._voice_status_key = 'voice_hotkey_unavailable'
                                self.voice_status.configure(text=self.text(self._voice_status_key))
                        self.voice_button.configure(state='disabled' if self.speech.options.always_listening else 'normal')
                elif event.kind in ('error','stopped'):
                    self._voice_ready = False
                    self.voice_button.configure(state='disabled')
                    self.voice_hotkey.stop()
                    if event.key:
                        self._voice_status_key = event.key
                        self.voice_status.configure(text=self.text(event.key))
        except Empty:
            pass

    def voice_feedback(self, key: str) -> None:
        if self.voice_overlay is None or not self.voice_overlay.winfo_exists():
            self.voice_overlay = VoiceOverlay(self)
        self.voice_overlay.show(self.s['voice_heard'].format(text=self._voice_heard) if self._voice_heard else '', self.text(key))

    def dispatch_voice(self, text: str) -> None:
        if self._quit_requested or self.execution.recovery_required:
            return
        command = parse_command(text, {profile.id:profile.name for profile in self.profiles},
                                require_wake=self.speech.options.always_listening)
        if command.kind == 'wake_missing':
            return
        self._voice_heard = text[:180]
        if command.kind in ('unknown','ambiguous'):
            self.voice_feedback('voice_'+command.kind)
        elif command.kind == 'activate':
            profile = next((profile for profile in self.profiles if profile.id==command.profile_id),None)
            if profile is not None:
                if self.active_profile is not None or self.execution.busy:
                    self.voice_feedback('voice_busy')
                elif self.start_run(profile):
                    self.voice_feedback('voice_profile_started')
        elif command.kind in ('volume_up','volume_down','dnd_on','dnd_off'):
            arguments = {'volume_delta':10 if command.kind=='volume_up' else -10} if command.kind.startswith('volume_') else {'dnd':command.kind=='dnd_on'}
            if not self.execution.change_system(self.s['voice_manual_profile'],**arguments):
                self.voice_feedback('voice_busy')
        elif command.kind == 'stop':
            if self._voice_stop_pending or self._voice_stop_music_pending:
                self.voice_feedback('voice_busy')
                return
            self._voice_stop_music_error = None
            self._voice_stop_system_error = None
            if not self.scheduler.paused:
                self.toggle_scheduler()
            self._voice_stop_pending = True
            self.end_profile()
            self.voice_feedback('system_ending')
            self._voice_stop_music_pending = self.voice_tasks.submit(self,'voice_pause',lambda:self.spotify.control('pause'))
            if not self._voice_stop_music_pending:
                self._voice_stop_music_error = 'voice_busy'
        else:
            if not self.voice_tasks.submit(self,'voice_control',lambda:self.spotify.control(command.kind)):
                self.voice_feedback('voice_busy')

    def finish_voice_stop(self) -> None:
        if self._voice_stop_pending or self._voice_stop_music_pending:
            return
        key = self._voice_stop_system_error or 'voice_stopped'
        self.voice_feedback(key)
        if self._voice_stop_music_error:
            message = self.text(key) + ' ' + self.text(self._voice_stop_music_error)
            self.voice_overlay.show(self.s['voice_heard'].format(text=self._voice_heard),message)

    def handle_task_result(self, result) -> None:
        if result.operation == 'voice_pause':
            self._voice_stop_music_pending = False
            self._voice_stop_music_error = result.error_key
            self.finish_voice_stop()
        else:
            self.voice_feedback(result.error_key or 'voice_spotify_sent')

    def next_run_text(self, profile_id: str) -> str:
        next_run = self.scheduler.next_run(profile_id)
        if self.scheduler.paused:
            return self.s['scheduler_paused']
        if next_run is not None:
            return self.s['schedule_next'].format(time=self.s[f'weekday_{next_run.weekday()}'] + next_run.strftime(' %d/%m %H:%M %Z'))
        profile = next((profile for profile in self.profiles if profile.id == profile_id), None)
        return self.s['trigger_login'] if profile and any(trigger.type == 'login' for trigger in profile.triggers) else self.s['trigger_manual']

    def toggle_scheduler(self) -> None:
        if self.scheduler.paused:
            self.scheduler.resume()
        else:
            self.scheduler.pause()
            self.scheduled_pending.clear()
            if self.notice is not None:
                self.notice.cancel()
        self.pause_button.configure(text=self.s['scheduler_resume' if self.scheduler.paused else 'scheduler_pause'])
        self.automation_status.configure(text=self.s['scheduler_paused' if self.scheduler.paused else 'scheduler_active'])
        self.tray.update(self.profiles, self.s, self.scheduler.paused)
        self.update_schedule_labels()

    def update_schedule_labels(self) -> None:
        for profile_id, widget in getattr(self, 'schedule_labels', {}).items():
            widget.configure(text=self.next_run_text(profile_id))

    def poll_automation(self) -> None:
        import time
        try:
            while True:
                command = self.tray.events.get_nowait()
                if command.operation == 'ready':
                    if self.minimize_requested:
                        self.minimize_requested = False
                        self.withdraw()
                elif command.operation == 'unavailable':
                    self.deiconify()
                    self.automation_status.configure(text=self.s['tray_unavailable'])
                elif command.operation == 'open':
                    self.deiconify()
                    self.lift()
                elif command.operation == 'pause':
                    self.toggle_scheduler()
                elif command.operation == 'quit':
                    self.quit_app()
                    if self._closing:
                        return
                elif command.operation == 'run':
                    profile = next((profile for profile in self.profiles if profile.id == command.profile_id), None)
                    if profile is not None:
                        self.start_run(profile)
        except Empty:
            pass
        try:
            while True:
                request = self.scheduler.events.get_nowait()
                key = (request.profile_id, request.scheduled_at, request.revision)
                if key not in self.scheduled_seen and self.scheduler.is_current(request):
                    self.scheduled_seen.append(key)
                    self.scheduled_pending.append(request)
        except Empty:
            pass
        if self.notice is not None:
            if not self.scheduler.is_current(self.notice.request):
                self.notice.cancel()
            elif classify_run(self.notice.request, self.scheduler.clock()) == 'expired':
                self.notice.cancel()
                self.automation_status.configure(text=self.s['scheduled_expired'])
        if self.notice is None and self.active_profile is None and not self.execution.busy and not self.execution.recovery_required and not self._quit_requested and not self._ending:
            self.offer_scheduled_run()
        if time.monotonic() - self._last_schedule_labels >= 1:
            self.update_schedule_labels()
            self._last_schedule_labels = time.monotonic()

    def offer_scheduled_run(self) -> None:
        while self.scheduled_pending:
            request = self.scheduled_pending[0]
            if not self.scheduler.is_current(request):
                self.scheduled_pending.popleft()
                continue
            classification = classify_run(request, self.scheduler.clock())
            if classification == 'future':
                return
            self.scheduled_pending.popleft()
            if classification == 'expired':
                self.automation_status.configure(text=self.s['scheduled_expired'])
                continue
            profile = next((profile for profile in self.profiles if profile.id == request.profile_id), None)
            if profile is None:
                continue
            def cancel():
                self.notice = None
            def run(r=request):
                self.notice = None
                if not self.scheduler.is_current(r):
                    return
                classification = classify_run(r, self.scheduler.clock())
                if classification == 'expired':
                    self.automation_status.configure(text=self.s['scheduled_expired'])
                    return
                if classification == 'future':
                    self.scheduled_pending.appendleft(r)
                    return
                current = next((p for p in self.profiles if p.id == r.profile_id), None)
                if current is not None:
                    if self.active_profile is not None or self.execution.busy:
                        self.scheduled_pending.appendleft(r)
                    else:
                        self.start_run(current)
            self.notice = ScheduledNotice(self, self.s, profile.name, run, cancel, missed=classification == 'missed')
            self.notice.request = request
            return

    def close(self) -> None:
        if self.tray.ready:
            self.withdraw()
        else:
            self.automation_status.configure(text=self.s['tray_unavailable'])
            self.deiconify()

    def quit_app(self) -> None:
        if self._quit_requested:
            return
        if self.active_profile is not None and not messagebox.askyesno(
                self.s['quit'], self.s['close_confirmation'], parent=self):
            return
        self._quit_requested = True
        self.speech.stop()
        self.voice_hotkey.stop()
        self._voice_ready = False
        self._voice_status_key = 'voice_disabled'
        self.voice_button.configure(state='disabled')
        self.voice_status.configure(text=self.text('voice_disabled'))
        self._system_error = None
        self.scheduler.pause()
        self.scheduled_pending.clear()
        if self.notice is not None:
            self.notice.cancel()
        self.deiconify()
        self.execution.request_close()
        self.update_session_ui()

    def destroy(self) -> None:
        self._closing = True
        self.speech.stop()
        self.voice_hotkey.stop()
        self.execution.cancel()
        if not self.execution.closed and not getattr(self, '_force_exit', False):
            self.execution.request_close()
        if hasattr(self, 'poll_id'):
            self.after_cancel(self.poll_id)
        if self.notice is not None:
            self.notice.destroy()
            self.notice = None
        self.scheduler.stop()
        self.tray.stop()
        super().destroy()
