# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
import traceback

from ifc_ids_validator.config import (
    AppConfig, DisciplineRule, Profile, CONF_PATH,
    get_rules_path, save_rules
)
from ifc_ids_validator.validator import (
    MATCH_CONTAINS,
    match_rule, open_ids, open_ifc, emit_reports, get_ifc_site_data,
    _named_block_percent_from_html
)
from ifc_ids_validator.summary import write_summary, summary_path

APP_TITLE = "IFC → IDS HTML отчёт (двухэтапная проверка)"
DEFAULT_REPORT_SUBFOLDER = "Отчет IDS"
SUB_MSSK = "МССК"
SUB_DISC = "Дисциплинарные"

# =========================
# ФИРМЕННЫЕ ЦВЕТА / ТЕМА
# =========================
COLOR_BG = "#F4F7FB"
COLOR_SURFACE = "#FFFFFF"
COLOR_SURFACE_2 = "#EEF3FA"
COLOR_BORDER = "#D6DFEB"
COLOR_TEXT = "#183153"
COLOR_MUTED = "#6B7A90"
COLOR_BLUE = "#0B4EA2"       # основной синий
COLOR_BLUE_DARK = "#083A7A"  # тёмный синий
COLOR_RED = "#E53935"        # акцентный красный
COLOR_HOVER = "#0D5EC2"
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
        self.var_code = tk.StringVar(value=(initial.code if initial else ""))
        self.var_ids = tk.StringVar(value=(initial.ids_path if initial else ""))

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
        frm.grid_columnconfigure(1, weight=1, minsize=360)
        frm.grid_columnconfigure(2, weight=0)

        ttk.Label(frm, text="Паттерн в имени файла:", style="CardLabel.TLabel")\
            .grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Entry(frm, textvariable=self.var_pattern, width=50)\
            .grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(frm, text="Код дисциплины:", style="CardLabel.TLabel")\
            .grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frm, textvariable=self.var_code, width=20)\
            .grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(frm, text="IDS-файл дисциплины:", style="CardLabel.TLabel")\
            .grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frm, textvariable=self.var_ids)\
            .grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(frm, text="Выбрать…", command=self._pick_ids, style="Secondary.TButton")\
            .grid(row=2, column=2, sticky="w", padx=(8, 0), pady=4)

        btns = tk.Frame(frm, bg=COLOR_SURFACE)
        btns.grid(row=3, column=0, columnspan=3, sticky="e", pady=(14, 0))

        ttk.Button(btns, text="Отмена", width=14, command=self.destroy, style="Secondary.TButton").pack(side="right")
        ttk.Button(btns, text="OK", width=14, command=self._on_ok, style="Primary.TButton").pack(side="right", padx=(0, 8))

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _pick_ids(self):
        path = filedialog.askopenfilename(
            title="Выберите IDS спецификацию (дисциплина)",
            filetypes=[("IDS files", "*.ids;*.xml"), ("All files", "*.*")]
        )
        if path:
            self.var_ids.set(path)

    def _on_ok(self):
        patt = self.var_pattern.get().strip()
        code = self.var_code.get().strip()
        ids_path = self.var_ids.get().strip()
        if not patt or not code or not ids_path:
            messagebox.showwarning("Не заполнено", "Укажите паттерн, код и IDS-файл.")
            return
        self.result = {"pattern": patt, "code": code, "ids_path": ids_path}
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
        entry.bind("<Button-4>", self._on_mousewheel)  # Linux
        entry.bind("<Button-5>", self._on_mousewheel)  # Linux

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


