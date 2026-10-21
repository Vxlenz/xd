"""Explicit voice opt-in, microphone selection and first-use model preparation."""
from threading import Event

import customtkinter as ctk
from pydantic import ValidationError

from ..core.settings_store import VoiceOptions
from ..integrations.errors import IntegrationError
from ..voice.recognizer import microphones
from . import theme
from .widgets import button, label


class VoiceSettings(ctk.CTkFrame):
    def __init__(self, parent, strings, settings, tasks, service, on_change):
        super().__init__(parent, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS)
        self.s, self.settings, self.tasks, self.service, self.on_change = strings, settings, tasks, service, on_change
        self.cancel_download = Event()
        self.devices = {}
        self.selected_key = None
        label(self, strings['voice_settings_title'], font=('Segoe UI',20,'bold')).pack(anchor='w', padx=16, pady=12)
        label(self, strings['voice_privacy'], wraplength=580).pack(fill='x', padx=16)
        try:
            options = settings.load().voice
        except IntegrationError:
            options = VoiceOptions()
        self.enabled = ctk.BooleanVar(value=options.enabled)
        ctk.CTkSwitch(self, text=strings['voice_enable'], variable=self.enabled).pack(anchor='w', padx=16, pady=10)
        self.always = ctk.BooleanVar(value=options.always_listening)
        ctk.CTkSwitch(self, text=strings['voice_always'], variable=self.always).pack(anchor='w', padx=16, pady=8)
        label(self, strings['voice_language']).pack(anchor='w', padx=16)
        self.language = ctk.StringVar(value=strings['voice_spanish' if options.language=='es' else 'voice_english'])
        ctk.CTkOptionMenu(self, values=[strings['voice_spanish'], strings['voice_english']], variable=self.language).pack(fill='x', padx=16,pady=4)
        label(self, strings['voice_microphone']).pack(anchor='w', padx=16)
        self.selected_key = options.microphone
        self.microphone = ctk.StringVar(value=options.microphone or strings['voice_default_microphone'])
        self.mic_menu = ctk.CTkOptionMenu(self, values=[self.microphone.get()], variable=self.microphone)
        self.mic_menu.pack(fill='x', padx=16, pady=4)
        button(self, strings['voice_refresh_microphones'], self.load_microphones, secondary=True).pack(anchor='w', padx=16,pady=4)
        label(self, strings['voice_hotkey']).pack(anchor='w', padx=16)
        self.shortcut = ctk.CTkEntry(self)
        self.shortcut.insert(0, options.hotkey)
        self.shortcut.pack(fill='x', padx=16,pady=4)
        self.status = ctk.CTkLabel(self, text='', text_color=theme.ACCENT, wraplength=580)
        self.status.pack(fill='x',padx=16,pady=8)
        button(self,strings['voice_save'],self.save).pack(fill='x',padx=16,pady=4)
        button(self,strings['voice_download_models'],self.download_models,secondary=True).pack(fill='x',padx=16,pady=(4,12))

    def load_microphones(self) -> None:
        if not self.tasks.submit(self,'microphones',microphones):
            self.status.configure(text=self.s['voice_busy'])

    def download_models(self) -> None:
        if self.tasks.pending:
            self.status.configure(text=self.s['voice_busy'])
            return
        cancel = Event()
        self.cancel_download = cancel
        def prepare():
            for language in ('es','en'):
                self.service.models.ensure(language, cancel)
        if self.tasks.submit(self,'models',prepare):
            self.status.configure(text=self.s['voice_downloading'])
        else:
            self.status.configure(text=self.s['voice_busy'])

    def save(self) -> None:
        selected = self.microphone.get()
        key = None if selected==self.s['voice_default_microphone'] else self.devices.get(selected,self.selected_key)
        try:
            options = VoiceOptions(enabled=self.enabled.get(), always_listening=self.always.get(),
                                   language='es' if self.language.get()==self.s['voice_spanish'] else 'en',
                                   microphone=key, hotkey=self.shortcut.get())
        except ValidationError:
            self.status.configure(text=self.s['voice_invalid_settings'])
            return
        if not self.tasks.submit(self,'save_voice',lambda: self.settings.update(voice=options).voice):
            self.status.configure(text=self.s['voice_busy'])

    def handle_task_result(self,result):
        if result.error_key:
            self.status.configure(text=self.s.get(result.error_key,self.s['voice_failed']))
        elif result.operation=='microphones':
            self.devices = {device.key:device.key for device in result.value}
            values = [self.s['voice_default_microphone'], *self.devices]
            self.mic_menu.configure(values=values)
            if self.selected_key in self.devices:
                self.microphone.set(self.selected_key)
            elif self.selected_key is None:
                self.microphone.set(values[0])
            self.status.configure(text=self.s['voice_microphone_count'].format(count=len(result.value)))
        elif result.operation=='save_voice':
            self.on_change(result.value)
            self.status.configure(text=self.s['voice_saved'])
        else:
            self.status.configure(text=self.s['voice_models_ready'])

    def destroy(self):
        self.cancel_download.set()
        super().destroy()
