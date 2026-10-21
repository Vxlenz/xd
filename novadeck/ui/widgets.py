"""Consistent controls with keyboard activation."""
import customtkinter as ctk

from . import theme


def button(parent, text: str, command, *, secondary: bool = False, **kwargs) -> ctk.CTkButton:
    control = ctk.CTkButton(parent, text=text, command=command,
                           fg_color=theme.SURFACE_ALT if secondary else theme.PRIMARY,
                           hover_color=theme.BORDER, text_color=theme.TEXT,
                           corner_radius=theme.BUTTON_RADIUS, **kwargs)
    # CTkButton draws into a Canvas; make that canvas participate in Tk focus traversal.
    control._canvas.configure(takefocus=1, highlightthickness=1,
                              highlightcolor=theme.ACCENT, highlightbackground=theme.BORDER)
    control._canvas.bind('<Return>', lambda event: control.invoke())
    control._canvas.bind('<space>', lambda event: control.invoke())
    return control


def label(parent, text: str, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=theme.TEXT, **kwargs)
