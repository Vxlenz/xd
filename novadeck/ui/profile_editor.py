"""Modal profile editor. All mutations stay local until the user saves."""
from collections.abc import Callable
from tkinter import filedialog, messagebox

import customtkinter as ctk
from pydantic import ValidationError

from ..core.models import Profile, ProfileAction
from . import theme
from .editor_state import action_from_fields, move_action
from .widgets import button, label
from .trigger_editor import TriggerEditor


class ActionDialog(ctk.CTkToplevel):
    def __init__(self, parent, strings: dict[str, str], save: Callable[[ProfileAction], None],
                 action: ProfileAction | None = None, open_picker=None):
        super().__init__(parent)
        self.open_picker = open_picker
        self.parent_dialog = parent
        self.s = strings
        self.save_callback = save
        self.action = action
        self.title(strings['action_editor'])
        self.geometry('580x650')
        self.configure(fg_color=theme.BACKGROUND)
        self.transient(parent)
        self.kinds = ['steam', 'launch', 'spotify', 'system']
        self.kind = ctk.StringVar(value=strings['type_' + (action.type if action else 'steam')])
        ctk.CTkOptionMenu(self, variable=self.kind, values=[strings['type_' + kind] for kind in self.kinds],
                          command=lambda value: self.render_fields()).pack(fill='x', padx=24, pady=16)
        self.form = ctk.CTkScrollableFrame(self, fg_color=theme.SURFACE)
        self.form.pack(fill='both', expand=True, padx=24)
        self.error = ctk.CTkLabel(
            self, text='', text_color=theme.DANGER, wraplength=500)
        self.error.pack(padx=24, pady=8)
        button(self, strings['save_action'], self.save).pack(padx=24, pady=(0, 20))
        self.render_fields()
        self.bind('<Escape>', lambda event: self.destroy())
        self.after(50, self.grab_set)

    def destroy(self) -> None:
        super().destroy()
        if self.parent_dialog.winfo_exists():
            self.parent_dialog.grab_set()

    def selected_kind(self) -> str:
        return self.kinds[[self.s['type_' + kind] for kind in self.kinds].index(self.kind.get())]

    def render_fields(self) -> None:
        for widget in self.form.winfo_children():
            widget.destroy()
        self.inputs: dict[str, ctk.CTkEntry | ctk.CTkTextbox | ctk.StringVar] = {}
        kind = self.selected_kind()
        values = self.action.model_dump() if self.action and self.action.type == kind else {}
        if kind == 'system':
            label(self.form, self.s['system_dnd_limit'], wraplength=440).pack(pady=8)
        fields = {'steam': ['display_name', 'app_id'], 'launch': ['target', 'arguments'],
                  'spotify': ['uri', 'volume', 'shuffle'],
                  'system': ['volume', 'do_not_disturb', 'restore_volume']}[kind] + ['delay_seconds']
        for field in fields:
            label(self.form, self.s['field_' + field], anchor='w').pack(fill='x', padx=12, pady=(10, 2))
            value = values.get(field, 0 if field == 'delay_seconds' else None)
            if field in ('shuffle', 'do_not_disturb', 'restore_volume'):
                options = [self.s['unchanged'], self.s['yes'], self.s['no']]
                if field == 'restore_volume':
                    options = options[1:]
                    value = values.get(field, True)
                variable = ctk.StringVar(value=self.s['unchanged'] if value is None else self.s['yes' if value else 'no'])
                ctk.CTkOptionMenu(self.form, variable=variable, values=options).pack(fill='x', padx=12)
                self.inputs[field] = variable
            elif field == 'arguments':
                widget = ctk.CTkTextbox(self.form, height=90)
                widget.insert('1.0', '\n'.join(value or []))
                widget.pack(fill='x', padx=12)
                self.inputs[field] = widget
            else:
                entry = ctk.CTkEntry(self.form)
                entry.insert(0, '' if value is None else str(value))
                entry.pack(fill='x', padx=12)
                self.inputs[field] = entry
                if field == 'uri' and self.open_picker is not None:
                    button(self.form, self.s['spotify_choose_playlist'], self.pick_playlist, secondary=True).pack(
                        anchor='e', padx=12, pady=4)
                if field == 'target':
                    button(self.form, self.s['browse'], self.browse, secondary=True).pack(anchor='e', padx=12, pady=4)

    def pick_playlist(self) -> None:
        def selected(item):
            self.inputs['uri'].delete(0, 'end')
            self.inputs['uri'].insert(0, item.uri)
        self.open_picker(self, selected)

    def browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[(self.s['executable_files'], '*.exe')])
        if path:
            entry = self.inputs['target']
            entry.delete(0, 'end')
            entry.insert(0, path)

    def save(self) -> None:
        fields = {}
        for name, widget in self.inputs.items():
            if isinstance(widget, ctk.CTkTextbox):
                value = widget.get('1.0', 'end-1c')
            else:
                value = widget.get()
            if isinstance(widget, ctk.StringVar):
                value = {self.s['unchanged']: '', self.s['yes']: 'true', self.s['no']: 'false'}[value]
            fields[name] = value
        try:
            action = action_from_fields(self.selected_kind(), fields, self.action.id if self.action else None)
        except (ValueError, KeyError, ValidationError):
            self.error.configure(text=self.s['invalid_action'])
            return
        self.save_callback(action)
        self.destroy()


