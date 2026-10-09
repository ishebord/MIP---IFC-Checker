# ui_main.py
from __future__ import annotations
import os
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
import traceback
import sys
import subprocess

from ifc_ids_validator.config import (
    AppConfig, DisciplineRule, Profile, CONF_PATH
)
from ifc_ids_validator.validator import (
    MATCH_CONTAINS,
    match_rule, open_ids, open_ifc, emit_reports, get_ifc_site_data,
    get_ifc_elements_count, get_ifc_storey_names,
    _ifc_class_percent_from_html
)
from ifc_ids_validator.summary import write_summary, summary_path, record_check_history, ids_fingerprint

APP_TITLE = "IFC → IDS — проверка моделей проекта"
DEFAULT_REPORT_SUBFOLDER = "Отчет IDS"
SUB_COMMON = "Общие"
SUB_DISC = "Дисциплинарные"

# =========================
# ФИРМЕННЫЕ ЦВЕТА / ТЕМА
# =========================
COLOR_BG = "#F3F5F9"
COLOR_SURFACE = "#FFFFFF"
COLOR_SURFACE_2 = "#EDF2F9"
COLOR_BORDER = "#DFE5EE"
COLOR_TEXT = "#172A43"
COLOR_MUTED = "#738197"
COLOR_BLUE = "#3268E8"       # основной синий
COLOR_BLUE_DARK = "#14243C"  # тёмный синий
COLOR_RED = "#C94B59"        # акцентный красный
COLOR_HOVER = "#2455CC"
COLOR_SUCCESS = "#1F8A4D"

FONT_MAIN = ("Segoe UI", 10)
FONT_MAIN_BOLD = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 18)
FONT_SUBTITLE = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)


class RuleDialog(tk.Toplevel):
    def __init__(self, master, title="Правило дисциплины", initial: DisciplineRule | None = None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.configure(bg=COLOR_BG)

        self.var_pattern = tk.StringVar(value=(initial.pattern if initial else ""))
        self.var_ids = tk.StringVar(value=(initial.ids_path if initial else ""))
        self.var_mapping = tk.StringVar(value=(initial.mapping_path if initial else ""))

        outer = tk.Frame(self, bg=COLOR_BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        card = tk.Frame(
            outer,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0
        )
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=COLOR_BLUE, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text=title,
            bg=COLOR_BLUE,
            fg="white",
            font=("Segoe UI Semibold", 11)
        ).pack(side="left", padx=14)

        frm = tk.Frame(card, padx=16, pady=16, bg=COLOR_SURFACE)
        frm.pack(fill="both", expand=True)

        frm.grid_columnconfigure(0, weight=0, minsize=230)
        frm.grid_columnconfigure(1, weight=1, minsize=420)
        frm.grid_columnconfigure(2, weight=0)

        ttk.Label(
            frm,
            text="Паттерн в имени файла:",
            style="CardLabel.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

        ttk.Entry(
            frm,
            textvariable=self.var_pattern,
            width=60
        ).grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(
            frm,
            text="IDS-файл дисциплины:",
            style="CardLabel.TLabel"
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        ttk.Entry(
            frm,
            textvariable=self.var_ids
        ).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Button(
            frm,
            text="Выбрать…",
            command=self._pick_ids,
            style="Secondary.TButton"
        ).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        ttk.Label(
            frm,
            text="Файл сопоставления параметров:",
            style="CardLabel.TLabel"
        ).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)

        ttk.Entry(
            frm,
            textvariable=self.var_mapping
        ).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Button(
            frm,
            text="Выбрать…",
            command=self._pick_mapping,
            style="Secondary.TButton"
        ).grid(row=2, column=2, sticky="w", padx=(8, 0), pady=4)

        btns = tk.Frame(frm, bg=COLOR_SURFACE)
        btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))

        ttk.Button(
            btns,
            text="Отмена",
            width=14,
            command=self.destroy,
            style="Secondary.TButton"
        ).pack(side="right")

        ttk.Button(
            btns,
            text="OK",
            width=14,
            command=self._on_ok,
            style="Primary.TButton"
        ).pack(side="right", padx=(0, 8))

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _pick_ids(self):
        current = self.var_ids.get().strip()
        initial_dir = str(Path(current).parent) if current else str(Path.home())

        path = filedialog.askopenfilename(
            title="Выберите IDS спецификацию дисциплины",
            filetypes=[("IDS files", "*.ids;*.xml"), ("All files", "*.*")],
            initialdir=initial_dir
        )

        if path:
            self.var_ids.set(path)

    def _pick_mapping(self):
        current = self.var_mapping.get().strip()
        initial_dir = str(Path(current).parent) if current else str(Path.home())

        path = filedialog.askopenfilename(
            title="Выберите файл сопоставления параметров",
            filetypes=[
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
            initialdir=initial_dir
        )

        if path:
            self.var_mapping.set(path)

    def _on_ok(self):
        patt = self.var_pattern.get().strip()
        ids_path = self.var_ids.get().strip()
        mapping_path = self.var_mapping.get().strip()

        if not patt or not ids_path:
            messagebox.showwarning(
                "Не заполнено",
                "Укажите паттерн и IDS-файл.",
                parent=self
            )
            return

        self.result = {
            "pattern": patt,
            "ids_path": ids_path,
            "mapping_path": mapping_path,
        }

        self.destroy()


class SectionsDescriptionDialog(tk.Toplevel):
    def __init__(self, master, rows):
        super().__init__(master)
        self.title("Описание разделов")
        self.geometry("780x620")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)

        self.result = False
        self.rows_vars = []
        self.rows_widgets = []
        self.current_row_index = None

        self.initial_rows = [
            [str(row[0]), str(row[1])]
            for row in rows
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        if not self.initial_rows:
            self.initial_rows = [["", ""]]

        outer = tk.Frame(self, bg=COLOR_BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        card = tk.Frame(
            outer,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=COLOR_BLUE, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="Описание разделов",
            bg=COLOR_BLUE,
            fg="white",
            font=("Segoe UI Semibold", 12)
        ).pack(side="left", padx=16)

        body = tk.Frame(card, bg=COLOR_SURFACE, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Область таблицы со скроллом
        table_outer = tk.Frame(body, bg=COLOR_SURFACE)
        table_outer.grid(row=0, column=0, sticky="nsew")
        table_outer.grid_rowconfigure(1, weight=1)
        table_outer.grid_columnconfigure(0, weight=1)

        # Заголовки
        header_row = tk.Frame(table_outer, bg=COLOR_SURFACE)
        header_row.grid(row=0, column=0, sticky="ew")
        header_row.grid_columnconfigure(0, weight=0)
        header_row.grid_columnconfigure(1, weight=1)

        tk.Label(
            header_row,
            text="Код",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT,
            font=("Segoe UI Semibold", 10),
            bd=1,
            relief="solid",
            padx=8,
            pady=8,
            width=18
        ).grid(row=0, column=0, sticky="nsew")

        tk.Label(
            header_row,
            text="Описание",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT,
            font=("Segoe UI Semibold", 10),
            bd=1,
            relief="solid",
            padx=8,
            pady=8
        ).grid(row=0, column=1, sticky="nsew")

        # Canvas + scrollbar
        canvas_wrap = tk.Frame(table_outer, bg=COLOR_SURFACE)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.grid_rowconfigure(0, weight=1)
        canvas_wrap.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_wrap,
            bg=COLOR_SURFACE,
            highlightthickness=0,
            bd=0
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.canvas.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")

        self.canvas.configure(yscrollcommand=v_scroll.set)

        self.table_frame = tk.Frame(self.canvas, bg=COLOR_SURFACE)
        self.table_frame.grid_columnconfigure(0, weight=0)
        self.table_frame.grid_columnconfigure(1, weight=1)

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.table_frame,
            anchor="nw"
        )

        self.table_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Начальные строки
        for code, desc in self.initial_rows:
            self._append_row(code, desc)

        # Нижние кнопки
        bottom = tk.Frame(body, bg=COLOR_SURFACE)
        bottom.grid(row=1, column=0, sticky="ew", pady=(14, 0))

        info = tk.Label(
            bottom,
            text="Enter — новая строка   |   Delete — удалить строку",
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=FONT_SMALL
        )
        info.pack(side="left")

        right_btns = tk.Frame(bottom, bg=COLOR_SURFACE)
        right_btns.pack(side="right")

        ttk.Button(
            right_btns,
            text="Закрыть",
            width=16,
            command=self.destroy,
            style="Secondary.TButton"
        ).pack(side="right")

        ttk.Button(
            right_btns,
            text="Сохранить",
            width=16,
            command=self.on_save,
            style="Primary.TButton"
        ).pack(side="right", padx=(0, 8))

        self.bind_all("<Delete>", self._on_delete_key, add="+")
        self.bind_all("<Return>", self._on_enter_key, add="+")
        self.bind_all("<KP_Enter>", self._on_enter_key, add="+")

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _focus_row(self, row_index: int):
        self.current_row_index = row_index
        if 0 <= row_index < len(self.rows_widgets):
            code_entry, _ = self.rows_widgets[row_index]
            try:
                code_entry.focus_set()
            except Exception:
                pass

    def _bind_entry_events(self, entry: tk.Entry, row_index: int):
        entry.bind("<FocusIn>", lambda e, i=row_index: self._set_current_row(i))
        entry.bind("<Button-1>", lambda e, i=row_index: self._set_current_row(i))
        entry.bind("<MouseWheel>", self._on_mousewheel)
        entry.bind("<Button-4>", self._on_mousewheel)
        entry.bind("<Button-5>", self._on_mousewheel)

    def _set_current_row(self, row_index: int):
        self.current_row_index = row_index

    def _on_mousewheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        else:
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

    def _append_row(self, code="", desc=""):
        var_code = tk.StringVar(value=code)
        var_desc = tk.StringVar(value=desc)

        row_index = len(self.rows_vars)
        self.rows_vars.append((var_code, var_desc))

        ent_code = tk.Entry(
            self.table_frame,
            textvariable=var_code,
            font=FONT_MAIN,
            relief="solid",
            bd=1
        )
        ent_code.grid(row=row_index, column=0, sticky="nsew", ipady=6)

        ent_desc = tk.Entry(
            self.table_frame,
            textvariable=var_desc,
            font=FONT_MAIN,
            relief="solid",
            bd=1
        )
        ent_desc.grid(row=row_index, column=1, sticky="nsew", ipady=6)

        self.rows_widgets.append((ent_code, ent_desc))

        self._bind_entry_events(ent_code, row_index)
        self._bind_entry_events(ent_desc, row_index)

    def _rebuild_rows(self):
        for code_entry, desc_entry in self.rows_widgets:
            code_entry.destroy()
            desc_entry.destroy()

        old_data = [(v_code.get(), v_desc.get()) for v_code, v_desc in self.rows_vars]

        self.rows_vars = []
        self.rows_widgets = []

        for code, desc in old_data:
            self._append_row(code, desc)

        self._on_frame_configure()

    def _on_enter_key(self, event=None):
        widget = self.focus_get()
        if widget is None:
            return

        if not self._widget_belongs_to_table(widget):
            return

        insert_after = self.current_row_index if self.current_row_index is not None else len(self.rows_vars) - 1

        current_data = [(v_code.get(), v_desc.get()) for v_code, v_desc in self.rows_vars]
        current_data.insert(insert_after + 1, ("", ""))

        self.rows_vars = [(tk.StringVar(value=c), tk.StringVar(value=d)) for c, d in current_data]
        self._rebuild_rows()
        self.current_row_index = insert_after + 1
        self.after(10, lambda: self._focus_row(self.current_row_index))

        return "break"

    def _on_delete_key(self, event=None):
        widget = self.focus_get()
        if widget is None:
            return

        if not self._widget_belongs_to_table(widget):
            return

        if self.current_row_index is None:
            return

        if len(self.rows_vars) <= 1:
            self.rows_vars[0][0].set("")
            self.rows_vars[0][1].set("")
            return "break"

        current_data = [(v_code.get(), v_desc.get()) for v_code, v_desc in self.rows_vars]
        del current_data[self.current_row_index]

        self.rows_vars = [(tk.StringVar(value=c), tk.StringVar(value=d)) for c, d in current_data]
        next_index = min(self.current_row_index, len(current_data) - 1)

        self._rebuild_rows()
        self.current_row_index = next_index
        self.after(10, lambda: self._focus_row(self.current_row_index))

        return "break"

    def _widget_belongs_to_table(self, widget):
        parent = widget
        while parent is not None:
            if parent == self.table_frame:
                return True
            try:
                parent = parent.master
            except Exception:
                break
        return False

    def on_save(self):
        self.result = [
            [var_code.get().strip(), var_desc.get().strip()]
            for var_code, var_desc in self.rows_vars
        ]
        self.destroy()

    def destroy(self):
        try:
            self.unbind_all("<Delete>")
            self.unbind_all("<Return>")
            self.unbind_all("<KP_Enter>")
        except Exception:
            pass
        super().destroy()


class CopyIdsDialog(tk.Toplevel):
    def __init__(self, master, profiles, target_name):
        super().__init__(master)
        self.title("Копировать IDS из другого проекта")
        self.geometry("720x480")
        self.minsize(540, 380)
        self.configure(bg=COLOR_BG)
        self.result = None
        self.profiles = profiles
        sources = [name for name in profiles if name != target_name]
        self.source_var = tk.StringVar(value=sources[0] if sources else "")
        body = tk.Frame(self, bg=COLOR_SURFACE, padx=18, pady=18)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(body, text=f"Настройки IDS для проекта «{target_name}»",
                  style="SectionTitle.TLabel", wraplength=620).pack(anchor="w")
        ttk.Label(body, text="Из какого проекта скопировать:",
                  style="CardLabel.TLabel").pack(anchor="w", pady=(16, 6))
        selector = ttk.Combobox(body, textvariable=self.source_var,
                                values=sources, state="readonly")
        selector.pack(fill="x")
        selector.bind("<<ComboboxSelected>>", self.refresh_preview)
        table = tk.Frame(body, bg=COLOR_SURFACE)
        table.pack(fill="both", expand=True, pady=(12, 10))
        self.preview = tk.Text(table, height=9, wrap="word", font=FONT_MAIN,
                               bg=COLOR_SURFACE_2, fg=COLOR_TEXT, relief="flat",
                               padx=10, pady=10, state="disabled")
        self.preview.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.preview.yview)
        scrollbar.pack(side="right", fill="y")
        self.preview.configure(yscrollcommand=scrollbar.set)
        note = ttk.Label(body,
            text="Общая IDS, переключатель дисциплин и все правила с путями сопоставления заменят текущие настройки IDS. Файлы IFC и папка отчётов останутся прежними.",
            style="CardLabel.TLabel", wraplength=620)
        note.pack(fill="x", pady=(0, 14))
        body.bind("<Configure>", lambda event: note.configure(wraplength=max(240, event.width-36)))
        actions = tk.Frame(body, bg=COLOR_SURFACE)
        actions.pack(fill="x")
        ttk.Button(actions, text="Отмена", command=self.destroy,
                   style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Скопировать", command=self.on_copy,
                   style="Primary.TButton").pack(side="right", padx=8)
        self.bind("<Escape>", lambda event: self.destroy())
        self.refresh_preview()
        self.transient(master)
        self.grab_set()
        selector.focus_set()

    def refresh_preview(self, _event=None):
        source = self.profiles.get(self.source_var.get())
        lines = []
        if source is not None:
            lines = [
                "Общая IDS: " + (source.common_ids_path or "не задана"),
                "Дисциплинарные IDS: " + ("включены" if source.discipline_ids_enabled else "выключены"),
                f"Правил по паттернам: {len(source.disc_rules)}", "",
            ]
            for rule in source.disc_rules:
                lines.append(f"{rule.pattern} → {rule.ids_path or 'IDS не задана'}")
                if rule.mapping_path:
                    lines.append(f"  Сопоставление: {rule.mapping_path}")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "\n".join(lines))
        self.preview.configure(state="disabled")

    def on_copy(self):
        source = self.source_var.get()
        if source in self.profiles:
            self.result = source
            self.destroy()


