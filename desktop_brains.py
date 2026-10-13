"""BRAINS-style screens (version 1.13): Journal Voucher with multi-currency lines and the
Balance des Comptes panel used by both the Trial Balance and the Statement of Account."""
from __future__ import annotations
from desktop_common import add_search_bar  # 2.9.78
from desktop_common import search_arrows  # 2.9.78
import logging

from desktop_brains_common import (  # 2.9.102: the names this module uses (no more 'import *')
    currency_from_prefix, datetime, Decimal, export_sections_pdf, GOLD, InvalidOperation, LIGHT, messagebox, MUTED,
    NAVY, os, RED, sys, tempfile, tk, ttk, VOUCHER_TYPES
)
from desktop_common import main_currency  # 2.9.71
from desktop_common import account_label  # 2.9.79
from desktop_common import default_account_code  # 2.9.81
from desktop_brains_common import _date_text, _fmt, _num
from desktop_balance_reports import BalanceReportsMixin

ACCOUNT_KEYS = {"account", "vat_account", "supplier_account", "expense_account", "expense_no_vat_account", "cost_account",
                "cash_account", "party_account", "stock_account", "revenue_account", "commission_account", "exchange_account"}


class EditableSheet:
    """A Treeview that edits like a spreadsheet: double-click / Enter to type, Tab / Enter to move on."""

    def __init__(self, app, parent, columns, editable, on_change, on_select=None, height=10, lookup_column=None, lookup_columns=None, lookup_groups=False, choices_by_column=None, selectmode="browse"):
        self.app = app; self.columns = columns; self.editable = editable; self.on_change = on_change; self.on_select = on_select
        self.lookup_column = lookup_column; self.lookup_columns = tuple(lookup_columns or ([lookup_column] if lookup_column else []))
        self.lookup_groups = lookup_groups; self.rows = {}; self.choices_by_column = choices_by_column or {}
        # 2.9.79: account cells show 'number - name' unless the sheet has its own name column
        keys = [c[0] for c in columns]
        self.labelled = {k for k in keys if (k in ACCOUNT_KEYS or k in self.lookup_columns)
                         and f"{k}_name" not in keys and not (k == "account" and "name" in keys)}
        frame = tk.Frame(parent, bg=LIGHT); frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode=selectmode)
        for key, label, width, anchor in columns: self.tree.heading(key, text=label); self.tree.column(key, width=width, anchor=anchor, stretch=key == "account")
        if any(key in ("department", "project") for key, *_ in columns):
            app._dimension_sheets.append(self)
            self.set_dimension_visibility(app.show_department.get(), app.show_project.get())
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview); xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); yscroll.grid(row=0, column=1, sticky="ns"); xscroll.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1); frame.grid_columnconfigure(0, weight=1)
        # 2.9.95: a wide sheet scrolls sideways inside its frame instead of making the whole screen wider than a laptop
        frame.configure(width=min(760, sum(int(c[2]) for c in columns) + 20), height=int(height) * 27 + 52); frame.grid_propagate(False)
        self.tree.tag_configure("odd", background="#fbf3e4")
        self.tree.bind("<Double-1>", self._clicked); self.tree.bind("<Return>", lambda _e: self.edit(self.tree.focus(), self.editable[0]))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select(self.selected()) if self.on_select else None)
        self.tree.bind("<Button-3>", self._right_clicked)  # right-click a cell: open the search for that cell
        if sys.platform == "darwin": self.tree.bind("<Button-2>", self._right_clicked)
        if self.lookup_columns: self.tree.bind("<F2>", self._lookup_selected_account)

    def _lookup_selected_account(self, _event=None):
        iid=self.tree.focus()
        if iid in self.rows:
            key=getattr(self,"_focused_key",None)
            self._lookup_account(iid, key if key in self.lookup_columns else next(iter(self.lookup_columns)))
        return "break"

    def _lookup_account(self, iid, key):
        variable=tk.StringVar(value=str(self.rows[iid].get(key, "") or ""))
        def chosen(*_args):
            if variable.get() and iid in self.rows and self.on_change(iid, key, variable.get().split(" - ", 1)[0].strip()) is not False:
                self.refresh(iid)
        variable.trace_add("write", chosen)
        if self.lookup_groups: self.app.open_account_lookup(variable, include_groups=True)
        else: self.app.open_account_lookup(variable)

    def _right_clicked(self, event):
        """Right-click on the account cell opens the account search; on an item sheet the item search."""
        iid = self.tree.identify_row(event.y); column = self.tree.identify_column(event.x)
        if not iid: return
        self.tree.focus(iid); self.tree.selection_set(iid); self.tree.focus_set()
        visible = self.tree["displaycolumns"]
        keys = [c[0] for c in self.columns] if visible == ("#all",) else list(visible)
        try: key = keys[int(column.lstrip("#")) - 1]
        except (ValueError, IndexError): key = None
        if key in self.lookup_columns:
            self._focused_key=key; self._lookup_account(iid,key); return "break"
        action = getattr(self.tree, "_f2", None)
        if action: action(); return "break"

    def clear(self):
        self.tree.delete(*self.tree.get_children()); self.rows = {}

    def insert(self, row, index="end"):
        iid = self.tree.insert("", index, values=self.values(row)); self.rows[iid] = row; self.renumber(); return iid

    def values(self, row):
        shown = row.get("_display", {})
        return [shown[key] if key in shown else account_label(self.app, row.get(key, "")) if key in self.labelled else row.get(key, "")
                for key, _l, _w, _a in self.columns]

    def refresh(self, iid):
        if self.tree.exists(iid): self.tree.item(iid, values=self.values(self.rows[iid]))

    def renumber(self):
        for number, iid in enumerate(self.tree.get_children(), 1):
            self.rows[iid]["line"] = f"{number:03d}"; self.refresh(iid)
            self.tree.item(iid, tags=("odd",) if number % 2 else ())

    def ordered(self):
        return [self.rows[iid] for iid in self.tree.get_children()]

    def selected(self):
        iid = self.tree.focus(); return (iid, self.rows.get(iid)) if iid else (None, None)

    def delete_selected(self):
        iid = self.tree.focus()
        if not iid: return False
        self.tree.delete(iid); self.rows.pop(iid, None); self.renumber(); return True

    def _clicked(self, event):
        iid = self.tree.identify_row(event.y); column = self.tree.identify_column(event.x)
        if not iid or not column: return
        visible = self.tree["displaycolumns"]
        keys = [c[0] for c in self.columns] if visible == ("#all",) else list(visible)
        key = keys[int(column.lstrip("#")) - 1]
        self._focused_key=key
        self.edit(iid, key if key in self.editable else self.editable[0])

    def set_dimension_visibility(self, show_department, show_project):
        keys = [column[0] for column in self.columns]
        self.tree.configure(displaycolumns=[key for key in keys if (key != "department" or show_department)
                             and (key != "project" or show_project)])

    def edit(self, iid, key):
        if not iid or not self.tree.exists(iid) or not self.tree.winfo_ismapped(): return
        self._focused_key=key
        index = [c[0] for c in self.columns].index(key); self.tree.see(iid)
        visible = self.tree["displaycolumns"]
        displayed = [c[0] for c in self.columns] if visible == ("#all",) else list(visible)
        if key not in displayed: return
        bbox = self.tree.bbox(iid, f"#{displayed.index(key) + 1}")
        if not bbox or bbox[0] < 0 or bbox[0] + bbox[2] > self.tree.winfo_width():
            widths=[self.tree.column(column,"width") for column in displayed]
            start=sum(widths[:displayed.index(key)])
            visible=self.tree.winfo_width()
            target=max(0,start-max(0,visible-widths[displayed.index(key)]))
            self.tree.xview_moveto(target/max(1,sum(widths)))
            self.tree.update_idletasks()
            bbox=self.tree.bbox(iid, f"#{displayed.index(key) + 1}")
        if not bbox: return
        row = self.rows[iid]; value = row.get(key, "")
        if key in self.choices_by_column:
            editor = ttk.Combobox(self.tree, values=self.choices_by_column[key], state="readonly")
        else:
            editor = tk.Entry(self.tree, justify={"w": "left", "e": "right"}.get(self.columns[index][3], "center"))
        editor._saber_date = "date" in key  # date cells (Date From / To, due date...) get their dashes while typing
        if key in self.choices_by_column: editor.set("" if value is None else str(value))
        else: editor.insert(0, "" if value is None else str(value))
        editor.place(x=bbox[0], y=bbox[1], width=max(bbox[2], 70), height=bbox[3])
        editor.focus_set(); editor.select_range(0, "end"); done = {"flag": False}
        def commit(move):
            if done["flag"]: return
            done["flag"] = True; text = editor.get().strip()
            if iid not in self.rows or not self.tree.exists(iid): editor.destroy(); return
            outcome = self.on_change(iid, key, text)
            if outcome == "lookup" and key in self.lookup_columns:
                # 2.9.71: the typed number is not one account - open the search with it, arrows choose
                done["flag"]=False; self.app.after(1, lookup); return
            if outcome is False or outcome == "lookup":
                done["flag"]=False; editor.focus_set(); editor.select_range(0,"end"); return
            editor.destroy()
            self.refresh(iid)
            if move:
                available = [field for field in self.editable if field in displayed]
                position = available.index(key)
                if position + 1 < len(available): self.app.after(10, lambda: self.edit(iid, available[position + 1]))
                else:
                    rows = self.tree.get_children(); at = rows.index(iid)
                    if at + 1 < len(rows): self.app.after(10, lambda: self.edit(rows[at + 1], available[0]))
        editor.bind("<Return>", lambda _e: commit(True)); editor.bind("<Tab>", lambda _e: (commit(True), "break")[1])
        if key in self.choices_by_column: editor.bind("<<ComboboxSelected>>", lambda _e: commit(False))
        editor.bind("<FocusOut>", lambda _e: commit(False)); editor.bind("<Escape>", lambda _e: (done.__setitem__("flag", True), editor.destroy()))
        if key == "line_currency":
            def currency_typed(event):
                if done["flag"] or len(event.keysym) != 1 or not event.keysym.isalpha(): return
                entered = editor.get().strip()
                matched = currency_from_prefix(entered, self.app.currency_codes)
                if matched in self.app.currency_codes:
                    editor.delete(0, "end"); editor.insert(0, matched); commit(True)
            editor.bind("<KeyRelease>", currency_typed)
        if key in self.lookup_columns:
            def lookup(_e=None):
                variable = tk.StringVar(value=editor.get()); done["flag"] = True; editor.destroy()
                def chosen(*_args):
                    if variable.get() and self.on_change(iid, key, variable.get().split(" - ", 1)[0].strip()) is not False: self.refresh(iid)
                variable.trace_add("write", chosen)
                if self.lookup_groups: self.app.open_account_lookup(variable, include_groups=True)
                else: self.app.open_account_lookup(variable)
                return "break"
            editor.bind("<F2>", lookup)
            editor.bind("<Button-3>", lookup)
            if sys.platform == "darwin": editor.bind("<Button-2>", lookup)
            if self.lookup_groups: editor.bind("<Down>", lookup)


