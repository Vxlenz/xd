"""Multiple weekly schedules and a login trigger; manual execution is always available."""
import customtkinter as ctk

from ..core.models import Trigger
from . import theme
from .widgets import button, label


class TriggerEditor(ctk.CTkFrame):
    def __init__(self, parent, strings: dict[str, str], triggers: list[Trigger]):
        super().__init__(parent, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS)
        self.s = strings
        self.rows: list[dict] = []
        heading = ctk.CTkFrame(self, fg_color='transparent')
        heading.pack(fill='x', padx=12, pady=6)
        self.login = ctk.BooleanVar(value=any(trigger.type == 'login' for trigger in triggers))
        ctk.CTkCheckBox(heading, text=strings['trigger_login'], variable=self.login).pack(side='left')
        button(heading, strings['schedule_add'], self.add_schedule, secondary=True, width=130).pack(side='right')
        label(self, strings['schedule_hint'], wraplength=780, anchor='w').pack(fill='x', padx=12)
        self.schedules = ctk.CTkScrollableFrame(self, height=95, fg_color=theme.SURFACE)
        self.schedules.pack(fill='x', padx=6, pady=6)
        for trigger in triggers:
            if trigger.type == 'schedule':
                self.add_schedule(trigger)

    def add_schedule(self, trigger: Trigger | None = None) -> None:
        row = ctk.CTkFrame(self.schedules, fg_color=theme.SURFACE_ALT)
        row.pack(fill='x', pady=3)
        entry = ctk.CTkEntry(row, width=65, placeholder_text=self.s['schedule_time'])
        entry.insert(0, trigger.time if trigger is not None else '09:00')
        entry.pack(side='left', padx=6, pady=8)
        days = []
        for index in range(7):
            selected = ctk.BooleanVar(value=trigger is not None and index in trigger.weekdays)
            ctk.CTkCheckBox(row, text=self.s[f'weekday_{index}'], variable=selected, width=58,
                            checkbox_width=18, checkbox_height=18).pack(side='left', padx=2)
            days.append(selected)
        record = {'frame': row, 'time': entry, 'days': days}
        button(row, self.s['remove'], lambda: self.remove_schedule(record), secondary=True, width=65).pack(side='right', padx=4)
        self.rows.append(record)

    def remove_schedule(self, row: dict) -> None:
        self.rows.remove(row)
        row['frame'].destroy()

    def get_triggers(self) -> list[Trigger]:
        triggers = [Trigger(type='login')] if self.login.get() else []
        for row in self.rows:
            triggers.append(Trigger(type='schedule', time=row['time'].get().strip(),
                                    weekdays=[index for index, value in enumerate(row['days']) if value.get()]))
        return triggers or [Trigger()]
