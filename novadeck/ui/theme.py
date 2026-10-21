"""Shared NovaDeck visual tokens."""
BACKGROUND = "#0B0F1A"
SURFACE = "#141B2D"
SURFACE_ALT = "#1C2540"
BORDER = "#26304F"
PRIMARY = "#7C5CFF"
ACCENT = "#22D3EE"
SUCCESS = "#34D399"
WARNING = "#FBBF24"
DANGER = "#F43F5E"
TEXT = "#E6EAF5"
TEXT_MUTED = "#8B95B3"
CARD_RADIUS = 12
BUTTON_RADIUS = 8


def apply() -> None:
    """Use the same palette for native CTk inputs and the shared button helpers."""
    import customtkinter as ctk

    overrides = {
        'CTk': {'fg_color': BACKGROUND},
        'CTkToplevel': {'fg_color': BACKGROUND},
        'CTkFrame': {'fg_color': SURFACE, 'top_fg_color': SURFACE_ALT,
                     'border_color': BORDER, 'corner_radius': CARD_RADIUS},
        'CTkButton': {'fg_color': PRIMARY, 'hover_color': BORDER, 'border_color': BORDER,
                      'text_color': TEXT, 'text_color_disabled': TEXT_MUTED, 'corner_radius': BUTTON_RADIUS},
        'CTkLabel': {'text_color': TEXT},
        'CTkEntry': {'fg_color': SURFACE_ALT, 'border_color': BORDER, 'text_color': TEXT,
                     'placeholder_text_color': TEXT_MUTED, 'corner_radius': BUTTON_RADIUS},
        'CTkTextbox': {'fg_color': SURFACE_ALT, 'border_color': BORDER, 'text_color': TEXT,
                       'scrollbar_button_color': BORDER, 'scrollbar_button_hover_color': PRIMARY},
        'CTkOptionMenu': {'fg_color': SURFACE_ALT, 'button_color': PRIMARY, 'button_hover_color': BORDER,
                          'text_color': TEXT, 'text_color_disabled': TEXT_MUTED, 'corner_radius': BUTTON_RADIUS},
        'DropdownMenu': {'fg_color': SURFACE_ALT, 'hover_color': BORDER, 'text_color': TEXT},
        'CTkCheckBox': {'fg_color': PRIMARY, 'border_color': BORDER, 'hover_color': PRIMARY,
                        'checkmark_color': TEXT, 'text_color': TEXT, 'text_color_disabled': TEXT_MUTED},
        'CTkSwitch': {'fg_color': BORDER, 'progress_color': PRIMARY, 'button_color': TEXT,
                      'button_hover_color': ACCENT, 'text_color': TEXT, 'text_color_disabled': TEXT_MUTED},
        'CTkSlider': {'fg_color': BORDER, 'progress_color': PRIMARY,
                      'button_color': ACCENT, 'button_hover_color': TEXT},
        'CTkScrollbar': {'button_color': BORDER, 'button_hover_color': PRIMARY},
        'CTkFont': {'family': 'Segoe UI', 'size': 13},
    }
    for name, values in overrides.items():
        ctk.ThemeManager.theme[name].update(values)