class RulesSettingsDialog(tk.Toplevel):
    def __init__(self, master, profile: Profile, mode_title: str):
        super().__init__(master)
        self.title(f"Настройки — {mode_title}")
        self.geometry("980x600")
        self.resizable(False, False)
        self.result = False
        self.profile = profile
        self.mode_title = mode_title
        self.configure(bg=COLOR_BG)

        self.var_common = tk.StringVar(value=self.profile.common_ids_path)
        self.local_rules = [
            DisciplineRule(pattern=r.pattern, code=r.code, ids_path=r.ids_path)
            for r in self.profile.disc_rules
        ]
        self.local_section_descriptions = [
            [str(row[0]), str(row[1])]
            for row in self.profile.section_descriptions
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        if not self.local_section_descriptions:
            self.local_section_descriptions = [["", ""]]

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
            text=f"Настройки набора правил: {mode_title}",
            bg=COLOR_BLUE,
            fg="white",
            font=("Segoe UI Semibold", 12)
        ).pack(side="left", padx=16)

        body = tk.Frame(card, bg=COLOR_SURFACE, padx=16, pady=16)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        frm_header = tk.Frame(body, bg=COLOR_SURFACE)
        frm_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        frm_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            frm_header,
            text=f"Набор настроек: {mode_title}",
            style="SectionTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frm_header,
            text=f"Файл правил: {get_rules_path(mode_title)}",
            style="Muted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        frm_common = ttk.LabelFrame(body, text=" Общая IDS (Классификатор МССК) ", padding=12, style="Card.TLabelframe")
        frm_common.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        frm_common.grid_columnconfigure(1, weight=1)

        ttk.Label(frm_common, text="Путь к общей IDS:", style="CardLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frm_common, textvariable=self.var_common).grid(row=0, column=1, sticky="ew")
        ttk.Button(frm_common, text="Выбрать…", command=self.pick_common_ids, style="Secondary.TButton").grid(row=0, column=2, padx=(8, 0))

        frm_rules = ttk.LabelFrame(body, text=" Правила дисциплин ", padding=12, style="Card.TLabelframe")
        frm_rules.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        frm_rules.grid_columnconfigure(0, weight=1)
        frm_rules.grid_rowconfigure(0, weight=1)

        left = tk.Frame(frm_rules, bg=COLOR_SURFACE)
        left.grid(row=0, column=0, sticky="nsew")
        right = tk.Frame(frm_rules, bg=COLOR_SURFACE)
        right.grid(row=0, column=1, sticky="ns", padx=(12, 0))

        self.rules_list = tk.Listbox(
            left,
            height=14,
            font=FONT_MAIN,
            bg="white",
            fg=COLOR_TEXT,
            selectbackground=COLOR_BLUE,
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            activestyle="none"
        )
        self.rules_list.pack(fill="both", expand=True)
        self.refresh_rules()

        ttk.Button(right, text="Добавить…", command=self.on_rule_add, style="Primary.TButton").pack(fill="x")
        ttk.Button(right, text="Изменить…", command=self.on_rule_edit, style="Secondary.TButton").pack(fill="x", pady=6)
        ttk.Button(right, text="Удалить", command=self.on_rule_del, style="Danger.TButton").pack(fill="x")

        frm_bottom = tk.Frame(body, bg=COLOR_SURFACE)
        frm_bottom.grid(row=3, column=0, sticky="ew")
        frm_bottom.grid_columnconfigure(0, weight=1)

        left_btns = tk.Frame(frm_bottom, bg=COLOR_SURFACE)
        left_btns.pack(side="left")

        right_btns = tk.Frame(frm_bottom, bg=COLOR_SURFACE)
        right_btns.pack(side="right")

        ttk.Button(
            left_btns,
            text="Описание разделов",
            width=20,
            command=self.open_sections_description,
            style="Secondary.TButton"
        ).pack(side="left")

        ttk.Button(
            right_btns,
            text="Отмена",
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

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def refresh_rules(self):
        self.rules_list.delete(0, "end")
        for r in self.local_rules:
            self.rules_list.insert("end", f"{r.pattern}  →  {r.code}  |  {r.ids_path}")

    def pick_common_ids(self):
        current = self.var_common.get().strip()
        initial_dir = Path(current).parent if current else Path.home()
        path = filedialog.askopenfilename(
            title="Выберите общую IDS (Классификатор МССК)",
            filetypes=[("IDS files", "*.ids;*.xml"), ("All files", "*.*")],
            initialdir=str(initial_dir)
        )
        if path:
            self.var_common.set(path)

    def open_sections_description(self):
        dlg = SectionsDescriptionDialog(self, self.local_section_descriptions)
        self.wait_window(dlg)
        if dlg.result:
            self.local_section_descriptions = dlg.result

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
        self.profile.common_ids_path = self.var_common.get().strip()
        self.profile.disc_rules = [
            DisciplineRule(pattern=r.pattern, code=r.code, ids_path=r.ids_path)
            for r in self.local_rules
        ]
        self.profile.section_descriptions = [
            [str(row[0]), str(row[1])]
            for row in self.local_section_descriptions
            if len(row) >= 2
        ]
        self.result = True
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x950")
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)

        self.ifc_paths = []
        self.open_after = tk.BooleanVar(value=False)
        self.create_summary = tk.BooleanVar(value=True)
        self.is_running = False
        self.ui_queue = queue.Queue()

        self.cfg: AppConfig = AppConfig.load()
        self.profile: Profile = self.cfg.get_active()
        self.current_rules_mode = self.profile.rules_mode
        self.rules_mode_var = tk.StringVar(value=self.current_rules_mode)

        self._setup_style()

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_project_tabs()
        self._build_main_ui()
        self._apply_profile_to_ui()

        self.after(100, self.process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- style ----------
    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=FONT_MAIN)

        style.configure(
            "TNotebook",
            background=COLOR_BG,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0)
        )
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI Semibold", 10),
            padding=(12, 6),   # неактивная вкладка меньше
            background=COLOR_SURFACE_2,
            foreground=COLOR_TEXT,
            borderwidth=0
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLOR_BLUE), ("active", "#DDE8F8")],
            foreground=[("selected", "white"), ("active", COLOR_TEXT)],
            padding=[("selected", (20, 10)), ("!selected", (12, 6))]   # активная вкладка больше
        )

        style.configure(
            "Primary.TButton",
            background=COLOR_BLUE,
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10)
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLOR_HOVER), ("disabled", "#9FB6D9")],
            foreground=[("disabled", "white")]
        )

        style.configure(
            "Secondary.TButton",
            background=COLOR_SURFACE_2,
            foreground=COLOR_TEXT,
            borderwidth=0,
            relief="flat",
            padding=(14, 8),
            font=("Segoe UI Semibold", 10)
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#E4ECF8"), ("disabled", "#F1F4F8")]
        )

        style.configure(
            "Danger.TButton",
            background=COLOR_RED,
            foreground="white",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10)
        )
        style.map(
            "Danger.TButton",
            background=[("active", "#C62D2A"), ("disabled", "#E9A3A1")]
        )

        style.configure(
            "Action.TButton",
            background=COLOR_BLUE_DARK,
            foreground="white",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10)
        )
        style.map(
            "Action.TButton",
            background=[("active", "#0A458F"), ("disabled", "#9FB1C8")]
        )

        style.configure(
            "Card.TLabelframe",
            background=COLOR_SURFACE,
            bordercolor=COLOR_BORDER,
            relief="solid",
            borderwidth=1
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            font=("Segoe UI Semibold", 10)
        )

        style.configure("CardLabel.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=FONT_MAIN)
        style.configure("Muted.TLabel", background=COLOR_SURFACE, foreground=COLOR_MUTED, font=FONT_SMALL)
        style.configure("SectionTitle.TLabel", background=COLOR_SURFACE, foreground=COLOR_TEXT, font=("Segoe UI Semibold", 11))
        style.configure("HeaderTitle.TLabel", background=COLOR_BLUE_DARK, foreground="white", font=FONT_TITLE)
        style.configure("HeaderSub.TLabel", background=COLOR_BLUE_DARK, foreground="#D9E7FB", font=FONT_SUBTITLE)

        style.configure(
            "Corp.TRadiobutton",
            background=COLOR_SURFACE,
            foreground=COLOR_TEXT,
            font=FONT_MAIN
        )

        style.configure(
            "Corp.TCheckbutton",
            background=COLOR_BG,
            foreground=COLOR_TEXT,
            font=FONT_MAIN
        )

        style.configure(
            "Corp.Horizontal.TProgressbar",
            troughcolor="#E6EDF7",
            background=COLOR_BLUE,
            bordercolor="#E6EDF7",
            lightcolor=COLOR_BLUE,
            darkcolor=COLOR_BLUE
        )

        style.configure(
            "Treeview",
            background="white",
            foreground=COLOR_TEXT,
            rowheight=28,
            fieldbackground="white",
            bordercolor=COLOR_BORDER,
            borderwidth=1,
            font=FONT_MAIN
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_SURFACE_2,
            foreground=COLOR_TEXT,
            font=("Segoe UI Semibold", 10)
        )
        style.map(
            "Treeview",
            background=[("selected", COLOR_BLUE)],
            foreground=[("selected", "white")]
        )

    # ---------- UI ----------
    def _build_header(self):
        header = tk.Frame(self, bg=COLOR_BLUE_DARK, height=84)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.pack_propagate(False)

        left = tk.Frame(header, bg=COLOR_BLUE_DARK)
        left.pack(side="left", fill="both", expand=True, padx=18, pady=12)

        tk.Label(
            left,
            text="IFC CHECKER",
            bg=COLOR_BLUE_DARK,
            fg="white",
            font=("Bahnschrift Light", 20)
        ).pack(anchor="w")

        tk.Label(
            left,
            text="Проверка IFC → IDS • HTML-отчёты",
            bg=COLOR_BLUE_DARK,
            fg="#D9E7FB",
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(2, 0))

        accent = tk.Frame(header, bg=COLOR_RED, width=10)
        accent.pack(side="right", fill="y")

    def _build_project_tabs(self):
        wrap = tk.Frame(self, bg=COLOR_BG)
        wrap.grid(row=1, column=0, sticky="ew", padx=14, pady=(12, 0))
        wrap.grid_columnconfigure(0, weight=1)

        card = tk.Frame(
            wrap,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        top_projects = tk.Frame(card, bg=COLOR_SURFACE, padx=14, pady=12)
        top_projects.grid(row=0, column=0, sticky="ew")
        top_projects.grid_columnconfigure(0, weight=1)

        tabs_wrap = tk.Frame(top_projects, bg=COLOR_SURFACE)
        tabs_wrap.grid(row=0, column=0, sticky="ew")
        tabs_wrap.grid_columnconfigure(0, weight=1)
        tabs_wrap.grid_rowconfigure(0, weight=1)

        self.project_tabs_canvas = tk.Canvas(
            tabs_wrap,
            bg=COLOR_SURFACE,
            highlightthickness=0,
            bd=0,
            height=42
        )
        self.project_tabs_canvas.grid(row=0, column=0, sticky="ew")

        self.project_tabs_scroll = ttk.Scrollbar(
            tabs_wrap,
            orient="horizontal",
            command=self.project_tabs_canvas.xview
        )
        self.project_tabs_scroll.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        self.project_tabs_canvas.configure(xscrollcommand=self.project_tabs_scroll.set)

        self.nb_projects = ttk.Notebook(self.project_tabs_canvas)
        self.nb_projects_window = self.project_tabs_canvas.create_window(
            (0, 0),
            window=self.nb_projects,
            anchor="nw"
        )

        self.nb_projects.bind("<<NotebookTabChanged>>", self.on_profile_tab_change)
        self.nb_projects.bind("<Configure>", self._update_project_tabs_scrollregion)
        self.project_tabs_canvas.bind("<Configure>", self._on_project_tabs_canvas_configure)

        btns = tk.Frame(top_projects, bg=COLOR_SURFACE)
        btns.grid(row=0, column=1, sticky="e", padx=(14, 0))

        ttk.Button(btns, text="➕", width=4, command=self.on_profile_add, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Переименовать", command=self.on_profile_rename, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Сохранить", command=self.on_profile_save, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Экспорт", command=self.on_profile_export, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Импорт", command=self.on_profile_import, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Удалить", command=self.on_profile_delete, style="Danger.TButton").pack(side="left")

        self._refresh_project_tabs()

    def _build_main_ui(self):
        main = tk.Frame(self, bg=COLOR_BG)
        main.grid(row=2, column=0, sticky="nsew", padx=14, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # Верхняя часть: IFC + правила
        top_area = tk.Frame(main, bg=COLOR_BG)
        top_area.grid(row=0, column=0, sticky="ew")
        top_area.grid_columnconfigure(0, weight=1)
        top_area.grid_columnconfigure(1, weight=1)

        # ---------- IFC ----------
        frm_ifc = ttk.LabelFrame(top_area, text=" Файлы IFC ", padding=12, style="Card.TLabelframe")
        frm_ifc.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        frm_ifc.grid_columnconfigure(0, weight=1)
        frm_ifc.grid_rowconfigure(1, weight=1)

        btns_ifc = tk.Frame(frm_ifc, bg=COLOR_SURFACE)
        btns_ifc.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(btns_ifc, text="Выбрать несколько…", command=self.pick_ifcs, style="Primary.TButton").pack(side="left")
        ttk.Button(btns_ifc, text="Очистить", command=self.clear_ifcs, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        list_wrap = tk.Frame(frm_ifc, bg=COLOR_SURFACE)
        list_wrap.grid(row=1, column=0, sticky="nsew")
        list_wrap.grid_columnconfigure(0, weight=1)
        list_wrap.grid_rowconfigure(0, weight=1)

        self.lst_ifc = tk.Listbox(
            list_wrap,
            height=10,
            font=FONT_MAIN,
            bg="white",
            fg=COLOR_TEXT,
            selectbackground=COLOR_BLUE,
            selectforeground="white",
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            activestyle="none"
        )
        self.lst_ifc.grid(row=0, column=0, sticky="nsew")

        sb_ifc = ttk.Scrollbar(list_wrap, orient="vertical", command=self.lst_ifc.yview)
        sb_ifc.grid(row=0, column=1, sticky="ns")
        self.lst_ifc.config(yscrollcommand=sb_ifc.set)

        # ---------- RULES ----------
        frm_modes = ttk.LabelFrame(top_area, text=" Наборы правил ", padding=12, style="Card.TLabelframe")
        frm_modes.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 10))
        for c in range(3):
            frm_modes.grid_columnconfigure(c, weight=1)

        self._build_rule_mode_column(frm_modes, 0, "Приказ 64")
        self._build_rule_mode_column(frm_modes, 1, "Приказ 178")
        self._build_rule_mode_column(frm_modes, 2, "Настроить")

        # Средняя часть: опции + прогресс + лог
        content = tk.Frame(main, bg=COLOR_BG)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        # Options
        frm_opts = tk.Frame(content, bg=COLOR_BG)
        frm_opts.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Checkbutton(
            frm_opts,
            text="Открывать отчёты после генерации",
            variable=self.open_after,
            style="Corp.TCheckbutton"
        ).pack(side="left")

        self.create_summary.set(bool(self.profile.create_summary))
        ttk.Checkbutton(
            frm_opts,
            text="Создать сводный HTML",
            variable=self.create_summary,
            style="Corp.TCheckbutton"
        ).pack(side="left", padx=(18, 0))

        ttk.Button(
            frm_opts,
            text="Открыть папку отчётов",
            command=self.open_reports_folder,
            style="Secondary.TButton"
        ).pack(side="right")

        # Progress card
        frm_prog = ttk.LabelFrame(content, text=" Статус ", padding=12, style="Card.TLabelframe")
        frm_prog.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.lbl_progress = ttk.Label(frm_prog, text="Готово.", style="SectionTitle.TLabel", anchor="w")
        self.lbl_progress.pack(fill="x")
        self.pb = ttk.Progressbar(frm_prog, orient="horizontal", mode="determinate", style="Corp.Horizontal.TProgressbar")
        self.pb.pack(fill="x", pady=(8, 0), ipady=5)

        # Log card
        frm_log = ttk.LabelFrame(content, text=" Журнал ", padding=12, style="Card.TLabelframe")
        frm_log.grid(row=2, column=0, sticky="nsew")
        frm_log.grid_columnconfigure(0, weight=1)
        frm_log.grid_rowconfigure(0, weight=1)

        text_wrap = tk.Frame(frm_log, bg=COLOR_SURFACE)
        text_wrap.grid(row=0, column=0, sticky="nsew")
        text_wrap.grid_columnconfigure(0, weight=1)
        text_wrap.grid_rowconfigure(0, weight=1)

        self.txt_log = tk.Text(
            text_wrap,
            height=13,
            font=("Consolas", 10),
            bg="white",
            fg=COLOR_TEXT,
            relief="flat",
            wrap="word",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            insertbackground=COLOR_TEXT
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")

        sb_log = ttk.Scrollbar(text_wrap, orient="vertical", command=self.txt_log.yview)
        sb_log.grid(row=0, column=1, sticky="ns")
        self.txt_log.config(yscrollcommand=sb_log.set)

        # Bottom buttons
        bottom = tk.Frame(main, bg=COLOR_BG)
        bottom.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        self.btn_stop = ttk.Button(
            bottom,
            text="Остановить",
            command=self.on_stop,
            state="disabled",
            style="Danger.TButton",
            width=34
        )
        self.btn_stop.pack(side="right")

        self.btn_run = ttk.Button(
            bottom,
            text="Проверить все модели (МССК → дисциплины)",
            command=self.on_run,
            style="Action.TButton",
            width=34
        )
        self.btn_run.pack(side="right", padx=(0, 10))

    def _build_rule_mode_column(self, parent, column, mode_title):
        cell = tk.Frame(
            parent,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        cell.grid(row=0, column=column, sticky="nsew", padx=6)
        cell.grid_columnconfigure(0, weight=1)

        top = tk.Frame(cell, bg=COLOR_SURFACE, padx=12, pady=12)
        top.pack(fill="both", expand=True)

        ttk.Radiobutton(
            top,
            text=f"Использовать «{mode_title}»",
            variable=self.rules_mode_var,
            value=mode_title,
            command=self.on_rules_mode_change,
            style="Corp.TRadiobutton"
        ).pack(anchor="w", pady=(0, 12))

        ttk.Button(
            top,
            text=mode_title,
            command=lambda m=mode_title: self.open_rules_settings(m),
            style="Primary.TButton"
        ).pack(fill="x")

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
        self.txt_log.insert("end", msg + "\n")
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
        self.current_rules_mode = self.profile.rules_mode
        self.rules_mode_var.set(self.current_rules_mode)
        self.create_summary.set(bool(self.profile.create_summary))
        self.ifc_paths = list(self.profile.ifc_paths)
        self._refresh_ifc_list()

    def _collect_ui_to_profile(self):
        self.profile.create_summary = bool(self.create_summary.get())
        self.profile.ifc_paths = list(self.ifc_paths)
        self.profile.rules_mode = self.rules_mode_var.get()

    def _load_rules_for_mode(self, mode_title: str):
        from ifc_ids_validator.config import load_rules

        rules_data = load_rules(mode_title)
        self.profile.rules_mode = mode_title
        self.profile.common_ids_path = rules_data.get("common_ids_path", "")
        self.profile.disc_rules = list(rules_data.get("disc_rules", []))
        self.profile.section_descriptions = [
            [str(row[0]), str(row[1])]
            for row in rules_data.get("section_descriptions", [])
            if isinstance(row, (list, tuple)) and len(row) >= 2
        ]
        self.current_rules_mode = mode_title
        self.rules_mode_var.set(mode_title)

    def _refresh_ifc_list(self):
        self.lst_ifc.delete(0, "end")
        for p in self.ifc_paths:
            self.lst_ifc.insert("end", p)

    # ---------- project tabs ----------
    def on_profile_tab_change(self, _evt=None):
        if not self.nb_projects.tabs():
            return

        self._collect_ui_to_profile()

        current_tab = self.nb_projects.select()
        if not current_tab:
            return

        idx = self.nb_projects.index(current_tab)
        sel = self._tab_profile_names[idx]

        self.cfg.set_active(sel)
        self.profile = self.cfg.get_active()
        self._load_rules_for_mode(self.profile.rules_mode)
        self._apply_profile_to_ui()
        self.cfg.save()

    def on_profile_add(self):
        name = simpledialog.askstring("Новый проект", "Название проекта:", parent=self) or ""
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

    # ---------- rules ----------
    def on_rules_mode_change(self):
        selected_mode = self.rules_mode_var.get()
        if not selected_mode:
            return
        self._load_rules_for_mode(selected_mode)
        self.cfg.save()

    def open_rules_settings(self, mode_title: str):
        self.rules_mode_var.set(mode_title)
        self._load_rules_for_mode(mode_title)

        dlg = RulesSettingsDialog(self, self.profile, mode_title)
        self.wait_window(dlg)
        if dlg.result:
            self.profile.rules_mode = mode_title
            self.rules_mode_var.set(mode_title)

            save_rules(
                mode_title,
                self.profile.common_ids_path,
                self.profile.disc_rules,
                self.profile.section_descriptions
            )

            self.cfg.save()

    # ---------- IFC ----------
    def pick_ifcs(self):
        initial = self.profile.last_ifc_dir or str(Path.home())
        paths = filedialog.askopenfilenames(
            title="Выберите одну или несколько IFC моделей",
            filetypes=[("IFC files", "*.ifc;*.ifczip"), ("All files", "*.*")],
            initialdir=initial
        )
        if paths:
            self.ifc_paths = list(paths)
            self.profile.ifc_paths = list(self.ifc_paths)
            self._refresh_ifc_list()
            self.profile.last_ifc_dir = str(Path(self.ifc_paths[0]).parent)
            self.cfg.save()

    def clear_ifcs(self):
        self.ifc_paths = []
        self.profile.ifc_paths = []
        self._refresh_ifc_list()
        self.cfg.save()

    def open_reports_folder(self):
        if not self.ifc_paths:
            messagebox.showinfo("Нет файлов", "Сначала выберите хотя бы один файл IFC.")
            return
        first_dir = Path(self.ifc_paths[0]).parent
        target = first_dir / DEFAULT_REPORT_SUBFOLDER
        target.mkdir(exist_ok=True)
        os.startfile(str(target))

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
        if cids and not Path(cids).exists():
            messagebox.showwarning("Не найдена общая IDS", f"Файл не найден:\n{cids}")
            return

        self.is_running = True
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.pb.config(value=0, maximum=len(self.ifc_paths) * 2)
        self.txt_log.delete("1.0", "end")
        self.set_status("Старт валидации…")

        threading.Thread(target=self.worker_run_two_passes, daemon=True).start()

    def on_stop(self):
        self.is_running = False

    def worker_run_two_passes(self):
        total = len(self.ifc_paths)
        open_after = self.open_after.get()
        make_summary = bool(self.create_summary.get())
        common_ids = self.profile.common_ids_path

        items_map: dict[str, dict] = {}

        common_specs = None
        if common_ids:
            try:
                self.ui_call(self.set_status, "Чтение общей IDS…")
                common_specs = open_ids(common_ids)
            except Exception as e:
                self.ui_call(self.log, f"! Ошибка чтения общей IDS: {e}")
                common_specs = None

        try:
            for i, ifc_path in enumerate(self.ifc_paths, start=1):
                if not self.is_running:
                    self.ui_call(self.set_status, "Остановлено пользователем.")
                    break

                name = Path(ifc_path).name
                model = open_ifc(ifc_path)
                site_data = get_ifc_site_data(model)

                ifc_p = Path(ifc_path)
                root_dir = ifc_p.parent / DEFAULT_REPORT_SUBFOLDER
                mssk_dir = root_dir / SUB_MSSK
                disc_dir = root_dir / SUB_DISC
                mssk_dir.mkdir(parents=True, exist_ok=True)
                disc_dir.mkdir(parents=True, exist_ok=True)

                item = items_map.get(ifc_path) or {
                    "model": name,
                    "site_name": None,
                    "x": None,
                    "y": None,
                    "z": None,
                    "lat": None,
                    "lon": None,
                    "site_building_pct": None,
                    "building_pct": None,
                    "storey_pct": None,
                    "dir_root": root_dir,
                    "common": None,
                    "common_pct": None,
                    "disc": None,
                    "disc_pct": None,
                    "disc_code": None,
                }

                item.update(site_data)

                if common_specs:
                    try:
                        self.ui_call(self.set_status, f"[{i}/{total}] МССК: {name}")
                        common_specs.validate(model)
                        out_base_common = mssk_dir / ifc_p.stem
                        html_c, json_c, pct_c = emit_reports(common_specs, out_base_common, common_ids, ifc_path)
                        self.ui_call(self.log, f"✓ МССК отчёт: {html_c}")
                        item["common"] = html_c
                        item["common_pct"] = pct_c
                        if open_after and html_c:
                            try:
                                webbrowser.open(html_c.as_uri())
                            except Exception:
                                pass
                    except Exception as e:
                        self.ui_call(self.log, f"! МССК ошибка: {e}")
                else:
                    self.ui_call(self.log, "• Общая IDS не задана — PASS1 пропущен.")

                items_map[ifc_path] = item
                self.ui_call(self.pb.step, 1)

            for j, ifc_path in enumerate(self.ifc_paths, start=1):
                if not self.is_running:
                    self.ui_call(self.set_status, "Остановлено пользователем.")
                    break

                name = Path(ifc_path).name
                self.ui_call(self.set_status, f"[{j}/{total}] Дисциплина: {name}")
                model = open_ifc(ifc_path)

                ifc_p = Path(ifc_path)
                root_dir = ifc_p.parent / DEFAULT_REPORT_SUBFOLDER
                disc_dir = root_dir / SUB_DISC
                disc_dir.mkdir(parents=True, exist_ok=True)

                item = items_map.get(ifc_path)
                if item is None:
                    item = {
                        "model": name,
                        "site_name": None,
                        "x": None,
                        "y": None,
                        "z": None,
                        "lat": None,
                        "lon": None,
                        "site_building_pct": None,
                        "building_pct": None,
                        "storey_pct": None,
                        "dir_root": root_dir,
                        "common": None,
                        "common_pct": None,
                        "disc": None,
                        "disc_pct": None,
                        "disc_code": None,
                    }

                if not item.get("site_name"):
                    item.update(get_ifc_site_data(model))

                rules = [r.__dict__ for r in self.profile.disc_rules]
                rule, code = match_rule(name, rules, self.cfg.match_mode)
                if rule:
                    d_ids = (rule.get("ids_path") or "").strip()
                    try:
                        d_specs = open_ids(d_ids)
                        d_specs.validate(model)
                        out_base_disc = disc_dir / f"{ifc_p.stem}.__{code}"
                        html_d, json_d, pct_d = emit_reports(d_specs, out_base_disc, d_ids, ifc_path)
                        self.ui_call(self.log, f"✓ Дисциплина ({code}): {html_d}")
                        item["disc"] = html_d
                        item["disc_pct"] = pct_d
                        item["disc_code"] = code
                        item["site_building_pct"] = _named_block_percent_from_html(html_d, "Участок застройки")
                        item["building_pct"] = _named_block_percent_from_html(html_d, "Здание (сооружение)")
                        item["storey_pct"] = _named_block_percent_from_html(html_d, "Этаж (уровень)")
                        if self.open_after.get() and html_d:
                            try:
                                webbrowser.open(html_d.as_uri())
                            except Exception:
                                pass
                    except Exception as e:
                        self.ui_call(self.log, f"! Ошибка дисциплины ({code}): {e}")
                else:
                    self.ui_call(self.log, "• Правило дисциплины не найдено (пропуск).")

                items_map[ifc_path] = item
                self.ui_call(self.pb.step, 1)

            items = list(items_map.values())
            if make_summary and items:
                try:
                    root_dir = items[0]["dir_root"]
                    s_path = summary_path(root_dir)
                    write_summary(s_path, items, project_name=self.profile.name)
                    self.ui_call(self.log, f"★ Сводный отчёт: {s_path}")
                    try:
                        webbrowser.open(s_path.as_uri())
                    except Exception:
                        pass
                except Exception as e:
                    self.ui_call(self.log, f"! Не удалось создать сводный отчёт: {e}")

            self.ui_call(self.set_status, "Завершено.")
        except Exception as e:
            tb = traceback.format_exc(limit=8)
            self.ui_call(self.log, "Критическая ошибка:\n" + tb)
            self.ui_call(self.set_status, f"Ошибка: {e}")
        finally:
            self.is_running = False
            self.ui_call(self.btn_run.config, state="normal")
            self.ui_call(self.btn_stop.config, state="disabled")

    def on_close(self):
        try:
            self._collect_ui_to_profile()
            self.cfg.save()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()