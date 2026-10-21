"""Visible, cancellable desktop toast, including while the main window is hidden."""
from collections.abc import Callable
import time

import customtkinter as ctk

from . import theme
from .widgets import button, label


class ScheduledNotice(ctk.CTkToplevel):
    def __init__(self, parent, strings: dict[str, str], name: str, on_run: Callable,
                 on_cancel: Callable, *, missed: bool = False, clock=time.monotonic):
        super().__init__(parent)
        self.s, self.name = strings, name
        self.on_run, self.on_cancel = on_run, on_cancel
        self.clock = clock
        self.deadline: float | None = None
        self.timer = None
        self.completed = False
        self.title(strings['scheduled_title'])
        self.configure(fg_color=theme.SURFACE)
        self.attributes('-topmost', True)
        self.resizable(False, False)
        width, height = 420, 190
        self.geometry(f'{width}x{height}+{max(0, self.winfo_screenwidth()-width-24)}+{max(0, self.winfo_screenheight()-height-72)}')
        # Do not make this transient: Windows may hide a transient whose owner is withdrawn.
        self.previous_grab = parent.grab_current()
        if self.previous_grab is not None:
            self.previous_grab.grab_release()
        self.message = label(self, '', wraplength=370)
        self.message.pack(fill='x', padx=20, pady=(24, 16))
        self.confirm = button(self, strings['run'], self.begin_countdown)
        self.cancel_button = button(self, strings['cancel'], self.cancel, secondary=True)
        self.cancel_button.pack(side='right', padx=20, pady=12)
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Escape>', lambda event: self.cancel())
        if missed:
            self.message.configure(text=strings['scheduled_missed'].format(name=name))
            self.confirm.pack(side='left', padx=20, pady=12)
        else:
            self.begin_countdown()
        self.lift()

    def begin_countdown(self) -> None:
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.confirm.pack_forget()
        self.last_tick = self.clock()
        self.deadline = self.last_tick + 5
        self.tick()

    def tick(self) -> None:
        self.timer = None
        now = self.clock()
        remaining = self.deadline - now
        if now - self.last_tick > 2:
            self.deadline = None
            self.message.configure(text=self.s['scheduled_missed'].format(name=self.name))
            self.confirm.pack(side='left', padx=20, pady=12)
            return
        self.last_tick = now
        if remaining <= 0:
            self.completed = True
            self.destroy()
            self.on_run()
            return
        self.message.configure(text=self.s['scheduled_countdown'].format(name=self.name, seconds=max(1, int(remaining + .999))))
        self.timer = self.after(100, self.tick)

    def cancel(self) -> None:
        self.completed = True
        self.destroy()
        self.on_cancel()

    def destroy(self) -> None:
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        super().destroy()
        if self.previous_grab is not None and self.previous_grab.winfo_exists():
            self.previous_grab.grab_set()
