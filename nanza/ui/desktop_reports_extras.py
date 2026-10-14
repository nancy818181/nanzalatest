"""2.9.82: Financial Reports > Management Pack, drill-down from the reports to the entries, and the budget alerts of
the Dashboard."""
from __future__ import annotations

import calendar
import logging
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
MUTED = "#5f6b76"
log = logging.getLogger("saber")


class ReportsExtrasMixin:
    # ------------------------------------------------------------ Management Pack
    def build_management_pack_page(self, nested):
        page = tk.Frame(nested, bg=LIGHT); nested.add(page, text="Management Pack"); self.management_pack_page = page
        from desktop_common import main_currency
        year = int(getattr(self, "current_fiscal_year", datetime.now().year)); now = datetime.now()
        month = (now.month - 1 or 1) if now.year == year else 12
        self.mp_month = tk.StringVar(value=f"{month:02d}-{year}"); self.mp_currency = tk.StringVar(value=main_currency(self, 1))
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=10, pady=8)
        tk.Label(bar, text="Month (MM-YYYY)", bg=LIGHT, fg=NAVY).pack(side="left"); tk.Entry(bar, textvariable=self.mp_month, width=8).pack(side="left", padx=(4, 10))
        tk.Label(bar, text="Currency", bg=LIGHT, fg=NAVY).pack(side="left")
        ttk.Combobox(bar, textvariable=self.mp_currency, values=list(getattr(self, "currency_codes", ["USD", "LBP"])), state="readonly", width=6).pack(side="left", padx=(4, 10))
        tk.Button(bar, text="Build Management Pack", command=self.build_management_pack, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        for label, fmt in (("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, label, lambda f=fmt: self.export_management_pack(f)).pack(side="left", padx=2)
        tk.Label(page, text="The month and the year to date against the budget and last year, the balance sheet, cash, ageing, the VAT of the quarter and the key ratios - "
                 "every currency converted into the one chosen.", bg=LIGHT, fg=MUTED, anchor="w").pack(fill="x", padx=12)
        self.mp_viewer = self.report_viewer(page, [300, 130, 130, 130, 130, 130, 130, 130, 130])

    def _management_month_end(self):
        month, year = (int(part) for part in self.mp_month.get().strip().split("-"))
        return f"{calendar.monthrange(year, month)[1]:02d}-{month:02d}-{year}"

    def build_management_pack(self):
        try: month_end = self._management_month_end()
        except (ValueError, calendar.IllegalMonthError): return messagebox.showwarning("Management Pack", "Enter the month as MM-YYYY, for example 03-2026")
        try: self.mp_result = self.client.management_pack(month_end, self.mp_currency.get())
        except Exception as exc: return messagebox.showerror("Management Pack", str(exc))
        self.show_sections(self.mp_viewer, self.mp_result["sections"])

    def export_management_pack(self, format_name):
        if not getattr(self, "mp_result", None): self.build_management_pack()
        result = getattr(self, "mp_result", None)
        if not result: return
        company = {}
        try: company = self.client.settings()
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        self.save_sections(f"{result['title']} - {company.get('company_name') or ''}", result["meta"], result["sections"],
                           result["title"].replace(" ", "_"), format_name)

    # ------------------------------------------------------------ drill-down
    def enable_drill_down(self, tree, account_column, dates):
        """Double-click a line of a report: the entries of its account in the report's period (dates() -> (from, to))."""
        def opened(_event=None):
            selected = tree.selection()
            if not selected: return
            values = tree.item(selected[0], "values")
            try: code = str(values[account_column]).split(" - ", 1)[0].strip()
            except IndexError: return
            if not code or not code.replace(".", "").isdigit(): return
            date_from, date_to = dates()
            self.open_account_entries(code, date_from, date_to)
            return "break"
        tree.bind("<Double-1>", opened, add="+")

    def open_account_entries(self, code, date_from=None, date_to=None):
        try: rows = self.client.account_lines(code, date_from, date_to)
        except Exception as exc: return messagebox.showerror("Entries", str(exc))
        from desktop_common import account_label
        window = tk.Toplevel(self); window.title(f"Entries of {account_label(self, code)}"); window.configure(bg=LIGHT); window.transient(self)
        self.fit_dialog(window, 1100, 520)
        debit = sum(float(r["debit"] or 0) for r in rows); credit = sum(float(r["credit"] or 0) for r in rows)
        tk.Label(window, text=f"{account_label(self, code)}   {date_from or ''} - {date_to or ''}   {len(rows)} line(s)   Debit {debit:,.2f}   Credit {credit:,.2f}   Balance {debit - credit:,.2f} "
                 "(amounts in the currency of each entry)", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        frame = tk.Frame(window, bg=LIGHT); frame.pack(fill="both", expand=True, padx=12, pady=4)
        tree = ttk.Treeview(frame, columns=("date", "entry", "description", "party", "currency", "debit", "credit"), show="headings")
        for key, label, width, anchor in (("date", "Date", 90, "center"), ("entry", "Entry", 130, "w"), ("description", "Description", 360, "w"), ("party", "Customer / Supplier", 180, "w"),
                                          ("currency", "Cur.", 50, "center"), ("debit", "Debit", 120, "e"), ("credit", "Credit", 120, "e")):
            tree.heading(key, text=label); tree.column(key, width=width, anchor=anchor, stretch=key == "description")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        by_iid = {}
        for row in rows:
            day = str(row["entry_date"]); shown = f"{day[8:10]}-{day[5:7]}-{day[:4]}" if len(day) == 10 and day[4] == "-" else day
            iid = tree.insert("", "end", values=(shown, row["entry_number"], row.get("line_description") or row["description"], row.get("party_name") or "", row["currency"],
                                                 f'{row["debit"]:,.2f}' if row["debit"] else "", f'{row["credit"]:,.2f}' if row["credit"] else ""))
            by_iid[iid] = row
        def open_source(_event=None):
            selected = tree.selection()
            if not selected: return
            row = by_iid[selected[0]]; window.destroy()
            self.open_entry_source({"source_type": row.get("source_type"), "source_id": row.get("source_id"), "entry_id": row.get("entry_id")})
        tree.bind("<Double-1>", open_source)
        tk.Label(window, text="Double-click a line to open its document.", bg=LIGHT, fg=MUTED).pack(anchor="w", padx=12, pady=(0, 8))
        return window

    # ------------------------------------------------------------ Dashboard: budget alerts
    def budget_alert_item(self):
        """('amber', text, label, callback) when accounts pass their budget, else None."""
        from desktop_common import accounting_setup, main_currency
        year = int(getattr(self, "current_fiscal_year", datetime.now().year)); now = datetime.now()
        month = 12 if year < now.year else now.month - 1 if year == now.year else 0
        if month < 1: return None
        try: threshold = float(accounting_setup(self).get("budget_alert_percent") or 10)
        except (TypeError, ValueError): threshold = 10.0
        alerts = self.client.budget_alerts(year, month, main_currency(self, 1), threshold)
        if not alerts: return None
        top = alerts[0]
        text = (f"{len(alerts)} account(s) off budget by more than {threshold:g}% (Jan-{calendar.month_abbr[month]}): "
                f"{top['account']} {top['name']} {'+' if top['type'] == 'expense' else '-'}{top['percent']:g}%")
        return ("amber", text, "Budget vs Actual", self.open_budget_page)

    def open_budget_page(self):
        page = self.reports_tab
        while page not in self.main_tab_pages and page is not None: page = page.master
        if page is None: return
        self.select_main_tab(page)
        notebook = self.__dict__.get("financial_notebook")
        if notebook is not None:
            for tab in notebook.tabs():
                if notebook.tab(tab, "text") == "Budget": notebook.select(tab)