class RulesSettingsDialog(tk.Toplevel):
    def __init__(self, master, profile: Profile):
        super().__init__(master)
        self.title(f"Дисциплинарные IDS — {profile.name}")
        self.geometry("980x540")
        self.minsize(760, 420)
        self.result = False
        self.profile = profile
        self.configure(bg=COLOR_BG)
        self.local_rules = deepcopy(profile.disc_rules)
        self.local_section_descriptions = deepcopy(profile.section_descriptions)
        body = tk.Frame(self, bg=COLOR_SURFACE, padx=18, pady=18)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(body, text=f"Правила проекта: {profile.name}",
                  style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(body,
                  text="Паттерн ищется в имени IFC без учёта регистра. Применяется первое совпавшее правило.",
                  style="CardLabel.TLabel", wraplength=890).pack(anchor="w", pady=(8, 14))
        table = tk.Frame(body, bg=COLOR_SURFACE)
        table.pack(fill="both", expand=True)
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.rules_list = tk.Listbox(table, font=FONT_MAIN, bg="white", fg=COLOR_TEXT,
            selectbackground=COLOR_BLUE, selectforeground="white", activestyle="none")
        self.rules_list.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(table, orient="vertical", command=self.rules_list.yview)
        sy.grid(row=0, column=1, sticky="ns")
        sx = ttk.Scrollbar(table, orient="horizontal", command=self.rules_list.xview)
        sx.grid(row=1, column=0, sticky="ew")
        self.rules_list.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        actions = tk.Frame(table, bg=COLOR_SURFACE)
        actions.grid(row=0, column=2, sticky="ns", padx=(12, 0))
        for label, command in (("Добавить…", self.on_rule_add),
                               ("Изменить…", self.on_rule_edit),
                               ("Удалить", self.on_rule_del),
                               ("Выше ↑", lambda: self.move_rule(-1)),
                               ("Ниже ↓", lambda: self.move_rule(1))):
            ttk.Button(actions, text=label, command=command,
                       style="Secondary.TButton").pack(fill="x", pady=(0, 8))
        self.rules_list.bind("<Double-Button-1>", lambda event: self.on_rule_edit())
        bottom = tk.Frame(body, bg=COLOR_SURFACE)
        bottom.pack(fill="x", pady=(14, 0))
        ttk.Button(bottom, text="Отмена", command=self.destroy,
                   style="Secondary.TButton").pack(side="right")
        ttk.Button(bottom, text="Сохранить", command=self.on_save,
                   style="Primary.TButton").pack(side="right", padx=8)
        self.refresh_rules()
        self.transient(master)
        self.grab_set()

    def move_rule(self, offset):
        selected = self.rules_list.curselection()
        if not selected:
            return
        index = selected[0]
        target = index + offset
        if 0 <= target < len(self.local_rules):
            self.local_rules[index], self.local_rules[target] = self.local_rules[target], self.local_rules[index]
            self.refresh_rules()
            self.rules_list.selection_set(target)
            self.rules_list.see(target)

    def refresh_rules(self):
        self.rules_list.delete(0, "end")

        for r in self.local_rules:
            mapping_name = Path(r.mapping_path).name if r.mapping_path else "без сопоставления"
            self.rules_list.insert(
                "end",
                f"{r.pattern}  |  IDS: {r.ids_path}  |  TXT: {mapping_name}"
            )

    def on_rule_add(self):
        dlg = RuleDialog(self, "Добавить правило дисциплины")
        self.wait_window(dlg)
        if dlg.result:
            self.local_rules.append(DisciplineRule(**dlg.result))
            self.refresh_rules()

    def on_rule_edit(self):
        sel = self.rules_list.curselection()
        if not sel:
            messagebox.showinfo("Нет выбора", "Выберите правило для редактирования.", parent=self)
            return
        i = sel[0]
        current = self.local_rules[i]
        dlg = RuleDialog(self, "Изменить правило дисциплины", initial=current)
        self.wait_window(dlg)
        if dlg.result:
            self.local_rules[i] = DisciplineRule(**dlg.result)
            self.refresh_rules()

    def on_rule_del(self):
        sel = self.rules_list.curselection()
        if not sel:
            return
        del self.local_rules[sel[0]]
        self.refresh_rules()

    def on_save(self):
        self.profile.disc_rules = [
            DisciplineRule(
                pattern=r.pattern,
                ids_path=r.ids_path,
                mapping_path=getattr(r, "mapping_path", "")
            )
            for r in self.local_rules
        ]

        self.profile.section_descriptions = [
            [str(row[0]), str(row[1])]
            for row in self.local_section_descriptions
            if len(row) >= 2
        ]

        self.result = True
        self.destroy()


class IfcRevitMappingDialog(tk.Toplevel):
    INITIAL_ROWS_COUNT = 20
    COLS_COUNT = 2

    def __init__(self, master, rows=None):
        super().__init__(master)
        self.title("Сопоставление наименований IFC ↔ Revit")
        self.geometry("920x720")
        self.minsize(760, 560)
        self.resizable(True, True)
        self.configure(bg=COLOR_BG)
        self.result = None

        source_rows = rows or []
        normalized_rows = []

        for row in source_rows:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                normalized_rows.append([str(row[0]), str(row[1])])

        while len(normalized_rows) < self.INITIAL_ROWS_COUNT:
            normalized_rows.append(["", ""])

        self.rows_vars: list[tuple[tk.StringVar, tk.StringVar]] = []
        self.rows_widgets: list[tuple[tk.Label, tk.Entry, tk.Entry]] = []
        self.current_row_index: int | None = None

        outer = tk.Frame(self, bg=COLOR_BG, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        card = tk.Frame(
            outer,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=COLOR_BLUE, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="Сопоставление наименований IFC ↔ Revit",
            bg=COLOR_BLUE,
            fg="white",
            font=("Segoe UI Semibold", 12)
        ).pack(side="left", padx=16)

        body = tk.Frame(card, bg=COLOR_SURFACE, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        info = tk.Label(
            body,
            text=(
                "Ctrl+V — вставка диапазона из Excel / Google Таблиц. "
                "Enter — добавить строку после текущей. Delete — удалить текущую строку. "
                "Расширения .ifc и .rvt при сопоставлении игнорируются."
            ),
            bg=COLOR_SURFACE,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
            justify="left",
            anchor="w",
            wraplength=840
        )
        info.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # Таблица. Заголовок и тело используют одну и ту же геометрию:
        # фиксированная колонка номера + две одинаковые по ширине колонки.
        # Благодаря этому границы заголовка и строк совпадают пиксель в пиксель.
        table_wrap = tk.Frame(body, bg=COLOR_SURFACE)
        table_wrap.grid(row=1, column=0, rowspan=2, sticky="nsew")
        table_wrap.grid_rowconfigure(1, weight=1)
        table_wrap.grid_columnconfigure(0, weight=0, minsize=46)
        table_wrap.grid_columnconfigure(1, weight=1, uniform="mapping_cols")
        table_wrap.grid_columnconfigure(2, weight=1, uniform="mapping_cols")
        table_wrap.grid_columnconfigure(3, weight=0)

        tk.Label(
            table_wrap,
            text="№",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT,
            font=("Segoe UI Semibold", 10),
            bd=1,
            relief="solid",
            padx=4,
            pady=7
        ).grid(row=0, column=0, sticky="nsew")

        tk.Label(
            table_wrap,
            text="Наименование IFC",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT,
            font=("Segoe UI Semibold", 10),
            bd=1,
            relief="solid",
            padx=8,
            pady=7
        ).grid(row=0, column=1, sticky="nsew")

        tk.Label(
            table_wrap,
            text="Наименование Revit",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT,
            font=("Segoe UI Semibold", 10),
            bd=1,
            relief="solid",
            padx=8,
            pady=7
        ).grid(row=0, column=2, sticky="nsew")

        # Пустой элемент над вертикальным scrollbar, чтобы заголовок
        # заканчивался ровно там же, где и тело таблицы.
        tk.Frame(
            table_wrap,
            bg=COLOR_SURFACE_2,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        ).grid(row=0, column=3, sticky="nsew")

        self.canvas = tk.Canvas(
            table_wrap,
            bg=COLOR_SURFACE,
            highlightthickness=0,
            bd=0
        )
        self.canvas.grid(row=1, column=0, columnspan=3, sticky="nsew")

        self.v_scroll = ttk.Scrollbar(
            table_wrap,
            orient="vertical",
            command=self.canvas.yview
        )
        self.v_scroll.grid(row=1, column=3, sticky="ns")

        self.canvas.configure(yscrollcommand=self.v_scroll.set)

        self.table_frame = tk.Frame(self.canvas, bg=COLOR_SURFACE)
        self.table_frame.grid_columnconfigure(0, weight=0, minsize=46)
        self.table_frame.grid_columnconfigure(1, weight=1, uniform="mapping_cols")
        self.table_frame.grid_columnconfigure(2, weight=1, uniform="mapping_cols")

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.table_frame,
            anchor="nw"
        )

        self.table_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)

        for ifc_name, revit_name in normalized_rows:
            self._append_row(ifc_name, revit_name)

        bottom = tk.Frame(body, bg=COLOR_SURFACE)
        bottom.grid(row=3, column=0, sticky="ew", pady=(14, 0))

        ttk.Button(
            bottom,
            text="Очистить таблицу",
            command=self._clear_table,
            style="Secondary.TButton"
        ).pack(side="left")

        ttk.Button(
            bottom,
            text="Отмена",
            width=16,
            command=self.destroy,
            style="Secondary.TButton"
        ).pack(side="right")

        ttk.Button(
            bottom,
            text="Сохранить",
            width=16,
            command=self._save,
            style="Primary.TButton"
        ).pack(side="right", padx=(0, 8))

        self.bind_all("<Delete>", self._on_delete_key, add="+")
        self.bind_all("<Return>", self._on_enter_key, add="+")
        self.bind_all("<KP_Enter>", self._on_enter_key, add="+")

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _refresh_scrollregion(self):
        """
        Если строк меньше, чем высота видимой области, таблица всегда
        прижата к верхнему краю и прокрутка по вертикали фактически
        отключена. Если строк больше — прокрутка работает как обычно.
        """
        try:
            viewport_width = max(1, self.canvas.winfo_width())
            viewport_height = max(1, self.canvas.winfo_height())

            content_height = max(1, self.table_frame.winfo_reqheight())

            # Ширина содержимого всегда равна ширине Canvas.
            # Высота scrollregion не может быть меньше высоты Canvas —
            # благодаря этому короткую таблицу нельзя "утянуть" вниз.
            scroll_height = max(viewport_height, content_height)

            self.canvas.configure(
                scrollregion=(0, 0, viewport_width, scroll_height)
            )

            if content_height <= viewport_height:
                self.canvas.yview_moveto(0.0)

        except Exception:
            pass

    def _on_frame_configure(self, _event=None):
        self.after_idle(self._refresh_scrollregion)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        self.after_idle(self._refresh_scrollregion)

    def _on_mousewheel(self, event):
        try:
            content_height = self.table_frame.winfo_reqheight()
            viewport_height = self.canvas.winfo_height()

            # Короткая таблица не должна прокручиваться вообще.
            if content_height <= viewport_height:
                self.canvas.yview_moveto(0.0)
                return "break"
        except Exception:
            pass

        if getattr(event, "delta", 0):
            self.canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units"
            )
        else:
            if getattr(event, "num", None) == 4:
                self.canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                self.canvas.yview_scroll(1, "units")

        return "break"

    def _set_current_row(self, row_index: int):
        self.current_row_index = row_index

    def _bind_entry_events(self, entry: tk.Entry, row_index: int, col_index: int):
        entry.bind("<FocusIn>", lambda e, i=row_index: self._set_current_row(i))
        entry.bind("<Button-1>", lambda e, i=row_index: self._set_current_row(i))

        # В Windows Tk сочетания <Control-v> / <Control-V> зависят от
        # текущей раскладки. На русской раскладке keysym для физической
        # клавиши V может быть "??", поэтому перехватываем любой KeyPress
        # и определяем Ctrl+V по неизменному Windows virtual-key code 86.
        entry.bind(
            "<KeyPress>",
            lambda event, r=row_index, c=col_index:
                self._on_table_keypress(event, r, c)
        )

        # Резервный системный способ вставки, также независимый от раскладки.
        entry.bind(
            "<Shift-Insert>",
            lambda event, r=row_index, c=col_index:
                self._paste_from_clipboard(r, c)
        )

        entry.bind("<MouseWheel>", self._on_mousewheel)
        entry.bind("<Button-4>", self._on_mousewheel)
        entry.bind("<Button-5>", self._on_mousewheel)

    def _on_table_keypress(self, event, row_index: int, col_index: int):
        """
        Универсальный Ctrl+V для Windows/Tk независимо от раскладки.

        В Tk под Windows на русской раскладке:
        - event.keysym для физической V может быть "??";
        - event.char для Ctrl+V обычно равен '\\x16';
        - event.keycode остаётся 86 (VK_V).

        Поэтому не используем <Control-v>, а проверяем состояние Ctrl
        и физический virtual-key code.
        """
        ctrl_pressed = bool(event.state & 0x0004)

        if ctrl_pressed and (
            event.keycode == 86
            or event.char == "\x16"
        ):
            return self._paste_from_clipboard(row_index, col_index)

        return None

    def _append_row(self, ifc_name="", revit_name=""):
        row_index = len(self.rows_vars)
        var_ifc = tk.StringVar(value=ifc_name)
        var_revit = tk.StringVar(value=revit_name)
        self.rows_vars.append((var_ifc, var_revit))

        number_label = tk.Label(
            self.table_frame,
            text=str(row_index + 1),
            bg=COLOR_SURFACE_2,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
            bd=1,
            relief="solid",
            padx=4,
            pady=4
        )
        number_label.grid(row=row_index, column=0, sticky="nsew")

        entry_ifc = tk.Entry(
            self.table_frame,
            textvariable=var_ifc,
            font=FONT_MAIN,
            relief="solid",
            bd=1
        )
        entry_ifc.grid(row=row_index, column=1, sticky="nsew", ipady=5)

        entry_revit = tk.Entry(
            self.table_frame,
            textvariable=var_revit,
            font=FONT_MAIN,
            relief="solid",
            bd=1
        )
        entry_revit.grid(row=row_index, column=2, sticky="nsew", ipady=5)

        self.rows_widgets.append((number_label, entry_ifc, entry_revit))
        self._bind_entry_events(entry_ifc, row_index, 0)
        self._bind_entry_events(entry_revit, row_index, 1)
        self._on_frame_configure()

    def _get_rows_data(self):
        return [(var_ifc.get(), var_revit.get()) for var_ifc, var_revit in self.rows_vars]

    def _rebuild_rows(self, rows_data):
        for number_label, entry_ifc, entry_revit in self.rows_widgets:
            number_label.destroy()
            entry_ifc.destroy()
            entry_revit.destroy()

        self.rows_vars = []
        self.rows_widgets = []

        for ifc_name, revit_name in rows_data:
            self._append_row(ifc_name, revit_name)

        self._on_frame_configure()

    def _focus_row(self, row_index: int, col_index: int = 0):
        if not self.rows_widgets:
            return

        row_index = max(0, min(row_index, len(self.rows_widgets) - 1))
        self.current_row_index = row_index

        widget = self.rows_widgets[row_index][1 + col_index]
        widget.focus_set()

        self.update_idletasks()

        try:
            content_height = self.table_frame.winfo_reqheight()
            viewport_height = self.canvas.winfo_height()

            # Если вся таблица помещается на экране, всегда оставляем её сверху.
            if content_height <= viewport_height:
                self.canvas.yview_moveto(0.0)
                return

            row_widget = self.rows_widgets[row_index][0]
            row_top = row_widget.winfo_y()
            row_bottom = row_top + row_widget.winfo_height()

            view_top = self.canvas.canvasy(0)
            view_bottom = view_top + viewport_height

            # Прокручиваем только если выбранная строка реально вышла
            # за пределы видимой области.
            if row_top < view_top:
                self.canvas.yview_moveto(
                    max(0.0, min(1.0, row_top / content_height))
                )

            elif row_bottom > view_bottom:
                target_top = max(0, row_bottom - viewport_height)
                self.canvas.yview_moveto(
                    max(0.0, min(1.0, target_top / content_height))
                )

        except Exception:
            pass

    def _on_enter_key(self, event=None):
        widget = self.focus_get()
        if widget is None or not self._widget_belongs_to_table(widget):
            return

        insert_after = (
            self.current_row_index
            if self.current_row_index is not None
            else len(self.rows_vars) - 1
        )

        rows_data = self._get_rows_data()
        rows_data.insert(insert_after + 1, ("", ""))
        self._rebuild_rows(rows_data)
        self.after(10, lambda: self._focus_row(insert_after + 1, 0))
        return "break"

    def _on_delete_key(self, event=None):
        widget = self.focus_get()
        if widget is None or not self._widget_belongs_to_table(widget):
            return

        if self.current_row_index is None:
            return

        rows_data = self._get_rows_data()

        if len(rows_data) <= 1:
            self.rows_vars[0][0].set("")
            self.rows_vars[0][1].set("")
            return "break"

        del rows_data[self.current_row_index]
        next_index = min(self.current_row_index, len(rows_data) - 1)
        self._rebuild_rows(rows_data)
        self.after(10, lambda: self._focus_row(next_index, 0))
        return "break"

    def _widget_belongs_to_table(self, widget):
        parent = widget
        while parent is not None:
            if parent == self.table_frame:
                return True
            try:
                parent = parent.master
            except Exception:
                break
        return False

    def _ensure_row_count(self, count: int):
        while len(self.rows_vars) < count:
            self._append_row("", "")

    def _paste_from_clipboard(self, start_row: int, start_col: int):
        try:
            text = self.clipboard_get()
        except Exception:
            return "break"

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        # Excel часто добавляет перевод строки в конец буфера.
        while lines and lines[-1] == "":
            lines.pop()

        if not lines:
            return "break"

        self._ensure_row_count(start_row + len(lines))

        for row_offset, line in enumerate(lines):
            target_row = start_row + row_offset
            values = line.split("\t")

            for col_offset, value in enumerate(values):
                target_col = start_col + col_offset
                if target_col >= self.COLS_COUNT:
                    break
                self.rows_vars[target_row][target_col].set(value.strip())

        self._on_frame_configure()
        return "break"

    def _clear_table(self):
        for var_ifc, var_revit in self.rows_vars:
            var_ifc.set("")
            var_revit.set("")

    def _save(self):
        self.result = [
            [var_ifc.get().strip(), var_revit.get().strip()]
            for var_ifc, var_revit in self.rows_vars
        ]
        self.destroy()

    def destroy(self):
        try:
            self.unbind_all("<Delete>")
            self.unbind_all("<Return>")
            self.unbind_all("<KP_Enter>")
        except Exception:
            pass
        super().destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(1320, screen_w - 60), min(900, screen_h - 80)
        self.geometry(f"{width}x{height}+{max(0, (screen_w-width)//2)}+{max(0, (screen_h-height)//2)}")
        self.minsize(min(1040, width), min(740, height))
        self.resizable(True, True)
        self.configure(bg=COLOR_BG)

        self.ifc_paths = []
        self.ifc_filter = tk.StringVar(value="")
        self.model_count = tk.StringVar(value="0 моделей")
        self.model_detail = tk.StringVar(value="Добавьте IFC-файлы или папку с моделями.")
        self.reports_dir_var = tk.StringVar(value="")
        self.open_after = tk.BooleanVar(value=False)
        self.create_summary = tk.BooleanVar(value=True)
        self.remove_empty_ifc_classes = tk.BooleanVar(value=False)
        self.run_game = tk.BooleanVar(value=True)
        self.is_running = False
        self.stop_event = threading.Event()
        self._ui_ready = False
        self.ui_queue = queue.Queue()

        self.game_process = None

        self.cfg: AppConfig = AppConfig.load()
        self.profile: Profile = self.cfg.get_active()
        self.common_ids_var = tk.StringVar(value=self.profile.common_ids_path)
        self.discipline_ids_var = tk.BooleanVar(value=self.profile.discipline_ids_enabled)

        self._setup_style()

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_project_tabs()
        self._build_main_ui()
        self._apply_profile_to_ui()
        self._ui_ready = True
        self.ifc_filter.trace_add("write", lambda *_: self._refresh_ifc_list())
        self.bind("<Control-s>", lambda event: self.on_profile_save())
        self.bind("<Control-o>", lambda event: self.pick_ifcs())
        self.bind("<F5>", lambda event: self.on_run())

        self.after(100, self.process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- style ----------
    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=FONT_MAIN, background=COLOR_BG, foreground=COLOR_TEXT)
        for name, bg, fg, pad in (
            ("Primary", COLOR_BLUE, "white", (14, 9)),
            ("Action", COLOR_BLUE, "white", (22, 12)),
            ("Secondary", COLOR_SURFACE_2, COLOR_TEXT, (12, 8)),
            ("CompactPrimary", COLOR_BLUE, "white", (10, 7)),
            ("CompactSecondary", COLOR_SURFACE_2, COLOR_TEXT, (10, 7)),
            ("Danger", "#FBECEF", "#AA3549", (12, 8)),
            ("Header", "#243954", "white", (14, 9)),
        ):
            style.configure(name + ".TButton", background=bg, foreground=fg,
                borderwidth=0, relief="flat", padding=pad, font=FONT_MAIN_BOLD,
                focusthickness=1, focuscolor=fg)
            style.map(name + ".TButton",
                background=[("disabled", "#E8EDF4"),
                            ("pressed", "#243954" if name == "Header" else COLOR_HOVER if name in ("Primary", "Action", "CompactPrimary") else "#CBD8ED"),
                            ("active", "#314A6C" if name == "Header" else COLOR_HOVER if name in ("Primary", "Action", "CompactPrimary") else "#DCE5F3")],
                foreground=[("disabled", "#98A4B5")])
        style.configure("TEntry", fieldbackground="white", foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER,
                        padding=8, insertcolor=COLOR_TEXT)
        style.map("TEntry", bordercolor=[("focus", COLOR_BLUE)])
        style.configure("TMenubutton", padding=(12, 8), relief="flat", background=COLOR_SURFACE_2)
        style.configure("TNotebook", background=COLOR_SURFACE, borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab", background=COLOR_SURFACE, foreground=COLOR_MUTED,
                        padding=(16, 8), font=FONT_MAIN_BOLD, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", "#EAF0FF"), ("active", "#F3F6FB")],
                  foreground=[("selected", COLOR_BLUE), ("active", COLOR_TEXT)])
        style.configure("Card.TLabelframe", background=COLOR_SURFACE, bordercolor=COLOR_BORDER,
                        relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=COLOR_SURFACE,
                        foreground=COLOR_TEXT, font=FONT_MAIN_BOLD)
        for name, font, color in (("CardLabel", FONT_MAIN, COLOR_TEXT),
                                  ("Muted", FONT_SMALL, COLOR_MUTED),
                                  ("SectionTitle", ("Segoe UI Semibold", 12), COLOR_TEXT)):
            style.configure(name + ".TLabel", background=COLOR_SURFACE, foreground=color, font=font)
        for name in ("Corp.TCheckbutton", "Corp.TRadiobutton"):
            style.configure(name, background=COLOR_SURFACE, foreground=COLOR_TEXT, font=FONT_MAIN)
            style.map(name, background=[("active", COLOR_SURFACE)])
        style.configure("Corp.Horizontal.TProgressbar", troughcolor="#E9EEF6", background=COLOR_BLUE,
                        borderwidth=0, lightcolor=COLOR_BLUE, darkcolor=COLOR_BLUE, thickness=6)
        style.configure("Treeview", background="white", fieldbackground="white", foreground=COLOR_TEXT,
                        rowheight=34, borderwidth=0, font=FONT_MAIN)
        style.configure("Treeview.Heading", background="#F5F7FB", foreground=COLOR_MUTED,
                        relief="flat", font=FONT_SMALL, padding=(10, 8))
        style.map("Treeview", background=[("selected", "#EAF0FF")], foreground=[("selected", COLOR_BLUE)])
        style.configure("Vertical.TScrollbar", arrowsize=12, background="#DAE2EF", troughcolor="#F6F8FC", borderwidth=0)
        style.configure("Horizontal.TScrollbar", arrowsize=12, background="#DAE2EF", troughcolor="#F6F8FC", borderwidth=0)

    def _build_header(self):
        header = tk.Frame(self, bg=COLOR_BLUE_DARK, padx=24, pady=15)
        header.grid(row=0, column=0, sticky="ew")
        mark = tk.Label(header, text="IFC", font=("Segoe UI Semibold", 16), bg=COLOR_BLUE,
                        fg="white", padx=10, pady=5)
        mark.pack(side="left", padx=(0, 14))
        title = tk.Frame(header, bg=COLOR_BLUE_DARK)
        title.pack(side="left")
        tk.Label(title, text="IFC CHECKER", bg=COLOR_BLUE_DARK, fg="white",
                 font=("Segoe UI Semibold", 17)).pack(anchor="w")
        tk.Label(title, text="Проверка моделей · IDS · Сводный отчёт", bg=COLOR_BLUE_DARK,
                 fg="#AABBD0", font=FONT_SMALL).pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="Открыть сводный отчёт  ↗", command=self.open_summary_report,
                   style="Header.TButton").pack(side="right")

    def _build_project_tabs(self):
        bar = tk.Frame(self, bg=COLOR_SURFACE, padx=20, pady=8)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        tk.Label(bar, text="ПРОЕКТЫ", bg=COLOR_SURFACE, fg=COLOR_MUTED,
                 font=("Segoe UI Semibold", 9)).grid(row=0, column=0, padx=(0, 16))
        tabs = tk.Frame(bar, bg=COLOR_SURFACE)
        tabs.grid(row=0, column=1, sticky="ew")
        tabs.grid_columnconfigure(0, weight=1)
        self.project_tabs_canvas = tk.Canvas(tabs, bg=COLOR_SURFACE, highlightthickness=0, height=38)
        self.project_tabs_canvas.grid(row=0, column=0, sticky="ew")
        self.project_tabs_scroll = ttk.Scrollbar(tabs, orient="horizontal", command=self.project_tabs_canvas.xview)
        self.project_tabs_scroll.grid(row=1, column=0, sticky="ew")
        self.project_tabs_canvas.configure(xscrollcommand=self.project_tabs_scroll.set)
        self.nb_projects = ttk.Notebook(self.project_tabs_canvas)
        self.nb_projects_window = self.project_tabs_canvas.create_window((0, 0), window=self.nb_projects, anchor="nw")
        self.nb_projects.bind("<<NotebookTabChanged>>", self.on_profile_tab_change)
        self.nb_projects.bind("<Configure>", self._update_project_tabs_scrollregion)
        self.project_tabs_canvas.bind("<Configure>", self._on_project_tabs_canvas_configure)
        actions = tk.Frame(bar, bg=COLOR_SURFACE)
        actions.grid(row=0, column=2, padx=(16, 0))
        ttk.Button(actions, text="+ Проект", command=self.on_profile_add,
                   style="CompactSecondary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Сохранить", command=self.on_profile_save,
                   style="CompactSecondary.TButton").pack(side="left", padx=(0, 8))
        menu_button = ttk.Menubutton(actions, text="Действия  ▾")
        menu_button.pack(side="left")
        menu = tk.Menu(menu_button, tearoff=False, font=FONT_MAIN, bg="white", fg=COLOR_TEXT)
        menu.add_command(label="Переименовать проект", command=self.on_profile_rename)
        menu.add_command(label="Экспортировать настройки…", command=self.on_profile_export)
        menu.add_command(label="Импортировать настройки…", command=self.on_profile_import)
        menu.add_separator()
        menu.add_command(label="Удалить проект…", command=self.on_profile_delete)
        menu_button.configure(menu=menu)
        self._refresh_project_tabs()

    def _card(self, parent, title, subtitle, column, weight=1):
        card = tk.Frame(parent, bg=COLOR_SURFACE, highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        card.grid_columnconfigure(0, weight=1)
        head = tk.Frame(card, bg=COLOR_SURFACE, padx=18, pady=12)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(head, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        return card

    def _build_main_ui(self):
        main = tk.Frame(self, bg=COLOR_BG)
        main.grid(row=2, column=0, sticky="nsew", padx=20, pady=(14, 16))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=3)
        main.grid_rowconfigure(2, weight=1)
        top = tk.Frame(main, bg=COLOR_BG)
        top.grid(row=0, column=0, sticky="nsew")
        top.grid_columnconfigure(0, weight=3, uniform="main")
        top.grid_columnconfigure(1, weight=2, uniform="main")
        top.grid_rowconfigure(0, weight=1)

        models = self._card(top, "01  Модели IFC", "Добавьте модели, которые нужно проверить", 0)
        models.grid_rowconfigure(3, weight=1)
        toolbar = tk.Frame(models, bg=COLOR_SURFACE)
        toolbar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        ttk.Button(toolbar, text="+ Файлы", command=self.pick_ifcs,
                   style="CompactPrimary.TButton").pack(side="left")
        ttk.Button(toolbar, text="+ Папка", command=self.pick_ifc_folder,
                   style="CompactSecondary.TButton").pack(side="left", padx=6)
        ttk.Button(toolbar, text="Убрать выбранные", command=self.remove_selected_ifcs,
                   style="CompactSecondary.TButton").pack(side="left")
        ttk.Label(toolbar, textvariable=self.model_count, style="Muted.TLabel").pack(side="right")
        search = tk.Frame(models, bg=COLOR_SURFACE)
        search.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        ttk.Label(search, text="Поиск", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        ttk.Entry(search, textvariable=self.ifc_filter).pack(side="left", fill="x", expand=True)
        ttk.Button(search, text="×", width=3, command=lambda: self.ifc_filter.set(""),
                   style="CompactSecondary.TButton").pack(side="left", padx=(6, 0))
        table = tk.Frame(models, bg=COLOR_SURFACE)
        table.grid(row=3, column=0, sticky="nsew", padx=18)
        table.grid_rowconfigure(0, weight=1); table.grid_columnconfigure(0, weight=1)
        self.lst_ifc = ttk.Treeview(table, columns=("rule",), show="tree headings", selectmode="extended", height=5)
        self.lst_ifc.heading("#0", text="МОДЕЛЬ IFC", anchor="w")
        self.lst_ifc.heading("rule", text="ПРАВИЛО IDS", anchor="w")
        self.lst_ifc.column("#0", width=285, minwidth=150, stretch=True)
        self.lst_ifc.column("rule", width=140, minwidth=110, stretch=False)
        self.lst_ifc.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(table, orient="vertical", command=self.lst_ifc.yview)
        sb.grid(row=0, column=1, sticky="ns"); self.lst_ifc.configure(yscrollcommand=sb.set)
        sx = ttk.Scrollbar(table, orient="horizontal", command=self.lst_ifc.xview)
        sx.grid(row=1, column=0, sticky="ew"); self.lst_ifc.configure(xscrollcommand=sx.set)
        self.lst_ifc.tag_configure("alternate", background="#F7F9FC")
        self.lst_ifc.tag_configure("missing", foreground="#B15825")
        self.lst_ifc.bind("<<TreeviewSelect>>", self.on_model_select)
        self.lst_ifc.bind("<Delete>", lambda event: self.remove_selected_ifcs())
        footer = tk.Frame(models, bg=COLOR_SURFACE)
        footer.grid(row=4, column=0, sticky="ew", padx=18, pady=(6, 12))
        self.model_detail_label = ttk.Entry(footer, textvariable=self.model_detail, state="readonly")
        self.model_detail_label.pack(anchor="w", fill="x")
        links = tk.Frame(footer, bg=COLOR_SURFACE)
        links.pack(fill="x", pady=(6, 0))
        ttk.Button(links, text="IFC ↔ Revit", command=self.open_ifc_revit_mapping,
                   style="CompactSecondary.TButton").pack(side="left")
        ttk.Button(links, text="Очистить список", command=self.clear_ifcs,
                   style="CompactSecondary.TButton").pack(side="right")

        ids = self._card(top, "02  Подбор IDS", "Настройки сохраняются в текущем проекте", 1)
        body = tk.Frame(ids, bg=COLOR_SURFACE, padx=18, pady=2)
        body.grid(row=1, column=0, sticky="nsew");body.grid_columnconfigure(0, weight=1)
        ids_header = tk.Frame(body, bg=COLOR_SURFACE)
        ids_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(ids_header, text="Общая IDS", style="SectionTitle.TLabel").pack(side="left")
        ttk.Button(ids_header, text="Копировать IDS…", command=self.copy_ids_from_project,
                   style="CompactSecondary.TButton").pack(side="right")
        ttk.Label(body, text="Применяется ко всем моделям проекта", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 8))
        common = tk.Frame(body, bg=COLOR_SURFACE);common.grid(row=2, column=0, sticky="ew")
        entry = ttk.Entry(common, textvariable=self.common_ids_var, width=22)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<FocusOut>", self.on_ids_settings_change)
        ttk.Button(common, text="Выбрать…", command=self.pick_common_ids,
                   style="CompactSecondary.TButton").pack(side="left", padx=(6, 0))
        ttk.Separator(body).grid(row=3, column=0, sticky="ew", pady=14)
        ttk.Checkbutton(body, text="Дисциплинарные IDS", variable=self.discipline_ids_var,
                        command=self.on_ids_settings_change, style="Corp.TCheckbutton").grid(row=4, column=0, sticky="w")
        self.discipline_status = ttk.Label(body, style="Muted.TLabel", wraplength=320)
        self.discipline_status.grid(row=5, column=0, sticky="ew", pady=(6, 10))
        self.btn_discipline_settings = ttk.Button(body, text="Настроить паттерны → IDS", command=self.open_rules_settings,
                                                   style="Secondary.TButton")
        self.btn_discipline_settings.grid(row=6, column=0, sticky="ew")
        ttk.Button(body, text="Описания разделов…", command=self.open_project_sections,
                   style="CompactSecondary.TButton").grid(row=7, column=0, sticky="w", pady=(10, 12))
        body.bind("<Configure>", lambda event: self.discipline_status.configure(wraplength=max(180, event.width-36)))

        reports = tk.Frame(main, bg=COLOR_SURFACE, highlightbackground=COLOR_BORDER, highlightthickness=1, padx=18, pady=10)
        reports.grid(row=1, column=0, sticky="ew", pady=12);reports.grid_columnconfigure(1, weight=1)
        ttk.Label(reports, text="Отчёты", style="SectionTitle.TLabel").grid(row=0, column=0, padx=(0, 14), sticky="w")
        self.reports_display_var = tk.StringVar(value="Папка рядом с первой моделью · можно изменить")
        self.reports_dir_var.trace_add("write", lambda *_: self.reports_display_var.set(
            self.reports_dir_var.get() or "Папка рядом с первой моделью · можно изменить"))
        self.report_location = ttk.Entry(reports, textvariable=self.reports_display_var, state="readonly")
        self.report_location.grid(row=0, column=1, sticky="ew")
        ttk.Button(reports, text="Папка…", command=self.pick_reports_folder,
                   style="CompactSecondary.TButton").grid(row=0, column=2, padx=6)
        ttk.Button(reports, text="Открыть ↗", command=self.open_reports_folder,
                   style="CompactSecondary.TButton").grid(row=0, column=3)
        options = tk.Frame(reports, bg=COLOR_SURFACE);options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        for col, (text, var) in enumerate((("Обновлять сводный отчёт", self.create_summary),
                                           ("Открывать отчёты моделей", self.open_after),
                                           ("Скрывать пустые IFC-классы", self.remove_empty_ifc_classes))):
            ttk.Checkbutton(options, text=text, variable=var, command=self.on_ids_settings_change,
                            style="Corp.TCheckbutton").grid(row=0, column=col, sticky="w", padx=(0, 22))

        journal = tk.Frame(main, bg=COLOR_SURFACE, highlightbackground=COLOR_BORDER, highlightthickness=1, padx=18, pady=10)
        journal.grid(row=2, column=0, sticky="nsew");journal.grid_columnconfigure(0, weight=1);journal.grid_rowconfigure(2, weight=1)
        head = tk.Frame(journal, bg=COLOR_SURFACE);head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Журнал проверки", style="SectionTitle.TLabel").pack(side="left")
        self.lbl_progress = ttk.Label(head, text="Готово к проверке", style="Muted.TLabel", anchor="e")
        self.lbl_progress.pack(side="right", fill="x", expand=True, padx=(20, 0))
        self.pb = ttk.Progressbar(journal, mode="determinate", style="Corp.Horizontal.TProgressbar")
        self.pb.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        log = tk.Frame(journal, bg=COLOR_SURFACE);log.grid(row=2, column=0, sticky="nsew")
        log.grid_columnconfigure(0, weight=1);log.grid_rowconfigure(0, weight=1)
        self.txt_log = tk.Text(log, height=3, font=("Consolas", 10), bg=COLOR_SURFACE, fg=COLOR_MUTED,
                             relief="flat", highlightthickness=0, wrap="word", padx=2, pady=4)
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log, orient="vertical", command=self.txt_log.yview)
        scroll.grid(row=0, column=1, sticky="ns");self.txt_log.configure(yscrollcommand=scroll.set)
        for tag, color in (("error", "#BF4053"), ("success", "#238565"), ("warning", "#A56823")):
            self.txt_log.tag_configure(tag, foreground=color)
        self.txt_log.insert("end", "Здесь появятся результаты проверки моделей.\n")
        bottom = tk.Frame(main, bg=COLOR_BG);bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        tk.Label(bottom, text="F5 — проверить   ·   Ctrl+O — добавить IFC   ·   Ctrl+S — сохранить",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=("Segoe UI", 8)).pack(side="left")
        self.btn_run = ttk.Button(bottom, text="Проверить модели  →", command=self.on_run, style="Action.TButton")
        self.btn_run.pack(side="right")
        self.btn_stop = ttk.Button(bottom, text="Остановить", command=self.on_stop, state="disabled", style="Danger.TButton")
        self.btn_stop.pack(side="right", padx=8)
        ttk.Checkbutton(bottom, text="Игра", variable=self.run_game, command=self.on_ids_settings_change,
                        style="Corp.TCheckbutton").pack(side="right", padx=(0, 14))

    def open_summary_report(self):
        target = self.get_reports_root_dir() / "__Сводный_ИДС_отчет.html"
        if not target.is_file():
            messagebox.showinfo("Сводный отчёт", "Сначала запустите проверку с включённым обновлением сводного отчёта.", parent=self)
            return
        webbrowser.open(target.resolve().as_uri())

    def on_model_select(self, _event=None):
        selected = self.lst_ifc.selection()
        if selected:
            self.model_detail.set(self.ifc_paths[int(selected[0])])

    def remove_selected_ifcs(self):
        selected = {int(value) for value in self.lst_ifc.selection()}
        if not selected:
            return
        self.ifc_paths = [path for index, path in enumerate(self.ifc_paths) if index not in selected]
        self.profile.ifc_paths = list(self.ifc_paths)
        self._refresh_ifc_list()
        self.cfg.save()

    # ---------- helpers ----------
    def _update_project_tabs_scrollregion(self, _event=None):
        self.project_tabs_canvas.configure(
            scrollregion=self.project_tabs_canvas.bbox("all")
        )

    def _on_project_tabs_canvas_configure(self, event):
        self.update_idletasks()
        req_width = self.nb_projects.winfo_reqwidth()
        new_width = max(event.width, req_width)

        self.project_tabs_canvas.itemconfigure(
            self.nb_projects_window,
            width=new_width
        )
        self.project_tabs_canvas.configure(
            scrollregion=self.project_tabs_canvas.bbox("all")
        )

    def _refresh_project_tabs(self):
        current_name = self.cfg.active

        for tab_id in self.nb_projects.tabs():
            self.nb_projects.forget(tab_id)

        self._tab_profile_names = []
        for name in self.cfg.profiles.keys():
            frm = tk.Frame(self.nb_projects, bg=COLOR_SURFACE)
            self.nb_projects.add(frm, text=name)
            self._tab_profile_names.append(name)

        if current_name in self._tab_profile_names:
            idx = self._tab_profile_names.index(current_name)
            self.nb_projects.select(idx)
        
        self.update_idletasks()
        self._update_project_tabs_scrollregion()

    def log(self, msg: str):
        tag = "error" if "❌" in msg or "ошибка" in msg.casefold() else "success" if "✅" in msg or "🆗" in msg else "warning" if "🟡" in msg or "⚠" in msg else ""
        self.txt_log.insert("end", msg + "\n", tag)
        self.txt_log.see("end")
        self.update_idletasks()

    def set_status(self, msg: str):
        self.lbl_progress.config(text=msg)
        self.update_idletasks()

    def ui_call(self, fn, *args, **kwargs):
        self.ui_queue.put((fn, args, kwargs))

    def process_ui_queue(self):
        try:
            while True:
                fn, args, kwargs = self.ui_queue.get_nowait()
                fn(*args, **kwargs)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_ui_queue)

    def _apply_profile_to_ui(self):
        self.title(f"IFC CHECKER — {self.profile.name}")
        self.common_ids_var.set(self.profile.common_ids_path)
        self.discipline_ids_var.set(self.profile.discipline_ids_enabled)
        self._refresh_ids_controls()
        self.create_summary.set(bool(self.profile.create_summary))
        self.remove_empty_ifc_classes.set(bool(self.profile.remove_empty_ifc_classes))
        self.run_game.set(bool(self.profile.run_game))
        self.reports_dir_var.set(self.profile.reports_dir or "")
        self.ifc_paths = list(self.profile.ifc_paths)
        self._refresh_ifc_list()

    def _collect_ui_to_profile(self):
        self.profile.create_summary = bool(self.create_summary.get())
        self.profile.remove_empty_ifc_classes = bool(self.remove_empty_ifc_classes.get())
        self.profile.ifc_paths = list(self.ifc_paths)
        self.profile.reports_dir = self.reports_dir_var.get().strip()
        self.profile.common_ids_path = self.common_ids_var.get().strip()
        self.profile.discipline_ids_enabled = bool(self.discipline_ids_var.get())
        self.profile.run_game = bool(self.run_game.get())

    def _refresh_ifc_list(self):
        self.lst_ifc.delete(*self.lst_ifc.get_children())
        query = self.ifc_filter.get().strip().casefold()
        rules = [rule.__dict__ for rule in self.profile.disc_rules]
        visible = 0
        for index, path in enumerate(self.ifc_paths):
            name = Path(path).name
            if query and query not in str(path).casefold():
                continue
            rule, _ = match_rule(name, rules) if self.profile.discipline_ids_enabled else (None, None)
            label = (rule["pattern"] if rule else "Без правила") if self.profile.discipline_ids_enabled else "Общая IDS"
            tags = ["alternate"] if visible % 2 else []
            if not Path(path).is_file():
                tags.append("missing");label = "Файл не найден"
            self.lst_ifc.insert("", "end", iid=str(index), text=name, values=(label,), tags=tags)
            visible += 1
        self.model_count.set(f"{visible} из {len(self.ifc_paths)}" if query else f"Моделей: {len(self.ifc_paths)}")
        self.model_detail.set("Выберите модель, чтобы увидеть полный путь." if visible else
                              ("Нет совпадений. Измените поисковый запрос." if self.ifc_paths else "Добавьте IFC-файлы или папку с моделями."))

    # ---------- project tabs ----------
    def on_profile_tab_change(self, _evt=None):
        if not self._ui_ready or not self.nb_projects.tabs():
            return

        current_tab = self.nb_projects.select()
        if not current_tab:
            return

        idx = self.nb_projects.index(current_tab)
        sel = self._tab_profile_names[idx]
        if sel == self.profile.name:
            return
        self._collect_ui_to_profile()

        self.cfg.set_active(sel)
        self.profile = self.cfg.get_active()
        self._apply_profile_to_ui()
        self.cfg.save()

    def on_profile_add(self):
        name = simpledialog.askstring("Новый проект", "Название проекта:", parent=self)
        if name is None:
            return
        name = name.strip() or "Project"
        self._collect_ui_to_profile()
        self.profile = self.cfg.create_profile(name)
        self.cfg.save()
        self._refresh_project_tabs()
        self._apply_profile_to_ui()

    def on_profile_rename(self):
        new_name = simpledialog.askstring(
            "Переименовать проект", "Новое название:",
            initialvalue=self.profile.name, parent=self
        )
        if not new_name:
            return
        self._collect_ui_to_profile()
        final = self.cfg.rename_profile(self.profile.name, new_name.strip())
        self.profile = self.cfg.get_active()
        self.cfg.save()
        self._refresh_project_tabs()
        if final in self._tab_profile_names:
            self.nb_projects.select(self._tab_profile_names.index(final))
        self._apply_profile_to_ui()

    def on_profile_save(self):
        self._collect_ui_to_profile()
        self.cfg.save()
        messagebox.showinfo(
            "Сохранено",
            f"Настройки профиля «{self.profile.name}» сохранены.\n\nПуть:\n{str(CONF_PATH)}"
        )

    def on_profile_export(self):
        self._collect_ui_to_profile()
        out = filedialog.asksaveasfilename(
            title="Экспорт профиля в JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{self.profile.name}.json"
        )
        if out:
            if self.cfg.export_profile(self.profile.name, Path(out)):
                messagebox.showinfo("Готово", f"Профиль экспортирован:\n{out}")

    def on_profile_import(self):
        path = filedialog.askopenfilename(
            title="Импорт профиля из JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        new_name = simpledialog.askstring("Импорт", "Имя нового проекта (можно оставить пустым):", parent=self)
        self._collect_ui_to_profile()
        p = self.cfg.import_profile(Path(path), new_name.strip() if new_name else None)
        self.profile = p
        self.cfg.save()
        self._refresh_project_tabs()
        self._apply_profile_to_ui()
        messagebox.showinfo("Импортировано", f"Создан профиль «{p.name}».")

    def on_profile_delete(self):
        if len(self.cfg.profiles) <= 1:
            messagebox.showinfo("Нельзя удалить", "Должен остаться хотя бы один проект.")
            return
        if messagebox.askyesno("Удалить проект", f"Удалить профиль «{self.profile.name}»?"):
            self.cfg.delete_profile(self.profile.name)
            self.profile = self.cfg.get_active()
            self.cfg.save()
            self._refresh_project_tabs()
            self._apply_profile_to_ui()

    # ---------- project IDS ----------
    def copy_ids_from_project(self):
        if len(self.cfg.profiles) < 2:
            messagebox.showinfo("Копирование IDS",
                "Создайте или импортируйте ещё один проект, чтобы скопировать его настройки IDS.", parent=self)
            return
        self._collect_ui_to_profile()
        dialog = CopyIdsDialog(self, self.cfg.profiles, self.profile.name)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        try:
            self.cfg.copy_project_ids(dialog.result, self.profile.name)
        except Exception as exc:
            messagebox.showerror("Не удалось скопировать IDS", str(exc), parent=self)
            return
        self._apply_profile_to_ui()
        self.set_status(f"IDS скопирована из проекта «{dialog.result}»")
        self.log(f"✅ Настройки IDS скопированы из «{dialog.result}» в «{self.profile.name}» и сохранены.")

    def _refresh_ids_controls(self):
        enabled = bool(self.discipline_ids_var.get())
        self.btn_discipline_settings.configure(state="normal" if enabled else "disabled")
        count = len(self.profile.disc_rules)
        self.discipline_status.configure(text=(
            f"Правил: {count}. Дополнительная проверка по имени IFC."
            if enabled else "Выключено. Проверка только по общей IDS."
        ))

    def on_ids_settings_change(self, _event=None):
        if not self._ui_ready:
            return
        self._collect_ui_to_profile()
        self._refresh_ids_controls()
        self._refresh_ifc_list()
        self.cfg.save()

    def pick_common_ids(self):
        current = self.common_ids_var.get().strip()
        path = filedialog.askopenfilename(
            title="Общая IDS для всех моделей проекта",
            filetypes=[("IDS files", "*.ids;*.xml"), ("All files", "*.*")],
            initialdir=str(Path(current).parent if current else Path.home())
        )
        if path:
            self.common_ids_var.set(path)
            self.on_ids_settings_change()

    def open_rules_settings(self):
        if not self.discipline_ids_var.get():
            return
        self._collect_ui_to_profile()
        dlg = RulesSettingsDialog(self, self.profile)
        self.wait_window(dlg)
        if dlg.result:
            self.cfg.save()
            self._refresh_ids_controls()
            self._refresh_ifc_list()

    def open_project_sections(self):
        self._collect_ui_to_profile()
        dlg = SectionsDescriptionDialog(self, self.profile.section_descriptions)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.profile.section_descriptions = deepcopy(dlg.result)
            self.cfg.save()

    def report_callback_exception(self, exc_type, exc_value, exc_tb):
        messagebox.showerror("Ошибка", str(exc_value), parent=self)

    # ---------- IFC ----------
    def pick_ifcs(self):
        initial = self.profile.last_ifc_dir or str(Path.home())

        paths = filedialog.askopenfilenames(
            title="Выберите одну или несколько IFC моделей",
            filetypes=[("IFC files", "*.ifc;*.ifczip"), ("All files", "*.*")],
            initialdir=initial
        )

        if not paths:
            return

        self.ifc_paths = self._normalize_ifc_paths([*self.ifc_paths, *paths])
        self.profile.ifc_paths = list(self.ifc_paths)

        self._refresh_ifc_list()

        if self.ifc_paths:
            self.profile.last_ifc_dir = str(Path(self.ifc_paths[0]).parent)

        self.cfg.save()

    def pick_ifc_folder(self):
        initial = self.profile.last_ifc_dir or str(Path.home())

        folder = filedialog.askdirectory(
            title="Выберите папку с IFC моделями",
            initialdir=initial
        )

        if not folder:
            return

        root = Path(folder)

        found_files = []
        found_files.extend(root.rglob("*.ifc"))
        found_files.extend(root.rglob("*.ifczip"))

        found_files = [
            str(p)
            for p in found_files
            if p.is_file()
        ]

        if not found_files:
            messagebox.showinfo(
                "IFC не найдены",
                "В выбранной папке и её вложенных папках не найдено файлов IFC."
            )
            return

        self.ifc_paths = self._normalize_ifc_paths([*self.ifc_paths, *found_files])
        self.profile.ifc_paths = list(self.ifc_paths)
        self.profile.last_ifc_dir = str(root)

        self._refresh_ifc_list()
        self.cfg.save()

        messagebox.showinfo(
            "Готово",
            f"Найдено IFC-файлов: {len(self.ifc_paths)}"
        )

    def _normalize_ifc_paths(self, paths):
        result = []

        for p in paths:
            try:
                path = Path(p)
                suffix = path.suffix.lower()

                if suffix in (".ifc", ".ifczip") and path.exists():
                    result.append(str(path))
            except Exception:
                pass

        # убираем дубли и сортируем
        return sorted(set(result), key=lambda x: x.lower())

    def open_ifc_revit_mapping(self):
        dlg = IfcRevitMappingDialog(self, self.profile.ifc_revit_names)
        self.wait_window(dlg)

        if dlg.result is None:
            return

        self.profile.ifc_revit_names = [
            [str(row[0]).strip(), str(row[1]).strip()]
            for row in dlg.result
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        self.cfg.save()

    @staticmethod
    def _normalize_model_name_for_mapping(value: str) -> str:
        """
        Нормализация имени для прямого сопоставления IFC ↔ Revit.

        Игнорируем регистр и конечные расширения .ifc / .rvt.
        Например, все варианты ниже считаются одним именем:
        MODEL_AR
        MODEL_AR.ifc
        MODEL_AR.rvt
        """
        name = (value or "").strip()
        if not name:
            return ""

        # Если пользователь вставил полный путь, сравниваем только имя файла.
        name = Path(name).name.strip()
        lowered = name.casefold()

        for suffix in (".ifc", ".rvt"):
            if lowered.endswith(suffix):
                name = name[:-len(suffix)]
                break

        return name.strip().casefold()

    def _get_revit_name_for_ifc(self, ifc_filename: str, profile=None) -> str:
        """
        Прямое сопоставление по имени модели.
        Регистр и расширения .ifc / .rvt не учитываются.
        """
        target = self._normalize_model_name_for_mapping(ifc_filename)
        if not target:
            return ""

        for row in (profile if profile is not None else self.profile).ifc_revit_names:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue

            ifc_name = str(row[0]).strip()
            revit_name = str(row[1]).strip()

            if (
                ifc_name
                and self._normalize_model_name_for_mapping(ifc_name) == target
            ):
                return revit_name

        return ""

    def clear_ifcs(self):
        self.ifc_paths = []
        self.profile.ifc_paths = []
        self._refresh_ifc_list()
        self.cfg.save()

    def get_reports_root_dir(self, ifc_path: str | None = None, profile=None) -> Path:
        profile = profile if profile is not None else self.profile
        reports_dir = profile.reports_dir.strip() if profile.reports_dir else ""

        if reports_dir:
            return Path(reports_dir)

        if ifc_path:
            return Path(ifc_path).parent / DEFAULT_REPORT_SUBFOLDER

        if self.ifc_paths:
            return Path(self.ifc_paths[0]).parent / DEFAULT_REPORT_SUBFOLDER

        return Path.home() / DEFAULT_REPORT_SUBFOLDER

    def pick_reports_folder(self):
        initial = self.profile.reports_dir or self.profile.last_ifc_dir or str(Path.home())

        folder = filedialog.askdirectory(
            title="Выберите папку для сохранения отчётов",
            initialdir=initial
        )

        if not folder:
            return

        self.profile.reports_dir = folder
        self.reports_dir_var.set(folder)
        self.cfg.save()

        messagebox.showinfo(
            "Папка выбрана",
            f"Отчёты будут сохраняться сюда:\n{folder}"
        )

    def open_reports_folder(self):
        target = self.get_reports_root_dir()
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))

    def start_game_process(self):
        try:
            if self.game_process and self.game_process.poll() is None:
                return

            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--game"]
            else:
                game_path = Path(__file__).resolve().parent / "game.py"

                if not game_path.exists():
                    self.log(f"⚠️ Игра не найдена: {game_path}")
                    return

                cmd = [sys.executable, str(game_path)]

            creationflags = 0

            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW

            self.game_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )

        except Exception as e:
            self.log(f"⚠️ Не удалось запустить игру: {e}")

    def stop_game_process(self):
        try:
            if self.game_process and self.game_process.poll() is None:
                self.game_process.terminate()
                self.game_process = None
        except Exception:
            pass

    # ---------- run ----------
    def on_run(self):
        if self.is_running:
            return
        if not self.ifc_paths:
            messagebox.showwarning("Нет IFC", "Выберите один или несколько файлов IFC.")
            return

        self.cfg.match_mode = MATCH_CONTAINS
        self._collect_ui_to_profile()
        self.cfg.save()

        cids = self.profile.common_ids_path
        if not cids or not Path(cids).is_file():
            messagebox.showwarning("Общая IDS", "Выберите существующий файл общей IDS для проекта.")
            return
        if self.profile.discipline_ids_enabled:
            if not self.profile.disc_rules:
                messagebox.showwarning("Дисциплинарные IDS", "Добавьте хотя бы одно правило или отключите дисциплинарные IDS.")
                return
            rules = [r.__dict__ for r in self.profile.disc_rules]
            for ifc_path in self.ifc_paths:
                rule, _ = match_rule(Path(ifc_path).name, rules)
                if rule:
                    for key, label in (("ids_path", "IDS дисциплины"), ("mapping_path", "файл сопоставления")):
                        value = (rule.get(key) or "").strip()
                        if (key == "ids_path" or value) and (not value or not Path(value).is_file()):
                            messagebox.showwarning("Файл не найден", f"Правило «{rule['pattern']}»: {label}\n{value}")
                            return
        report_root = self.get_reports_root_dir(self.ifc_paths[0]).resolve()
        # A dashboard folder belongs to one project; otherwise matching IFC names
        # in different projects would replace each other's results.
        for other in self.cfg.profiles.values():
            if other is self.profile or not other.reports_dir:
                continue
            if os.path.normcase(str(Path(other.reports_dir).resolve())) == os.path.normcase(str(report_root)):
                messagebox.showwarning(
                    "Папка другого проекта",
                    f"Эта папка отчётов уже используется проектом «{other.name}».\n"
                    "Выберите отдельную папку отчётов для текущего проекта."
                )
                return
        if not self.profile.reports_dir:
            self.profile.reports_dir = str(report_root)
            self.reports_dir_var.set(self.profile.reports_dir)
            self.cfg.save()
        profile_snapshot = deepcopy(self.profile)
        paths_snapshot = tuple(self.ifc_paths)
        open_after = bool(self.open_after.get())
        self.stop_event.clear()

        self.is_running = True
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.pb.config(value=0, maximum=len(paths_snapshot) * (2 if profile_snapshot.discipline_ids_enabled else 1))
        self.txt_log.delete("1.0", "end")
        self.set_status("Старт валидации…")

        if self.run_game.get():
            self.start_game_process()

        threading.Thread(target=self.worker_run_two_passes,
                         args=(profile_snapshot, paths_snapshot, open_after), daemon=True).start()

    def on_stop(self):
        self.stop_event.set()
        self.btn_stop.configure(state="disabled")
        self.set_status("Остановка после текущей операции…")

    def _finish_run(self):
        self.is_running = False
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def worker_run_two_passes(self, profile, ifc_paths, open_after):
        total = len(ifc_paths)
        make_summary = profile.create_summary
        remove_empty_ifc_classes = profile.remove_empty_ifc_classes
        common_ids = profile.common_ids_path
        common_signature = ids_fingerprint(common_ids)
        discipline_signatures = {}
        use_discipline = profile.discipline_ids_enabled
        steps_per_model = 2 if use_discipline else 1
        items = []
        history_run_id = uuid4().hex
        rules = [r.__dict__ for r in profile.disc_rules]

        try:
            for i, ifc_path in enumerate(ifc_paths, start=1):
                if self.stop_event.is_set():
                    self.ui_call(self.set_status, "Остановлено пользователем.")
                    break

                ifc_p = Path(ifc_path)
                name = ifc_p.name

                root_dir = self.get_reports_root_dir(ifc_path, profile)
                common_dir = root_dir / SUB_COMMON
                disc_dir = root_dir / SUB_DISC
                common_dir.mkdir(parents=True, exist_ok=True)
                if use_discipline:
                    disc_dir.mkdir(parents=True, exist_ok=True)

                item = {
                    "model": name,
                    "common_ids": common_ids,
                    "common_ids_fingerprint": common_signature,
                    "disc_ids": "",
                    "common_status": "error",
                    "disc_status": "not_run" if use_discipline else "disabled",
                    "revit_name": self._get_revit_name_for_ifc(name, profile),
                    "site_name": None,
                    "x": None,
                    "y": None,
                    "z": None,
                    "lat": None,
                    "lon": None,
                    "site_building_pct": None,
                    "building_pct": None,
                    "storey_pct": None,
                    "qty": None,
                    "dir_root": root_dir,
                    "common": None,
                    "common_pct": None,
                    "disc": None,
                    "disc_pct": None,
                    "disc_code": None,
                    "storey_names": [],
                }

                try:
                    self.ui_call(self.set_status, f"[{i}/{total}] Открытие IFC: {name}")
                    model = open_ifc(ifc_path)
                    if self.stop_event.is_set():
                        break

                    item.update(get_ifc_site_data(model))
                    item["qty"] = get_ifc_elements_count(model)
                    item["storey_names"] = get_ifc_storey_names(model)

                    # ---------- PASS 1: Общая IDS ----------
                    if common_ids:
                        try:
                            self.ui_call(self.set_status, f"[{i}/{total}] Общая IDS: {name}")
                            common_specs = open_ids(common_ids)
                            common_specs.validate(model)

                            out_base_common = common_dir / ifc_p.stem
                            html_c, pct_c = emit_reports(
                                common_specs,
                                out_base_common,
                                common_ids,
                                ifc_path,
                                remove_empty_ifc_classes=remove_empty_ifc_classes
                            )

                            self.ui_call(self.log, f"✅ Отчёт по общей IDS: {html_c}")
                            item["common"] = html_c
                            item["common_pct"] = pct_c
                            item["common_status"] = "result" if pct_c is not None else "no_result"
                            for key, ifc_class in (("site_building_pct", "IfcSite"),
                                                   ("building_pct", "IfcBuilding"),
                                                   ("storey_pct", "IfcBuildingStorey")):
                                item[key] = _ifc_class_percent_from_html(html_c, ifc_class)

                            if open_after and html_c:
                                try:
                                    os.startfile(str(html_c))
                                except Exception:
                                    pass

                        except Exception as e:
                            self.ui_call(self.log, f"❌ Ошибка общей IDS: {name}: {e}")
                    else:
                        self.ui_call(self.log, f"🟡 Общая IDS не задана — проверка пропущена: {name}")

                    self.ui_call(self.pb.step, 1)

                    if self.stop_event.is_set():
                        item["checked_at"] = datetime.now().astimezone().isoformat(timespec="microseconds")
                        items.append(item)
                        break

                    # ---------- PASS 2: дисциплина ----------
                    rule, _ = match_rule(name, rules) if use_discipline else (None, None)

                    if rule:
                        d_ids = (rule.get("ids_path") or "").strip()
                        item["disc_ids"] = d_ids
                        if d_ids not in discipline_signatures:
                            discipline_signatures[d_ids] = ids_fingerprint(d_ids)
                        item["disc_ids_fingerprint"] = discipline_signatures[d_ids]
                        item["disc_status"] = "error"
                        mapping_path = (rule.get("mapping_path") or "").strip()

                        try:
                            self.ui_call(self.set_status, f"[{i}/{total}] Дисциплина: {name}")

                            d_specs = open_ids(d_ids)
                            d_specs.validate(model)

                            out_base_disc = disc_dir / ifc_p.stem
                            html_d, pct_d = emit_reports(
                                d_specs,
                                out_base_disc,
                                d_ids,
                                ifc_path,
                                mapping_path=mapping_path,
                                remove_empty_ifc_classes=remove_empty_ifc_classes
                            )

                            self.ui_call(self.log, f"✅ Дисциплина: {html_d}")

                            item["disc"] = html_d
                            item["disc_pct"] = pct_d
                            item["disc_status"] = "result" if pct_d is not None else "no_result"
                            item["disc_code"] = ""
                            for key, ifc_class in (("site_building_pct", "IfcSite"),
                                                   ("building_pct", "IfcBuilding"),
                                                   ("storey_pct", "IfcBuildingStorey")):
                                value = _ifc_class_percent_from_html(html_d, ifc_class)
                                if value is not None:
                                    item[key] = value

                            if open_after and html_d:
                                try:
                                    os.startfile(str(html_d))
                                except Exception:
                                    pass

                        except Exception as e:
                            self.ui_call(self.log, f"❌ Ошибка дисциплины: {name}: {e}")
                    elif use_discipline:
                        item["disc_status"] = "no_rule"
                        self.ui_call(self.log, f"🟡 Правило дисциплины не найдено — выполнена только общая проверка: {name}")

                    if use_discipline:
                        self.ui_call(self.pb.step, 1)

                except Exception as e:
                    self.ui_call(self.log, f"❌ Ошибка обработки IFC: {name}: {e}")
                    self.ui_call(self.pb.step, steps_per_model)

                item["checked_at"] = datetime.now().astimezone().isoformat(timespec="microseconds")
                items.append(item)

            if items:
                try:
                    record_check_history(items[0]["dir_root"], items, profile.name, run_id=history_run_id)
                    self.ui_call(self.log, "Статистика проверок сохранена.")
                except Exception as error:
                    self.ui_call(self.log, f"❌ Не удалось сохранить статистику: {error}")

            if make_summary and items:
                try:
                    root_dir = items[0]["dir_root"]
                    s_path = summary_path(root_dir)

                    write_summary(
                        s_path,
                        items,
                        project_name=profile.name,
                        section_descriptions=profile.section_descriptions,
                        record_history=False,
                    )

                    self.ui_call(self.log, f"🆗 Сводный отчёт обновлён по именам IFC: {s_path}")

                    try:
                        os.startfile(str(s_path))
                    except Exception:
                        pass

                except Exception as e:
                    self.ui_call(self.log, f"! Не удалось создать сводный отчёт: {e}")

            self.ui_call(self.set_status, "Остановлено пользователем." if self.stop_event.is_set() else "Завершено.")

        except Exception as e:
            tb = traceback.format_exc(limit=8)
            self.ui_call(self.log, "Критическая ошибка:\n" + tb)
            self.ui_call(self.set_status, f"Ошибка: {e}")

        finally:
            self.ui_call(self._finish_run)

    def on_close(self):
        try:
            self._collect_ui_to_profile()
            self.cfg.save()
        except Exception as error:
            messagebox.showerror("Не удалось сохранить проект", str(error), parent=self)
            return
        self.stop_event.set()
        self.stop_game_process()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