class BrainsScreensMixin(BalanceReportsMixin):
    # ================================================================ Journal Voucher
    def build_manual(self):
        page = self.manual_tab; self.editing_voucher_id = None; self.voucher_rates = {}
        bar = tk.Frame(page, bg=NAVY); bar.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(bar, text="General Voucher", bg=NAVY, fg="white", font=("Segoe UI", 11, "bold")).pack(side="left", padx=10, pady=5)
        for text, step in (("|<", "first"), ("<", "previous"), (">", "next"), (">|", "last")):
            tk.Button(bar, text=text, command=lambda s=step: self.navigate_voucher(s), bg="#1E4268", fg="white", activebackground="#2E5277",
                    activeforeground="white", border=0, width=3, font=("Segoe UI", 9, "bold")).pack(side="left", padx=2, pady=4)
        tk.Button(bar, text="New", command=self.new_manual_voucher, bg="white", fg=NAVY, border=0, padx=12).pack(side="left", padx=(12, 2), pady=4)
        tk.Button(bar, text="Edit...", command=self.choose_voucher_to_edit, bg="white", fg=NAVY, border=0, padx=12, font=("Segoe UI", 9, "bold")).pack(side="left", padx=2, pady=4)
        tk.Button(bar, text="Save", command=self.save_manual_invoice, bg=GOLD, fg=NAVY, border=0, padx=14, font=("Segoe UI", 9, "bold")).pack(side="left", padx=2, pady=4)
        tk.Button(bar, text="Automatic DOE", command=self.show_doe_page, bg="white", fg=NAVY, border=0, padx=10).pack(side="left", padx=2, pady=4)
        tk.Button(bar, text="Delete", command=self.delete_current_voucher, bg=RED, fg="white", border=0, padx=12).pack(side="left", padx=2, pady=4)
        self.action_button(bar,"Add Line",self.add_manual_item).pack(side="left",padx=(14,2),pady=4)
        self.action_button(bar,"New Account",self.create_voucher_account).pack(side="left",padx=2,pady=4)
        self.action_button(bar,"Insert Line",self.insert_manual_item).pack(side="left",padx=2,pady=4)
        tk.Button(bar,text="Delete Line",command=self.remove_manual_item,bg=RED,fg="white",border=0,padx=10).pack(side="left",padx=2,pady=4)
        self.action_button(bar,"Show Rates",self.toggle_voucher_rates).pack(side="left",padx=(8,2),pady=4)
        for text, fmt in (("Excel", "xlsx"), ("PDF", "pdf"), ("Print", "print")):
            tk.Button(bar, text=text, command=lambda f=fmt: self.manual_entry_report(f), bg="white", fg=NAVY, border=0, padx=10).pack(side="right", padx=2, pady=4)
        from desktop_common import flow_toolbar
        flow_toolbar(bar)  # 2.9.95: wraps onto a second line on a laptop screen instead of being cut off
        header = tk.Frame(page, bg=LIGHT); header.pack(fill="x", padx=10, pady=6)
        self.manual_type = tk.StringVar(value=VOUCHER_TYPES[0]); self.manual_no = tk.StringVar(); self.manual_date = tk.StringVar(value=self.fiscal_today())
        self.manual_currency = tk.StringVar(value="USD"); self.manual_find = tk.StringVar()
        tk.Label(header, text="Type", bg=LIGHT).pack(side="left")
        self.manual_type_box=ttk.Combobox(header, textvariable=self.manual_type, values=VOUCHER_TYPES, state="readonly", width=17)
        self.manual_type_box.pack(side="left", padx=(4, 8))
        tk.Label(header, text="Number", bg=LIGHT).pack(side="left")
        tk.Entry(header, textvariable=self.manual_no, width=15, state="readonly", takefocus=0, readonlybackground="white", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 8))
        tk.Label(header, text="Date", bg=LIGHT).pack(side="left")
        self.manual_date_box=self.date_entry(header, self.manual_date, 12)
        self.manual_date_box.pack(side="left", padx=(4, 12))
        tk.Label(header, text="Currency", bg=LIGHT).pack(side="left")
        voucher_currency_box=ttk.Combobox(header, textvariable=self.manual_currency, values=self.currency_codes, state="readonly", width=6)
        voucher_currency_box.pack(side="left", padx=(4, 12))
        def select_currency_initial(event):
            if len(event.keysym)==1 and event.keysym.isalpha():
                matched=currency_from_prefix(event.char,self.currency_codes)
                if matched in self.currency_codes: self.manual_currency.set(matched)
                return "break"
        voucher_currency_box.bind("<KeyPress>",select_currency_initial)
        tk.Label(header, text="Branch", bg=LIGHT).pack(side="left")
        branch_box=self.branch_selector(header, self.manual_branch, 12, False)
        branch_box.pack(side="left", padx=(4, 8))
        tk.Label(header, text="Find", bg=LIGHT).pack(side="left")
        self.manual_find_box = ttk.Combobox(header, textvariable=self.manual_find, width=24); self.manual_find_box.pack(side="left", padx=4)
        self.manual_find_box.bind("<<ComboboxSelected>>", lambda _e: self.open_found_voucher()); self.manual_find_box.bind("<KeyRelease>", self.search_vouchers)
        def find_or_edit(_event=None):
            if self.manual_find.get().strip(): self.open_found_voucher()
            else: self.focus_voucher_entries()
            return "break"
        self.manual_find_box.bind("<Return>", find_or_edit)
        self.manual_find_box.bind("<Tab>", self.focus_voucher_entries)
        self.manual_type_box.bind("<Return>", lambda _e: (self.manual_date_box.focus_set(), "break")[1])
        self.manual_date_box.bind("<Return>", lambda _e: (voucher_currency_box.focus_set(), "break")[1], add="+")
        voucher_currency_box.bind("<Return>", lambda _e: (branch_box.focus_set(), "break")[1])
        branch_box.bind("<Return>", self.focus_voucher_entries)
        self.manual_currency.trace_add("write", lambda *_a: self.update_manual_totals())
        self.manual_date.trace_add("write", lambda *_a: self.voucher_date_changed())
        columns = [("line", "#", 45, "center"), ("account", "Account No. - Name", 230, "w"), ("description", "Line Detail", 330, "w"), ("line_currency",
                "Currency", 70, "center"), ("side", "D/C", 45, "center"),
                   ("amount", "Amount (Account Currency)", 165, "e"), ("amount_lbp", "Amount LBP", 145, "e"), ("amount_usd", "Amount USD", 120, "e"),
                   ("due_date", "Due Date", 95, "center"), ("reference", "Reference", 110, "w"), ("department", "Dep.", 60, "center"), ("project", "Project", 85, "center"),
                   ("rate_lbp", "Rate LBP", 95, "e"), ("rate_usd", "Rate USD", 95, "e")]
        bottom = tk.Frame(page, bg=LIGHT); bottom.pack(side="bottom", fill="x", padx=10, pady=(2, 6))
        totals = tk.LabelFrame(bottom, text="Totals", bg=LIGHT, padx=10, pady=2); totals.pack(side="right")
        tk.Label(totals, text="", bg=LIGHT).grid(row=0, column=0)
        for column, text in enumerate(("LBP", "USD", "Voucher Cur."), 1): tk.Label(totals, text=text, bg=LIGHT, font=("Segoe UI", 9, "bold")).grid(row=0, column=column, padx=6)
        self.voucher_total_labels = {}
        for row, name in enumerate(("Debit", "Credit", "Balance"), 1):
            tk.Label(totals, text=name, bg=LIGHT).grid(row=row, column=0, sticky="e", padx=4)
            for column, key in enumerate(("lbp", "usd", "voucher"), 1):
                label = tk.Label(totals, text="0.00", bg="#dfe6ee", width=15, anchor="e", font=("Segoe UI", 9, "bold")); label.grid(row=row, column=column, padx=3, pady=2)
                self.voucher_total_labels[(name, key)] = label
        # Voucher details come from the editable Line Detail cells; retain the hidden
        # backing widget for opening older vouchers and existing export code.
        self.manual_details=tk.Text(page,height=1)
        tk.Label(bottom,text="Double-click Line Detail to type · F2 = account list",bg=LIGHT,fg=MUTED).pack(side="left",padx=4)
        self.manual_line_info = tk.Label(page, text="", bg="#dfe6ee", fg=NAVY, anchor="w", font=("Segoe UI", 9, "bold"), padx=8)
        self.manual_line_info.pack(side="bottom", fill="x", padx=10)
        self.voucher_sheet = EditableSheet(self, page, columns, ["account", "description", "line_currency", "side", "amount", "due_date", "reference", "department", "project", "rate_lbp", "rate_usd"],
                                           self.voucher_cell_changed, self.voucher_line_selected, height=6, lookup_column="account")
        self.voucher_sheet.tree.bind("<Tab>", self.focus_voucher_entries)
        for key in ("rate_lbp","rate_usd"):
            self.voucher_sheet.tree.column(key,width=0,minwidth=0,stretch=False)
        self.voucher_sheet.editable=[key for key in self.voucher_sheet.editable if key not in ("rate_lbp","rate_usd")]
        self.voucher_rates_visible=False
        self.manual_items = []; self.manual_tree = self.voucher_sheet.tree
        self.load_manual_vouchers(); self.new_manual_voucher(confirm=False)

    def focus_voucher_entries(self, _event=None):
        """Enter the first empty account cell from the voucher header via Tab or Enter."""
        sheet=self.voucher_sheet
        rows=sheet.tree.get_children()
        if not rows or all(sheet.rows[iid].get("account") for iid in rows):
            self.add_manual_item(edit=False)
            rows=sheet.tree.get_children()
        iid=next(iid for iid in rows if not sheet.rows[iid].get("account"))
        sheet.tree.selection_set(iid); sheet.tree.focus(iid); sheet.tree.see(iid); sheet.tree.focus_set()
        self.after(20, lambda: sheet.edit(iid,"account"))
        return "break"

    # ---- rates and lines
    def voucher_rates_for(self, currency):
        key = (currency, self.manual_date.get().strip())
        if key not in self.voucher_rates:
            try: self.voucher_rates[key] = self.client.suggested_rates(currency, key[1] if len(key[1]) == 10 else None)
            except Exception: self.voucher_rates[key] = {"rate_lbp": 1 if currency == "LBP" else 89500, "rate_usd": 89500 if currency == "LBP" else 1}
        return self.voucher_rates[key]

    def toggle_voucher_rates(self):
        self.voucher_rates_visible=not self.voucher_rates_visible
        for key in ("rate_lbp","rate_usd"):
            self.voucher_sheet.tree.column(key,width=100 if self.voucher_rates_visible else 0,
                                           minwidth=90 if self.voucher_rates_visible else 0,stretch=False)
        if self.voucher_rates_visible: self.voucher_sheet.editable.extend(("rate_lbp","rate_usd"))
        else: self.voucher_sheet.editable=[key for key in self.voucher_sheet.editable if key not in ("rate_lbp","rate_usd")]

    def voucher_date_changed(self):
        if len(self.manual_date.get()) == 10 and not self.editing_voucher_id: self.set_next_manual_voucher_number()

    def new_voucher_line(self, account=""):
        currency = self.manual_currency.get() or "USD"; rates = self.voucher_rates_for(currency)
        return self.recalculate_voucher_line({"account": account, "description": "", "_description_inherited": True, "line_currency": currency, "side": "D",
                "amount": "", "due_date": self.manual_date.get(), "reference": "", "department": "", "project": "",
                                              "rate_lbp": rates["rate_lbp"], "rate_usd": rates["rate_usd"]})

    def recalculate_voucher_line(self, row):
        amount = _num(row.get("amount")); rate_lbp = _num(row.get("rate_lbp")) or 1; rate_usd = _num(row.get("rate_usd")) or 1
        row["amount_lbp"] = amount * rate_lbp; row["amount_usd"] = amount / rate_usd if row.get("line_currency") == "LBP" else amount * rate_usd
        row["_display"] = {"amount": _fmt(amount, 3) if row.get("amount") not in ("", None) else "", "amount_lbp": _fmt(row["amount_lbp"], 3), "amount_usd": _fmt(row["amount_usd"], 3),
                           "rate_lbp": f"{rate_lbp:,.4f}", "rate_usd": f"{rate_usd:,.4f}"}
        return row

    def voucher_cell_changed(self, iid, key, text):
        row = self.voucher_sheet.rows.get(iid)
        if row is None: return False
        if key == "account":
            code = text.split(" - ", 1)[0].strip()
            if code:
                account = self.account_by_code(code) or self.voucher_account_by_prefix(code)
                if not account: return "lookup"  # 2.9.71: open the search with what was typed (arrows + Enter choose)
                code = str(account["code"])
                row["account_name"] = account["name_en"]
                party = next((p for p in getattr(self, "party_rows", []) or [] if p.get("account_number") == code), None)
                if party and party.get("currency") and not row.get("amount"): self.voucher_cell_changed(iid, "line_currency", party["currency"])
            row["account"] = code
        elif key == "line_currency":
            currency = currency_from_prefix(text,self.currency_codes) or self.manual_currency.get()
            if currency in ("01", "1"): currency = "LBP"
            if currency in ("02", "2"): currency = "USD"
            if currency not in self.currency_codes: messagebox.showwarning("Journal Voucher", "Choose a currency from Settings"); return False
            rates = self.voucher_rates_for(currency); row.update(line_currency=currency, rate_lbp=rates["rate_lbp"], rate_usd=rates["rate_usd"])
        elif key == "description":
            row["description"] = text
            row["_description_inherited"] = False
            siblings = list(self.voucher_sheet.tree.get_children())
            position = siblings.index(iid)
            if position + 1 < len(siblings):
                next_id = siblings[position + 1]; next_row = self.voucher_sheet.rows[next_id]
                if not next_row.get("description") or next_row.get("_description_inherited"):
                    next_row["description"] = text
                    next_row["_description_inherited"] = True
                    self.voucher_sheet.refresh(next_id)
        elif key == "side":
            side = text.upper()[:1]
            if side not in ("D", "C"): messagebox.showwarning("Journal Voucher", "Type D for Debit or C for Credit"); return False
            row["side"] = side
        elif key in ("amount", "rate_lbp", "rate_usd"):
            if text and _num(text) <= 0 and text.replace(",", "") not in ("0",):
                messagebox.showwarning("Journal Voucher", "Enter a positive number"); return False
            row[key] = text.replace(",", "")
        elif key == "due_date": row["due_date"] = _date_text(text)
        elif key in ("department", "project"):
            code = text.split(" - ", 1)[0].strip().upper()
            items = self.dimension_lists(refresh=True)["departments" if key == "department" else "projects"]
            if code and not any(i["code"].upper() == code for i in items):
                messagebox.showwarning("Journal Voucher", f"{key.title()} {code} was not found. Available: " + ", ".join(i["code"] for i in items[:15])); return False
            row[key] = code
        else: row[key] = text
        self.recalculate_voucher_line(row); self.update_manual_totals(); self.voucher_line_selected((iid, row))
        rows = self.voucher_sheet.tree.get_children()
        if key == "reference" and rows and iid == rows[-1] and row.get("account") and row.get("amount"): self.add_manual_item(edit=False)

    def voucher_account_by_prefix(self, typed):
        """2.9.71: the posting account (9 digits or more) whose number starts with the typed digits, when only ONE does."""
        typed = str(typed or "").strip()
        if not typed.isdigit(): return None
        self.account_by_code(typed)  # loads the list of accounts
        matches = [a for code, a in (getattr(self, "_account_cache", None) or {}).items()
                   if code.isdigit() and len(code) >= 9 and code.startswith(typed)]
        return matches[0] if len(matches) == 1 else None

    def account_by_code(self, code):
        if not getattr(self, "_account_cache", None):
            try: self._account_cache = {str(a["code"]): a for a in self.client.accounts()}
            except Exception: self._account_cache = {}
        if code and str(code) not in self._account_cache:
            try: self._account_cache = {str(a["code"]): a for a in self.client.accounts()}
            except Exception: logging.getLogger("saber.ignored").debug("Ignored error", exc_info=True)
        return self._account_cache.get(str(code))

    def create_voucher_account(self):
        """Create an account independently of the current unsaved voucher."""
        window=tk.Toplevel(self); window.title("New Journal Account"); window.configure(bg=LIGHT)
        window.transient(self); window.grab_set()
        code=tk.StringVar(); name=tk.StringVar(); kind=tk.StringVar(value="expense")
        for index,(label,variable) in enumerate((("4-digit prefix or 9-digit account",code),("Account name",name))):
            tk.Label(window,text=label,bg=LIGHT).grid(row=index,column=0,sticky="w",padx=12,pady=8)
            tk.Entry(window,textvariable=variable,width=32).grid(row=index,column=1,padx=12,pady=8)
        tk.Label(window,text="Type",bg=LIGHT).grid(row=2,column=0,sticky="w",padx=12,pady=8)
        ttk.Combobox(window,textvariable=kind,values=["asset","liability","equity","income","expense"],state="readonly",width=29).grid(row=2,column=1,padx=12,pady=8)
        def save():
            try: account=self.client.save_account({"code":code.get(),"name_en":name.get(),"type":kind.get()})
            except Exception as exc: return messagebox.showerror("New Journal Account",str(exc),parent=window)
            self._account_cache=None
            self.load_accounts()
            iid,row=self.voucher_sheet.selected()
            if row is None or row.get("account"):
                iid=self.voucher_sheet.insert(self.new_voucher_line())
            self.voucher_cell_changed(iid,"account",account["code"])
            self.voucher_sheet.refresh(iid)
            self.voucher_sheet.tree.selection_set(iid); self.voucher_sheet.tree.focus(iid)
            window.destroy()
            self.manual_line_info.config(text=f'Account {account["code"]} created and ready; voucher is still unsaved')
        self.action_button(window,"Create Account",save).grid(row=3,column=1,sticky="e",padx=12,pady=12)
        window.bind("<Return>",lambda _event:save()); window.bind("<Escape>",lambda _event:window.destroy())

    def voucher_line_selected(self, selection):
        _iid, row = selection
        if not row: self.manual_line_info.config(text=""); return
        name = row.get("account_name") or (self.account_by_code(row.get("account")) or {}).get("name_en", "")
        self.manual_line_info.config(text=f"{row.get('account') or ''}  {name}      {_fmt(row.get('amount'), 3)} {row.get('line_currency')}      {_fmt(row.get('amount_lbp'), 3)} LBP      {_fmt(row.get('amount_usd'), 3)} USD")

    def add_manual_item(self, edit=True):
        row=self.new_voucher_line()
        previous=self.voucher_sheet.ordered()
        if previous: row["description"]=previous[-1].get("description") or ""
        iid = self.voucher_sheet.insert(row)
        self.voucher_sheet.tree.selection_set(iid); self.voucher_sheet.tree.focus(iid)
        if edit: self.after(30, lambda: self.voucher_sheet.edit(iid, "account"))
        self.update_manual_totals()

    def insert_manual_item(self):
        iid, _row = self.voucher_sheet.selected()
        index = self.voucher_sheet.tree.index(iid) if iid else "end"
        row=self.new_voucher_line()
        previous=self.voucher_sheet.ordered()
        if previous and isinstance(index,int) and index>0: row["description"]=previous[index-1].get("description") or ""
        new = self.voucher_sheet.insert(row, index)
        self.voucher_sheet.tree.selection_set(new); self.voucher_sheet.tree.focus(new); self.after(30, lambda: self.voucher_sheet.edit(new, "account"))

    def remove_manual_item(self):
        if not self.voucher_sheet.delete_selected(): return messagebox.showwarning("Journal Voucher", "Select a line first")
        self.update_manual_totals()

    def voucher_lines(self):
        return [row for row in self.voucher_sheet.ordered() if row.get("account") and _num(row.get("amount")) > 0]

    def voucher_value(self, row):
        currency = self.manual_currency.get()
        if row.get("line_currency") == currency: return _num(row.get("amount"))
        return row.get("amount_usd", 0) if currency == "USD" else row.get("amount_lbp", 0) if currency == "LBP" else None

    def update_manual_totals(self):
        if not hasattr(self, "voucher_total_labels"): return 0, 0
        totals = {key: {"D": 0.0, "C": 0.0} for key in ("lbp", "usd", "voucher")}; mixed = False
        for row in self.voucher_lines():
            side = row.get("side", "D"); totals["lbp"][side] += row.get("amount_lbp", 0); totals["usd"][side] += row.get("amount_usd", 0)
            value = self.voucher_value(row)
            if value is None: mixed = True
            else: totals["voucher"][side] += value
        for key in totals:
            debit, credit = totals[key]["D"], totals[key]["C"]; balance = debit - credit
            self.voucher_total_labels[("Debit", key)].config(text=_fmt(debit)); self.voucher_total_labels[("Credit", key)].config(text=_fmt(credit))
            self.voucher_total_labels[("Balance", key)].config(text="MIXED" if key == "voucher" and mixed else _fmt(balance),
                    fg=NAVY if abs(balance) < 0.005 and not (key == "voucher" and mixed) else RED)
        self.manual_items = self.voucher_lines()
        return totals["voucher"]["D"], totals["voucher"]["C"]

    # ---- voucher list, navigation, open, save
    def choose_voucher_to_edit(self):
        """2.9.49: list of saved vouchers; double-click / Enter opens one here to change it, then Save."""
        self.load_manual_vouchers()
        window = tk.Toplevel(self); window.title("Open a voucher to edit"); window.configure(bg=LIGHT); window.transient(self)
        self.fit_dialog(window, 900, 520, 600, 320)
        search = tk.StringVar(); top = tk.Frame(window, bg=LIGHT); top.pack(fill="x", padx=10, pady=8)
        tk.Label(top, text="Search (number, date, description, amount)", bg=LIGHT).pack(side="left")
        entry = tk.Entry(top, textvariable=search, width=40); entry.pack(side="left", padx=6); entry.focus_set()
        tree = ttk.Treeview(window, columns=("number", "date", "description", "amount"), show="headings", height=16)
        for key, label, width in (("number", "Number", 140), ("date", "Date", 95), ("description", "Description", 420), ("amount", "Amount", 150)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="e" if key == "amount" else "w")
        tree.pack(fill="both", expand=True, padx=10)
        rows = sorted(getattr(self, "manual_voucher_rows", {}).values(), key=lambda v: self.voucher_order.index(v["id"]) if v["id"] in getattr(self, "voucher_order", []) else 0, reverse=True)
        def fill(*_a):
            tree.delete(*tree.get_children()); typed = search.get().strip().casefold()
            for v in rows:
                values = (v["number"], _date_text(v["date"]), v["description"], f'{v["debit"]:,.2f} {v["currency"]}')
                if not typed or typed in " ".join(values).casefold(): tree.insert("", "end", iid=str(v["id"]), values=values)
            children = tree.get_children()
            if children: tree.selection_set(children[0]); tree.focus(children[0])
        def open_selected(_e=None):
            selected = tree.selection()
            if not selected: return
            window.destroy(); self.open_voucher(int(selected[0]))
        search.trace_add("write", fill); fill()
        tree.bind("<Double-1>", open_selected); tree.bind("<Return>", open_selected)
        search_arrows(entry, tree, open_selected, search); window.bind("<Escape>", lambda _e: window.destroy())  # 2.9.78: arrows from the search box
        buttons = tk.Frame(window, bg=LIGHT); buttons.pack(pady=8)
        tk.Button(buttons, text="Open to edit", command=open_selected, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=4)
        tk.Button(buttons, text="Close", command=window.destroy, bg=NAVY, fg="white", border=0, padx=14, pady=6).pack(side="left", padx=4)
        return window

    def load_manual_vouchers(self):
        if not hasattr(self, "manual_find_box"): return
        try: rows = [row for row in self.client.journal(source_type="journal_voucher") if row.get("source_type") == "journal_voucher"]
        except Exception: rows = []
        grouped = {}
        for row in rows:
            item = grouped.setdefault(row["entry_id"], {"id": row["entry_id"], "number": row["entry_number"], "date": row["entry_date"], "description": row.get("description") or "",
                                                        "currency": row["currency"], "debit": 0.0})
            item["debit"] += float(row["debit"] or 0)
        self.manual_voucher_rows = grouped
        def key(item):
            try: return (datetime.strptime(_date_text(item["date"]), "%d-%m-%Y"), item["number"])
            except ValueError: return (datetime.min, item["number"])
        self.voucher_order = [item["id"] for item in sorted(grouped.values(), key=key)]
        self.voucher_choices = {f'{v["number"]} | {_date_text(v["date"])} | {v["description"][:40]} | {v["debit"]:,.2f} {v["currency"]}': v["id"] for v in grouped.values()}
        line_details = {}
        for row in rows: line_details.setdefault(row["entry_id"], []).append(str(row.get("line_description") or ""))
        self.voucher_search = {label: f'{label} {" ".join(line_details.get(vid, []))}' for label, vid in self.voucher_choices.items()}
        self.manual_find_box["values"] = list(self.voucher_choices)
        self.set_next_manual_voucher_number()

    def populate_manual_vouchers(self): self.load_manual_vouchers()

    def search_vouchers(self, _event=None):
        from desktop import row_matches_search
        typed = self.manual_find.get().strip(); choices = list(getattr(self, "voucher_choices", {}))
        searchmap = getattr(self, "voucher_search", {})
        values = [c for c in choices if row_matches_search((searchmap.get(c, c),), typed)] if typed else choices
        self.manual_find_box["values"] = values
        if typed and values and _event is not None and getattr(_event, "keysym", "") not in ("Up", "Down", "Return", "Escape", "Tab"):
            self.manual_find_box.after_idle(lambda: self.manual_find_box.event_generate("<Down>"))

    def set_next_manual_voucher_number(self):
        if not hasattr(self, "manual_no") or self.editing_voucher_id: return
        try: year = datetime.strptime(self.manual_date.get(), "%d-%m-%Y").year
        except ValueError: year = datetime.now().year
        prefix = f"JV-{year}-"; numbers = []
        for row in getattr(self, "manual_voucher_rows", {}).values():
            if str(row["number"]).startswith(prefix):
                try: numbers.append(int(str(row["number"]).rsplit("-", 1)[-1]))
                except ValueError: pass
        self.manual_no.set(f"{prefix}{max(numbers, default=0) + 1:06d}")

    def new_manual_voucher(self, confirm=True):
        if confirm and self.voucher_lines() and not self.editing_voucher_id and not messagebox.askyesno("Journal Voucher", "Start a new voucher? Lines that are not saved will be cleared."): return
        self.editing_voucher_id = None; self.voucher_sheet.clear(); self.manual_details.delete("1.0", "end"); self.manual_find.set("")
        self.manual_type.set(VOUCHER_TYPES[0]); self.manual_currency.set(main_currency(self, 1)); self.manual_date.set(self.fiscal_today())
        self._account_cache = None; self.set_next_manual_voucher_number()
        for _ in range(2): self.voucher_sheet.insert(self.new_voucher_line())
        self.update_manual_totals(); self.manual_line_info.config(text="New voucher")

    def open_found_voucher(self):
        choices=getattr(self,"voucher_choices",{})
        entry_id=choices.get(self.manual_find.get())
        if not entry_id:
            matches=list(self.manual_find_box["values"])
            if len(matches)==1: self.manual_find.set(matches[0]); entry_id=choices.get(matches[0])
        if entry_id: self.open_voucher(entry_id)

    def navigate_voucher(self, step):
        order = getattr(self, "voucher_order", [])
        if not order: return messagebox.showinfo("Journal Voucher", "There are no saved vouchers yet")
        if step == "first": target = order[0]
        elif step == "last": target = order[-1]
        else:
            current = order.index(self.editing_voucher_id) if self.editing_voucher_id in order else (len(order) if step == "previous" else -1)
            position = current - 1 if step == "previous" else current + 1
            if not 0 <= position < len(order): return
            target = order[position]
        self.open_voucher(target)

    def open_voucher(self, entry_id):
        try: detail = self.client.journal_voucher(int(entry_id))
        except Exception as exc: return messagebox.showerror("Journal Voucher", str(exc))
        voucher = detail["voucher"]; self.editing_voucher_id = int(voucher["id"])
        self.manual_no.set(voucher["entry_number"]); self.manual_date.set(_date_text(voucher["entry_date"])); self.manual_currency.set(voucher["currency"])
        self.manual_type.set(next((t for t in VOUCHER_TYPES if t.startswith(str(voucher.get("voucher_type") or "01"))), VOUCHER_TYPES[0]))
        self.manual_details.delete("1.0", "end"); self.manual_details.insert("1.0", voucher.get("description") or "")
        try: self.manual_branch.set(next(b["name"] for b in self.client.branches() if b["id"] == voucher.get("branch_id")))
        except Exception: self.manual_branch.set("Head Office")
        self.voucher_sheet.clear()
        for line in detail["lines"]:
            side = "D" if float(line.get("debit") or 0) else "C"
            if line.get("line_currency"):
                row = {"account": line["account_code"], "account_name": line["account_name"], "description": line.get("description") or "",
                        "line_currency": line["line_currency"], "side": side, "amount": line["amount"],
                       "rate_lbp": line["rate_lbp"], "rate_usd": line["rate_usd"], "due_date": line.get("due_date") or "", "reference": line.get("reference") or "",
                       "department": line.get("department") or "", "project": line.get("project") or ""}
            else:
                rates = self.voucher_rates_for(voucher["currency"])
                row = {"account": line["account_code"], "account_name": line["account_name"], "description": line.get("description") or "", "line_currency": voucher["currency"], "side": side,
                       "amount": float(line.get("debit") or 0) or float(line.get("credit") or 0), "rate_lbp": rates["rate_lbp"], "rate_usd": rates["rate_usd"], "due_date": "", "reference": "",
                       "department": line.get("department") or "", "project": line.get("project") or ""}
            self.voucher_sheet.insert(self.recalculate_voucher_line(row))
        self.update_manual_totals(); self.manual_line_info.config(text=f"Voucher {voucher['entry_number']} opened")

    def show_doe_page(self):
        """Automatic DOE. Choose the books to revalue - LBP or USD - and one currency or all of them;
        one auditable DOE voucher is posted per currency (a USD voucher, a EUR voucher, an LBP voucher, ...).
        LBP books: foreign-currency class 4/5 balances are revalued in LBP.
        USD books: LBP and other non-USD class 4/5 balances are revalued in USD; their own balance and the
        LBP books do not change."""
        page=tk.Toplevel(self); page.title("DOE - Automatic Exchange Difference"); page.geometry("1180x620")
        page.configure(bg=LIGHT); page.transient(self)
        date=tk.StringVar(value=self.manual_date.get()); basis=tk.StringVar(value="LBP"); only=tk.StringVar(value="All currencies")
        bar=tk.Frame(page,bg=LIGHT); bar.pack(fill="x",padx=10,pady=(10,4))
        tk.Label(bar,text="DOE posting date",bg=LIGHT).pack(side="left")
        self.date_entry(bar,date,12).pack(side="left",padx=(4,12))
        tk.Label(bar,text="Revalue in",bg=LIGHT).pack(side="left")
        # 2.9.78: the books to revalue - LBP, USD, EUR or another currency of the company
        books=["LBP","USD","EUR"]+[c for c in getattr(self,"currency_codes",[]) if c not in ("LBP","USD","EUR")]
        basis_box=ttk.Combobox(bar,textvariable=basis,values=books,state="readonly",width=6); basis_box.pack(side="left",padx=(4,12))
        tk.Label(bar,text="Currencies",bg=LIGHT).pack(side="left")
        from multi_select import MultiSelect, chosen_values
        only.set("All")  # 2.9.78: tick one, several (USD + EUR + SAR ...) or All
        only_box=MultiSelect(bar,only,[],width=18,title="Currencies to revalue",on_change=lambda:load()); only_box.pack(side="left",padx=(4,12))
        rates_bar=tk.Frame(page,bg=LIGHT); rates_bar.pack(fill="x",padx=10,pady=(0,4))
        info=tk.Label(page,text="",bg=LIGHT,fg=NAVY,anchor="w"); info.pack(fill="x",padx=10)
        columns=("currency","account","name","foreign","carrying","target","difference","offset")
        tree=ttk.Treeview(page,columns=columns,show="headings",selectmode="extended")
        for key,label,width in (("currency","Currency",70),("account","Class 4/5 account",130),("name","Account name",220),("foreign","Balance",140),
                                ("carrying","Carrying",140),("target","At DOE rate",140),("difference","Difference",140),("offset","Gain / Loss A/C",230)):
            tree.heading(key,text=label); tree.column(key,width=width,stretch=key=="name")
        tree.pack(fill="both",expand=True,padx=10,pady=6); add_search_bar(tree)  # 2.9.78
        state={"candidates":[],"preview":{},"date":None,"basis":None,"rates":{},"rate_vars":{}}

        def factor(code,rate):
            # USD / EUR ... books: an LBP balance is divided by "LBP per 1 USD (EUR ...)"; every other rate is "1 unit = x".
            return (Decimal("1")/rate) if state["basis"]!="LBP" and code=="LBP" else rate

        def carrying_key_of(books):
            return "carrying_usd" if books=="USD" else "carrying_lbp" if books=="LBP" else "carrying"

        def read_rates():
            rates={}
            for code,variable in state["rate_vars"].items():
                value=Decimal(variable.get().strip().replace(",",""))
                if not value.is_finite() or value<=0: raise ValueError(f"Enter a positive DOE date rate for {code}")
                rates[code]=value
            return rates

        def load():
            try:
                day=datetime.strptime(date.get().strip(),"%d-%m-%Y").strftime("%d-%m-%Y")
                result=self.client.doe_candidates(day,basis.get())
            except Exception as exc: return messagebox.showerror("DOE",str(exc),parent=page)
            chosen_basis=basis.get(); items=[r for r in result["items"] if r["currency"]!=chosen_basis]
            available=sorted({r["currency"] for r in items},key=lambda c:(c not in ("USD","LBP"),c))
            only_box["values"]=available
            wanted=[c for c in chosen_values(only.get()) if c in available]
            if chosen_values(only.get()) and not wanted: only.set("All")
            if wanted: items=[r for r in items if r["currency"] in wanted]
            if chosen_basis not in ("LBP","USD"):  # LBP shown as "1 EUR = x LBP" like the USD books
                items=[{**r,"suggested_rate":str((Decimal("1")/Decimal(r["suggested_rate"])).quantize(Decimal("0.01"))) if r["currency"]=="LBP" and Decimal(r["suggested_rate"] or 0) else r["suggested_rate"]} for r in items]
            state.update(candidates=items,preview={},date=day,basis=chosen_basis,rates={},rate_vars={})
            for child in rates_bar.winfo_children(): child.destroy()
            tk.Label(rates_bar,text="DOE date rates:",bg=LIGHT,font=("Segoe UI",9,"bold")).pack(side="left",padx=(0,8))
            for code in sorted({r["currency"] for r in items},key=lambda c:(c not in ("USD","LBP"),c)):
                suggested=next((r["suggested_rate"] for r in items if r["currency"]==code),"")
                variable=tk.StringVar(value=str(suggested or "")); state["rate_vars"][code]=variable
                label=f"1 {chosen_basis} =" if chosen_basis!="LBP" and code=="LBP" else f"1 {code} ="
                unit="LBP" if chosen_basis=="LBP" or code=="LBP" else chosen_basis
                tk.Label(rates_bar,text=label,bg=LIGHT).pack(side="left"); tk.Entry(rates_bar,textvariable=variable,width=12).pack(side="left",padx=(4,2))
                tk.Label(rates_bar,text=unit,bg=LIGHT).pack(side="left",padx=(0,12))
            tree.heading("carrying",text=f"Carrying {chosen_basis}"); tree.heading("target",text=f"{chosen_basis} at DOE rate"); tree.heading("difference",text=f"Difference {chosen_basis}")
            tree.delete(*tree.get_children())
            skipped=result.get("skipped_accounts") or []
            info.config(text=f'{chosen_basis} books: {len(items)} class 4/5 account(s) to review ({", ".join(state["rate_vars"]) or "none"}). ' +
                (f"Mixed-currency accounts omitted for manual review: {', '.join(skipped)}. " if skipped else "") + "Check the rates, then Preview.")
        basis_box.bind("<<ComboboxSelected>>",lambda _event:load())

        def preview():
            if state["date"]!=date.get().strip() or state["basis"]!=basis.get(): return messagebox.showwarning("DOE","Load balances after changing the date or the books",parent=page)
            try: rates=read_rates()
            except (InvalidOperation,ValueError) as exc: return messagebox.showwarning("DOE",str(exc) if isinstance(exc,ValueError) and str(exc) else "Enter the DOE date rates as numbers",parent=page)
            tree.delete(*tree.get_children()); state["preview"]={}; state["rates"]=rates
            carrying_key=carrying_key_of(state["basis"])
            for row in state["candidates"]:
                code_currency=row["currency"]; balance=Decimal(row["balance"]); carrying=Decimal(row[carrying_key])
                target=(balance*factor(code_currency,rates[code_currency])).quantize(Decimal("0.01")); difference=target-carrying
                if not difference: continue
                offset=default_account_code(self,"exchange_gain") if difference>0 else default_account_code(self,"exchange_loss"); key=f'{code_currency}|{row["account"]}'
                state["preview"][key]=(row,difference)
                tree.insert("","end",iid=key,values=(code_currency,row["account"],row["name"],f'{balance:,.2f} {code_currency}',f'{carrying:,.2f}',
                    f'{target:,.2f}',f'{difference:,.2f}',account_label(self,offset)))
            tree.selection_set(tree.get_children())
            vouchers=len({key.split("|")[0] for key in state["preview"]})
            info.config(text=f'{state["basis"]} books: {len(state["preview"])} account(s) to adjust = {vouchers} DOE voucher(s), one per currency; gains credit 7751, losses debit 6751.')

        def post():
            selected=list(tree.selection())
            if not selected: return messagebox.showwarning("DOE","Select the accounts to post",parent=page)
            if state["date"]!=date.get().strip() or state["basis"]!=basis.get(): return messagebox.showwarning("DOE","Preview again after changing the date or the books",parent=page)
            try:
                if not state["preview"] or read_rates()!=state["rates"]: return messagebox.showwarning("DOE","Preview again after changing a rate",parent=page)
            except (InvalidOperation,ValueError): return messagebox.showwarning("DOE","Preview the vouchers first",parent=page)
            books=state["basis"]; carrying_key=carrying_key_of(books)
            by_currency={}
            for key in selected: by_currency.setdefault(key.split("|")[0],[]).append(key)
            if not messagebox.askyesno("Post DOE",f"Post {len(by_currency)} {books} DOE voucher(s) ({', '.join(sorted(by_currency))}) dated {state['date']}?",parent=page): return
            posted=[]
            try:
                latest={f'{r["currency"]}|{r["account"]}':r for r in self.client.doe_candidates(state["date"],books)["items"]}
                for code_currency in sorted(by_currency,key=lambda c:(c not in ("USD","LBP"),c)):
                    lines=[]; gains=Decimal("0"); losses=Decimal("0"); accounts=[]
                    for key in by_currency[code_currency]:
                        row,difference=state["preview"][key]; current=latest.get(key)
                        if not current or current["balance"]!=row["balance"] or current[carrying_key]!=row[carrying_key]:
                            raise ValueError(f"Account {row['account']} changed since the preview. Reload the DOE balances.")
                        lines.append({"account_code":row["account"],"debit" if difference>0 else "credit":str(abs(difference)),"native_currency":code_currency,
                                      "description":f"DOE {books} {code_currency} {row['account']}: balance {row['balance']}, carrying {books} {row[carrying_key]}"})
                        if difference>0: gains+=difference
                        else: losses+=-difference
                        accounts.append(row["account"])
                    if gains: lines.append({"account_code":default_account_code(self,"exchange_gain"),"credit":str(gains),"description":f"DOE gain {code_currency} ({books} books)"})
                    if losses: lines.append({"account_code":default_account_code(self,"exchange_loss"),"debit":str(losses),"description":f"DOE loss {code_currency} ({books} books)"})
                    details=f"DOE {books} books {state['date']} {code_currency} at {state['rates'][code_currency]}; accounts {', '.join(accounts)}"
                    self.client.save_journal_voucher({"entry_date":state["date"],"description":details,"currency":books,"voucher_type":"07","doe_basis":books},lines)
                    posted.append(code_currency)
            except Exception as exc:
                self.load_journal(); self.load_trial(); load()
                return messagebox.showerror("DOE",f"Posted: {', '.join(posted) or 'none'}. Not posted: {exc}",parent=page)
            self.load_journal(); self.load_trial(); load()
            messagebox.showinfo("DOE",f"Posted {len(posted)} {books} DOE voucher(s) on {state['date']}: {', '.join(posted)}.",parent=page)

        self.action_button(bar,"Load balances",load).pack(side="left",padx=3)
        self.action_button(bar,"Preview",preview).pack(side="left",padx=3)
        self.action_button(bar,"Post DOE vouchers",post).pack(side="left",padx=3)
        load()

    def save_manual_invoice(self):
        lines = self.voucher_lines(); debit, credit = self.update_manual_totals()
        if len(lines) < 2: return messagebox.showwarning("Journal Voucher", "Enter at least two lines with an account and an amount")
        if any(self.voucher_value(row) is None for row in lines):
            return messagebox.showerror("Journal Voucher",
                    f"A {self.manual_currency.get()} voucher can only contain {self.manual_currency.get()} lines. Choose USD or LBP as the voucher currency to mix currencies.")
        if abs(debit - credit) >= 0.005:
            needed = f"Credit {debit - credit:,.2f}" if debit > credit else f"Debit {credit - debit:,.2f}"
            return messagebox.showerror("Unbalanced Journal Voucher",
                    f"Debit: {debit:,.2f}\nCredit: {credit:,.2f}\nStill needed: {needed} {self.manual_currency.get()}\n\nDebit must equal Credit before saving.")
        details = "\n".join(str(row.get("description") or "").strip() for row in lines if str(row.get("description") or "").strip())
        if not details: details = self.manual_details.get("1.0", "end").strip() or f"Journal Voucher {self.manual_no.get().strip()}"
        detail_lines=details.splitlines()
        try: entry_date = datetime.strptime(self.manual_date.get().strip(), "%d-%m-%Y").strftime("%d-%m-%Y")
        except ValueError: return messagebox.showwarning("Journal Voucher", "Enter the date as 8 digits: DDMMYYYY")
        voucher = {"entry_number": self.manual_no.get().strip(), "entry_date": entry_date, "description": details, "currency": self.manual_currency.get(),
                   "branch": self.manual_branch.get(), "voucher_type": self.manual_type.get()[:2]}
        payload = [{"account_code": r["account"], "line_currency": r["line_currency"], "side": r["side"], "amount": r["amount"], "rate_lbp": r["rate_lbp"], "rate_usd": r["rate_usd"],
                    "due_date": r.get("due_date") or "", "reference": r.get("reference") or "", "department": r.get("department") or "", "project": r.get("project") or "",
                    "description": (r.get("description") or detail_lines[min(index,len(detail_lines)-1)])[:120]} for index,r in enumerate(lines)]
        try: saved = self.client.save_journal_voucher(voucher, payload, self.editing_voucher_id)
        except Exception as exc: return messagebox.showerror("Journal Voucher", str(exc))
        messagebox.showinfo("Journal Voucher", f'Voucher {saved["voucher"]["entry_number"]} saved')
        self.load_manual_vouchers(); self.open_voucher(saved["voucher"]["id"]); self.load_journal(); self.load_trial()

    def delete_current_voucher(self):
        if not self.editing_voucher_id: return messagebox.showwarning("Journal Voucher", "Open a saved voucher first")
        if not messagebox.askyesno("Delete Journal Voucher", f"Delete voucher {self.manual_no.get()} and all its lines?"): return
        try: self.client.delete_journal_voucher(self.editing_voucher_id)
        except Exception as exc: return messagebox.showerror("Journal Voucher", str(exc))
        self.editing_voucher_id = None; self.load_manual_vouchers(); self.new_manual_voucher(confirm=False); self.load_journal(); self.load_trial()

    def delete_selected_manual_from_tab(self): self.delete_current_voucher()
    def edit_selected_manual_voucher(self): self.open_found_voucher()

    def manual_entry_report(self, format_name):
        lines = self.voucher_lines()
        if not lines: return messagebox.showwarning("Journal Voucher", "No lines to export")
        headers = ["#", "Account", "Account Name", "Currency", "D/C", "Amount", "Amount LBP", "Amount USD", "Due Date", "Reference", "Rate LBP", "Rate USD"]
        rows = [[r["line"], r["account"], (self.account_by_code(r["account"]) or {}).get("name_en", ""), r["line_currency"], r["side"], _num(r["amount"]), round(r["amount_lbp"], 2),
                 round(r["amount_usd"], 3), r.get("due_date", ""), r.get("reference", ""), _num(r["rate_lbp"]), _num(r["rate_usd"])] for r in lines]
        debit_lbp = sum(r["amount_lbp"] for r in lines if r["side"] == "D"); credit_lbp = sum(r["amount_lbp"] for r in lines if r["side"] == "C")
        debit_usd = sum(r["amount_usd"] for r in lines if r["side"] == "D"); credit_usd = sum(r["amount_usd"] for r in lines if r["side"] == "C")
        totals = [["", "", "Debit", "", "", "", round(debit_lbp, 2), round(debit_usd, 3), "", "", "", ""], ["", "", "Credit", "", "", "", round(credit_lbp, 2), round(credit_usd, 3), "", "", "", ""],
                  ["", "", "Balance", "", "", "", round(debit_lbp - credit_lbp, 2), round(debit_usd - credit_usd, 3), "", "", "", ""]]
        details = self.manual_details.get("1.0", "end").strip()
        title = f"Journal Voucher {self.manual_no.get()}"
        meta = [f"Type: {self.manual_type.get()}   Date: {self.manual_date.get()}   Voucher currency: {self.manual_currency.get()}", f"Details: {details}"]
        sections = [{"heading": "Voucher lines", "headers": headers, "rows": rows + totals, "total_rows": [len(rows), len(rows) + 1, len(rows) + 2]}]
        self.output_sections(title, meta, sections, title.replace(" ", "_"), format_name)

    def output_sections(self, title, meta, sections, name, format_name):
        if format_name == "preview":
            handle = tempfile.NamedTemporaryFile(prefix=f"{name}_", suffix=".pdf", delete=False); handle.close()
            try:
                export_sections_pdf(handle.name, title, meta, sections)
                if os.name != "nt": raise RuntimeError("The preview opens in the Windows application")
                os.startfile(handle.name)
            except Exception as exc: messagebox.showinfo(title, f"The PDF is ready: {handle.name}\n{exc}")
            return
        if format_name == "print":
            handle = tempfile.NamedTemporaryFile(prefix="SaberAccounting_", suffix=".pdf", delete=False); handle.close()
            try:
                export_sections_pdf(handle.name, title, meta, sections)
                if os.name != "nt": raise RuntimeError("Printing is available in the Windows application")
                os.startfile(handle.name, "print")
            except Exception as exc: messagebox.showerror(title, str(exc))
            return
        self.save_sections(title, meta, sections, name, format_name)
