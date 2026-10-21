"""Transient visual feedback only. Heard text is never written to disk."""
import customtkinter as ctk

from ..ui import theme
from ..ui.widgets import label


class VoiceOverlay(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.configure(fg_color=theme.SURFACE)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.geometry(f'460x120+24+{max(0,self.winfo_screenheight()-200)}')
        self.heard = label(self, '', wraplength=420, anchor='w')
        self.heard.pack(fill='x', padx=18, pady=(16,4))
        self.result = ctk.CTkLabel(self, text='', text_color=theme.ACCENT, wraplength=420, anchor='w')
        self.result.pack(fill='x', padx=18)
        self.timer = None

    def show(self, heard: str, result: str) -> None:
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.heard.configure(text=heard[:180])
        self.result.configure(text=result)
        self.deiconify()
        self.lift()
        self.timer = self.after(5000, self.hide)

    def hide(self) -> None:
        self.timer = None
        self.heard.configure(text='')
        self.result.configure(text='')
        self.withdraw()

    def destroy(self) -> None:
        if self.timer is not None:
            self.after_cancel(self.timer)
        super().destroy()
