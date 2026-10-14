"""2.9.81: Settings > Accounting Settings - what the company uses, what I see, the default posting accounts,
and the Year-End Check (also run before closing a year)."""
from __future__ import annotations
import logging

import tkinter as tk
from tkinter import messagebox, ttk

import accounting_setup as rules
from desktop_common import account_code, account_label, accounting_setup

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
RED, MUTED, GREEN, AMBER = "#8B1E1E", "#5f6b76", "#2E7D5B", "#8a5a00"


class AccountingSetupMixin:
    # ------------------------------------------------------------ Settings > Accounting Settings
    def build_accounting_setup_page(self, page):
        values = accounting_setup(self, refresh=True)
        is_admin = (self.current_user or {}).get("role") == "admin"
        tk.Label(page, text="Choose what this company uses and what you see. Hidden screens and reports leave the menu; nothing is deleted, "
                 "and users' permissions (payroll, VAT, delete) still apply.", bg=LIGHT, fg=MUTED, anchor="w", justify="left", wraplength=1100).pack(fill="x", padx=12, pady=(8, 4))
        top = tk.Frame(page, bg=LIGHT); top.pack(fill="x", padx=8)
        keys = [m["key"] for m in values.get("modules") or []] + [f"report:{r}" for r in values.get("reports") or []]
        labels = {m["key"]: m["label"] for m in values.get("modules") or []}; labels.update({f"report:{r}": f"Report: {r}" for r in values.get("reports") or []})
        company_hidden = set(values.get("hidden") or []); mine = set(values.get("user_hidden") or [])
        self.setup_company_vars = {key: tk.BooleanVar(value=key not in company_hidden) for key in keys}
        self.setup_user_vars = {key: tk.BooleanVar(value=key not in mine) for key in keys}
        for title, variables, editable, note in (("This company uses (administrator)", self.setup_company_vars, is_admin, "Untick what the company does not use."),
                                                  ("I see (only for me)", self.setup_user_vars, True, "Untick what you do not need; the company's choice comes first.")):
            box = tk.LabelFrame(top, text=title, bg=LIGHT, padx=8, pady=4); box.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            tk.Label(box, text=note, bg=LIGHT, fg=MUTED).grid(row=0, column=0, columnspan=2, sticky="w")
            for index, key in enumerate(keys):
                check = tk.Checkbutton(box, text=labels[key], variable=variables[key], bg=LIGHT, anchor="w", state="normal" if editable else "disabled")
                check.grid(row=1 + index % 12, column=index // 12, sticky="w", padx=(0, 12))
        buttons = tk.Frame(page, bg=LIGHT); buttons.pack(fill="x", padx=12, pady=4)
        if is_admin: tk.Button(buttons, text="Save for the Company", command=self.save_company_view, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6,
                font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        self.action_button(buttons, "Save for Me", self.save_my_view).pack(side="left", padx=3)
        accounts = tk.LabelFrame(page, text="Default posting accounts - used when a document does not name an account", bg=LIGHT, padx=8, pady=6)
        accounts.pack(fill="x", padx=8, pady=6)
        self.setup_default_vars = {}
        for row, item in enumerate(values.get("defaults") or []):
            tk.Label(accounts, text=item["label"], bg=LIGHT, anchor="w").grid(row=row, column=0, sticky="w", pady=1)
            variable = tk.StringVar(value=account_label(self, item["account"])); self.setup_default_vars[item["key"]] = variable
            box = self.account_search_box(accounts, variable, 38); box.grid(row=row, column=1, sticky="w", padx=8, pady=1)
            if not is_admin: box.configure(state="disabled")
            default = f'default {item["default"]}' + (f' - {item["default_name"]}' if item.get("default_name") else "")
            tk.Label(accounts, text=f'{item["used_for"]}  ({default})', bg=LIGHT, fg=MUTED, anchor="w", justify="left", wraplength=420).grid(row=row, column=2, sticky="w")  # 2.9.98: wraps
        tk.Label(accounts, text=values.get("payroll_note") or "", bg=LIGHT, fg=NAVY, anchor="w", justify="left",
                wraplength=900).grid(row=len(self.setup_default_vars), column=0, columnspan=3, sticky="w", pady=(6, 0))
        if is_admin:
            bar = tk.Frame(accounts, bg=LIGHT); bar.grid(row=len(self.setup_default_vars) + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))
            tk.Button(bar, text="Save Default Accounts", command=self.save_default_accounts, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
            self.action_button(bar, "Program Defaults", self.restore_default_accounts).pack(side="left", padx=3)
        # 2.9.100: selective approval - this company chooses which documents need approval (each client company its own choice)
        approval = tk.LabelFrame(page, text="Approval (internal control) - for this company", bg=LIGHT, padx=8, pady=6); approval.pack(fill="x", padx=8, pady=6)
        try: info = self.client.approvals()
        except Exception: info = {"types": ["invoices"] if values.get("approval_required") else [], "labels": {}, "items": []}
        labels = info.get("labels") or {"invoices": "Sales / purchase invoices", "journal_vouchers": "Journal vouchers", "payments": "Receipts and payments", "expenses": "Expenses"}
        tk.Label(approval, text="Need approval (users without 'Can approve' save them as drafts; another user with 'Can approve' posts them):",
                 bg=LIGHT, fg=NAVY, wraplength=900, justify="left").pack(anchor="w")
        ticks = tk.Frame(approval, bg=LIGHT); ticks.pack(anchor="w", pady=(4, 2))
        self.setup_approval_types = {}
        for key, label in labels.items():
            self.setup_approval_types[key] = tk.BooleanVar(value=key in (info.get("types") or []))
            tk.Checkbutton(ticks, text=label, variable=self.setup_approval_types[key], bg=LIGHT, state="normal" if is_admin else "disabled").pack(side="left", padx=(0, 14))
        buttons = tk.Frame(approval, bg=LIGHT); buttons.pack(anchor="w", pady=(2, 0))
        if is_admin: tk.Button(buttons, text="Save", command=self.save_approval_setting, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        waiting = len(info.get("items") or [])
        self.action_button(buttons, f"Pending approvals ({waiting})", self.open_approvals).pack(side="left")
        self.build_vat_ledgers_box(page, is_admin)  # 2.9.97
        alerts = tk.LabelFrame(page, text="Dashboard", bg=LIGHT, padx=8, pady=6); alerts.pack(fill="x", padx=8, pady=6)  # 2.9.82
        self.setup_alert_percent = tk.StringVar(value=str(values.get("budget_alert_percent") or "10"))
        tk.Label(alerts, text="Show the accounts off budget (costs above / revenue below) by more than", bg=LIGHT).pack(side="left")
        tk.Entry(alerts, textvariable=self.setup_alert_percent, width=6, state="normal" if is_admin else "disabled").pack(side="left", padx=4)
        tk.Label(alerts, text="% (year to date, the company budget in the main currency)", bg=LIGHT).pack(side="left")
        if is_admin: self.action_button(alerts, "Save", self.save_alert_percent).pack(side="left", padx=8)
        check = tk.LabelFrame(page, text="Year-End Check", bg=LIGHT, padx=8, pady=6); check.pack(fill="x", padx=8, pady=6)
        tk.Label(check, text="The points an auditor checks before the books are closed. It runs again by itself when you close the year (Profit & Loss).", bg=LIGHT, fg=MUTED).pack(side="left")
        tk.Button(check, text="Run Year-End Check", command=self.show_year_end_check, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=8)

    # ------------------------------------------------------------ 2.9.97: VAT account per customer / supplier
    def build_vat_ledgers_box(self, page, is_admin):
        box = tk.LabelFrame(page, text="VAT by customer / supplier (VAT 140)", bg=LIGHT, padx=8, pady=6); box.pack(fill="x", padx=8, pady=6)
        try: values = self.client.vat_ledgers()
        except Exception: values = {"enabled": False, "auto_close": True, "ledgers": []}
        state = "normal" if is_admin else "disabled"
        self.vat_by_party = tk.BooleanVar(value=bool(values.get("enabled"))); self.vat_auto_close = tk.BooleanVar(value=bool(values.get("auto_close", True)))
        top = tk.Frame(box, bg=LIGHT); top.pack(fill="x")
        tk.Checkbutton(top, text="Every customer / supplier has its own VAT account (supplier 401100025 -> VAT 442100025)", variable=self.vat_by_party, bg=LIGHT, state=state).pack(anchor="w")
        tk.Checkbutton(top, text="Close the VAT automatically when the quarterly return is saved", variable=self.vat_auto_close, bg=LIGHT, state=state).pack(anchor="w")
        grid = tk.Frame(box, bg=LIGHT); grid.pack(anchor="w", pady=(6, 2))
        for column, title in enumerate(("Ledger", "VAT", "Main", "Closing", "")):
            tk.Label(grid, text=title, bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, padx=4, sticky="w")
        self.vat_ledger_vars = []
        for row_index, row in enumerate(values.get("ledgers") or [], start=1):
            variables = {key: tk.StringVar(value=str(row.get(key) or "")) for key in ("ledger", "vat", "main", "closing", "label")}
            for column, key in enumerate(("ledger", "vat", "main", "closing")):
                tk.Entry(grid, textvariable=variables[key], width=12, state=state).grid(row=row_index, column=column, padx=4, pady=2)
            tk.Label(grid, text=row.get("label") or "", bg=LIGHT, fg=MUTED).grid(row=row_index, column=4, padx=6, sticky="w")
            self.vat_ledger_vars.append(variables)
        actions = tk.Frame(box, bg=LIGHT); actions.pack(fill="x", pady=(4, 0))
        self.vat_start_from = tk.StringVar(value="0")
        if is_admin:
            tk.Button(actions, text="Save", command=self.save_vat_ledgers, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
            tk.Label(actions, text="Start from (>)", bg=LIGHT).pack(side="left", padx=(10, 2))
            tk.Entry(actions, textvariable=self.vat_start_from, width=11).pack(side="left")
            self.action_button(actions, "Create VAT Accounts", self.create_vat_accounts).pack(side="left", padx=6)
        self.action_button(actions, "Testing VAT Accounts", self.test_vat_accounts).pack(side="left", padx=6)
        tk.Label(box, text="The VAT of each invoice goes to its customer / supplier's own VAT account. At the quarter end each one is closed into the "
                 "Closing account of its ledger, then the settlement closes those into VAT payable (4425) / VAT to recover (4429).",
                 bg=LIGHT, fg=MUTED, wraplength=900, justify="left").pack(anchor="w", pady=(4, 0))

    def save_vat_ledgers(self):
        ledgers = [{key: variable.get().strip() for key, variable in row.items()} for row in self.vat_ledger_vars]
        try: self.client.save_vat_ledgers({"enabled": self.vat_by_party.get(), "auto_close": self.vat_auto_close.get(), "ledgers": ledgers})
        except Exception as exc: return messagebox.showerror("VAT by customer / supplier", str(exc))
        messagebox.showinfo("VAT by customer / supplier", "Saved. New invoices post their VAT to the customer / supplier's own VAT account."
                            + ("" if not self.vat_by_party.get() else "\n\nPress 'Create VAT Accounts' once for the customers / suppliers you already have."))

    def create_vat_accounts(self):
        try: made = self.client.create_vat_accounts(int(self.vat_start_from.get() or 0))["created"]
        except Exception as exc: return messagebox.showerror("Create VAT Accounts", str(exc))
        try: self.load_accounts()
        except Exception: pass  # the chart screen refreshes when it is opened
        messagebox.showinfo("Create VAT Accounts", f"{made} VAT account(s) created.")

    def test_vat_accounts(self):
        try: result = self.client.test_vat_accounts()
        except Exception as exc: return messagebox.showerror("Testing VAT Accounts", str(exc))
        if result["ok"]: return messagebox.showinfo("Testing VAT Accounts", "Every customer / supplier has its VAT account, and every invoice's VAT is on its own party's account.")
        lines = "\n".join(p["detail"] for p in result["problems"][:40])
        more = len(result["problems"]) - 40
        messagebox.showwarning("Testing VAT Accounts", f"{len(result['problems'])} point(s) to check:\n\n{lines}" + (f"\n... and {more} more" if more > 0 else ""))

    def _view_choice(self, variables):
        return [key for key, variable in variables.items() if not variable.get()]

    def save_company_view(self):
        try: self.client.save_accounting_setup({"hidden": self._view_choice(self.setup_company_vars)})
        except Exception as exc: return messagebox.showerror("Accounting Settings", str(exc))
        self._apply_new_view("Saved for the company.")

    def save_my_view(self):
        try: self.client.save_my_hidden(self._view_choice(self.setup_user_vars))
        except Exception as exc: return messagebox.showerror("Accounting Settings", str(exc))
        self._apply_new_view("Saved for you.")

    def _apply_new_view(self, message):
        accounting_setup(self, refresh=True)
        messagebox.showinfo("Accounting Settings", message + " The menu and the reports are rebuilt now.")
        self.main_screen()

    def save_default_accounts(self):
        payload = {key: account_code(variable.get()) for key, variable in self.setup_default_vars.items()}
        try: self.client.save_accounting_setup({"defaults": payload})
        except Exception as exc: return messagebox.showerror("Accounting Settings", str(exc))
        accounting_setup(self, refresh=True)
        messagebox.showinfo("Accounting Settings", "Default accounts saved. New documents use them from now on; documents already saved are not changed.")

    def save_approval_setting(self):
        kinds = [key for key, var in self.setup_approval_types.items() if var.get()]
        try: self.client.save_accounting_setup({"approval_types": kinds})
        except Exception as exc: return messagebox.showerror("Accounting Settings", str(exc))
        messagebox.showinfo("Accounting Settings", "Approval is OFF for this company." if not kinds else
                            "Approval is ON for: " + ", ".join(kinds).replace("_", " ") + ". Documents of users without 'Can approve' wait for approval.")

    def open_approvals(self):
        """2.9.100: everything waiting for approval in this company; approve the selected ones."""
        try: info = self.client.approvals()
        except Exception as exc: return messagebox.showerror("Approvals", str(exc))
        window = tk.Toplevel(self); window.title("Pending approvals"); window.configure(bg=LIGHT); window.transient(self); window.geometry("900x420")
        tree = ttk.Treeview(window, columns=("kind", "number", "date", "description", "amount", "by"), show="headings", selectmode="extended")
        for key, label, width in (("kind", "Document", 150), ("number", "No.", 120), ("date", "Date", 90), ("description", "Description", 300), ("amount", "Amount", 110), ("by", "Prepared by", 100)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="e" if key == "amount" else "w")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        rows = {}
        for index, row in enumerate(info.get("items") or []):
            iid = f"{row['kind']}:{row['id']}"; rows[iid] = row
            tree.insert("", "end", iid=iid, values=((info.get("labels") or {}).get(row["kind"], row["kind"]), row["number"], row["date"], row["description"],
                                                     f"{row['currency']} {row['amount']:,.2f}", row["prepared_by"]))
        def approve():
            chosen = [rows[i] for i in tree.selection()]
            if not chosen: return messagebox.showwarning("Approvals", "Select the documents to approve", parent=window)
            try: result = self.client.approve_documents([r["id"] for r in chosen if r["kind"] != "invoices"], [r["id"] for r in chosen if r["kind"] == "invoices"])
            except Exception as exc: return messagebox.showerror("Approvals", str(exc), parent=window)
            window.destroy()
            for refresh in ("load_invoices", "load_journal", "load_trial", "load_dashboard"):
                try: getattr(self, refresh)()
                except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
            messagebox.showinfo("Approvals", f"Approved: {len(result.get('approved', []))}" + ("\n" + "\n".join(result["skipped"]) if result.get("skipped") else ""))
        bar = tk.Frame(window, bg=LIGHT); bar.pack(pady=(0, 10))
        tk.Button(bar, text="Approve Selected", command=approve, bg=GOLD, fg=NAVY, border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        tk.Label(window, text="" if info.get("items") else "Nothing waits for approval.", bg=LIGHT, fg=NAVY).pack()

    def save_alert_percent(self):
        try: self.client.save_accounting_setup({"budget_alert_percent": self.setup_alert_percent.get()})
        except Exception as exc: return messagebox.showerror("Accounting Settings", str(exc))
        accounting_setup(self, refresh=True); messagebox.showinfo("Accounting Settings", "Saved. The Dashboard uses it from now on.")

    def restore_default_accounts(self):
        if not messagebox.askyesno("Accounting Settings", "Put back the program's default accounts?"): return
        for key, variable in self.setup_default_vars.items(): variable.set(account_label(self, rules.DEFAULT_ACCOUNTS[key][1]))
        self.save_default_accounts()

    # ------------------------------------------------------------ Year-End Check
    # ------------------------------------------------------------ 2.9.84: warn before the cash / bank goes negative
    def confirm_cash_enough(self, account, currency, date, amount, title="Nanza Accounting"):
        """True to go on. Asks when paying `amount` out of a cash / bank account (class 5) leaves it negative in its currency."""
        try: check = self.client.cash_check(account, currency, date, amount)
        except Exception: return True  # the check never blocks a save by itself
        if not check.get("checked") or not check.get("negative"): return True
        return messagebox.askyesno(title, f"Account {check['account']} has {check['balance']:,.2f} {check['currency']} on {date}.\n"
                                          f"After this payment of {float(amount):,.2f} it would be {check['after']:,.2f} {check['currency']} (negative).\n\n"
                                          "Check the date, the account and the receipts not yet entered. Save anyway?")

    # ------------------------------------------------------------ 2.9.84: Settings > Audit Trail (administrator)
    def build_audit_trail_page(self, page):
        year = getattr(self, "current_fiscal_year", "") or ""
        self.audit_filters = {k: tk.StringVar(value=v) for k, v in (("date_from", f"01-01-{year}" if year else ""), ("date_to", f"31-12-{year}" if year else ""),
                                                                     ("username", "All"), ("entity", "All"), ("action", "All"), ("text", ""))}
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(bar, text="From", bg=LIGHT).pack(side="left"); self.date_entry(bar, self.audit_filters["date_from"], 11).pack(side="left", padx=(4, 8))
        tk.Label(bar, text="To", bg=LIGHT).pack(side="left"); self.date_entry(bar, self.audit_filters["date_to"], 11).pack(side="left", padx=(4, 8))
        self.audit_boxes = {}
        for key, label, width in (("username", "User", 12), ("entity", "Record", 16), ("action", "Action", 12)):
            tk.Label(bar, text=label, bg=LIGHT).pack(side="left")
            box = ttk.Combobox(bar, textvariable=self.audit_filters[key], values=["All"], state="readonly", width=width); box.pack(side="left", padx=(4, 8)); self.audit_boxes[key] = box
        tk.Label(bar, text="Contains", bg=LIGHT).pack(side="left"); tk.Entry(bar, textvariable=self.audit_filters["text"], width=16).pack(side="left", padx=(4, 8))
        tk.Button(bar, text="Show", command=self.load_audit_trail, bg=NAVY, fg="white", border=0, padx=14, pady=4).pack(side="left", padx=4)
        for label, fmt in (("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, label, lambda f=fmt: self.export_audit_trail(f)).pack(side="left", padx=2)
        auditor = tk.Frame(page, bg=LIGHT); auditor.pack(fill="x", padx=8, pady=(4, 2))  # 2.9.97
        tk.Label(auditor, text="For the auditor:", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.action_button(auditor, "Verify Audit Trail", self.verify_audit_trail).pack(side="left", padx=2)
        for label, fmt in (("Audit Report (Excel)", "xlsx"), ("Audit Report (PDF)", "pdf")):
            self.action_button(auditor, label, lambda f=fmt: self.export_audit_report(f)).pack(side="left", padx=2)
        tk.Label(auditor, text="Late entries = entered more than", bg=LIGHT).pack(side="left", padx=(12, 2))
        self.audit_late_days = tk.StringVar(value="30"); tk.Entry(auditor, textvariable=self.audit_late_days, width=4).pack(side="left")
        tk.Label(auditor, text="days after their date", bg=LIGHT).pack(side="left", padx=2)
        frame = tk.Frame(page, bg=LIGHT); frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.audit_tree = ttk.Treeview(frame, columns=("when", "user", "action", "entity", "id", "details"), show="headings")
        for key, label, width in (("when", "Date / time (UTC)", 150), ("user", "User", 100), ("action", "Action", 90), ("entity", "Record", 120), ("id", "No.", 60), ("details", "Details", 460)):
            self.audit_tree.heading(key, text=label); self.audit_tree.column(key, width=width, anchor="w", stretch=key == "details")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.audit_tree.yview); self.audit_tree.configure(yscrollcommand=scroll.set)
        self.audit_tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        self.audit_detail = tk.Label(page, text="Select a line to read its details in full.", bg=LIGHT, fg=NAVY, anchor="w", justify="left", wraplength=1100)
        self.audit_detail.pack(fill="x", padx=10, pady=(0, 8))
        self.audit_tree.bind("<<TreeviewSelect>>", lambda _e: self.audit_detail.config(text=str(self.audit_tree.item(self.audit_tree.selection()[0],
                "values")[-1])) if self.audit_tree.selection() else None)
        self.audit_rows = []

    def load_audit_trail(self):
        filters = {k: ("" if v.get() == "All" else v.get().strip()) for k, v in self.audit_filters.items()}
        try: result = self.client.audit_log(**filters)
        except Exception as exc: return messagebox.showerror("Audit Trail", str(exc))
        for key, choices in (("username", "users"), ("entity", "entities"), ("action", "actions")):
            self.audit_boxes[key].configure(values=["All"] + list(result.get(choices) or []))
        self.audit_rows = result["items"]; self.audit_tree.delete(*self.audit_tree.get_children())
        for row in self.audit_rows:
            self.audit_tree.insert("", "end", values=(str(row["created_at"])[:19].replace("T", " "), row["username"], row["action"], row["entity"], row["entity_id"] or "", row["details"]))
        return self.audit_rows

    def export_audit_trail(self, fmt):
        if not self.audit_rows: self.load_audit_trail()
        rows = [[str(r["created_at"])[:19].replace("T", " "), r["username"], r["action"], r["entity"], r["entity_id"] or "", r["details"]] for r in self.audit_rows]
        sections = [{"heading": "Audit trail", "headers": ["Date / time (UTC)", "User", "Action", "Record", "No.", "Details"], "rows": rows}]
        self.save_sections("Audit Trail", [f"{len(rows)} changes"], sections, "Audit_Trail", fmt)

    def verify_audit_trail(self):  # 2.9.97
        try: result = self.client.verify_audit_trail()
        except Exception as exc: return messagebox.showerror("Verify Audit Trail", str(exc))
        details = "\n".join(f"Line {b['id']}: {b['problem']}" for b in result.get("broken", [])[:15])
        (messagebox.showinfo if result["ok"] else messagebox.showwarning)("Verify Audit Trail", result["message"] + (f"\n\n{details}" if details else ""))

    def export_audit_report(self, fmt):  # 2.9.97
        filters = {k: v.get().strip() for k, v in self.audit_filters.items()}
        try: report = self.client.audit_report(filters["date_from"], filters["date_to"], self.audit_late_days.get() or "30")
        except Exception as exc: return messagebox.showerror("Audit Report", str(exc))
        s = report["summary"]
        meta = [f"Period {report['from']} - {report['to']}", report["integrity"]["message"],
                f"{s['entries']} entries, {s['changes']} changes after saving, {s['late']} late, {s['admin']} by the administrator, "
                f"{s['outside_hours']} outside working hours, {s['manual_cash']} manual vouchers on cash / bank"]
        self.save_sections("Audit Report", meta, report["sections"], "Audit_Report", fmt)

    def show_year_end_check(self, before_closing=False):
        """Shows the check; before closing, returns True when the user goes on."""
        year = int(getattr(self, "current_fiscal_year", 0) or 0)
        try: check = self.client.year_end_check(year)
        except Exception as exc:
            messagebox.showerror("Year-End Check", str(exc)); return False
        window = tk.Toplevel(self); window.title(f"Year-End Check {year}"); window.configure(bg=LIGHT); window.transient(self)
        self.fit_dialog(window, 1100, 560)
        colour = GREEN if not check["errors"] and not check["warnings"] else RED if check["errors"] else AMBER
        tk.Label(window, text=f"Year-End Check {year}: {check['summary']}", bg=LIGHT, fg=colour, font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        frame = tk.Frame(window, bg=LIGHT); frame.pack(fill="both", expand=True, padx=12, pady=4)
        tree = ttk.Treeview(frame, columns=("status", "check", "result", "fix"), show="headings")
        for key, label, width in (("status", "Status", 80), ("check", "Check", 230), ("result", "Result", 470), ("fix", "What to do", 330)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="w", stretch=key in ("result", "fix"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        for status, tint in (("ERROR", "#f8d7d7"), ("WARNING", "#fdf0d5"), ("OK", "#e3f2ea")): tree.tag_configure(status, background=tint)
        for item in check["results"]: tree.insert("", "end", values=(item["status"], item["check"], item["detail"], item["fix"]), tags=(item["status"],))
        detail = tk.Label(window, text="Select a line to read it in full.", bg=LIGHT, fg=NAVY, anchor="w", justify="left", wraplength=1050); detail.pack(fill="x", padx=12)
        tree.bind("<<TreeviewSelect>>", lambda _e: detail.config(text="   ".join(str(v) for v in tree.item(tree.selection()[0], "values")) if tree.selection() else ""))
        answer = {"go": False}
        bar = tk.Frame(window, bg=LIGHT); bar.pack(fill="x", padx=12, pady=8)
        for label, fmt in (("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, label, lambda f=fmt: self.save_sections(f"Year-End Check {year}", [check["summary"]], check["sections"], f"Year_End_Check_{year}", f)).pack(side="left", padx=2)
        if before_closing:
            def go(): answer["go"] = True; window.destroy()
            if check["errors"]:
                tk.Label(bar, text="Correct the errors first (red lines).", bg=LIGHT, fg=RED, font=("Segoe UI", 9, "bold")).pack(side="left", padx=12)
            else:
                tk.Button(bar, text=f"Close {year} anyway" if check["warnings"] else f"Go on and close {year}", command=go, bg=RED, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=12)
            self.action_button(bar, "Cancel", window.destroy).pack(side="left", padx=3)
            window.grab_set(); self.wait_window(window)
            return answer["go"]
        self.action_button(bar, "Close", window.destroy).pack(side="left", padx=12)
        return True
