"""Compact player; network work is delegated to the shared background worker."""
import customtkinter as ctk

from ..core.background import Background, TaskResult
from ..integrations.spotify_client import Playback, SpotifyClient
from . import theme
from .widgets import button, label


class MiniPlayer(ctk.CTkFrame):
    def __init__(self, parent, strings: dict[str, str], spotify: SpotifyClient, tasks: Background, open_picker):
        super().__init__(parent, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS)
        self.s, self.spotify, self.tasks = strings, spotify, tasks
        self.current = Playback()
        self.volume_timer = None
        self.track = label(self, strings['spotify_idle'], anchor='w', wraplength=850)
        self.track.pack(fill='x', padx=16, pady=(10, 4))
        controls = ctk.CTkFrame(self, fg_color='transparent')
        controls.pack(fill='x', padx=12, pady=4)
        for text, command in [(strings['spotify_previous'], lambda: self.control('previous')),
                              (strings['spotify_toggle'], lambda: self.control('toggle')),
                              (strings['spotify_next'], lambda: self.control('next')),
                              (strings['spotify_playlists'], open_picker),
                              (strings['spotify_refresh'], self.refresh)]:
            button(controls, text, command, secondary=True, width=140 if text == strings['spotify_toggle'] else 86).pack(side='left', padx=3)
        label(controls, strings['field_volume_short']).pack(side='left', padx=(12, 4))
        self.volume = ctk.CTkSlider(controls, from_=0, to=100, number_of_steps=100,
                                    width=130, command=self.volume_changed, progress_color=theme.PRIMARY)
        self.volume.set(50)
        self.volume.pack(side='left', padx=4)
        self.status = ctk.CTkLabel(self, text='', text_color=theme.TEXT_MUTED, wraplength=900, anchor='w')
        self.status.pack(fill='x', padx=16, pady=(0, 8))
        self.refresh_timer = self.after(5000, self.auto_refresh)

    def refresh(self) -> None:
        self.tasks.submit(self, 'playback', self.spotify.playback)

    def auto_refresh(self) -> None:
        self.refresh()
        self.refresh_timer = self.after(5000, self.auto_refresh)

    def control(self, operation: str) -> None:
        if not self.tasks.submit(self, 'control', lambda: self.spotify.control(operation)):
            self.status.configure(text=self.s['spotify_busy'])

    def volume_changed(self, value: float) -> None:
        if self.volume_timer is not None:
            self.after_cancel(self.volume_timer)
        volume = round(value)
        self.volume_timer = self.after(400, lambda: self.set_volume(volume))

    def set_volume(self, volume: int) -> None:
        self.volume_timer = None
        if not self.tasks.submit(self, 'volume', lambda: self.spotify.control('volume', volume)):
            self.status.configure(text=self.s['spotify_busy'])

    def handle_task_result(self, result: TaskResult) -> None:
        if result.error_key:
            self.status.configure(text=self.s.get(result.error_key, self.s['spotify_api_failed']))
        elif result.operation == 'playback':
            self.current = result.value
            self.track.configure(text=(self.s['spotify_track'].format(name=self.current.name, artists=self.current.artists)
                                       if self.current.name else self.s['spotify_no_track']))
            self.status.configure(text=self.s['spotify_playing' if self.current.playing else 'spotify_paused'])
            # Do not overwrite a volume adjustment still being dragged/debounced.
            if self.current.volume is not None and self.volume_timer is None:
                self.volume.set(self.current.volume)
        else:
            self.status.configure(text=self.s['spotify_control_sent'])
            self.refresh()

    def destroy(self) -> None:
        self.after_cancel(self.refresh_timer)
        if self.volume_timer is not None:
            self.after_cancel(self.volume_timer)
        super().destroy()
