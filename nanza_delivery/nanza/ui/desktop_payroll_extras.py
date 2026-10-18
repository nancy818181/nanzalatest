"""2.9.82: Payroll > End of Service & Leave - end-of-service provision (6355 / 1552.1), annual leave records and balances,
and every payslip of a month in one PDF."""
from __future__ import annotations
import logging

import calendar
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

NAVY, GOLD, LIGHT = "#0a1931", "#d4a017", "#f8fafc"
RED, MUTED = "#8B1E1E", "#5f6b76"
LEAVE_TYPES = {"Annual leave": "annual", "Sick leave": "sick", "Unpaid leave": "unpaid", "Other": "other"}


def _month_end(text):
    month, year = (int(part) for part in str(text).strip().split("-"))
    return f"{calendar.monthrange(year, month)[1]:02d}-{month:02d}-{year}"


class PayrollExtrasMixin:
    def build_payroll_extras_page(self, page):
        year = int(getattr(self, "current_fiscal_year", datetime.now().year))
        today = datetime.now().strftime("%d-%m-%Y") if datetime.now().year == year else f"31-12-{year}"
        self.px_date = tk.StringVar(value=today); self.px_month = tk.StringVar(value=today[3:])
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(bar, text="At date", bg=LIGHT).pack(side="left"); self.date_entry(bar, self.px_date, 11).pack(side="left", padx=(4, 10))
        tk.Button(bar, text="End-of-Service Provision", command=self.show_eos_provision, bg=GOLD, fg=NAVY, border=0, padx=12, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        tk.Button(bar, text="Post Provision", command=self.post_eos_provision, bg=NAVY, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=3)
        self.action_button(bar, "Leave Balances", self.show_leave_balances).pack(side="left", padx=(12, 3))
        for label, fmt in (("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, label, lambda f=fmt: self.export_payroll_extra(f)).pack(side="left", padx=2)
        tk.Label(bar, text="Payslips of month (MM-YYYY)", bg=LIGHT).pack(side="left", padx=(18, 2)); tk.Entry(bar, textvariable=self.px_month, width=8).pack(side="left")
        tk.Button(bar, text="All Payslips (PDF)", command=self.export_month_payslips, bg=GOLD, fg=NAVY, border=0, padx=12, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        tk.Label(page, text="End of service: last salary x years of service, less the end-of-service contributions paid (Nanza's posted payroll + 'contributions before Nanza' "
                 "on the employee). Post Provision brings 1552.1 to that amount (Dr 6355 / Cr 1552.1, or Dr 1552.1 / Cr 7552.2 when it goes down). "
                 "Annual leave: 15 days a year unless set on the employee; the value is the balance x monthly salary / 30.",
                 bg=LIGHT, fg=MUTED, anchor="w", justify="left", wraplength=1150).pack(fill="x", padx=12)
        self.px_viewer = self.report_viewer(page, [90, 220, 100, 90, 130, 150, 150, 130, 130]); self.px_viewer.configure(height=8)
        leave = tk.LabelFrame(page, text="Leave taken", bg=LIGHT, padx=8, pady=4); leave.pack(fill="both", expand=True, padx=8, pady=6)
        form = tk.Frame(leave, bg=LIGHT); form.pack(fill="x")
        self.px_leave = {key: tk.StringVar() for key in ("employee", "date_from", "date_to", "days", "note")}; self.px_leave_type = tk.StringVar(value="Annual leave")
        tk.Label(form, text="Employee", bg=LIGHT).pack(side="left"); self.px_employee_box = ttk.Combobox(form, textvariable=self.px_leave["employee"], width=28, state="readonly")
        self.px_employee_box.pack(side="left", padx=(4, 8))
        for label, key, width in (("From", "date_from", 11), ("To", "date_to", 11)):
            tk.Label(form, text=label, bg=LIGHT).pack(side="left"); self.date_entry(form, self.px_leave[key], width).pack(side="left", padx=(4, 8))
        tk.Label(form, text="Days (empty = calendar days)", bg=LIGHT).pack(side="left"); tk.Entry(form, textvariable=self.px_leave["days"], width=6).pack(side="left", padx=(4, 8))
        ttk.Combobox(form, textvariable=self.px_leave_type, values=list(LEAVE_TYPES), state="readonly", width=13).pack(side="left", padx=4)
        tk.Label(form, text="Note", bg=LIGHT).pack(side="left"); tk.Entry(form, textvariable=self.px_leave["note"], width=20).pack(side="left", padx=(4, 8))
        self.action_button(form, "Add Leave", self.add_leave).pack(side="left", padx=3)
        tk.Button(form, text="Delete Selected", command=self.delete_leave, bg=RED, fg="white", border=0, padx=10, pady=6).pack(side="left", padx=3)
        self.px_leave_tree = self.table(leave, [("employee", "Employee", 220), ("from", "From", 95), ("to", "To", 95), ("days", "Days", 70), ("type", "Type", 110), ("note", "Note", 260)])
        self.load_leave_records()

    def load_leave_records(self):
        try:
            employees = self.client.employees(); records = self.client.leave_records(getattr(self, "current_fiscal_year", None))
        except Exception: employees, records = [], []
        self._px_employees = {f'{e["full_name"]} ({e.get("employee_number") or ""})': e for e in employees}
        if hasattr(self, "px_employee_box"): self.px_employee_box["values"] = list(self._px_employees)
        if not hasattr(self, "px_leave_tree"): return
        self.px_leave_tree.delete(*self.px_leave_tree.get_children())
        labels = {v: k for k, v in LEAVE_TYPES.items()}
        for r in records:
            self.px_leave_tree.insert("", "end", iid=str(r["id"]), values=(r["full_name"], _display_day(r["date_from"]), _display_day(r["date_to"]), r["days"],
                    labels.get(r["leave_type"], r["leave_type"]), r.get("note") or ""))

    def add_leave(self):
        employee = getattr(self, "_px_employees", {}).get(self.px_leave["employee"].get())
        if not employee: return messagebox.showwarning("Leave", "Choose the employee")
        item = {"employee_id": employee["id"], "date_from": self.px_leave["date_from"].get(), "date_to": self.px_leave["date_to"].get() or self.px_leave["date_from"].get(),
                "days": self.px_leave["days"].get().strip(), "leave_type": LEAVE_TYPES[self.px_leave_type.get()], "note": self.px_leave["note"].get()}
        try: self.client.save_leave(item)
        except Exception as exc: return messagebox.showerror("Leave", str(exc))
        for key in ("date_from", "date_to", "days", "note"): self.px_leave[key].set("")
        self.load_leave_records()

    def delete_leave(self):
        selected = self.px_leave_tree.selection()
        if not selected or not messagebox.askyesno("Leave", f"Delete {len(selected)} leave line(s)?"): return
        for iid in selected:
            try: self.client.delete_leave(int(iid))
            except Exception as exc: return messagebox.showerror("Leave", str(exc))
        self.load_leave_records()

    def show_eos_provision(self):
        try: result = self.client.eos_provision(self.px_date.get())
        except Exception as exc: return messagebox.showerror("End of Service", str(exc))
        self._px_result = ("End-of-service provision", result); self.show_sections(self.px_viewer, result["sections"])

    def post_eos_provision(self):
        try: result = self.client.eos_provision(self.px_date.get())
        except Exception as exc: return messagebox.showerror("End of Service", str(exc))
        change = float(result["change_lbp"])
        if not change: return messagebox.showinfo("End of Service", "The provision booked already equals the provision needed.")
        if not messagebox.askyesno("End of Service", f"Provision needed {float(result['total_lbp']):,.0f} LBP, booked {float(result['booked_lbp']):,.0f} LBP.\n"
                                   f"Post {'an increase' if change > 0 else 'a decrease'} of {abs(change):,.0f} LBP at {self.px_date.get()}?"): return
        try: posted = self.client.post_eos_provision(self.px_date.get())
        except Exception as exc: return messagebox.showerror("End of Service", str(exc))
        messagebox.showinfo("End of Service", f'Voucher {posted["voucher"]} posted.'); self.show_eos_provision(); self.load_journal(); self.load_trial()

    def show_leave_balances(self):
        try: result = self.client.leave_balances(self.px_date.get())
        except Exception as exc: return messagebox.showerror("Leave", str(exc))
        self._px_result = ("Annual leave balances", result); self.show_sections(self.px_viewer, result["sections"])

    def export_payroll_extra(self, format_name):
        current = getattr(self, "_px_result", None)
        if not current: return messagebox.showwarning("Payroll", "Show the End-of-Service Provision or the Leave Balances first")
        title, result = current
        self.save_sections(f"{title} - {self.px_date.get()}", [f"Date: {self.px_date.get()}"], result["sections"], title.replace(" ", "_").replace("-", "_"), format_name)

    def export_month_payslips(self):
        try: month_end = _month_end(self.px_month.get())
        except (ValueError, calendar.IllegalMonthError): return messagebox.showwarning("Payslips", "Enter the month as MM-YYYY, for example 03-2026")
        try: sections = self.client.payslips(month_end)
        except Exception as exc: return messagebox.showerror("Payslips", str(exc))
        company = {}
        try: company = self.client.settings()
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        self.save_sections(f"Payslips {self.px_month.get()} - {company.get('company_name') or ''}", [f"{len(sections)} employee(s)"], sections, f"Payslips_{self.px_month.get()}", "pdf")


def _display_day(value):
    text = str(value or "")
    return f"{text[8:10]}-{text[5:7]}-{text[:4]}" if len(text) == 10 and text[4] == "-" else text
