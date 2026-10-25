"""Stage 3 screens (version 1.16): Import from Excel or PDF, Payment & Receipt, Purchases & Expenses."""
from __future__ import annotations
from desktop_tax_flag import tax_tick, save_tax_flag, load_tax_flag, place as place_tick  # 2.9.113
import logging

from desktop_stage3_common import (  # 2.9.102: the names this module uses (no more 'import *')
    asset_pdf_details, bulk_action, datetime, EXPENSE_VAT, filedialog, GOLD, LIGHT, messagebox,
    METHODS, MUTED, NAVY, notify_new_items, Path, prepare_pdf_reading, PURCHASE_VAT, read_expenses,
    read_invoice_pdf_pages, read_invoices, RED, resolve_item, run_with_progress, SALES_VAT, threading, tk, ttk, TYPES
)
from desktop_stage3_common import simpledialog  # noqa: F401 - desktop_stage3.simpledialog is patched by tests
from desktop_common import main_currency  # 2.9.71
from desktop_stage3_common import _dd, _num
from desktop_common import flow_toolbar, flow_toolbars
from desktop_common import account_label, account_code  # 2.9.79
from i18n import tr
from desktop_purchases import PurchasesMixin
from desktop_asset_register import AssetRegisterMixin
from desktop_expenses import ExpensesMixin