class ProfileEditor(ctk.CTkToplevel):
    def __init__(self, parent, strings: dict[str, str], profile: Profile,
                 on_save: Callable[[Profile], bool], on_test: Callable[[ProfileAction], bool], open_picker=None):
        super().__init__(parent)
        self.s = strings
        self.draft = profile.model_copy(deep=True)
        self.open_picker = open_picker
        self.on_save = on_save
        self.on_test = on_test
        self.title(strings['profile_editor'])
        self.geometry('900x720')
        self.minsize(760, 600)
        self.configure(fg_color=theme.BACKGROUND)
        self.transient(parent)
        self.fields = {}
        top = ctk.CTkFrame(self, fg_color=theme.SURFACE)
        top.pack(fill='x', padx=24, pady=16)
        for column, field in enumerate(['name', 'icon', 'color']):
            top.grid_columnconfigure(column, weight=3 if field == 'name' else 1)
            label(top, strings['field_' + field]).grid(row=0, column=column, sticky='w', padx=12)
            entry = ctk.CTkEntry(top, width=100)
            entry.insert(0, getattr(profile, field))
            entry.grid(row=1, column=column, sticky='ew', padx=12, pady=(0, 12))
            self.fields[field] = entry
        self.trigger_editor = TriggerEditor(self, strings, profile.triggers)
        self.trigger_editor.pack(fill='x', padx=24, pady=(0, 8))
        label(self, strings['reorder_hint']).pack(anchor='w', padx=24)
        self.rows_frame = ctk.CTkScrollableFrame(self, fg_color=theme.BACKGROUND)
        self.rows_frame.pack(fill='both', expand=True, padx=16, pady=8)
        self.test_status = ctk.CTkLabel(self, text='', text_color=theme.ACCENT, wraplength=820)
        self.test_status.pack(fill='x', padx=24)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.pack(fill='x', padx=24, pady=16)
        button(footer, strings['add_action'], self.add_action).pack(side='left')
        button(footer, strings['save_profile'], self.save).pack(side='right')
        button(footer, strings['cancel'], self.destroy, secondary=True).pack(side='right', padx=8)
        self.error = ctk.CTkLabel(self, text='', text_color=theme.DANGER)
        self.error.pack(fill='x', padx=24, pady=(0, 8))
        self.drag_source: int | None = None
        self.render_actions()
        self.bind('<Escape>', lambda event: self.destroy())
        self.after(50, self.grab_set)
        self.fields['name'].focus_set()

    def render_actions(self) -> None:
        for widget in self.rows_frame.winfo_children():
            widget.destroy()
        self.rows = []
        for index, action in enumerate(self.draft.actions):
            row = ctk.CTkFrame(self.rows_frame, fg_color=theme.SURFACE, corner_radius=theme.CARD_RADIUS)
            row.pack(fill='x', pady=5)
            self.rows.append(row)
            handle = label(row, self.s['drag_handle'], width=25, cursor='hand2')
            handle.pack(side='left', padx=6)
            handle.bind('<ButtonPress-1>', lambda event, i=index: self.begin_drag(i))
            handle.bind('<ButtonRelease-1>', self.end_drag)
            title = self.s['type_' + action.type]
            if action.type == 'steam':
                title += ' · ' + action.display_name
            label(row, f'{index + 1}. {title}', anchor='w', width=160, wraplength=160).pack(side='left', padx=6)
            for text, command in [
                (self.s['move_up'], lambda i=index: self.move(i, i - 1)),
                (self.s['move_down'], lambda i=index: self.move(i, i + 1)),
                (self.s['edit'], lambda i=index: self.edit_action(i)),
                (self.s['test_action'], lambda i=index: self.test_action(i)),
                (self.s['remove'], lambda i=index: self.remove_action(i)),
            ]:
                button(row, text, command, secondary=True, width=64).pack(side='left', padx=3, pady=12)
        if not self.draft.actions:
            label(self.rows_frame, self.s['empty_actions']).pack(pady=24)

    def begin_drag(self, index: int) -> None:
        self.drag_source = index

    def end_drag(self, event) -> None:
        if self.drag_source is not None and self.rows:
            nearest = min(range(len(self.rows)), key=lambda i: abs(
                self.rows[i].winfo_rooty() + self.rows[i].winfo_height() / 2 - event.y_root))
            self.move(self.drag_source, nearest)
        self.drag_source = None

    def move(self, source: int, destination: int) -> None:
        if 0 <= destination < len(self.draft.actions):
            move_action(self.draft, source, destination)
            self.render_actions()

    def add_action(self) -> None:
        def append(action):
            self.draft.actions.append(action)
            self.render_actions()
        ActionDialog(self, self.s, append, open_picker=self.open_picker)

    def edit_action(self, index: int) -> None:
        def replace(action):
            self.draft.actions[index] = action
            self.render_actions()
        ActionDialog(self, self.s, replace, self.draft.actions[index], self.open_picker)

    def remove_action(self, index: int) -> None:
        self.draft.actions.pop(index)
        self.render_actions()

    def test_action(self, index: int) -> None:
        action = self.draft.actions[index].model_copy(deep=True)
        # Testing is immediate; the saved configured delay is unchanged.
        action.delay_seconds = 0.0
        if messagebox.askyesno(self.s['test_action'], self.s['test_confirmation'], parent=self):
            if self.on_test(action):
                self.test_status.configure(text=self.s['test_running'])
            else:
                self.test_status.configure(text=self.s['test_not_started'])

    def save(self) -> None:
        try:
            triggers = self.trigger_editor.get_triggers()
        except ValidationError:
            self.error.configure(text=self.s['invalid_schedule'])
            return
        try:
            data = self.draft.model_dump()
            data['triggers'] = triggers
            data.update({name: entry.get() for name, entry in self.fields.items()})
            profile = Profile.model_validate(data)
        except ValidationError:
            self.error.configure(text=self.s['invalid_profile'])
            return
        if self.on_save(profile):
            self.destroy()
