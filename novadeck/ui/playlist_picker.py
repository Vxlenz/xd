"""Search and select the user's own playlists; selection does not imply playback."""
from collections.abc import Callable
import unicodedata

import customtkinter as ctk

from ..core.background import Background, TaskResult
from ..integrations.spotify_client import Playlist, SpotifyClient
from . import theme
from .widgets import button, label


def filter_playlists(playlists: list[Playlist], query: str) -> list[Playlist]:
    def normalize(text):
        return ''.join(char for char in unicodedata.normalize('NFKD', text.casefold())
                       if not unicodedata.combining(char))
    query = normalize(query.strip())
    return [item for item in playlists if query in normalize(item.name)]


class PlaylistPicker(ctk.CTkToplevel):
    def __init__(self, parent, strings: dict[str, str], spotify: SpotifyClient,
                 tasks: Background, on_pick: Callable[[Playlist], None]):
        super().__init__(parent)
        self.s, self.spotify, self.tasks, self.on_pick = strings, spotify, tasks, on_pick
        self.items: list[Playlist] = []
        self.title(strings['spotify_playlists'])
        self.geometry('600x560')
        self.configure(fg_color=theme.BACKGROUND)
        self.transient(parent)
        self.query = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.query, placeholder_text=strings['spotify_search']).pack(fill='x', padx=24, pady=20)
        self.query.trace_add('write', lambda *args: self.render_items())
        self.status = label(self, strings['spotify_loading'], wraplength=540)
        self.status.pack(fill='x', padx=24)
        self.rows = ctk.CTkScrollableFrame(self, fg_color=theme.SURFACE)
        self.rows.pack(fill='both', expand=True, padx=24, pady=12)
        button(self, strings['spotify_reload'], self.load, secondary=True).pack(pady=(0, 16))
        self.load()
        self.bind('<Escape>', lambda event: self.destroy())

    def load(self) -> None:
        if not self.tasks.submit(self, 'playlists', self.spotify.playlists):
            self.status.configure(text=self.s['spotify_busy'])
        else:
            self.status.configure(text=self.s['spotify_loading'])

    def handle_task_result(self, result: TaskResult) -> None:
        if result.error_key:
            self.status.configure(text=self.s.get(result.error_key, self.s['spotify_api_failed']))
            return
        self.items = result.value
        self.render_items()

    def render_items(self) -> None:
        for widget in self.rows.winfo_children():
            widget.destroy()
        visible = filter_playlists(self.items, self.query.get())
        self.status.configure(text=self.s['spotify_playlist_count'].format(count=len(visible)))
        for item in visible:
            button(self.rows, item.name, lambda value=item: self.select(value), secondary=True,
                   anchor='w').pack(fill='x', padx=8, pady=4)

    def select(self, item: Playlist) -> None:
        self.on_pick(item)
        self.destroy()