class Stage3Mixin(PurchasesMixin, AssetRegisterMixin, ExpensesMixin):
    def run_ai_task(self, work, success):
        """Run free local document/account assistance off the UI thread."""
        import queue
        events=queue.Queue()  # 2.9.87: the thread never calls the window (Tk is not thread-safe); the screen polls
        def run():
            try: events.put(("done",work(None)))
            except Exception as exc: events.put(("error",str(exc)))
        def poll():
            try: kind,value=events.get_nowait()
            except queue.Empty: self.after(100,poll); return
            if kind=="error": messagebox.showerror(tr(self.language.get(),"ai_accountant_title"),value)
            else: success(value)
        self.after(100,poll)
        threading.Thread(target=run,daemon=True,name="SaberLocalAssist").start()

    # ================================================================ Import
    def build_import(self):
        page = self.import_tab; self.import_rows = []; self.import_mode = "excel"
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=10, pady=8)
        self.import_type = tk.StringVar(value="Purchases"); self.currency = tk.StringVar(value=main_currency(self, 1)); self.import_replace = tk.BooleanVar(value=False)
        tk.Label(bar, text="Default Type", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Combobox(bar, textvariable=self.import_type, values=list(TYPES), state="readonly", width=11).pack(side="left", padx=(4, 10))
        tk.Label(bar, text="Default currency", bg=LIGHT).pack(side="left")
        ttk.Combobox(bar, textvariable=self.currency, values=self.currency_codes, state="readonly", width=6).pack(side="left", padx=(4, 10))
        tk.Button(bar, text="Choose Excel File", command=self.choose_import, bg=NAVY, fg="white", border=0, padx=14, pady=7).pack(side="left", padx=3)
        tk.Button(bar, text="Choose PDF Invoice(s)", command=self.choose_import_pdfs, bg=NAVY, fg="white", border=0, padx=14, pady=7).pack(side="left", padx=3)
        tk.Label(bar, text="Show", bg=LIGHT).pack(side="left", padx=(12, 2))
        ttk.Combobox(bar, textvariable=self.import_view_currency, values=["All Currencies"]+self.currency_codes, state="readonly", width=13).pack(side="left")
        tk.Button(bar, text="Apply", command=self.populate_import_preview, bg=GOLD, fg=NAVY, border=0, padx=10, pady=5).pack(side="left", padx=4)
        self.file_label = tk.Label(page, text="No file selected. Excel: one invoice per row. PDF: each file becomes one invoice and is attached to it.", bg=LIGHT, fg=MUTED, anchor="w")
        self.file_label.pack(fill="x", padx=12)
        tk.Label(page,text="PDF: review each row's Type and use Review original document before saving. Account cells: F2 / Down / right-click searches the chart; Tab saves.",
                 bg=LIGHT,fg=MUTED,anchor="w").pack(fill="x",padx=12,pady=(2,0))
        tk.Label(page, text="Select preview rows with Ctrl / Shift (Ctrl+A or Select All = every row), choose a VAT A/C below, then apply it to the selection.",
                 bg=LIGHT, fg=MUTED, anchor="w").pack(fill="x", padx=12)
        from desktop_brains import EditableSheet
        columns = [("line", "#", 40, "center"), ("invoice_number", "Invoice No.", 110, "w"), ("invoice_date", "Date", 90, "center"), ("party_name", "Customer / Supplier", 200, "w"),
                   ("entry_type", "Type (review)", 120, "w"), ("currency", "Currency", 65, "center"), ("subtotal", "Before VAT", 105, "e"), ("vat", "VAT", 90,
                           "e"), ("vat_account", "VAT A/C", 170, "w"),
                   ("total", "Total", 105, "e"), ("supplier_account", "Party / Paid A/C", 200, "w"), ("expense_account", "Cost / Revenue A/C", 200, "w"),
                   ("expense_no_vat_account", "No-VAT A/C", 170, "w"),
                   ("source", "Source", 150, "w"), ("notes", "Check", 230, "w")]
        bottom = tk.Frame(page, bg=LIGHT); bottom.pack(side="bottom", fill="x", padx=10, pady=8)
        tk.Checkbutton(bottom, text="Replace ALL previous invoices (a safety backup is made first)", variable=self.import_replace, bg=LIGHT, fg=RED).pack(side="left")
        tk.Button(bottom, text="Auto Calculate Totals", command=self.import_auto_calculate, bg=NAVY, fg="white", border=0, padx=14, pady=8).pack(side="right", padx=6)  # 2.9.89
        tk.Button(bottom, text="Review & Save Import", command=self.send_import, bg=GOLD, fg=NAVY, font=("Segoe UI", 10, "bold"), border=0, padx=26, pady=8).pack(side="right")
        tk.Button(bottom, text="Remove Row", command=lambda: self.import_sheet.delete_selected(), bg=RED, fg="white", border=0, padx=12, pady=8).pack(side="right", padx=6)
        self.import_status = tk.Label(bottom, text="", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")); self.import_status.pack(side="right", padx=10)
        tk.Button(bottom, text="Select All", command=self.select_all_import_rows,
                  bg=LIGHT, fg=NAVY, border=0, padx=10, pady=8).pack(side="left", padx=(12, 0))  # 2.9.107
        tk.Button(bottom, text="Apply VAT A/C to selected", command=self.apply_selected_import_vat_account,
                  bg=NAVY, fg="white", border=0, padx=10, pady=8).pack(side="left", padx=(12, 3))
        self.import_bulk_vat_account = tk.StringVar()
        self.account_search_box(bottom, self.import_bulk_vat_account, 16).pack(side="left", padx=3)
        self.import_sheet = EditableSheet(self, page, columns, ["invoice_number", "invoice_date", "party_name", "entry_type", "currency", "subtotal", "vat",
            "vat_account", "total", "supplier_account", "expense_account", "expense_no_vat_account"], self.import_cell_changed, height=12,
            lookup_columns=("vat_account","supplier_account","expense_account","expense_no_vat_account"), lookup_groups=True,
            choices_by_column={"entry_type":list(TYPES)}, selectmode="extended")
        self.import_tree = self.import_sheet.tree
        self.import_check_label = tk.Label(page, text="Select a row to read its full Check note here.", bg="#fff8e6", fg=NAVY, anchor="w", justify="left", wraplength=1200)
        self.import_check_label.pack(fill="x", padx=12, pady=(0, 4), before=bottom)
        self.import_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_import_check(), add="+")
        tk.Button(bar,text="Review original document",command=self.review_import_document,bg=NAVY,fg="white").pack(side="left",padx=3)
        flow_toolbars(bar, bottom)  # 2.9.59: Save button stays visible on 1366-px screens

    def review_import_document(self):
        selected=self.import_tree.selection()
        if not selected: return messagebox.showwarning("Invoice review","Select an imported PDF/photo row")
        row=self.import_sheet.rows.get(selected[0])
        if not row or not row.get("_path"): return messagebox.showwarning("Invoice review","This row has no original document")
        from desktop_stage3_common import review_handwriting
        data=dict(row.get("_reading") or {})
        data.update({key:row.get(key) for key in ("invoice_number","invoice_date","party_name","currency","subtotal","vat","total")})
        data["items"]=row.get("_items") or []
        result=review_handwriting(self,row["_path"],data,force=True)
        if result is None: return
        for key in ("invoice_number","invoice_date","party_name","currency","subtotal","vat","total"): row[key]=result.get(key)
        row["_items"]=result.get("items") or [];row["_reading"]=result;row["_human_reviewed"]=True
        self.import_sheet.refresh(selected[0])

    def select_all_import_rows(self):
        rows = list(self.import_tree.get_children())
        if rows: self.import_tree.selection_set(rows); self.import_tree.focus_set()

    def apply_selected_import_vat_account(self):
        selected = [iid for iid in self.import_tree.get_children() if iid in self.import_tree.selection()]
        if not selected:
            return messagebox.showwarning("Import", "Select the preview rows to change (Ctrl / Shift for multiple rows)")
        try:
            account = self.resolve_import_account(self.import_bulk_vat_account.get())
            if not account:
                raise ValueError("Choose a VAT account before applying it")
        except ValueError as exc:
            return messagebox.showwarning("Import", str(exc))
        if not messagebox.askyesno("Apply VAT account",
                                   f"Set VAT A/C {account} on {len(selected)} selected preview row(s)?\n"
                                   "Other rows and already imported invoices will not change."):
            return
        for iid in selected:
            row = self.import_sheet.rows[iid]
            row["vat_account"] = account
            row["_vat_account_chosen"] = True
            self.import_sheet.refresh(iid)
        self.import_bulk_vat_account.set(account)

    def resolve_import_account(self, text):
        value=str(text or "").strip()
        if not value: return ""
        code=value.split(" - ",1)[0].strip()
        if code.replace(".","").isdigit(): return code
        names=getattr(self,"_all_accounts",None)
        if names is None:
            names={str(row["code"]):row["name_en"] for row in self.client.accounts()}
            self._all_accounts=names
        from desktop import row_matches_search
        matches=[account for account,name in names.items() if row_matches_search((account,name),value)]
        if len(matches)==1: return matches[0]
        raise ValueError("Choose one account from the list (F2 / right-click), or enter its number")

    def show_import_check(self):
        """Show the full Check note of the selected preview row (the column is too narrow for long notes)."""
        label = getattr(self, "import_check_label", None)
        selected = self.import_tree.selection()
        if label is None or not selected: return
        row = self.import_sheet.rows.get(selected[0], {})
        label.config(text=f'Row {row.get("line", "")} - Check: {row.get("notes") or "nothing to review"}')

    def import_cell_changed(self, iid, key, text):
        row = self.import_sheet.rows[iid]
        if key in ("party_name", "invoice_date", "subtotal", "vat", "total") and row.get("problem"):
            row.pop("problem", None)  # corrected by hand: checked again when saving
            if str(row.get("notes") or "").startswith("Check"): row["notes"] = ""
        if key == "entry_type":
            if text not in TYPES: messagebox.showwarning("Import","Choose Purchases, Expenses, Assets or Sales"); return False
            row[key] = text
            if self.import_mode == "pdf":
                if not row.get("_vat_account_chosen") and row.get("vat_account") in (PURCHASE_VAT,EXPENSE_VAT,SALES_VAT):
                    row["vat_account"] = EXPENSE_VAT if text=="Expenses" else SALES_VAT if text=="Sales" else PURCHASE_VAT
                cost_code=str(row.get("expense_account") or "").split(" - ",1)[0].strip()
                required_cost_class={"Assets":"2","Sales":"7","Purchases":"6","Expenses":"6"}[text]
                if not cost_code.startswith(required_cost_class):
                    row["expense_account"] = "" if text=="Assets" else "713" if text=="Sales" else "601100000"
                party_code=str(row.get("supplier_account") or "").split(" - ",1)[0].strip()
                required_party_prefix={"Assets":"40","Purchases":"40","Sales":"41","Expenses":"5"}[text]
                if party_code and not party_code.startswith(required_party_prefix):
                    row["supplier_account"] = ""
        elif key in ("vat_account","supplier_account","expense_account","expense_no_vat_account"):
            try: row[key]=self.resolve_import_account(text)
            except ValueError as exc: messagebox.showwarning("Import",str(exc)); return False
            if key == "vat_account": row["_vat_account_chosen"] = True
        elif key in ("subtotal", "vat", "total"):
            value = _num(text, None)
            if value is None and text.strip(): messagebox.showwarning("Import", "Enter a number"); return False
            row[key] = value
            if self.import_mode != "pdf" and key in ("subtotal", "vat") and row.get("subtotal") is not None and row.get("vat") is not None:
                row["total"] = round(row["subtotal"] + row["vat"], 2)
        elif key == "currency":
            if text.upper() not in self.currency_codes: messagebox.showwarning("Import", "Choose a currency from Settings"); return False
            row[key] = text.upper()
        elif key == "invoice_date": row[key] = _dd(text)
        else: row[key] = text
        row["_display"] = {k: (f"{row[k]:,.2f}" if isinstance(row.get(k), (int, float)) else "") for k in ("subtotal", "vat", "total", "deductible", "non_deductible")}

    def choose_import(self, path=None):
        path = path or filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm")])
        if not path: return
        kind, entry_type = TYPES[self.import_type.get()]
        try:
            if entry_type == "expenses":
                rows = [{"invoice_number": r["reference"], "invoice_date": r["expense_date"], "party_name": r.get("supplier") or r["description"],
                        "items": r.get("items") or r["description"], "currency": r["currency"],
                         "deductible": r["with_vat_subtotal"], "non_deductible": r["without_vat_subtotal"],
                         "subtotal": r["with_vat_subtotal"] + r["without_vat_subtotal"], "vat": r["vat"], "total": r["with_vat_subtotal"] + r["without_vat_subtotal"] + r["vat"],
                         "source": f"Excel row {r['source_row']}", "_expense": r} for r in read_expenses(path)]
            else:
                rows = [{**r, "source": f"Excel row {r['source_row']}", **({"notes": r["problem"]} if r.get("problem") else {})}
                        for r in read_invoices(path, default_currency=self.currency.get(), default_kind=kind,allowed_currencies=self.currency_codes)]
        except Exception as exc: return messagebox.showerror("Import", f"The Excel file could not be read: {exc}")
        self.import_mode = "excel"; self.import_rows = rows; self.file_label.config(text=f"Excel: {path}", fg=NAVY); self.populate_import_preview()

    def choose_import_pdfs(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF invoices or photos", "*.pdf *.png *.jpg *.jpeg"), ("PDF invoices", "*.pdf")])
        if not paths: return
        prepare_pdf_reading(self)  # 2.9.85: the company (buyer) and the known suppliers
        def work(progress, cancel):  # 2.9.85: off the screen, page by page, with a Stop button
            read, errors = [], []
            for number, path in enumerate(paths, 1):
                if cancel is not None and cancel.is_set(): break
                report = (lambda done, total, stage="OCR", n=number: progress(done, total, f"File {n} of {len(paths)} - {stage}")) if progress else None
                try: read.append((path, read_invoice_pdf_pages(path, progress=report, cancel=cancel) if report else read_invoice_pdf_pages(path)))
                except Exception as exc: errors.append(f"{Path(path).name}: {exc}")
            return read, errors
        run_with_progress(self, "Import PDF", work, lambda result: Stage3Mixin._show_import_pdfs(self, paths, *result))

    def _show_import_pdfs(self, paths, read, errors):
        for error in errors: messagebox.showerror("Import PDF", error)
        rows = []
        for path, documents in read:
            for data in documents:
                from invoice_intake import enrich
                data=enrich(data)
                suggested = "Sales" if self.import_type.get()=="Sales" else data.get("suggested_type") or ""
                asset_details=asset_pdf_details(data)
                type_note = (f"Suggested Type: {suggested}; review before import" if suggested else
                             "Type not clear from PDF; choose Purchases, Expenses or Assets")
                rows.append({"invoice_number": data.get("invoice_number") or "", "invoice_date": data.get("invoice_date") or "",
                         "party_name": data.get("party_name") or "", "currency": data.get("currency") or "",
                          "subtotal": data.get("subtotal"), "vat": data.get("vat"), "total": data.get("total"),
                          **({"deductible": data["taxable_subtotal"], "non_deductible": data["exempt_subtotal"]} if data.get("taxable_subtotal") is not None else {}),  # 2.9.85
                          "entry_type": suggested, "source": f'{data["file"]} - {data["page_range"]}',
                           "notes": (data.get("notes", "") + "; " + type_note + "; Human review required").strip("; "), "_path": path, "_items": data.get("items") or [], "_reading":data,
                           "_review_warnings": list(data.get("review_warnings") or []),
                           "_asset_name":asset_details["name"],"_asset_date":asset_details["acquired_on"],
                           "_asset_currency":asset_details["currency"],"_asset_cost":asset_details["cost"]})
                if suggested != "Sales" and hasattr(self, "import_row_rule"):  # 2.9.121: posted like this supplier's last invoice
                    note = self.import_row_rule(rows[-1], data)
                    if note: rows[-1]["notes"] = f"{note}; {rows[-1]['notes']}".strip("; ")
        self.import_mode = "pdf"; self.import_rows = rows
        self.file_label.config(text=f"{len(paths)} PDF file(s). Confirm each Type and amount; VAT 0 if none. Expenses are paid transactions.", fg=NAVY); self.populate_import_preview()

    def populate_import_preview(self):
        self.import_sheet.clear(); selected = self.import_view_currency.get()
        rows = [r for r in self.import_rows if selected == "All Currencies" or r.get("currency") == selected]
        for row in rows[:20000]:
            expense=row.get("_expense") or {}
            entry_type=row.get("entry_type") if self.import_mode=="pdf" else self.import_type.get()
            if self.import_mode!="pdf": row["entry_type"]=entry_type
            row.setdefault("supplier_account", expense.get("payment_account") or ("531" if expense else ""))
            row.setdefault("vat_account", expense.get("vat_account") or (EXPENSE_VAT if entry_type=="Expenses" else SALES_VAT if entry_type=="Sales" else PURCHASE_VAT))
            row.setdefault("expense_account", expense.get("expense_account") or ("" if self.import_mode=="pdf" and entry_type=="Assets" else "713" if entry_type=="Sales" else "601100000"))
            row.setdefault("expense_no_vat_account", expense.get("expense_without_vat_account") or "601100001")
            row.setdefault("notes", row.get("currency_issue") or ""); self.import_cell_changed_display(row); self.import_sheet.insert(row)
        self.import_status.config(text=f"{len(rows)} row(s) — review each Type ({selected})" if self.import_mode=="pdf" else
                                  f"{len(rows)} row(s) ready as {self.import_type.get()} ({selected})")

    def import_cell_changed_display(self, row):
        row["_display"] = {k: (f"{float(row[k]):,.2f}" if row.get(k) not in (None, "") else "") for k in ("subtotal", "vat", "total", "deductible", "non_deductible")}

    def auto_send_import(self):
        """Compatibility callback: imports stay in the editable preview until explicitly saved."""
        if hasattr(self, "import_status"):
            self.import_status.config(text="Review the preview and select Review & Save Import to post.")

    def import_duplicates(self, rows, default_entry_type="purchases"):
        """{id(row): (row, [saved invoices])} for preview rows already in the books (2.9.51). Expenses are not invoices."""
        checked = []
        for r in rows:
            entry_type = TYPES[r["entry_type"]][1] if self.import_mode == "pdf" and r.get("entry_type") in TYPES else default_entry_type
            if entry_type == "expenses" or not r.get("invoice_number"): continue
            checked.append((r, {"kind": entry_type, "party_name": r.get("party_name"), "invoice_number": r.get("invoice_number"), "doc_subtype": r.get("doc_subtype") or "invoice",
                                "by_amount": bool(r.get("number_from_row")), "invoice_date": r.get("invoice_date"), "total": r.get("total")}))
        if not checked: return {}
        try:
            found = self.client.invoice_duplicates([item for _r, item in checked])
            if not isinstance(found, list): return {}
            result = {id(r): (r, matches) for (r, _item), matches in zip(checked, found) if isinstance(matches, list) and matches}
        except Exception: result = {}  # the check never blocks an import when the service cannot answer
        seen = {}  # 2.9.103: the same supplier and invoice number twice in the same upload is a duplicate too
        for r, item in checked:
            key = (item["kind"], str(item.get("party_name") or "").strip().casefold(), str(item.get("invoice_number") or "").strip().casefold())
            if key in seen:
                first = seen[key]
                match = {"id": "earlier in this upload", "invoice_number": first.get("invoice_number"), "invoice_date": first.get("invoice_date"),
                         "total": first.get("total"), "currency": first.get("currency"), "party_name": first.get("party_name")}
                result.setdefault(id(r), (r, []))[1].append(match)
            else: seen[key] = r
        return result

    def import_auto_calculate(self):
        """2.9.89: complete or correct the amounts of the selected rows (all rows when none is selected):
        Total = Subtotal + VAT; a missing amount is worked out from the other two; with the subtotal only, VAT at the
        standard rate. Each changed row says so in its notes."""
        sheet = self.import_sheet; chosen = [i for i in sheet.tree.selection() if i in sheet.rows] or list(sheet.rows)
        rate = 11.0
        try: rate = float(self.client.settings().get("vat_rate") or 11)
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        changed = 0
        for iid in chosen:
            row = sheet.rows[iid]
            amounts = {k: _num(row.get(k), None) if row.get(k) not in (None, "") else None for k in ("subtotal", "vat", "total")}
            s, v, total = amounts["subtotal"], amounts["vat"], amounts["total"]
            if s is not None and v is not None: new = (s, v, round(s + v, 2))
            elif total is not None and v is not None: new = (round(total - v, 2), v, total)
            elif s is not None and total is not None: new = (s, round(total - s, 2), total)
            elif s is not None: new = (s, round(s * rate / 100, 2), round(s * (1 + rate / 100), 2))
            elif total is not None: new = (round(total / (1 + rate / 100), 2), round(total - total / (1 + rate / 100), 2), total)
            else: continue
            if (s, v, total) == new: continue
            row["subtotal"], row["vat"], row["total"] = new
            row["notes"] = (f"Amounts auto-calculated ({new[0]:,.2f} + VAT {new[1]:,.2f} = {new[2]:,.2f}); " + str(row.get("notes") or "").replace("subtotal + VAT differ from the total", "")).strip()
            self.import_cell_changed_display(row); sheet.refresh(iid); changed += 1
        self.import_status.config(text=f"{changed} row(s) recalculated: Total = Subtotal + VAT. Check them, then press Review & Save Import.")
        return changed

    def split_ready_import_rows(self, rows):
        """Rows that can be posted without a question, and the others (their Check note says why)."""
        ready = []; waiting = []
        for r in rows:
            problems = list(r.get("_review_warnings") or [])
            if not r.get("party_name"): problems.append("customer / supplier")
            if r.get("total") in (None, "", 0, 0.0): problems.append("total")
            if r.get("problem") and "date" in str(r.get("problem")): problems.append("date")
            if self.import_mode == "pdf":
                if not r.get("invoice_number"): problems.append("invoice number")
                if not r.get("invoice_date"): problems.append("date")
                if r.get("subtotal") in (None, "") or r.get("vat") in (None, ""): problems.append("subtotal / VAT")
                elif r.get("total") not in (None, "") and abs(r["subtotal"] + r["vat"] - r["total"]) > max(0.05, abs(r["total"]) * 0.005): problems.append("subtotal + VAT differ from the total")
                if r.get("entry_type") in ("Assets", "Expenses"): problems.append(f"{r['entry_type']} rows need the account review")
                elif not str(r.get("expense_account") or "").startswith("7" if r.get("entry_type") == "Sales" else "6"): problems.append("cost / revenue account")
            if problems:
                r["notes"] = ("Not saved automatically - check: " + ", ".join(problems) + ". " + str(r.get("notes") or "")).strip()
                waiting.append(r)
            else: ready.append(r)
        return ready, waiting

    def _post_pdf_purchase_with_items(self, r):
        """A purchase PDF whose item lines were read: missing items are created in Inventory and received in stock."""
        items = [it for it in (r.get("_items") or []) if it.get("description") and it.get("quantity")]
        subtotal = float(r.get("subtotal") or 0); vat = float(r.get("vat") or 0)
        if not items or not subtotal or abs(sum(float(it.get("total") or 0) for it in items) - subtotal) > max(0.05, subtotal * 0.01): return None
        rate = round(vat / subtotal * 100, 4) if subtotal else 0
        lines = []; remaining_subtotal = round(subtotal, 2); remaining_vat = round(vat, 2)
        for index, it in enumerate(items):
            item = resolve_item(self, it["description"], it.get("unit") or "unit", None, None)
            last = index == len(items) - 1
            line_subtotal = remaining_subtotal if last else round(float(it["total"]), 2)
            line_vat = remaining_vat if last else round(line_subtotal * rate / 100, 2)
            line_rate = rate
            if all("vat" in x for x in items) and abs(sum(float(x["vat"]) for x in items) - vat) <= 0.05:  # 2.9.86: each row's own VAT (0% / 11%)
                line_vat = remaining_vat if last else round(float(it["vat"]), 2)
                line_rate = round(line_vat / line_subtotal * 100, 4) if line_subtotal else 0
            remaining_subtotal = round(remaining_subtotal - line_subtotal, 2); remaining_vat = round(remaining_vat - line_vat, 2)
            lines.append({"item_code": item["sku"], "description": item.get("name") or it["description"], "quantity": float(it["quantity"]), "unit": item.get("unit") or "unit",
                          "unit_price": round(line_subtotal / float(it["quantity"]), 6), "discount_percent": 0, "vat_rate": line_rate, "warehouse": "MAIN",
                          "deductible_subtotal": line_subtotal, "vat": line_vat})
        invoice = {"invoice_number": r["invoice_number"], "invoice_date": r["invoice_date"], "party_name": r["party_name"], "kind": "purchases",
                   "currency": r["currency"], "status": "posted", "source_file": r.get("source") or "PDF import", "remember_posting": True,
                   "expense_account": str(r.get("expense_account") or "601100000").split(" - ", 1)[0].strip(),
                   "vat_account": str(r.get("vat_account") or "442660000").split(" - ", 1)[0].strip(), "vat_use": "mixed"}
        account = str(r.get("supplier_account") or "").split(" - ", 1)[0].strip()
        if account.startswith("40") and account != "401": invoice["supplier_account"] = account
        return self.client.create_manual_invoice({**invoice, "duplicate_ok": True}, lines)["invoice_id"]  # checked with the upload

    def send_import(self, auto=False, rows=None):
        if auto:
            return messagebox.showwarning("Import", "Automatic saving is disabled. Review the preview and use Review & Save Import.")
        rows = rows if rows is not None else self.import_sheet.ordered()
        if not rows: return messagebox.showwarning("Import", "Choose an Excel or PDF file first")
        asset_rows=[r for r in rows if self.import_mode=="pdf" and r.get("entry_type")=="Assets"]
        if asset_rows:
            row=asset_rows[0]
            if not str(row.get("expense_account") or "").split(" - ",1)[0].strip().startswith("2"):
                return messagebox.showwarning("Asset PDF",
                    f"PDF row {row.get('line','')}: choose a class 2 fixed-asset account before register review.")
            if not messagebox.askyesno("Review asset PDF",
                    "This Assets row will create one fixed-asset register item after review. "
                    "It will NOT create a supplier invoice, journal posting, stock movement, or PDF attachment. "
                    "Process this row now?"):
                return
            reviewer=getattr(self,"start_import_asset_review",None)
            if not callable(reviewer):
                return messagebox.showerror("Asset PDF",
                    "Asset register review is unavailable. The preview row was kept and no invoice was posted.")
            reviewer(row)
            return
        if self.import_mode=="pdf":
            unreviewed=[str(r.get("line", "?")) for r in rows if not r.get("_human_reviewed")]
            if unreviewed:
                return messagebox.showwarning("Import",f"Review the original PDF/photo for row(s) {', '.join(unreviewed[:10])} before saving.")
        kind, entry_type = TYPES[self.import_type.get()]
        if self.import_mode == "pdf":
            missing = [str(r.get("line", "")) for r in rows if not r.get("party_name") or r.get("total") in (None, "")]
            if missing: return messagebox.showwarning("Import", f"Row(s) {', '.join(missing[:10])}: enter the customer/supplier and the total")
        else:
            # 2.9.54: an Excel file with some incomplete rows is no longer refused as a whole - those rows stay in the
            # preview with the reason (Check column) and the others are imported.
            def row_day(r):
                for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
                    try: return datetime.strptime(str(r.get("invoice_date") or "").strip(), pattern)
                    except ValueError: pass
                return None
            def incomplete(r):
                return not r.get("party_name") or r.get("total") in (None, "", 0, 0.0) or bool(r.get("problem")) or row_day(r) is None
            waiting = [r for r in rows if incomplete(r)]
            for r in waiting:
                if not str(r.get("notes") or "").startswith("Check"):
                    r["notes"] = ("Check: supplier / customer, date and amount. " + str(r.get("notes") or "")).strip()
            ready = [r for r in rows if not incomplete(r)]
            fiscal_year = getattr(self, "current_fiscal_year", None)
            other_year = [r for r in ready if fiscal_year and row_day(r).year != int(fiscal_year)]
            if other_year:
                years = ", ".join(sorted({str(row_day(r).year) for r in other_year}))
                keep = True if auto else messagebox.askyesnocancel("Import", f"{len(other_year)} row(s) are dated {years}, not {fiscal_year} (the year open now).\n\n"
                    f"Yes = keep them in the preview: open {years} (Switch Company / Year) and import them there\nNo = import them in {fiscal_year} anyway\nCancel = stop")
                if keep is None: return
                if keep:
                    for r in other_year: r["notes"] = f"Check: dated {row_day(r).year} - open {row_day(r).year} (Switch Company / Year) to import this row"
                    waiting += other_year; ready = [r for r in ready if not any(r is o for o in other_year)]
            # 2.9.55: the same supplier, date and total twice in the file (no invoice number to tell them apart)
            seen = {}; repeats = []
            for r in ready:
                key = (str(r.get("party_name") or "").strip().casefold(), str(r.get("invoice_date") or ""), round(float(r.get("total") or 0), 2))
                if r.get("number_from_row") and key in seen: repeats.append((r, seen[key]))
                else: seen.setdefault(key, r)
            if repeats:
                listed = ", ".join(f"{r.get('source_row')} (= {first.get('source_row')})" for r, first in repeats[:12])
                keep = True if auto else messagebox.askyesnocancel("Import", f"{len(repeats)} row(s) repeat another row of the file - same name, date and total, "
                    f"and the file has no invoice number to tell them apart: rows {listed}{' ...' if len(repeats) > 12 else ''}.\n\n"
                    "Yes = keep the repeats in the preview (import only the first)\nNo = they are different invoices, import them all\nCancel = stop")
                if keep is None: return
                if keep:
                    for r, first in repeats: r["notes"] = f"Check: same supplier, date and total as Excel row {first.get('source_row')}"
                    waiting += [r for r, _first in repeats]; ready = [r for r in ready if not any(r is x for x, _f in repeats)]
            if waiting:
                for iid in getattr(self.import_sheet, "rows", {}): self.import_sheet.refresh(iid)
                lines = ", ".join(str(r.get("line") or r.get("source_row") or "") for r in waiting[:15])
                if not ready: return messagebox.showwarning("Import", f"No row can be imported now: rows {lines}{' ...' if len(waiting) > 15 else ''} need a check. See the Check column.")
                if not auto and not messagebox.askyesno("Import", f"{len(waiting)} row(s) stay in the preview (see the Check column): {lines}{' ...' if len(waiting) > 15 else ''}.\n\n"
                                                        f"Import the other {len(ready)} row(s) now?"): return
                rows = ready
        if self.import_mode == "pdf":
            incomplete = [str(r["line"]) for r in rows if not r.get("invoice_number") or not r.get("invoice_date")
                          or r.get("subtotal") in (None, "") or r.get("vat") in (None, "")]
            if incomplete:
                return messagebox.showwarning("Import", f"PDF row(s) {', '.join(incomplete[:10])}: enter invoice number, date, subtotal and VAT (type 0 if none) before importing")
            inconsistent = [str(r["line"]) for r in rows if abs(r["subtotal"] + r["vat"] - r["total"]) > max(0.05, abs(r["total"]) * 0.005)]
            if inconsistent:
                return messagebox.showwarning("Import", f"PDF row(s) {', '.join(inconsistent[:10])}: subtotal, VAT and total do not reconcile. Correct the amounts before importing")
            uncategorized = [str(r["line"]) for r in rows if r.get("entry_type") not in TYPES]
            if uncategorized:
                return messagebox.showwarning("Import",f"PDF row(s) {', '.join(uncategorized[:10])}: choose a Type for each row before importing")
            assets = [str(r["line"]) for r in rows if r["entry_type"]=="Assets" and not str(r.get("expense_account") or "").startswith("2")]
            if assets:
                return messagebox.showwarning("Import",f"PDF asset row(s) {', '.join(assets[:10])}: select a class 2 fixed-asset account in Cost / Revenue A/C")
            wrong_cost = [str(r["line"]) for r in rows if r["entry_type"]!="Assets" and not
                          str(r.get("expense_account") or "").startswith("7" if r["entry_type"]=="Sales" else "6")]
            if wrong_cost:
                return messagebox.showwarning("Import",
                        f"PDF row(s) {', '.join(wrong_cost[:10])}: choose a cost/revenue account matching the selected Type (class 6 for Purchases/Expenses, class 7 for Sales)")
            wrong_party = [str(r["line"]) for r in rows if r.get("supplier_account") and r["entry_type"]!="Expenses" and not
                           str(r["supplier_account"]).startswith("41" if r["entry_type"]=="Sales" else "40")]
            if wrong_party:
                return messagebox.showwarning("Import",f"PDF row(s) {', '.join(wrong_party[:10])}: choose a matching party account (class 40 for Purchases/Assets, class 41 for Sales)")
            unpaid = [str(r["line"]) for r in rows if r["entry_type"]=="Expenses" and
                      not str(r.get("supplier_account") or "").split(" - ",1)[0].strip().startswith("5")]
            if unpaid:
                return messagebox.showwarning("Import",
                        f"PDF expense row(s) {', '.join(unpaid[:10])}: choose a class 5 cash/bank payment account in Party / Paid A/C. Expenses post as paid; use Purchases for unpaid invoices")
            if self.import_replace.get() and any(r["entry_type"]=="Expenses" for r in rows):
                return messagebox.showwarning("Import","Replace ALL previous invoices cannot be used with PDF expense rows. Uncheck Replace to import paid expenses")
            counts = ", ".join(f"{label}: {sum(r['entry_type']==label for r in rows)}" for label in TYPES if any(r["entry_type"]==label for r in rows))
            if not auto and not messagebox.askyesno("Confirm PDF types",
                    f"Review the Type of every PDF row before posting.\n{counts}\n\n"
                    "Expenses are recorded as PAID from the selected payment account; "
                    "Purchases are supplier invoices and Assets require a fixed-asset account.\n\n"
                    "Are these types and accounts correct?"):
                return
        if self.import_replace.get() and not messagebox.askyesno("Replace previous data", "ALL previous invoices will be removed and replaced. A safety backup is made first. Continue?"): return
        checker = getattr(self, "import_duplicates", None)
        duplicates = checker(rows, entry_type) if callable(checker) and not self.import_replace.get() else {}
        if duplicates:
            listed = "\n".join(f"Row {r.get('line', '')}: {r.get('invoice_number')} - {r.get('party_name')} (already saved {found[0]['invoice_date']}, total {float(found[0]['total'] or 0):,.2f})"
                               for r, found in list(duplicates.values())[:10])
            skip = True if auto else messagebox.askyesnocancel("Already saved",
                f"{len(duplicates)} invoice(s) are already in the books (same customer / supplier and number):\n{listed}\n\n"
                "Yes = skip them (they stay in the preview)\nNo = save them again anyway (administrator only; anyone else gets a duplicate-number error)\nCancel = stop")
            if skip is None: return
            for r, found in duplicates.values():
                r["notes"] = f"Already saved (ID {found[0]['id']}, {found[0]['invoice_date']}) - not saved again. " + str(r.get("notes") or "").replace("Already saved", "Was saved")
            if skip is False:
                for r, _found in duplicates.values(): r["allow_duplicate"] = True  # 2.9.134 (D3): honoured by the server for administrators only
            if skip:
                rows = [r for r in rows if id(r) not in duplicates]
                for iid in self.import_sheet.rows: self.import_sheet.refresh(iid)
                if not rows:
                    self.import_status.config(text=f"{len(duplicates)} row(s) already saved - nothing new to import")
                    if not auto: messagebox.showinfo("Import", "Every row is already in the books; nothing was saved again.")
                    return
        done = 0; errors = []; completed = []
        try:
            expense_rows = [r for r in rows if r.get("entry_type")=="Expenses"] if self.import_mode=="pdf" else rows if entry_type=="expenses" else []
            if self.import_mode == "excel" and entry_type != "expenses":
                items = [{**{k: v for k, v in r.items() if not k.startswith("_") and k not in ("line", "source", "notes")}, "entry_type": entry_type, "kind": kind} for r in rows]
                result = self.client.import_invoices(items, replace_existing=self.import_replace.get()); done = result["imported"]
                errors = [f"{e.get('invoice_number')}: {e['error']}" for e in result["errors"]]
                failed={e["index"] for e in result["errors"]}
                completed.extend(r for index,r in enumerate(rows) if index not in failed)
            elif self.import_mode == "pdf":
                invoice_rows = [r for r in rows if r["entry_type"]!="Expenses"]
                if not self.import_replace.get():  # 2.9.50: read item lines -> items created and received in stock
                    with_items = []
                    for r in [r for r in invoice_rows if r["entry_type"] == "Purchases" and r.get("_items")]:
                        try: invoice_id = self._post_pdf_purchase_with_items(r)
                        except Exception as exc:
                            errors.append(f"{r['line']}: {exc}"); with_items.append(r); continue
                        if invoice_id is None: continue
                        with_items.append(r); done += 1; completed.append(r)
                        try: self.client.upload_attachment(invoice_id, Path(r["_path"]).name, "application/pdf", Path(r["_path"]).read_bytes())
                        except Exception as exc: errors.append(f"{r['line']}: invoice POSTED (ID {invoice_id}), PDF attachment failed: {exc}. Attach it manually; do not re-import")
                    invoice_rows = [r for r in invoice_rows if not any(r is w for w in with_items)]
                    notify_new_items(self, "Import PDF")  # 2.9.86: the items that did not exist
                items=[]
                for r in invoice_rows:
                    row_kind,row_type=TYPES[r["entry_type"]]
                    items.append({"invoice_number": r["invoice_number"], "invoice_date": r["invoice_date"], "party_name": r["party_name"],
                                  "kind": row_kind, "entry_type": row_type, "currency": r["currency"], "subtotal": r["subtotal"], "vat": r["vat"],
                                  "total": r["total"], "source_file": r["source"], "remember_posting": self.import_mode == "pdf",
                                  "supplier_account": r.get("supplier_account") or "", "vat_account": r.get("vat_account") or "",
                                  "expense_account": r.get("expense_account") or "", "expense_no_vat_account": r.get("expense_no_vat_account") or "",
                                  "allow_duplicate": bool(r.get("allow_duplicate"))})
                if items:
                    result=self.client.import_invoices(items, replace_existing=self.import_replace.get())
                    done+=result["imported"]
                    errors += [f"{e.get('invoice_number')}: {e['error']}" for e in result["errors"]]
                    failed={e["index"] for e in result["errors"]}
                    successful_rows=[r for index,r in enumerate(invoice_rows) if index not in failed]
                    completed.extend(successful_rows)
                    if len(result["ids"]) != len(successful_rows):
                        errors.append("The service did not return every posted invoice ID. Check posted invoices and attach missing PDFs manually; do not re-import those rows")
                    for r, invoice_id in zip(successful_rows,result["ids"]):
                        try:
                            self.client.upload_attachment(invoice_id, Path(r["_path"]).name, "application/pdf", Path(r["_path"]).read_bytes())
                        except Exception as exc: errors.append(f"{r['line']}: invoice POSTED (ID {invoice_id}), PDF attachment failed: {exc}. Attach it manually; do not re-import")
            for r in expense_rows:
                try:
                    item = dict(r.get("_expense") or {}); vat = r.get("vat") or 0
                    base = r.get("subtotal") if r.get("subtotal") is not None else r["total"] - vat
                    without = float(item.get("without_vat_subtotal") or 0)
                    item.update(expense_date=r["invoice_date"], description=r["party_name"], currency=r["currency"], reference=r.get("invoice_number") or "",
                                with_vat_subtotal=round(base - without, 2), without_vat_subtotal=without, vat=vat,
                                payment_account=r.get("supplier_account") or item.get("payment_account"),
                                expense_account=r.get("expense_account") or item.get("expense_account"),
                                expense_without_vat_account=r.get("expense_no_vat_account") or item.get("expense_without_vat_account"),
                                vat_account=r.get("vat_account") or item.get("vat_account"))
                    expense_id = self.client.add_expense(item)["expense_id"]; done += 1; completed.append(r)
                except Exception as exc:
                    errors.append(f"{r['line']}: expense not imported: {exc}")
                    continue
                if r.get("_path"):
                    try: self.client.upload_expense_attachment(expense_id, Path(r["_path"]).name, "application/pdf", Path(r["_path"]).read_bytes())
                    except Exception as exc: errors.append(f"{r['line']}: expense POSTED (ID {expense_id}), PDF attachment failed: {exc}. Attach it manually; do not re-import")
        except Exception as exc:
            return messagebox.showerror("Import",f"{exc}\n\nThe import result may be uncertain. Check posted invoices before retrying, to avoid duplicates.")
        remaining = [r for r in self.import_sheet.ordered() if id(r) not in {id(item) for item in completed}]
        message = f"{done} {'PDF document(s)' if self.import_mode=='pdf' else self.import_type.get().lower()} imported." + (f"\n\n{len(errors)} issue(s):\n" + "\n".join(errors[:12]) if errors else "")
        if remaining and done: message += f"\n\n{len(remaining)} unfinished row(s) kept in the preview for correction."
        (messagebox.showwarning if errors else messagebox.showinfo)("Import", message)
        if done:
            self.import_sheet.clear()
            for row in remaining: self.import_sheet.insert(row)
            self.import_rows = remaining
            if remaining and self.import_replace.get(): self.import_replace.set(False)
        self.load_dashboard(); self.load_invoices(); self.load_journal(); self.load_trial(); self.load_transactions()

    def start_import_asset_review(self,row):
        """Route an Assets preview row to the register, never to invoice import/posting."""
        self.new_asset()
        for key in ("name","acquired_on","start_on","currency","cost"):
            self.asset_fields[key].set("")
        for key,value in (("name",row.get("_asset_name")),("acquired_on",row.get("_asset_date")),
                          ("currency",row.get("_asset_currency")),("cost",row.get("_asset_cost")),
                          ("asset_account",row.get("expense_account"))):
            if value not in (None,""):
                self.asset_fields[key].set(f"{value:.2f}" if key=="cost" else str(value))
        if row.get("_asset_date"):
            self.asset_fields["start_on"].set(row["_asset_date"])
        def complete(_asset):
            self.import_rows=[item for item in self.import_rows if item is not row]
            self.populate_import_preview()
            self.import_status.config(text=f"Asset registered; {len(self.import_sheet.ordered())} preview row(s) remain")
        self.review_asset_pdf(row.get("_path") or row.get("source","PDF preview"),
                              row.get("notes",""),on_created=complete)

    # ================================================================ Payment & Receipt
    def build_transactions(self):
        nested = ttk.Notebook(self.transactions_tab); nested.pack(fill="both", expand=True, padx=8, pady=8)
        self.payment_forms = {}
        for kind, title in (("customer_receipt", "Add Customer Receipt"), ("supplier_payment", "Add Supplier Payment")):
            page = tk.Frame(nested, bg=LIGHT); nested.add(page, text=title); self.payment_forms[kind] = self.build_payment_form(page, kind)
        bank_page = tk.Frame(nested, bg=LIGHT); nested.add(bank_page, text="Bank Reconciliation"); self.build_bank_rec_page(bank_page)
        import desktop_design
        desktop_design.tab_bar(nested,min_tabs=3)
        self.load_transactions()

    def build_payment_form(self, page, kind):
        form = {"kind": kind, "id": None, "vars": {k: tk.StringVar() for k in ("number", "date", "party", "currency", "amount", "method", "cash_account",
                "reference", "description", "bank_commission", "exchange_difference",
                                                                            "commission_account", "exchange_gain_account", "exchange_loss_account")}}
        v = form["vars"]; v["date"].set(self.fiscal_today()); v["currency"].set(main_currency(self, 1)); v["method"].set("Cash"); v["cash_account"].set("531")
        form["department"] = tk.StringVar(); form["project"] = tk.StringVar()
        import desktop_design as design
        outer, box = design.panel(page, "Customer Receipt (RV)" if kind == "customer_receipt" else "Supplier Payment (PV)",
                                  "Money received from a customer" if kind == "customer_receipt" else "Money paid to a supplier",padx=10,pady=5)
        outer.pack(fill="x", padx=8, pady=(3,4))
        # Group related receipt/payment fields into compact rows. The controls remain in
        # entry order so keyboard navigation and the existing callbacks stay intact.
        grid = tk.Frame(box, bg=LIGHT); grid.pack(fill="x")
        for column in (1, 4, 7): grid.grid_columnconfigure(column, weight=1)
        form["not_deductible"] = tk.BooleanVar(value=False)
        place_tick(tax_tick(box, form["not_deductible"], LIGHT), side="bottom", anchor="w")  # 2.9.113 (bank commission / expense lines)
        def put(row, column, label, widget, bold=False, note=None):
            if label:
                tk.Label(grid, text=label, bg=LIGHT, fg=NAVY if bold else "#33475B", font=("Segoe UI", 9, "bold") if bold else ("Segoe UI", 9)
                         ).grid(row=row, column=3 * column, sticky="w", padx=(0 if column == 0 else 12, 6), pady=1)
            widget.grid(row=row, column=3 * column + 1, sticky="ew", padx=(0, 6), pady=1)
            if note: tk.Label(grid, text=note, bg=LIGHT, fg=MUTED).grid(row=row, column=3 * column + 2, sticky="w", padx=(2, 0),pady=1)
            return widget
        section=design.section_label(grid, "Document", 0, columns=9); section.grid_configure(pady=(3,1))
        put(1, 0, "Number", tk.Entry(grid, textvariable=v["number"], width=16, state="readonly", readonlybackground="white", font=("Segoe UI", 10, "bold")), True)
        put(1, 1, "Date", self.date_entry(grid, v["date"], 11))
        form["type"] = tk.StringVar(value="All")
        type_box = ttk.Combobox(grid, textvariable=form["type"], values=["All", "client", "supplier", "asset_supplier", "other_payable"], state="readonly", width=13)
        put(1, 2, "Customer Type" if kind == "customer_receipt" else "Supplier Type", type_box)
        type_box.bind("<<ComboboxSelected>>", lambda _e: self.payment_type_changed(form))
        form["party_box"] = put(2, 0, "Customer" if kind == "customer_receipt" else "Supplier", ttk.Combobox(grid, textvariable=v["party"], width=26))
        form["party_box"].bind("<KeyRelease>", lambda e: self.filter_payment_parties(form, e)); form["party_box"].bind("<<ComboboxSelected>>", lambda _e: self.payment_party_chosen(form))
        form["party_box"].bind("<FocusOut>", lambda _e: self.payment_party_chosen(form), add="+"); form["party_box"].bind("<Return>", lambda _e: self.payment_party_chosen(form), add="+")
        put(2, 1, "Currency", ttk.Combobox(grid, textvariable=v["currency"], values=self.currency_codes, state="readonly", width=8))
        put(2, 2, "Amount", tk.Entry(grid, textvariable=v["amount"], width=15, font=("Segoe UI", 10, "bold")), True)
        section=design.section_label(grid, "Payment", 3, columns=9); section.grid_configure(pady=(3,1))
        put(4, 0, "Method", ttk.Combobox(grid, textvariable=v["method"], values=METHODS, state="readonly", width=14))
        form["cash_box"] = put(4, 1, "Cash / Bank Account", ttk.Combobox(grid, textvariable=v["cash_account"], width=25, state="readonly"))
        put(4, 2, "Ref. / Cheque", tk.Entry(grid, textvariable=v["reference"], width=16))
        put(5, 0, "Description", tk.Entry(grid, textvariable=v["description"], width=28))
        # 2.9.79: bank commission and exchange difference, each on the account chosen here (number - name)
        section=design.section_label(grid, "Bank commission and exchange difference", 6, columns=9); section.grid_configure(pady=(3,1))
        put(7, 0, "Bank Commission", tk.Entry(grid, textvariable=v["bank_commission"], width=13))
        put(7, 1, "Commission A/C", self.account_search_box(grid, v["commission_account"], 42))
        put(7, 2, "Exchange Difference (+ / -)", tk.Entry(grid, textvariable=v["exchange_difference"], width=13))
        put(8, 0, "Exchange Gain A/C", self.account_search_box(grid, v["exchange_gain_account"], 42))
        put(8, 1, "Exchange Loss A/C", self.account_search_box(grid, v["exchange_loss_account"], 42))
        form["preview"] = tk.Label(box, text="", bg="#eef3f8", fg=NAVY, anchor="w", justify="left", font=("Consolas", 9))
        form["preview"].pack(fill="x", pady=(3, 0))
        self.reset_payment_accounts(form)
        for key in ("amount", "bank_commission", "exchange_difference", "cash_account", "commission_account", "exchange_gain_account", "exchange_loss_account", "party"):
            v[key].trace_add("write", lambda *_a, f=form: self.update_payment_preview(f))
        row3 = tk.Frame(box, bg=LIGHT); row3.pack(fill="x", pady=(3, 0))
        self.dimension_selectors(row3, form["department"], form["project"])
        form["balance"] = tk.Label(row3, text="", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")); form["balance"].pack(side="left", padx=10)
        alloc = tk.LabelFrame(page, text="Allocation - which invoices this " + ("receipt settles" if kind == "customer_receipt" else "payment settles"), bg=LIGHT, padx=6, pady=2)
        alloc.pack(fill="x", padx=8, pady=(0, 3))
        bar = tk.Frame(alloc, bg=LIGHT); bar.pack(fill="x")
        self.action_button(bar, "Auto Allocate (oldest first)", lambda: self.auto_allocate(form)).pack(side="left", padx=(0, 4))
        self.action_button(bar, "Clear Allocation", lambda: self.clear_allocation(form)).pack(side="left", padx=4)
        form["alloc_info"] = tk.Label(bar, text="Choose the customer / supplier to see the open invoices", bg=LIGHT, fg=MUTED,
                                      font=("Segoe UI",9,"bold")); form["alloc_info"].pack(side="left", padx=8)
        flow_toolbars(bar)
        from desktop_brains import EditableSheet
        form["alloc_sheet"] = EditableSheet(self, alloc, [("line", "#", 35, "center"), ("number", "Document", 140, "w"), ("date", "Date", 90, "center"), ("type", "Type", 90, "w"),
            ("currency", "Cur.", 50, "center"), ("total", "Total", 110, "e"), ("open", "Open", 110, "e"), ("allocate", "Allocate", 110, "e")], ["allocate"],
            lambda iid, key, text: self.allocation_changed(form, iid, text), height=6)
        # Keep primary actions beside the dimensions so the open-document allocation
        # table rises into view sooner below this compact payment header.
        buttons = tk.Frame(row3, bg=LIGHT); buttons.pack(side="left", padx=(8, 0))
        self.action_button(buttons, "New", lambda: self.new_payment(form)).pack(side="left", padx=(0, 3))
        tk.Button(buttons, text="Save", command=lambda: self.save_payment(form), bg=GOLD, fg=NAVY, border=0, padx=18, pady=7, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        tk.Button(buttons, text="Delete", command=lambda: self.delete_payment(form), bg=RED, fg="white", border=0, padx=12, pady=7).pack(side="left", padx=3)
        tk.Label(buttons, text="Double-click a line in the list to edit it.", bg=LIGHT, fg=MUTED).pack(side="left", padx=10)
        flow_toolbar(row3)
        find_bar = tk.Frame(page, bg=LIGHT); find_bar.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(find_bar, text="Find", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        form["find"] = tk.StringVar()
        find_entry = tk.Entry(find_bar, textvariable=form["find"], width=32); find_entry.pack(side="left", padx=(4, 6))
        find_entry.bind("<KeyRelease>", lambda _e: self.filter_payments(form))
        tk.Button(find_bar, text="Clear", command=lambda: (form["find"].set(""), self.filter_payments(form)), bg=LIGHT, border=0, fg=NAVY).pack(side="left")
        flow_toolbars(find_bar)
        form["tree"] = self.table(page, [("number", "Number", 125), ("date", "Date", 90), ("party", "Customer" if kind == "customer_receipt" else "Supplier", 210), ("currency", "Currency", 65),
            ("amount", "Amount", 110), ("method", "Method", 100), ("cash", "Cash / Bank", 220), ("reference", "Reference", 110), ("description", "Description", 200), ("dims", "Dep. / Project", 110)])
        form["tree"].bind("<Double-1>", lambda _e: self.edit_payment(form))
        return form

    def filter_payment_parties(self, form, event=None):
        typed = form["vars"]["party"].get().strip().casefold()
        kind = form["type"].get() if form.get("type") else "All"
        def cat(p): return (p.get("account_category") or ("client" if p.get("kind") == "customer" else "supplier"))
        result = [name for name, p in form.get("party_map", {}).items()
                  if (kind in ("All", "") or cat(p) == kind) and (not typed or typed in name.casefold())]
        form["party_box"]["values"] = result
        if typed and result and event is not None and getattr(event, "keysym", "") not in ("Up", "Down", "Return", "Escape", "Tab"):
            form["party_box"].after_idle(lambda: form["party_box"].event_generate("<Down>"))

    def payment_type_changed(self, form):
        form.pop("_chosen_party_id", None); form["vars"]["party"].set(""); self.filter_payment_parties(form)
        if "alloc_sheet" in form: form["alloc_sheet"].clear(); form["alloc_info"].config(text="Choose the customer / supplier to see the open invoices")
        form["balance"].config(text="")

    def load_open_documents(self, form, party, existing=None):
        sheet = form["alloc_sheet"]; sheet.clear(); existing = {a["invoice_id"]: a["amount"] for a in (existing or [])}
        try: documents = self.client.open_documents(party["id"])
        except Exception: documents = []
        known = {d["id"] for d in documents}
        for invoice_id, amount in existing.items():
            if invoice_id not in known:
                row = next((r for r in self.client.invoices() if r["id"] == invoice_id), None)
                if row: documents.append({"id": row["id"], "invoice_number": row["invoice_number"], "invoice_date": row["invoice_date"], "kind": row["kind"], "doc_subtype": row.get("doc_subtype"),
                                          "currency": row["currency"], "total": float(row["total"] or 0), "open_amount": 0.0})
        for d in documents:
            expected_kind = ("supplier_payment" if d.get("doc_subtype") == "credit_note" else "customer_receipt") if d["kind"] == "sale" else ("customer_receipt" if \
                d.get("doc_subtype") == "credit_note" else "supplier_payment")
            if expected_kind != form["kind"] and d["id"] not in existing: continue
            open_amount = float(d["open_amount"]) + float(existing.get(d["id"], 0))
            row = {"invoice_id": d["id"], "expected_kind": expected_kind, "number": d["invoice_number"], "date": _dd(d["invoice_date"]),
                    "type": {"credit_note": "Credit note", "debit_note": "Debit note"}.get(d.get("doc_subtype"),
                    "Sale" if d["kind"] == "sale" else "Purchase"),
                   "currency": d["currency"], "total": d["total"], "open": open_amount, "allocate": float(existing.get(d["id"], 0))}
            row["_display"] = {"total": f'{d["total"]:,.2f}', "open": f"{open_amount:,.2f}", "allocate": f'{row["allocate"]:,.2f}' if row["allocate"] else ""}
            sheet.insert(row)
        self.update_allocation_info(form)

    def allocation_changed(self, form, iid, text):
        row = form["alloc_sheet"].rows[iid]; value = _num(text, 0.0)
        if value is None or value < 0: messagebox.showwarning("Allocation", "Enter a positive amount"); return False
        if value > abs(row["open"]) + 0.005: messagebox.showwarning("Allocation", f"{row['number']} is open for {row['open']:,.2f} only"); return False
        row["allocate"] = value; row["_display"]["allocate"] = f"{value:,.2f}" if value else ""; self.update_allocation_info(form)

    def update_allocation_info(self, form):
        rows = form["alloc_sheet"].ordered(); allocated = sum(r["allocate"] for r in rows); amount = _num(form["vars"]["amount"].get()) or 0
        form["alloc_info"].config(text=f"{len(rows)} open document(s)   Allocated: {allocated:,.2f} of {amount:,.2f}   Unallocated (on account): {amount - allocated:,.2f}",
                                  fg="#8B1E1E" if allocated > amount + 0.005 else NAVY)

    def auto_allocate(self, form):
        remaining = _num(form["vars"]["amount"].get()) or 0
        if remaining <= 0: return messagebox.showwarning("Allocation", "Enter the amount first")
        for iid in form["alloc_sheet"].tree.get_children():
            row = form["alloc_sheet"].rows[iid]
            if row["currency"] != form["vars"]["currency"].get() or row["expected_kind"] != form["kind"] or abs(row["open"]) < 0.01: row["allocate"] = 0
            else: row["allocate"] = round(min(remaining, abs(row["open"])), 2); remaining -= row["allocate"]
            row["_display"]["allocate"] = f'{row["allocate"]:,.2f}' if row["allocate"] else ""; form["alloc_sheet"].refresh(iid)
        self.update_allocation_info(form)

    def clear_allocation(self, form):
        for iid, row in form["alloc_sheet"].rows.items(): row["allocate"] = 0; row["_display"]["allocate"] = ""; form["alloc_sheet"].refresh(iid)
        self.update_allocation_info(form)

    def resolve_payment_party(self, form, refresh=True):
        """2.9.48: find the customer / supplier from what is in the box - the full list text, the name alone,
        the account number, or a part of the name that matches one party only. A party created after the
        screen was opened is found too (the list is reloaded once)."""
        text = str(form["vars"]["party"].get() or "").strip()
        if not text: return None
        for attempt in (0, 1):
            party_map = form.get("party_map", {})
            if text in party_map: return party_map[text]
            folded = text.casefold(); name_part = text.split(" | ", 1)[0].strip().casefold()
            exact = [(k, p) for k, p in party_map.items() if p["name"].strip().casefold() in (folded, name_part)
                     or str(p.get("account_number") or "").casefold() == folded]
            if not exact:
                exact = [(k, p) for k, p in party_map.items() if folded in k.casefold()]
            if len(exact) == 1:
                form["vars"]["party"].set(exact[0][0]); return exact[0][1]
            if len(exact) > 1:
                raise ValueError("More than one customer / supplier matches '" + text + "':\n" + "\n".join(k for k, _p in exact[:8]) + "\n\nChoose one from the list.")
            if attempt or not refresh: break
            try:
                parties = self.client.parties()
                form["party_map"] = {f'{p["name"]} | {p.get("account_number") or ""}': p for p in parties}
                form["party_box"]["values"] = list(form["party_map"])
            except Exception: break
        return None

    def payment_party_chosen(self, form):
        try: party = self.resolve_payment_party(form)
        except ValueError: party = None
        if not party: return
        if form.get("_chosen_party_id") == party["id"] and form.get("_chosen_party_text") == form["vars"]["party"].get(): return  # same party: keep the allocations typed
        form["_chosen_party_id"] = party["id"]; form["_chosen_party_text"] = form["vars"]["party"].get()
        self.load_open_documents(form, party)
        if party.get("currency"): form["vars"]["currency"].set(party["currency"])
        account = party.get("account_number")
        if not account: form["balance"].config(text=""); return
        try:
            report = self.client.account_report({"account_from": account, "account_to": account, "first_column": "account", "second_column": "none", "carry_forward": False, "posting_status": "all"})
            balances = []
            for section in report["sections"]:
                grand = section["rows"][-1] if section["rows"] else None
                if grand and grand[0] == "GRAND TOTAL" and abs(float(grand[-1] or 0)) > 0.004:
                    balances.append(f'{section["heading"].rsplit(" - ", 1)[-1]} {float(grand[-1]):,.2f}')
            form["balance"].config(text=f"Account {account}   Balance: " + ("   ".join(balances) if balances else "0.00") + "   (+ owes you / - you owe)")
        except Exception: form["balance"].config(text=f"Account {account}")

    def reset_payment_accounts(self, form):
        """2.9.79: the default accounts of the bank commission and the exchange gain / loss."""
        from desktop_common import default_account_code  # 2.9.81: Settings > Accounting Settings
        v = form["vars"]
        for key, code in (("commission_account", default_account_code(self, "bank_commission")), ("exchange_gain_account", default_account_code(self, "exchange_gain")),
                          ("exchange_loss_account", default_account_code(self, "exchange_loss"))):
            v[key].set(account_label(self, code))

    def payment_journal_preview(self, form):
        """The journal entry the receipt / payment will post: [(account, debit, credit)] (same rule as the books)."""
        v = form["vars"]
        amount = _num(v["amount"].get(), 0.0) or 0.0; commission = _num(v["bank_commission"].get(), 0.0) or 0.0; difference = _num(v["exchange_difference"].get(), 0.0) or 0.0
        if amount <= 0: return []
        try: party = self.resolve_payment_party(form, refresh=False)
        except ValueError: party = None
        party_account = (party or {}).get("account_number") or ("4111" if form["kind"] == "customer_receipt" else "4011")
        cash = account_code(v["cash_account"].get()) or "531"; settled = amount + difference
        if form["kind"] == "customer_receipt": lines = [(cash, amount - commission, 0.0), (party_account, 0.0, settled)]
        else: lines = [(party_account, settled, 0.0), (cash, 0.0, amount + commission)]
        if commission: lines.append((account_code(v["commission_account"].get()), commission, 0.0))
        balance = round(sum(d for _c, d, _cr in lines) - sum(c for _c, _d, c in lines), 2)
        if balance > 0: lines.append((account_code(v["exchange_gain_account"].get()), 0.0, balance))
        elif balance < 0: lines.append((account_code(v["exchange_loss_account"].get()), -balance, 0.0))
        return [(code, debit, credit) for code, debit, credit in lines if round(debit, 2) or round(credit, 2)]

    def update_payment_preview(self, form):
        label = form.get("preview")
        if label is None or not label.winfo_exists(): return
        try: lines = self.payment_journal_preview(form)
        except Exception: lines = []
        if not lines: label.config(text=""); return
        text = [f'{"Journal entry:":<63}{"Debit":>14}{"Credit":>14}'] + [f'  {"Dr" if debit else "   Cr"}  {account_label(self, code)[:57]:<{57 if debit else 54}}'
                                                                         f'{(f"{debit:,.2f}" if debit else ""):>14}{(f"{credit:,.2f}" if credit else ""):>14}' for code, debit, credit in lines]
        label.config(text="\n".join(text))

    def new_payment(self, form):
        form["id"] = None; v = form["vars"]; form.pop("_chosen_party_id", None)
        if "not_deductible" in form: form["not_deductible"].set(False)
        for key in ("party", "amount", "reference", "description", "bank_commission", "exchange_difference"): v[key].set("")
        self.reset_payment_accounts(form)
        if "alloc_sheet" in form: form["alloc_sheet"].clear(); form["alloc_info"].config(text="Choose the customer / supplier to see the open invoices")
        v["date"].set(self.fiscal_today()); v["method"].set("Cash"); form["department"].set("(none)"); form["project"].set("(none)"); form["balance"].config(text="")
        try: v["number"].set(self.client.next_document_number(form["kind"], v["date"].get()))
        except Exception: v["number"].set("")

    def payment_payload(self, form):
        v = form["vars"]; party = self.resolve_payment_party(form)
        if not party: raise ValueError(f"Customer / supplier '{v['party'].get().strip()}' was not found. Choose it from the list (type a part of the name, then pick it).")
        amount = _num(v["amount"].get(), None)
        if not amount or amount <= 0: raise ValueError("Enter an amount above zero")
        datetime.strptime(v["date"].get().strip(), "%d-%m-%Y")
        return {"kind": form["kind"], "party_id": party["id"], "payment_date": v["date"].get().strip(), "currency": v["currency"].get(), "amount": amount,
                "cash_account": v["cash_account"].get().split(" - ", 1)[0].strip() or "531", "reference": v["reference"].get().strip(), "description": v["description"].get().strip(),
                "payment_method": v["method"].get(), "department": self.dimension_code(form["department"].get()), "project": self.dimension_code(form["project"].get()),
                "bank_commission": _num(v["bank_commission"].get(), 0.0) or 0.0, "exchange_difference": _num(v["exchange_difference"].get(), 0.0) or 0.0,
                "commission_account": account_code(v["commission_account"].get()), "exchange_gain_account": account_code(v["exchange_gain_account"].get()),
                "exchange_loss_account": account_code(v["exchange_loss_account"].get())}

    def save_payment(self, form):
        try: payload = self.payment_payload(form)
        except ValueError as exc: return messagebox.showwarning("Payment & Receipt", str(exc) if "time data" not in str(exc) else "Date must be DD-MM-YYYY")
        incompatible = next((r for r in form["alloc_sheet"].ordered() if r["allocate"] and r["expected_kind"] != form["kind"]), None)
        if incompatible:
            direction = "outgoing payment/refund" if incompatible["expected_kind"] == "supplier_payment" else "incoming receipt/refund"
            return messagebox.showwarning("Payment & Receipt", f"{incompatible['number']} requires an {direction}. A credit-note offset needs a separate journal adjustment.")
        allocations = [{"invoice_id": r["invoice_id"], "amount": r["allocate"]} for r in form["alloc_sheet"].ordered() if r["allocate"]]
        if sum(a["amount"] for a in allocations) > payload["amount"] + 0.005: return messagebox.showwarning("Payment & Receipt", "The allocation is more than the amount")
        if form["kind"] == "supplier_payment" and not form["id"] and not self.confirm_cash_enough(payload["cash_account"], payload["currency"], payload["payment_date"],
                payload["amount"] + (payload.get("bank_commission") or 0), "Payment & Receipt"): return
        try:
            payment_id = self.client.update_payment(form["id"], payload) if form["id"] else self.client.add_payment(payload)["payment_id"]
            if allocations: self.client.save_allocations(payment_id, allocations)
        except Exception as exc: return messagebox.showerror("Payment & Receipt", str(exc))
        if "not_deductible" in form: save_tax_flag(self.client, "payment", payment_id, form["not_deductible"])
        number = form["vars"]["number"].get()
        messagebox.showinfo("Payment & Receipt", f"{'Receipt' if form['kind'] == 'customer_receipt' else 'Payment'} {number} saved")
        self.load_transactions(); self.new_payment(form); self.load_journal(); self.load_trial()

    def edit_payment(self, form):
        selected = form["tree"].selection()
        if not selected: return
        row = form.get("rows", {}).get(selected[0])
        if not row: return
        form["id"] = row["id"]; v = form["vars"]
        if "not_deductible" in form: load_tax_flag(self.client, "payment", row["id"], form["not_deductible"])
        label = next((name for name, p in form.get("party_map", {}).items() if p["id"] == row["party_id"]), row["party_name"])
        for key, value in (("number", row.get("payment_number") or ""), ("date", _dd(row["payment_date"])), ("party", label), ("currency", row["currency"]), ("amount", f'{row["amount"]:g}'),
                           ("method", row.get("payment_method") or "Cash"), ("cash_account", account_label(self, row["cash_account"])), ("reference",
                                   row.get("reference") or ""), ("description", row.get("description") or ""),
                           ("bank_commission", f'{row.get("bank_commission") or 0:g}' if (row.get("bank_commission") or 0) else ""), ("exchange_difference",
                                   f'{row.get("exchange_difference") or 0:g}' if (row.get("exchange_difference") or 0) else "")):
            v[key].set(value)
        self.reset_payment_accounts(form)
        for key in ("commission_account", "exchange_gain_account", "exchange_loss_account"):
            if row.get(key): v[key].set(account_label(self, row[key]))
        lists = self.dimension_lists()
        form["department"].set(next((f'{d["code"]} - {d["name"]}' for d in lists["departments"] if d["code"] == row.get("department")), "(none)"))
        form["project"].set(next((f'{p["code"]} - {p["name"]}' for p in lists["projects"] if p["code"] == row.get("project")), "(none)"))
        form["balance"].config(text=f"Editing {row.get('payment_number') or ''}")
        party = next((p for p in form.get("party_map", {}).values() if p["id"] == row["party_id"]), None)
        if party:
            try: existing = self.client.payment_allocations(row["id"])
            except Exception: existing = []
            self.load_open_documents(form, party, existing)
            form["_chosen_party_id"] = party["id"]; form["_chosen_party_text"] = form["vars"]["party"].get()

    def delete_payment(self, form):
        selected = form["tree"].selection()
        if len(selected) > 1:  # 2.9.69: several selected
            items = [(form["rows"][iid]["id"], form["rows"][iid].get("payment_number") or iid) for iid in selected if iid in form.get("rows", {})]
            if not messagebox.askyesno("Payment & Receipt", f"Void {len(items)} payments / receipts? Posted ones stay in the journal, marked Void."): return
            reason = self._void_reason()
            if reason is None: return
            bulk_action("Payment & Receipt", items, lambda payment_id: self.client.delete_payment(payment_id, reason))
            self.load_transactions(); self.new_payment(form); self.load_journal(); self.load_trial(); return
        if not form["id"]: return messagebox.showwarning("Payment & Receipt", "Double-click a saved line to open it first")
        if not messagebox.askyesno("Payment & Receipt", f"Void {form['vars']['number'].get()}? A posted one stays in the journal, marked Void "
                                   "(administrator only). To correct it, edit it instead: it is reversed and a new number is posted."): return
        reason = self._void_reason()
        if reason is None: return
        try: self.client.delete_payment(form["id"], reason)
        except Exception as exc: return messagebox.showerror("Payment & Receipt", str(exc))
        self.load_transactions(); self.new_payment(form); self.load_journal(); self.load_trial()

    def _void_reason(self):
        """2.9.136 (F1): the reason kept in the audit log when a posted receipt / payment is voided."""
        from tkinter import simpledialog
        reason = simpledialog.askstring("Payment & Receipt", "Reason for voiding (kept in the audit log):", parent=self)
        if reason is None: return None
        if not reason.strip():
            messagebox.showwarning("Payment & Receipt", "Enter a reason"); return None
        return reason.strip()

    def load_transactions(self):
        if hasattr(self, "payment_forms") and all(f["tree"].winfo_exists() for f in self.payment_forms.values()):
            try: payments = self.client.payments(); parties = self.client.parties()
            except Exception as exc: return messagebox.showerror("Payment & Receipt", str(exc))
            for kind, form in self.payment_forms.items():
                # clients and suppliers are both available in receipts and payments (refunds, advances, settlements)
                form["party_map"] = {f'{p["name"]} | {p.get("account_number") or ""}': p for p in parties}
                if not getattr(self, "_cash_accounts", None):
                    try: self._cash_accounts = [f'{a["code"]} - {a["name_en"]}' for a in self.client.accounts() if str(a["code"]).startswith(("511", "512", "519", "53"))]
                    except Exception: self._cash_accounts = ["531 - Cash"]
                form["cash_box"]["values"] = self._cash_accounts
                if not form["vars"]["cash_account"].get() or form["vars"]["cash_account"].get() == "531":
                    form["vars"]["cash_account"].set(next((a for a in self._cash_accounts if a.startswith("531")), self._cash_accounts[0] if self._cash_accounts else "531"))
                form["party_box"]["values"] = list(form["party_map"])
                rows = [r for r in payments if r["kind"] == kind]; form["rows"] = {str(r["id"]): r for r in rows}
                self.filter_payments(form)
                if not form["id"] and not form["vars"]["number"].get(): self.new_payment(form)
        if hasattr(self, "purchase_form"): self.load_purchases()
        if hasattr(self, "expense_form"): self.load_expenses()

    def _payment_tree_values(self, r):
        return (r.get("payment_number") or f"#{r['id']}", _dd(r["payment_date"]), r["party_name"], r["currency"], f'{r["amount"]:,.2f}',
                r.get("payment_method") or "", account_label(self, r["cash_account"]), r.get("reference") or "", r.get("description") or "",
                        " / ".join(x for x in (r.get("department"), r.get("project")) if x))

    def filter_payments(self, form):
        from desktop import row_matches_search
        needle = (form["find"].get() if form.get("find") else "").strip()
        form["tree"].delete(*form["tree"].get_children())
        for r in form.get("rows", {}).values():
            values = self._payment_tree_values(r)
            if not row_matches_search(values, needle): continue
            form["tree"].insert("", "end", iid=str(r["id"]), values=values)
