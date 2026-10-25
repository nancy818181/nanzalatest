"""Balance des Comptes panel: Trial Balance and Statement of Account (moved out of desktop_brains.py in 2.9.42, unchanged)."""
from __future__ import annotations

from desktop_brains_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, GOLD, LIGHT, messagebox, MUTED, NAVY, RED, tk, ttk
)
from desktop_common import flow_toolbars, main_currency  # responsive controls / 2.9.134
from desktop_brains_common import _date_text, _fmt, _num
import logging
from multi_select import MultiSelect, chosen_values


class BalanceReportsMixin:
    # ================================================================ Balance des Comptes
    def build_balance_panel(self, page, statement=False):
        notebook = ttk.Notebook(page); notebook.pack(fill="both", expand=True, padx=6, pady=4)
        options_page = tk.Frame(notebook, bg=LIGHT); notebook.add(options_page, text="  Options  "); page = options_page
        year = getattr(self, "current_fiscal_year", datetime.now().year)
        v = {"account_from": tk.StringVar(), "account_to": tk.StringVar(), "date_from": tk.StringVar(value=f"01-01-{year}"), "date_to": tk.StringVar(value=f"31-12-{year}"),
             "print_date": tk.StringVar(value=datetime.now().strftime("%d-%m-%Y")), "branch": tk.StringVar(value="All Branches"), "summary_digits": tk.StringVar(value="4"),
             "posting": tk.StringVar(value="Posted only"), "first_column": tk.StringVar(value="account"), "second_column": tk.StringVar(value=main_currency(self, 2)), "party": tk.StringVar()}
        flags = {name: tk.BooleanVar(value=default) for name, default in (("summary", False), ("by_due_date", False), ("reference", statement), ("with_branch", False),
                 ("detailed", statement), ("include_zero", False), ("order_by_description", False), ("non_zero_only", False), ("chapters", False), ("sub_chapters", False),
                 ("balance_sheet_only", False), ("profit_loss_only", False), ("tax_basis", False), ("balance_format", False), ("carry_forward", True), ("monthly", False),
                 ("without_opening", False), ("without_closing", False))}
        currencies = {code: tk.BooleanVar(value=True) for code in self.currency_codes}
        box = tk.LabelFrame(page, text="Statement of Account - options" if statement else "Balance des Comptes - options", bg=LIGHT, padx=8, pady=6)
        box.pack(fill="x", padx=10, pady=(8, 4))
        row0 = tk.Frame(box, bg=LIGHT); row0.pack(fill="x")
        if statement:
            tk.Label(row0, text="Customer / Supplier", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
            party_box = ttk.Combobox(row0, textvariable=v["party"], width=34); party_box.pack(side="left", padx=(4, 12)); v["party_box"] = party_box
            party_box.bind("<<ComboboxSelected>>", lambda _e: self.balance_party_chosen(v)); party_box.bind("<KeyRelease>", lambda _e: self.balance_party_search(v))
        rows_box = tk.Frame(box, bg=LIGHT); rows_box.pack(fill="x", pady=(4, 0))
        for label, key in (("Account From", "account_from"), ("Account To", "account_to")):
            line = tk.Frame(rows_box, bg=LIGHT); line.pack(fill="x", pady=1)
            tk.Label(line, text=label, bg=LIGHT, width=12, anchor="w", font=("Segoe UI", 9, "bold")).pack(side="left")
            account_box=self.account_range_box(line, v[key], v.setdefault(f"{key}_name", tk.StringVar()))
            account_box.pack(side="left", padx=(4, 6)); v[f"{key}_box"]=account_box
            tk.Label(line, textvariable=v[f"{key}_name"], bg="#dfe6ee", fg=NAVY, width=46, anchor="w", padx=6).pack(side="left")
            if key == "account_from":
                tk.Button(line, text="Same as From  >", command=lambda: v["account_to"].set(v["account_from"].get()), bg=NAVY, fg="white", border=0, padx=8).pack(side="left", padx=8)
        if statement:
            v["_auto_account_to"]=None
            v["account_from"].trace_add("write",lambda *_args:self.statement_account_from_changed(v))

        row1 = tk.Frame(box, bg=LIGHT); row1.pack(fill="x", pady=(4, 0))
        # 2.9.109: View Year - read another fiscal year of the company (read only) without switching
        v["view_year"] = tk.StringVar(value=str(year))
        years = sorted({str(item["year"]) for item in (getattr(self, "current_company", None) or {}).get("years", [])} | {str(year)})
        tk.Label(row1, text="View Year", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        year_box = ttk.Combobox(row1, textvariable=v["view_year"], values=years, state="readonly", width=6); year_box.pack(side="left", padx=(4, 10))
        def year_chosen(_event=None):
            chosen = v["view_year"].get(); v["date_from"].set(f"01-01-{chosen}"); v["date_to"].set(f"31-12-{chosen}")
        year_box.bind("<<ComboboxSelected>>", year_chosen)
        tk.Label(row1, text="Date From", bg=LIGHT).pack(side="left"); self.date_entry(row1, v["date_from"], 11).pack(side="left", padx=(4, 8))
        tk.Label(row1, text="To", bg=LIGHT).pack(side="left"); self.date_entry(row1, v["date_to"], 11).pack(side="left", padx=(4, 8))
        tk.Label(row1, text="Print Date", bg=LIGHT).pack(side="left"); self.date_entry(row1, v["print_date"], 11).pack(side="left", padx=(4, 8))
        tk.Label(row1, text="Branch", bg=LIGHT).pack(side="left"); self.branch_multi_selector(row1, v["branch"]).pack(side="left", padx=(4, 8))
        ttk.Combobox(row1, textvariable=v["posting"], values=["Posted only", "Posted + Review", "Review only"], state="readonly", width=15).pack(side="left", padx=4)

        options = tk.Frame(box, bg=LIGHT); options.pack(fill="x", pady=(6, 0))
        groups = [("Lines", [("summary", "Summary (Resume)"), ("by_due_date", "By Due Date"), ("reference", "Reference"), ("with_branch", "With Branch")]),
                  ("Accounts", [("detailed", "Detailed Account (statement)"), ("include_zero", "All accounts"), ("order_by_description",
                          "Order by Description"), ("non_zero_only", "Non-zero Balances only")]),
                  ("Grouping", [("chapters", "Chapters (class)"), ("sub_chapters", "Sub-chapters"), ("balance_sheet_only", "Balance Sheet (1-5)"), ("profit_loss_only", "Profit & Loss (6-7)"),
                                ("tax_basis", "P&L tax basis (without non-deductible expenses)")]),
                  ("Format", [("balance_format", "Format Balance (Dr / Cr balance)"), ("carry_forward", "With Carry Forward (opening)"), ("monthly", "Monthly"),
                              ("without_opening", "Without Opening entries"), ("without_closing", "Without Closing entries")])]
        for title, items in groups:
            frame = tk.LabelFrame(options, text=title, bg=LIGHT, padx=4); frame.pack(side="left", fill="y", padx=(0, 6))
            for name, label in items: tk.Checkbutton(frame, text=label, variable=flags[name], bg=LIGHT, anchor="w").pack(anchor="w")
            if title == "Grouping":
                digits = tk.Frame(frame, bg=LIGHT); digits.pack(anchor="w")
                tk.Label(digits, text="Summary digits", bg=LIGHT).pack(side="left"); ttk.Combobox(digits, textvariable=v["summary_digits"], values=["1", "2",
                        "3", "4", "5", "6"], width=3, state="readonly").pack(side="left", padx=3)
        row3 = tk.Frame(box, bg=LIGHT); row3.pack(fill="x", pady=(4, 0))
        for title, key, choices in (("1st Column", "first_column", (("account", "Account Currency"),)+tuple((code,code) for code in self.currency_codes)),
                                    ("2nd Column", "second_column", (("account", "Account Currency"),)+tuple((code,code) for code in self.currency_codes)+(("none", "None"),))):
            frame = tk.LabelFrame(row3, text=title, bg=LIGHT, padx=4); frame.pack(side="left", padx=(0, 6))
            ttk.Combobox(frame,textvariable=v[key],values=[value for value,_label in choices],state="readonly",width=12).pack(side="left",padx=4,pady=3)
        # Column-format selectors stay together; report actions get a full-width
        # compact row below the filters so they do not collapse into a vertical stack.
        state = {"vars": v, "flags": flags, "currencies": currencies, "statement": statement, "result": None}
        self.add_dimension_options(state, box)
        tk.Label(state["dimension_row"], text="Currencies", bg=LIGHT).pack(side="left", padx=(10, 0))
        for code, var in currencies.items(): tk.Checkbutton(state["dimension_row"], text=code, variable=var, bg=LIGHT).pack(side="left")
        actions = tk.Frame(box, bg=LIGHT); actions.pack(fill="x", pady=(4, 0), padx=2)
        tk.Button(actions, text="Show", command=lambda: self.run_balance_report(state), bg=GOLD, fg=NAVY, border=0, padx=22, pady=7, font=("Segoe UI", 10, "bold")).pack(side="left", padx=3)
        for text, fmt in (("Print", "print"), ("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(actions, text, lambda f=fmt: self.export_balance_report(state, f)).pack(side="left", padx=3)
        flow_toolbars(row0, rows_box, row1, options, row3, state["dimension_row"], actions)
        state["info"] = tk.Label(page, text="Choose the options and press Show. Each Show opens its own tab; double-click a line to open the transaction.", bg=LIGHT, fg=MUTED, anchor="w")
        state["info"].pack(fill="x", padx=12)
        state["notebook"] = notebook; state["options_page"] = options_page
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self.result_tab_changed(state)); state["tabs"] = {}
        state["viewer"] = None
        return state

    def account_range_box(self, parent, variable, name_variable):
        """All accounts (parents too), searched by number or name; the account name shows beside the box."""
        if not getattr(self, "_all_accounts", None):
            try: self._all_accounts = {str(a["code"]): a["name_en"] for a in self.client.accounts()}
            except Exception: self._all_accounts = {}
        def choices(): return [f"{code} - {name}" for code, name in sorted(self._all_accounts.items())]
        box = ttk.Combobox(parent, textvariable=variable, values=choices(), width=16)
        def show_name(*_args):
            code = variable.get().split(" - ", 1)[0].strip()
            name_variable.set(self._all_accounts.get(code, "" if not code else "(account not found)"))
        def search(event=None):
            if event is not None and event.keysym in ("Up", "Down", "Return", "Escape", "Tab"): return
            typed = variable.get().strip().casefold()
            available=choices()
            box["values"] = [c for c in available if typed in c.casefold()] if typed else available
            show_name()
        def choose(_event=None):
            value = variable.get()
            if " - " in value: variable.set(value.split(" - ", 1)[0].strip())
            show_name()
        box.bind("<KeyRelease>", search); box.bind("<FocusIn>", search)
        box.bind("<<ComboboxSelected>>", choose); box.bind("<FocusOut>", choose); box.bind("<Return>", choose)
        box._f2 = lambda: (self.open_account_lookup(variable), None)[1]
        variable.trace_add("write", show_name); show_name()
        return box

    def statement_account_from_changed(self, v):
        """Mirror a known account to the second row unless the user chose a different end account."""
        code=v["account_from"].get().split(" - ",1)[0].strip()
        if code not in getattr(self,"_all_accounts",{}): return
        current=v["account_to"].get().split(" - ",1)[0].strip()
        if not current or current==v.get("_auto_account_to"):
            v["_auto_account_to"]=code
            v["account_to"].set(code)

    def new_result_tab(self, state, title):
        frame = tk.Frame(state["notebook"], bg=LIGHT); state["notebook"].add(frame, text=f"  {title[:34]}  ")
        bar = tk.Frame(frame, bg=LIGHT); bar.pack(fill="x", padx=10, pady=(6, 0))
        tk.Button(bar, text="Close Tab", command=lambda: self.close_result_tab(state), bg=RED, fg="white", border=0, padx=10, pady=5).pack(side="right", padx=2)
        for text, fmt in (("PDF", "pdf"), ("Excel", "xlsx"), ("Print", "print"), ("Print Preview", "preview")):
            tk.Button(bar, text=text, command=lambda f=fmt: self.export_balance_report(state, f), bg=NAVY, fg="white", border=0, padx=10, pady=5).pack(side="right", padx=2)
        tk.Button(bar, text="< Options", command=lambda: state["notebook"].select(state["options_page"]), bg=GOLD, fg=NAVY, border=0, padx=10, pady=5).pack(side="right", padx=(2, 10))
        flow_toolbars(bar)
        info = tk.Label(bar, text="", bg=LIGHT, fg=NAVY, anchor="w", font=("Segoe UI", 9, "bold")); info.pack(side="left", fill="x", expand=True)
        viewer = self.report_viewer(frame, [95, 130, 330, 110, 110, 110, 110, 115, 115, 115]); viewer.bind("<Double-1>", lambda event: self.open_report_line(state, viewer, event)); viewer._info = info
        tk.Label(frame, text="Double-click a line to open the transaction (statement) or the statement of the account (trial balance).", bg=LIGHT, fg=MUTED).pack(anchor="w", padx=12, pady=(0, 4))
        state["notebook"].select(frame); return frame, viewer

    def result_tab_changed(self, state):
        current = state["notebook"].select()
        if current in state["tabs"]: state["result"], state["viewer"] = state["tabs"][current]

    def close_result_tab(self, state):
        current = state["notebook"].select()
        if not current or current == str(state["options_page"]): return
        state["tabs"].pop(current, None); state["notebook"].forget(current)
        if not state["notebook"].tabs(): state["result"] = None; state["viewer"] = None

    def open_report_line(self, state, viewer, event):
        values = viewer.item(viewer.identify_row(event.y), "values")
        if not values: return
        result = state.get("result") or {}
        detailed = result.get("title", "").startswith(("Statement", "Detailed"))
        if detailed and len(values) > 1 and values[1] and values[1] not in ("Voucher",):
            self._opening_from_state = state
            return self.open_transaction(str(values[1]))
        code = str(values[0]).strip()
        if code and code.replace(".", "").isdigit():  # trial balance line: open the statement of that account in a new tab
            v = state["vars"]; v["account_from"].set(code); v["account_to"].set(code); state["flags"]["detailed"].set(True)
            parent = state["notebook"].select()
            self.run_balance_report(state); state["flags"]["detailed"].set(state["statement"])
            state.setdefault("parents", {})[state["notebook"].select()] = parent  # Escape comes back to the trial balance

    def open_transaction(self, entry_number):
        other_year = getattr(self, "_report_view_year", "")  # 2.9.109: a line of another fiscal year (read only)
        try:
            if other_year: rows = [r for r in self.client.fiscal_year_journal(int(other_year)) if r["entry_number"] == entry_number]
            else: rows = [r for r in self.client.journal(entry_number=entry_number) if r["entry_number"] == entry_number]
        except Exception as exc: return messagebox.showerror("Transaction", str(exc))
        if not rows: return messagebox.showinfo("Transaction", f"{entry_number} was not found in this fiscal year")
        first = rows[0]
        window = tk.Toplevel(self); window.title(f"Transaction {entry_number}"); window.configure(bg=LIGHT); window.geometry("860x380"); window.transient(self)
        tk.Label(window, text=f"{entry_number}   |   {_date_text(first['entry_date'])}   |   {first.get('description') or ''}", bg=LIGHT, fg=NAVY,
                font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=8)
        tree = ttk.Treeview(window, columns=("account", "name", "party", "debit", "credit"), show="headings", height=9)
        for key, label, width in (("account", "Account", 110), ("name", "Account Name", 260), ("party", "Customer / Supplier", 200), ("debit", "Debit", 110), ("credit", "Credit", 110)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="e" if key in ("debit", "credit") else "w")
        for r in rows: tree.insert("", "end", values=(r["account_code"], r.get("account_name") or "", r.get("party_name") or "", f'{float(r["debit"] or 0):,.2f}', f'{float(r["credit"] or 0):,.2f}'))
        tree.pack(fill="both", expand=True, padx=10)
        tk.Label(window, text=f'Total  Debit {sum(float(r["debit"] or 0) for r in rows):,.2f}   Credit {sum(float(r["credit"] or 0) for r in rows):,.2f}  {first["currency"]}',
                bg=LIGHT, fg=NAVY).pack(anchor="e", padx=10)
        buttons = tk.Frame(window, bg=LIGHT); buttons.pack(pady=8)
        def edit(_event=None):
            window.destroy(); self.open_entry_source(first, return_state)
        return_state = getattr(self, "_opening_from_state", None); self._opening_from_state = None
        tk.Button(buttons, text="Edit this entry", command=edit, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        tk.Button(buttons, text="Close (Esc)", command=window.destroy, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=4)
        tree.bind("<Double-1>", edit); window.bind("<Escape>", lambda _e: window.destroy()); window.bind("<Return>", edit)
        window.focus_set()
        return window

    # ------------------------------------------------------------ open an entry in the screen where it can be edited (2.9.47)
    def go_to_main_tab(self, page):
        """Show a main tab even when it is outside the visible group of tabs."""
        page = self.main_tab_container(page) if hasattr(self, "main_tab_container") else page
        try: self.select_main_tab(page)
        except tk.TclError:
            index = self.main_tab_pages.index(page); self.show_tab_window(max(0, index - 2), index); self.highlight_main_tab()

    def open_entry_source(self, first, return_state=None):
        """Open the document behind a journal entry where it can be changed. With return_state (a trial balance /
        statement), Escape on that screen comes back to the same report tab, refreshed."""
        source, source_id, entry_id = first.get("source_type"), first.get("source_id"), first.get("entry_id")
        self._report_return = return_state
        self._opening_step = "finding the document"
        try:
            if source in ("invoice", "invoice_payment", "journal_voucher") and source_id:
                self._opening_step = "reading the invoice list"
                invoice = next((r for r in self.client.invoices() if r["id"] == source_id), None)
                if invoice:
                    if invoice["kind"] == "sale" and invoice.get("source_file") == "Sales Invoice" and hasattr(self, "sales_tab"):
                        self.go_to_main_tab(self.sales_tab); self.load_sales_customer_list()
                        key = next((k for k, r in getattr(self, "sales_open_map", {}).items() if r["id"] == source_id), None)
                        if key: self.sales_open_choice.set(key); self.open_sales_invoice(); return True
                    if invoice["kind"] != "sale" and hasattr(self, "purchases_tab"):
                        self._opening_step = "opening the Purchases screen"
                        self.go_to_main_tab(self.purchases_tab); self.load_purchases(); f = getattr(self, "purchase_form", {})
                        key = next((k for k, i in f.get("find_map", {}).items() if i == source_id), None)
                        self._opening_step = f"loading purchase {invoice.get('invoice_number')}"
                        if key: f["find"].set(key); self.purchase_found(); return True
                    # Uploaded data (imported / manual rows): the invoice edit window.
                    self._opening_step = "opening Uploaded Data"
                    self.go_to_main_tab(self.invoices_tab); self.load_invoices()
                    if self.invoice_tree.exists(str(source_id)):
                        self.invoice_tree.selection_set(str(source_id)); self.invoice_tree.see(str(source_id)); self.edit_selected_invoice(); return True
            if source == "journal_voucher" or (source in (None, "", "manual") and entry_id):
                self.go_to_main_tab(self.manual_tab); self.open_voucher(entry_id); return True
            if source == "payment" and hasattr(self, "transactions_tab"):
                self.go_to_main_tab(self.transactions_tab); self.load_transactions()
                for form in getattr(self, "payment_forms", {}).values():
                    if str(source_id) in form.get("rows", {}): form["tree"].selection_set(str(source_id)); self.edit_payment(form); return True
            if source == "expense" and hasattr(self, "purchases_tab"):
                self.go_to_main_tab(self.purchases_tab); self.load_expenses(); self.expense_form["tree"].selection_set(str(source_id)); self.edit_expense(); return True
            if source == "payroll" and hasattr(self, "payroll_tab"):
                self.go_to_main_tab(self.payroll_tab)
                messagebox.showinfo("Transaction", "Payroll entries come from the payroll: posted payroll is changed by a new payroll or a journal voucher."); return True
            self._report_return = None
            messagebox.showinfo("Transaction", "This entry is made automatically (opening, closing, depreciation or stock variation) and has no editing screen. Correct it with a Journal Voucher.")
        except Exception as exc:
            self._report_return = None
            logging.getLogger("saber.desktop").exception("Opening entry %s failed while %s", first.get("entry_number"), self._opening_step)
            messagebox.showerror("Transaction", f"{exc}\n\nStep: {self._opening_step} ({first.get('entry_number')}).")
        return False

    def edit_journal_selection(self, _event=None):
        """General Journal: open the selected entry in its editing screen."""
        selected = self.journal_tree.selection()
        if not selected: return messagebox.showwarning("General Journal", "Select a line of the entry you want to edit")
        number = str(self.journal_tree.item(selected[0], "values")[0])
        try: rows = [r for r in self.client.journal(entry_number=number) if r["entry_number"] == number]
        except Exception as exc: return messagebox.showerror("General Journal", str(exc))
        if not rows: return messagebox.showinfo("General Journal", f"{number} was not found")
        return self.open_entry_source(rows[0])

    # ------------------------------------------------------------ Escape in the trial balance / statement (2.9.47)
    def report_escape(self, state):
        """Step back one level without closing anything: a statement opened from a line goes back to the line's
        report, a report goes back to Options. The open tabs (the layout) stay as they are."""
        if not state: return "break"
        notebook = state["notebook"]; current = notebook.select()
        if not current or current == str(state["options_page"]): return "break"
        parent = state.get("parents", {}).get(current)
        notebook.select(parent if parent in notebook.tabs() else state["options_page"])
        return "break"

    def return_to_report(self):
        """Escape on an editing screen opened from a report: back to that report tab, refreshed."""
        state = getattr(self, "_report_return", None); self._report_return = None
        if not state: return None
        tab = self.statement_tab if state.get("statement") else self.trial_tab
        self.go_to_main_tab(self.account_reports_tab)
        try: tab.master.select(tab)
        except (tk.TclError, AttributeError): pass
        if state.get("result") is not None: self.run_balance_report(state, refresh=True)
        return "break"

    def balance_party_search(self, v):
        from desktop import row_matches_search
        typed = v["party"].get().strip(); names = list(getattr(self, "balance_party_map", {}))
        v["party_box"]["values"] = [n for n in names if row_matches_search((n,), typed)] if typed else names

    def balance_party_chosen(self, v):
        party = getattr(self, "balance_party_map", {}).get(v["party"].get())
        if party and party.get("account_number"):
            code=party["account_number"]
            v["account_from"].set(code); v["account_to"].set(code)
            if "_auto_account_to" in v: v["_auto_account_to"]=code

    def balance_options(self, state):
        v, flags = state["vars"], state["flags"]
        options = {name: var.get() for name, var in flags.items()}
        if options.pop("include_zero"): options["non_zero_only"] = False
        options.update(account_from=v["account_from"].get().split(" - ", 1)[0].strip(), account_to=v["account_to"].get().split(" - ", 1)[0].strip(),
                       date_from=v["date_from"].get().strip(), date_to=v["date_to"].get().strip(), print_date=v["print_date"].get().strip(),
                       first_column=v["first_column"].get(), second_column=v["second_column"].get(), summary_digits=v["summary_digits"].get(),
                       currencies=[code for code, var in state["currencies"].items() if var.get()], statement=state["statement"],
                       posting_status={"Posted only": "posted", "Posted + Review": "all", "Review only": "review"}[v["posting"].get()],
                       departments=[self.dimension_code(x) for x in chosen_values(v["department"].get())],
                       projects=[self.dimension_code(x) for x in chosen_values(v["project"].get())])
        if len(options["currencies"]) == len(state["currencies"]): options["currencies"] = []
        view_year = v["view_year"].get() if "view_year" in v else ""
        current = str(getattr(self, "current_fiscal_year", "") or "")
        options["view_year"] = view_year if view_year and view_year != current else ""  # 2.9.109: another year, read only
        self._report_view_year = options["view_year"]
        if options["view_year"]: options["filter_text"] = (options.get("filter_text", "") + f"   Fiscal year {view_year} (read only)").strip()
        if options.get("tax_basis"):  # 2.9.112: said on the report, so it is never mistaken for the accounting P&L
            options["profit_loss_only"] = True
            basis = "   TAX BASIS - without expenses not deductible for income tax (no official invoice) | على الأساس الضريبي"
            options["filter_text"] = (options.get("filter_text", "") + basis).strip()
        branches = chosen_values(v["branch"].get())
        if branches:  # 2.9.62: one or several branches ticked
            try: known = {row["name"]: row["id"] for row in self.client.branches()}
            except Exception: known = {}
            options["branch_ids"] = [known[name] for name in branches if name in known]
        shown = [f"{label}: {', '.join(values)}" for label, values in (("Branch", branches), ("Department", options["departments"]), ("Project", options["projects"])) if values]
        if shown: options["filter_text"] = "   ".join(shown)
        for key in ("date_from", "date_to", "print_date"):
            if options[key]:
                try: datetime.strptime(options[key], "%d-%m-%Y")
                except ValueError: raise ValueError(f"{key.replace('_', ' ').title()} must be DD-MM-YYYY")
        return options

    def branch_multi_selector(self, parent, variable):
        """2.9.62: tick one or several branches (empty = all)."""
        def names():
            try: return [row["name"] for row in self.client.branches()] if self.client else []
            except Exception: return []
        if variable.get() in ("", "All Branches"): variable.set("All")
        def reload(box): box["values"] = names()
        return MultiSelect(parent, variable, names(), width=16, title="Branch", before_open=reload, bg=LIGHT)

    def run_balance_report(self, state, refresh=False):
        try:
            if state["statement"] and not state["vars"]["account_from"].get().strip():
                raise ValueError("Choose a customer / supplier (or an account range) first")
            options = self.balance_options(state); result = self.client.account_report(options)
        except Exception as exc: return messagebox.showerror("Statement of Account" if state["statement"] else "Trial Balance", str(exc))
        if refresh and state.get("viewer") is not None and state["notebook"].select() in state["tabs"]: viewer = state["viewer"]
        else:
            v = state["vars"]; party = v.get("party").get() if v.get("party") is not None else ""
            name = party.split(" | ")[0] if party and v["account_from"].get() == v["account_to"].get() else f'{v["account_from"].get() or "first"} - {v["account_to"].get() or "last"}'
            frame, viewer = self.new_result_tab(state, ("Statement " if state["statement"] or options.get("detailed") else "TB ") + name)
            state["tabs"][str(frame)] = (result, viewer)
        state["result"] = result; state["viewer"] = viewer
        current = state["notebook"].select()
        if current: state["tabs"][current] = (result, viewer)
        self.show_sections(viewer, result["sections"])
        if getattr(viewer, "_info", None): viewer._info.config(text=f"{result['title']}  |  {result['account_count']} account(s)  |  " + result["meta"][2])
        state["info"].config(text=f"{result['title']}  |  {result['account_count']} account(s)  |  " + "   ".join(result["meta"][1:3]), fg=NAVY)

    def export_balance_report(self, state, format_name):
        if not state.get("result"): self.run_balance_report(state)
        result = state.get("result")
        if not result: return
        name = ("Statement_" + (state["vars"]["party"].get() or state["vars"]["account_from"].get())) if state["statement"] else "Trial_Balance"
        self.output_sections(result["title"], result["meta"], result["sections"], name.replace(" ", "_")[:60], format_name)

    # ---- tabs
    def build_trial(self):
        self.trial_state = self.build_balance_panel(self.trial_tab, statement=False)
        self.bind_report_escape()
        self.trial_rows = []

    def load_trial(self):
        state = getattr(self, "trial_state", None)
        if state and state.get("result") and state["notebook"].winfo_exists(): self.run_balance_report(state, refresh=True)

    def build_statement(self):
        self.statement_state = self.build_balance_panel(self.statement_tab, statement=True)
        self.load_statement_parties()
        self.bind_report_escape()

    def bind_report_escape(self):
        if not getattr(self,"_statement_escape_bound",False):
            self.bind("<Escape>",self.statement_escape,add="+")
            self._statement_escape_bound=True

    def statement_escape(self,event):
        """Escape: inside the trial balance / statement, step back one level (layout kept); on a screen opened
        from a report line, go back to that report."""
        for state_name, tab_name in (("statement_state","statement_tab"),("trial_state","trial_tab")):
            tab=getattr(self,tab_name,None); widget=event.widget
            while widget is not None and tab is not None:
                if widget is tab: return self.report_escape(getattr(self,state_name,None))
                widget=getattr(widget,"master",None)
        if getattr(self,"_report_return",None): return self.return_to_report()
        return None

    def load_statement_parties(self):
        state = getattr(self, "statement_state", None)
        if not state: return
        try: parties = self.client.parties()
        except Exception: parties = []
        self.party_rows = parties
        self.balance_party_map = {f'{p["name"]} | {p.get("account_number") or ""} | {p["kind"]}': p for p in parties}
        state["vars"]["party_box"]["values"] = list(self.balance_party_map)

    def refresh_statement_parties(self): self.load_statement_parties()

    def load_statement(self):
        state = getattr(self, "statement_state", None)
        if state and state.get("result") and state["notebook"].winfo_exists(): self.run_balance_report(state, refresh=True)
