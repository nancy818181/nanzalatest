"""Payroll > NSSF & MOF Forms: the 8 official forms as editable Excel, filled from the company, the employee and the
posted payroll (2.9.107 - replaces the PDF copies)."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from cnss_forms import FORMS, FORM_BY_KEY, FORM_BY_LABEL, LEGACY_FORM_KEYS, build_workbook, form_data, summary_rows

log = logging.getLogger("saber")


class CNSSFormsMixin:
    def build_cnss_forms_page(self, parent):
        self.cnss_form_label_var = tk.StringVar(value=FORMS[0].label)
        self.cnss_employee_var = tk.StringVar()
        self.cnss_period_type_var = tk.StringVar(value="Monthly")
        self.cnss_period_index_var = tk.StringVar()
        self.cnss_year_var = tk.StringVar(value=str(getattr(self, "current_fiscal_year", datetime.now().year)))
        self.cnss_payment_date_var = tk.StringVar()
        self.cnss_payment_amount_var = tk.StringVar()
        self.cnss_payment_reference_var = tk.StringVar()
        self.cnss_payment_method_var = tk.StringVar()
        self.cnss_open_after_var = tk.BooleanVar(value=True)
        self.cnss_employee_by_display = {}
        self.cnss_current_data = None
        self.cnss_current_form_key = None
        self.cnss_last_saved_path = None

        controls = ttk.Frame(parent, padding=(10, 8))
        controls.pack(fill="x")
        ttk.Label(controls, text="Form").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.cnss_form_combo = ttk.Combobox(controls, textvariable=self.cnss_form_label_var, values=[item.label for item in FORMS],
                                            state="readonly", width=70)
        self.cnss_form_combo.grid(row=0, column=1, columnspan=3, padx=4, pady=4, sticky="ew")
        self.cnss_form_combo.bind("<<ComboboxSelected>>", self._cnss_form_changed)
        ttk.Label(controls, text="Employee").grid(row=0, column=4, padx=4, pady=4, sticky="w")
        self.cnss_employee_combo = ttk.Combobox(controls, textvariable=self.cnss_employee_var, state="readonly", width=32)
        self.cnss_employee_combo.grid(row=0, column=5, padx=4, pady=4, sticky="ew")
        self.cnss_employee_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_cnss_form_preview())

        ttk.Label(controls, text="Period").grid(row=1, column=0, padx=4, pady=4, sticky="w")
        self.cnss_period_combo = ttk.Combobox(controls, textvariable=self.cnss_period_type_var, values=["Monthly", "Quarterly", "Yearly"],
                                              state="readonly", width=14)
        self.cnss_period_combo.grid(row=1, column=1, padx=4, pady=4, sticky="w")
        self.cnss_period_combo.bind("<<ComboboxSelected>>", self._cnss_period_changed)
        ttk.Label(controls, text="Year").grid(row=1, column=2, padx=4, pady=4, sticky="e")
        self.cnss_year_entry = ttk.Entry(controls, textvariable=self.cnss_year_var, width=10)
        self.cnss_year_entry.grid(row=1, column=3, padx=4, pady=4, sticky="w")
        self.cnss_year_entry.bind("<Return>", self._cnss_period_changed)
        self.cnss_year_entry.bind("<FocusOut>", self._cnss_period_changed)
        ttk.Label(controls, text="Month / quarter").grid(row=1, column=4, padx=4, pady=4, sticky="w")
        self.cnss_period_index_combo = ttk.Combobox(controls, textvariable=self.cnss_period_index_var, state="readonly", width=15)
        self.cnss_period_index_combo.grid(row=1, column=5, padx=4, pady=4, sticky="w")
        self.cnss_period_index_combo.bind("<<ComboboxSelected>>", self._cnss_period_changed)

        payment = ttk.LabelFrame(parent, text="Payment details (optional - written on the form)")
        payment.pack(fill="x", padx=10, pady=(0, 5))
        for col, (label, variable, width) in enumerate((("Payment date", self.cnss_payment_date_var, 14),
                                                        ("Receipt / document no.", self.cnss_payment_reference_var, 20))):
            ttk.Label(payment, text=label).grid(row=0, column=col * 2, padx=5, pady=5, sticky="w")
            ttk.Entry(payment, textvariable=variable, width=width).grid(row=0, column=col * 2 + 1, padx=5, pady=5, sticky="w")
        ttk.Label(payment, text="Method").grid(row=0, column=4, padx=5, pady=5, sticky="w")
        self.cnss_payment_method_combo = ttk.Combobox(payment, textvariable=self.cnss_payment_method_var,
                                                      values=["", "Cheque", "Bank transfer", "Cash", "Unpaid"], state="readonly", width=18)
        self.cnss_payment_method_combo.grid(row=0, column=5, padx=5, pady=5, sticky="w")
        self.cnss_payment_method_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_cnss_form_preview())
        self.cnss_payment_frame = payment

        toolbar = ttk.Frame(parent, padding=(10, 2))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Auto-fill / Refresh", command=self.refresh_cnss_form_preview).pack(side="left")
        self.cnss_save_button = ttk.Button(toolbar, text="Create Excel…", command=self.save_cnss_form, state="disabled")
        self.cnss_save_button.pack(side="left", padx=6)
        ttk.Checkbutton(toolbar, text="Open in Excel after saving", variable=self.cnss_open_after_var).pack(side="left", padx=4)
        self.cnss_print_button = ttk.Button(toolbar, text="Print last saved file", command=self.print_cnss_form, state="disabled")
        self.cnss_print_button.pack(side="left", padx=6)
        self.cnss_status = ttk.Label(toolbar, text="Excel forms: yellow cells are editable, totals are formulas. Check before filing.",
                                     foreground="#1F3A93")
        self.cnss_status.pack(side="left", padx=12, fill="x", expand=True)

        notes = ttk.LabelFrame(parent, text="Missing data and review notes")
        notes.pack(fill="x", padx=10, pady=(4, 5))
        notes.columnconfigure(0, weight=1)
        self.cnss_notes_text = tk.Text(notes, height=4, wrap="word", borderwidth=0, highlightthickness=0, padx=6, pady=4, state="disabled")
        notes_scroll = ttk.Scrollbar(notes, orient="vertical", command=self.cnss_notes_text.yview)
        self.cnss_notes_text.configure(yscrollcommand=notes_scroll.set)
        self.cnss_notes_text.grid(row=0, column=0, sticky="ew")
        notes_scroll.grid(row=0, column=1, sticky="ns")
        self._show_cnss_notes(["Choose a form: it is filled automatically."])

        values = ttk.LabelFrame(parent, text="What the form will be filled with")
        values.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.cnss_values_tree = ttk.Treeview(values, columns=("field", "value"), show="headings", height=12)
        self.cnss_values_tree.heading("field", text="Field"); self.cnss_values_tree.heading("value", text="Value")
        self.cnss_values_tree.column("field", width=360, anchor="w"); self.cnss_values_tree.column("value", width=620, anchor="w")
        values_scroll = ttk.Scrollbar(values, orient="vertical", command=self.cnss_values_tree.yview)
        self.cnss_values_tree.configure(yscrollcommand=values_scroll.set)
        self.cnss_values_tree.pack(side="left", fill="both", expand=True)
        values_scroll.pack(side="left", fill="y")
        self.payroll_notebook.bind("<<NotebookTabChanged>>", self._cnss_tab_activated, add="+")

        self._refresh_cnss_period_options()
        self._update_cnss_form_controls()

    # ------------------------------------------------------------------ selection
    def refresh_cnss_employee_options(self):
        rows = getattr(self, "employee_rows", []) or []
        self.cnss_employee_by_display = {}
        for employee in rows:
            self.cnss_employee_by_display[self._cnss_employee_display(employee)] = employee
        self.cnss_employee_combo.configure(values=list(self.cnss_employee_by_display))
        if self.cnss_employee_var.get() not in self.cnss_employee_by_display:
            self.cnss_employee_var.set("")

    @staticmethod
    def _cnss_employee_display(employee):
        return f'{employee.get("employee_number") or ""} — {employee.get("full_name") or ""}'.strip(" —")

    def open_cnss_form(self, form_key=None, employee_id=None):
        if not hasattr(self, "cnss_forms_page"):
            return
        was_active = self.payroll_notebook.select() == str(self.cnss_forms_page)
        key = LEGACY_FORM_KEYS.get(str(form_key), form_key)
        if key in FORM_BY_KEY:
            self.cnss_form_label_var.set(FORM_BY_KEY[key].label)
        if employee_id is not None:
            employee = next((row for row in getattr(self, "employee_rows", []) if str(row.get("id")) == str(employee_id)), None)
            if employee:
                self.cnss_employee_var.set(self._cnss_employee_display(employee))
        self._cnss_force_refresh = True
        self.payroll_notebook.select(self.cnss_forms_page)
        self._update_cnss_form_controls()
        if was_active:
            self._cnss_force_refresh = False
            self.refresh_cnss_form_preview()

    def _cnss_tab_activated(self, _event=None):
        if self.payroll_notebook.select() != str(self.cnss_forms_page):
            return
        if getattr(self, "_cnss_force_refresh", False) or self.cnss_current_data is None:
            self._cnss_force_refresh = False
            self.after_idle(self.refresh_cnss_form_preview)

    def _selected_cnss_form(self):
        return FORM_BY_LABEL.get(self.cnss_form_label_var.get())

    def _show_cnss_notes(self, items):
        if not hasattr(self, "cnss_notes_text"):
            return
        notes = list(items or []) or ["Nothing missing. Review the values before filing."]
        self.cnss_notes_text.configure(state="normal")
        self.cnss_notes_text.delete("1.0", tk.END)
        self.cnss_notes_text.insert("1.0", "\n".join(f"• {item}" for item in notes))
        self.cnss_notes_text.configure(state="disabled")

    def _cnss_form_changed(self, _event=None):
        self._update_cnss_form_controls()
        self.refresh_cnss_form_preview()

    def _cnss_period_changed(self, _event=None):
        self._refresh_cnss_period_options()
        self._update_cnss_form_controls()
        if self._selected_cnss_form():
            self.refresh_cnss_form_preview()

    def _refresh_cnss_period_options(self):
        kind = self.cnss_period_type_var.get()
        if kind == "Monthly":
            values, default = [f"{month:02d}" for month in range(1, 13)], f"{datetime.now().month:02d}"
        elif kind == "Quarterly":
            values, default = ["Q1", "Q2", "Q3", "Q4"], f"Q{(datetime.now().month - 1) // 3 + 1}"
        else:
            values, default = ["Full year"], "Full year"
        self.cnss_period_index_combo.configure(values=values)
        if self.cnss_period_index_var.get() not in values:
            self.cnss_period_index_var.set(default)

    def _update_cnss_form_controls(self):
        form = FORM_BY_KEY.get(self._selected_cnss_form())
        if not form:
            return
        self.cnss_employee_combo.configure(state="readonly" if form.kind == "employee" else "disabled")
        if form.kind == "period":
            self.cnss_period_combo.configure(values=["Monthly", "Quarterly"], state="readonly")
            if self.cnss_period_type_var.get() not in ("Monthly", "Quarterly"):
                self.cnss_period_type_var.set("Monthly")
            self._refresh_cnss_period_options()
        elif form.kind in ("yearly", "annual"):
            self.cnss_period_type_var.set("Yearly")
            self.cnss_period_combo.configure(values=["Yearly"], state="disabled")
            self._refresh_cnss_period_options()
        else:
            self.cnss_period_combo.configure(state="disabled")
        self.cnss_period_index_combo.configure(state="readonly" if form.kind == "period" else "disabled")
        contribution = form.kind in ("period", "yearly", "annual")
        self.cnss_year_entry.configure(state="normal" if contribution else "disabled")
        payment_state = "normal" if form.kind in ("period", "yearly") else "disabled"
        for child in self.cnss_payment_frame.winfo_children():
            try:
                child.configure(state=payment_state)
            except tk.TclError:
                log.debug("widget without state", exc_info=True)
        self.cnss_payment_method_combo.configure(state="readonly" if payment_state == "normal" else "disabled")

    # ------------------------------------------------------------------ fill
    def _cnss_load(self):
        """(form key, data, notes) for the current choices; raises ValueError on a wrong year."""
        key = self._selected_cnss_form()
        form = FORM_BY_KEY[key]
        company = self.client.settings()
        employee = self.cnss_employee_by_display.get(self.cnss_employee_var.get())
        report, filed, year, index = None, [], None, 1
        period_type = self.cnss_period_type_var.get().lower()
        if form.kind in ("period", "yearly", "annual"):
            try:
                year = int(self.cnss_year_var.get().strip())
            except ValueError:
                raise ValueError("Enter a valid year.") from None
            if not 1900 <= year <= 2200:
                raise ValueError("Enter a valid year.")
            if form.kind == "period":
                text = self.cnss_period_index_var.get()
                index = int(text) if period_type == "monthly" else int(text[1:])
                report = self.client.payroll_report("NSSF", period_type, year, index, "both", False)
            else:
                period_type = "yearly"
                report = self.client.payroll_report("NSSF", "yearly", year, 1, "both", False)
                filed = self.client.nssf_filed_wages(year)
        payment = {"payment_date": self.cnss_payment_date_var.get().strip(), "reference": self.cnss_payment_reference_var.get().strip(),
                   "method": self.cnss_payment_method_var.get().strip()}
        data, notes = form_data(key, company, employee, report, filed, year=year, period_type=period_type, index=index, payment_details=payment)
        return key, data, notes

    def refresh_cnss_form_preview(self):
        key = self._selected_cnss_form()
        if not key:
            return
        try:
            key, data, notes = self._cnss_load()
        except (ValueError, RuntimeError, OSError) as exc:
            self.cnss_current_data = None
            self.cnss_save_button.configure(state="disabled")
            self.cnss_status.configure(text=f"Could not fill this form: {exc}")
            return self._show_cnss_notes([str(exc)])
        self.cnss_current_data, self.cnss_current_form_key = data, key
        self.cnss_values_tree.delete(*self.cnss_values_tree.get_children())
        for label, value in summary_rows(key, data):
            self.cnss_values_tree.insert("", "end", values=(label, value if value not in (None, "") else "— (fill in Excel)"))
        self._show_cnss_notes(notes)
        form = FORM_BY_KEY[key]
        ready = not (form.kind == "employee" and not self.cnss_employee_by_display.get(self.cnss_employee_var.get()))
        self.cnss_save_button.configure(state="normal" if ready else "disabled")
        self.cnss_status.configure(text=f"{form.label.split('|')[0].strip()} · filled automatically · press Create Excel")

    def save_cnss_form(self):
        if not self.cnss_current_data:
            return messagebox.showwarning("NSSF & MOF Forms", "Choose a form first.", parent=self)
        key = self.cnss_current_form_key
        form = FORM_BY_KEY[key]
        employee = self.cnss_employee_by_display.get(self.cnss_employee_var.get())
        suffix = (employee or {}).get("employee_number") if form.kind == "employee" else (
            self.cnss_year_var.get().strip() + ("-" + self.cnss_period_index_var.get() if form.kind == "period" else "")
            if form.kind != "company" else "company")
        name = form.label.split("—")[0].strip().replace(" ", "_")
        target = filedialog.asksaveasfilename(parent=self, title="Save the filled form", defaultextension=".xlsx",
                                              initialfile=f"{name}_{suffix or 'form'}.xlsx", filetypes=[("Excel workbook", "*.xlsx")])
        if not target:
            return
        try:
            build_workbook(key, self.cnss_current_data, target)
        except PermissionError:
            return messagebox.showerror("NSSF & MOF Forms", "Close the file in Excel, then try again.", parent=self)
        except (OSError, ValueError, KeyError) as exc:
            log.error("CNSS form not saved", exc_info=True)
            return messagebox.showerror("NSSF & MOF Forms", f"Could not save the form: {exc}", parent=self)
        self.cnss_last_saved_path = Path(target)
        self.cnss_print_button.configure(state="normal" if sys.platform == "win32" else "disabled")
        self.cnss_status.configure(text=f"Saved: {target}")
        if self.cnss_open_after_var.get() and sys.platform == "win32":
            try:
                os.startfile(target)
            except OSError:
                log.warning("could not open %s", target, exc_info=True)
        else:
            messagebox.showinfo("NSSF & MOF Forms", f"Saved:\n{target}", parent=self)

    def print_cnss_form(self):
        if sys.platform != "win32":
            return messagebox.showerror("NSSF & MOF Forms", "Printing from this tab is supported only on Windows.", parent=self)
        if not self.cnss_last_saved_path or not self.cnss_last_saved_path.is_file():
            return messagebox.showwarning("NSSF & MOF Forms", "Save a filled form first.", parent=self)
        try:
            os.startfile(str(self.cnss_last_saved_path), "print")
        except OSError as exc:
            messagebox.showerror("NSSF & MOF Forms", f"Could not print: {exc}", parent=self)
