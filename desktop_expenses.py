"""Expenses page (moved out of desktop_stage3.py in 2.9.42, unchanged)."""
from __future__ import annotations

from desktop_stage3_common import (  # 2.9.102: the names this module uses (no more 'import *')
    bulk_action, filedialog, GOLD, LIGHT, messagebox, mimetypes, MUTED, NAVY, Path, prepare_pdf_reading, PURCHASE_USES,
    read_invoice_pdf, RED, tk, ttk
)
from desktop_common import vat_rate, vat_rate_text, vat_currency  # 2.9.72
from desktop_common import main_currency  # 2.9.71
from datetime import datetime
from desktop_stage3_common import _dd, _num


class ExpensesMixin:
    # ---- expenses
    def build_expenses_page(self, page):
        f = {"id": None, "pdf": None, "vars": {k: tk.StringVar() for k in ("date", "description", "category", "currency", "with_vat", "without_vat", "vat", "account", "no_vat_account",
                                                                          "vat_account", "payment_account", "reference")}}
        v = f["vars"]; v["date"].set(self.fiscal_today()); v["currency"].set(main_currency(self, 1)); v["category"].set("General")
        # 2.9.80: no automatic expense account (it was 601100000 Purchase of Goods, which put rent, fuel ... in purchases):
        # the account is chosen (F2), then kept for the next expense
        from desktop_common import default_account_code  # 2.9.81
        v["vat_account"].set(default_account_code(self, "expense_vat")); v["payment_account"].set(default_account_code(self, "cash"))
        f["department"] = tk.StringVar(); f["project"] = tk.StringVar(); f["non_deductible"] = tk.BooleanVar(value=False); f["vat_typed"] = False; self.expense_form = f
        f["tax_non_deductible"] = tk.BooleanVar(value=False)  # 2.9.110: no official invoice -> added back to the taxable profit
        f["use"] = tk.StringVar(value="Mixed (partial deduction)")
        box = tk.LabelFrame(page, text="Expense", bg=LIGHT, padx=8, pady=5); box.pack(fill="x", padx=8, pady=6)
        r1 = tk.Frame(box, bg=LIGHT); r1.pack(fill="x")
        f["number_label"] = tk.Label(r1, text="New expense", bg=LIGHT, fg=NAVY, font=("Segoe UI", 9, "bold")); f["number_label"].pack(side="left", padx=(0, 10))
        tk.Label(r1, text="Date", bg=LIGHT).pack(side="left"); self.date_entry(r1, v["date"], 11).pack(side="left", padx=(4, 8))
        tk.Label(r1, text="Description", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left"); tk.Entry(r1, textvariable=v["description"], width=32).pack(side="left", padx=(4, 8))
        tk.Label(r1, text="Category", bg=LIGHT).pack(side="left"); tk.Entry(r1, textvariable=v["category"], width=13).pack(side="left", padx=(4, 8))
        ttk.Combobox(r1, textvariable=v["currency"], values=self.currency_codes, state="readonly", width=5).pack(side="left", padx=4)
        tk.Label(r1, text="Reference", bg=LIGHT).pack(side="left"); tk.Entry(r1, textvariable=v["reference"], width=13).pack(side="left", padx=4)
        r2 = tk.Frame(box, bg=LIGHT); r2.pack(fill="x", pady=(5, 0))
        for label, key, width in (("With VAT (before VAT)", "with_vat", 12), ("Without VAT", "without_vat", 11), ("VAT", "vat", 10)):
            tk.Label(r2, text=label, bg=LIGHT).pack(side="left"); entry = tk.Entry(r2, textvariable=v[key], width=width); entry.pack(side="left", padx=(4, 8))
            entry.bind("<KeyRelease>", lambda e, k=key: self.expense_amounts_changed(k))
        f["total"] = tk.Label(r2, text="Total: 0.00", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold")); f["total"].pack(side="left", padx=6)
        tk.Checkbutton(r2, text="VAT not deductible", variable=f["non_deductible"], bg=LIGHT).pack(side="left", padx=8)
        from desktop_tax_flag import tax_tick, place as place_tick  # 2.9.113: Settings can hide it
        place_tick(tax_tick(r2, f["tax_non_deductible"], LIGHT), side="left", padx=8)
        r3 = tk.Frame(box, bg=LIGHT); r3.pack(fill="x", pady=(5, 0))
        for label, key in (("Expense A/C (626-69)", "account"), ("No-VAT A/C", "no_vat_account"), ("VAT A/C", "vat_account"), ("Paid from", "payment_account")):
            tk.Label(r3, text=label, bg=LIGHT).pack(side="left")
            if key in ("account", "no_vat_account", "payment_account"):
                box_widget = ttk.Combobox(r3, textvariable=v[key], width=24 if key == "account" else 14); box_widget.pack(side="left", padx=(4, 8)); f[f"{key}_box"] = box_widget
            else: self.account_search_box(r3, v[key], 9).pack(side="left", padx=(4, 8))
        tk.Button(r3, text="Suggest A/C", command=self.suggest_expense_account,
                  bg=GOLD, fg=NAVY, border=0).pack(side="left", padx=4)
        tk.Button(r3, text="AI Suggest A/C", command=self.ai_suggest_expense_account,
                  bg=NAVY, fg="white", border=0).pack(side="left", padx=4)
        r4 = tk.Frame(box, bg=LIGHT); r4.pack(fill="x", pady=(5, 0))
        self.dimension_selectors(r4, f["department"], f["project"])
        tk.Label(r4, text="VAT used for", bg=LIGHT).pack(side="left"); ttk.Combobox(r4, textvariable=f["use"], values=list(PURCHASE_USES), state="readonly", width=24).pack(side="left", padx=4)
        f["pdf_label"] = tk.Label(r4, text="No PDF", bg=LIGHT, fg=MUTED); f["pdf_label"].pack(side="left", padx=6)
        r5 = tk.Frame(box, bg=LIGHT); r5.pack(fill="x", pady=(5, 0))
        self.action_button(r5, "New", self.new_expense).pack(side="left", padx=(0, 3))
        tk.Button(r5, text="Save Expense", command=self.save_expense, bg=GOLD, fg=NAVY, border=0, padx=18, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        tk.Button(r5, text="Delete", command=self.delete_expense, bg=RED, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=3)
        self.action_button(r5, "Upload PDF", self.choose_expense_pdf).pack(side="left", padx=3)
        self.action_button(r5, "Attachments", self.expense_attachments_window).pack(side="left", padx=3)
        self.action_button(r5, "Import Expenses Excel", self.import_expenses_excel).pack(side="left", padx=3)
        self.action_button(r5, "Non-deductible Expenses Report", self.non_deductible_report).pack(side="left", padx=3)  # 2.9.110
        f["tree"] = ttk.Treeview(page, columns=[f"c{i}" for i in range(12)])  # kept hidden: the Find box replaces the list
        find = tk.Frame(page, bg=LIGHT); find.pack(fill="x", padx=8, pady=(0, 4), before=box); f["find"] = tk.StringVar()
        tk.Label(find, text="Find expense (No., description, date)", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
        f["find_box"] = ttk.Combobox(find, textvariable=f["find"], width=50); f["find_box"].pack(side="left", padx=6)
        f["find_box"].bind("<<ComboboxSelected>>", lambda _e: self.expense_found())
        f["find_box"].bind("<KeyRelease>", lambda _e: self.filter_found_expenses())
        f["find_box"].bind("<Return>", lambda _e: self.expense_found())

    def expense_amounts_changed(self, key):
        f = self.expense_form; v = f["vars"]
        if key == "vat": f["vat_typed"] = True
        if key == "with_vat" and not f.get("pdf_vat_review"): f["vat_typed"] = False
        base = _num(v["with_vat"].get()) or 0
        if not f["vat_typed"] and not f.get("pdf_vat_review"): v["vat"].set(f"{base * vat_rate(self) / 100:.2f}" if base else "")
        total = base + (_num(v["without_vat"].get()) or 0) + (_num(v["vat"].get()) or 0)
        f["total"].config(text=f"Total: {total:,.2f} {v['currency'].get()}")

    def new_expense(self):
        f = self.expense_form; v = f["vars"]; f["id"] = None; f["pdf"] = None; f["vat_typed"] = False; f["pdf_vat_review"] = False; f["pdf_suggested_type"] = ""
        for key in ("description", "with_vat", "without_vat", "vat", "reference"): v[key].set("")
        v["date"].set(self.fiscal_today()); f["non_deductible"].set(False); f["tax_non_deductible"].set(False); f["department"].set("(none)"); f["project"].set("(none)")
        f["pdf_label"].config(text="No PDF", fg=MUTED); f["total"].config(text="Total: 0.00"); f["number_label"].config(text="New expense")

    def choose_expense_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf"), ("Images", "*.png *.jpg *.jpeg")])
        if not path: return
        f = self.expense_form; v = f["vars"]; f["pdf"] = path; f["pdf_suggested_type"] = ""
        if path.lower().endswith(".pdf") and not f["id"]:
            prepare_pdf_reading(self); data = read_invoice_pdf(path)  # 2.9.85: the buyer is never the supplier
            f["pdf_suggested_type"] = data.get("suggested_type") or ""
            f["pdf_vat_review"] = True
            f["vat_typed"] = True
            v["vat"].set(f'{data["vat"]:.2f}' if data.get("vat") is not None else "")
            if data.get("invoice_number") and not v["reference"].get(): v["reference"].set(data["invoice_number"])
            if data.get("invoice_date"): v["date"].set(data["invoice_date"])
            elif v["date"].get() == self.fiscal_today(): v["date"].set("")
            if data.get("currency"): v["currency"].set(data["currency"])
            supplier = data.get("supplier_hint") or data.get("party_name") or ""  # 2.9.97: the issuer (Pegasus), not the buyer named on it
            if not v["description"].get():
                v["description"].set(" - ".join(part for part in (data.get("expense_category"), supplier) if part) or data.get("party_name") or "")
            amounts = ExpensesMixin.expense_amounts_from_pdf(data)
            for key in ("with_vat", "without_vat"):
                if amounts[key] is not None and not v[key].get(): v[key].set(f"{amounts[key]:.2f}")
            if amounts["vat"] is not None: v["vat"].set(f"{amounts['vat']:.2f}")
            account = ExpensesMixin.expense_account_from_pdf(self, data)  # 2.9.97: travel -> 626420000, electricity -> 626340000 (opened if missing)
            if account:
                from desktop_common import account_label
                if not v["account"].get().strip(): v["account"].set(account_label(self, account))
                if amounts["without_vat"] and not v["no_vat_account"].get().strip(): v["no_vat_account"].set(account_label(self, account))
            self.expense_amounts_changed("none")
            suggestion=f["pdf_suggested_type"]
            f["pdf_label"].config(text=f"{Path(path).name}: {data.get('notes', '')}" +
                                  (f"; Suggested Type: {suggestion} (review before Save)" if suggestion else
                                   "; Type unclear; confirm this is a paid Expense before Save"), fg=NAVY)
        else: f["pdf_label"].config(text=Path(path).name, fg=NAVY)

    @staticmethod
    def expense_amounts_from_pdf(data):
        """2.9.97: {with_vat, without_vat, vat} from what the PDF reading found.
        No VAT on the document (air tickets, commissions): the whole total is 'without VAT' and the VAT is 0.
        A utility bill: the base with VAT, and the stamp / rounding without VAT."""
        total, vat, subtotal = data.get("total"), data.get("vat"), data.get("subtotal")
        if data.get("taxable_subtotal") is not None and data.get("exempt_subtotal") is not None and vat is not None:
            return {"with_vat": data["taxable_subtotal"], "without_vat": data["exempt_subtotal"], "vat": vat}
        if vat is None and total is not None:
            return {"with_vat": None, "without_vat": round(total, 2), "vat": 0.0}
        if subtotal is None and total is not None and vat is not None: subtotal = round(total - vat, 2)
        return {"with_vat": subtotal, "without_vat": None, "vat": vat}

    def expense_account_from_pdf(self, data):
        """The 9-digit account of the expense category, opened under its chart account when it does not exist yet."""
        nine, parent, name = data.get("suggested_account_9"), data.get("suggested_account"), data.get("suggested_account_name")
        if not nine: return parent or ""
        try:
            known = {str(a.get("code")) for a in self.client.accounts()}
            if nine not in known:
                self.client.save_account({"code": nine, "name_en": name or f"Expense {nine}", "type": "expense", "parent_code": parent if parent in known else ""})
            return nine
        except Exception:
            return parent or ""

    def expense_payload(self):
        v = self.expense_form["vars"]; f = self.expense_form
        if f.get("pdf_vat_review") and not v["vat"].get().strip():
            raise ValueError("Confirm VAT from the PDF before saving; type 0 if there is no VAT")
        if not v["description"].get().strip(): raise ValueError("Enter the expense description")
        amounts = {k: _num(v[k].get()) for k in ("with_vat", "without_vat", "vat")}
        if None in amounts.values() or min(amounts.values()) < 0: raise ValueError("Amounts must be positive numbers")
        if not amounts["with_vat"] and not amounts["without_vat"]: raise ValueError("Enter the expense amount")
        for key, amount_key, label in (("account", "with_vat", "Expense A/C"), ("no_vat_account", "without_vat", "No-VAT A/C")):
            if amounts[amount_key] and not v[key].get().split(" - ", 1)[0].strip():
                raise ValueError(f"Choose the {label}: the class 6 account of this expense (F2 to search), for example 6263.1 rent")
        return {"expense_date": v["date"].get().strip(), "description": v["description"].get().strip(), "category": v["category"].get().strip(), "currency": v["currency"].get(),
                "with_vat_subtotal": amounts["with_vat"], "without_vat_subtotal": amounts["without_vat"], "vat": amounts["vat"], "reference": v["reference"].get().strip(),
                "expense_account": v["account"].get().split(" - ", 1)[0].strip(), "expense_without_vat_account": v["no_vat_account"].get().split(" - ", 1)[0].strip(),
                "vat_account": v["vat_account"].get().split(" - ", 1)[0].strip(), "payment_account": v["payment_account"].get().split(" - ", 1)[0].strip(),
                "vat_recoverable": not f["non_deductible"].get(), "department": self.dimension_code(f["department"].get()), "project": self.dimension_code(f["project"].get()),
                "vat_use": PURCHASE_USES.get(f["use"].get(), "mixed"), "tax_deductible": not f["tax_non_deductible"].get()}

    def non_deductible_report(self):
        """2.9.110: the expenses of the year marked not deductible for income tax - the amount to add back to the taxable profit."""
        year = str(getattr(self, "current_fiscal_year", "") or datetime.now().year)
        try: rows = self.client.non_deductible_expenses(year)
        except Exception as exc: return messagebox.showerror("Non-deductible Expenses", str(exc))
        lines = [[r.get("expense_number") or "", _dd(r["expense_date"]), r["description"], r.get("category") or "", r["expense_account"], r["currency"],
                  r["subtotal"], r.get("reference") or ""] for r in rows]
        totals = {}
        for r in rows: totals[r["currency"]] = totals.get(r["currency"], 0) + float(r["subtotal"] or 0)
        for currency, amount in sorted(totals.items()): lines.append(["TOTAL | المجموع", "", "To add back to the taxable profit", "", "", currency, amount, ""])
        sections = [{"heading": f"Expenses not deductible for income tax - {year} | أعباء غير مقبولة ضريبياً",
                     "headers": ["No.", "Date", "Description", "Category", "Account", "Currency", "Amount (before VAT)", "Reference"],
                     "rows": lines or [["No expense marked not deductible in this year", "", "", "", "", "", "", ""]],
                     "total_rows": list(range(len(rows), len(lines)))}]
        try: exempt = self.client.exempt_income(year)  # 2.9.113: income not subject to income tax, deducted with its legal reason
        except (RuntimeError, OSError, ValueError): exempt = []
        if exempt:
            rows2 = [[r["entry_number"], _dd(r["date"]), r["description"], r["reason"], r["account"], r["currency"], r["amount"], ""] for r in exempt]
            sums = {}
            for r in exempt: sums[r["currency"]] = sums.get(r["currency"], 0) + float(r["amount"] or 0)
            for currency, amount in sorted(sums.items()): rows2.append(["TOTAL | المجموع", "", "To deduct from the taxable profit", "", "", currency, amount, ""])
            sections.append({"heading": f"Income not subject to income tax - {year} | إيرادات غير خاضعة لضريبة الدخل",
                             "headers": ["No.", "Date", "Description", "Legal reason", "Account", "Currency", "Amount", ""],
                             "rows": rows2, "total_rows": list(range(len(exempt), len(rows2)))})
        meta = [f"Fiscal year {year}", "These expenses stay in the books (profit and loss); they are added back to the accounting profit in the income tax computation."]
        self.output_sections("Non-deductible Expenses", meta, sections, f"Non_deductible_expenses_{year}", "preview")

    def save_expense(self):
        f = self.expense_form
        try: payload = self.expense_payload()
        except ValueError as exc: return messagebox.showwarning("Expenses", str(exc))
        suggestion=f.get("pdf_suggested_type")
        if suggestion and suggestion != "Expenses":
            if not messagebox.askyesno("Review PDF type",
                    f"This PDF suggests {suggestion}, but this form records a PAID Expense.\n"
                    "Confirm it was paid and is not a supplier invoice or a capital asset.\n\nSave as a paid Expense anyway?"):
                return
        if not f["id"] and not self.confirm_cash_enough(payload["payment_account"], payload["currency"], payload["expense_date"],
                (payload["with_vat_subtotal"] or 0) + (payload["without_vat_subtotal"] or 0) + (payload["vat"] or 0), "Expenses"): return
        try:
            expense_id = self.client.update_expense(f["id"], payload) if f["id"] else self.client.add_expense(payload)["expense_id"]
            if f["pdf"]: self.client.upload_expense_attachment(expense_id, Path(f["pdf"]).name, mimetypes.guess_type(f["pdf"])[0] or "application/pdf", Path(f["pdf"]).read_bytes())
        except Exception as exc: return messagebox.showerror("Expenses", str(exc))
        messagebox.showinfo("Expenses", "Expense saved" + (" with its PDF" if f["pdf"] else ""))
        self.new_expense(); self.load_expenses(); self.load_journal(); self.load_trial(); self.load_profit_loss()

    def load_expenses(self):
        f = getattr(self, "expense_form", None)
        if not f or not f["tree"].winfo_exists(): return
        try: rows = self.client.expenses()
        except Exception: rows = []
        lists = self.dimension_lists(); departments = {d["id"]: d["code"] for d in lists["departments"]}; projects = {p["id"]: p["code"] for p in lists["projects"]}
        f["rows"] = {str(r["id"]): r for r in rows}; f["tree"].delete(*f["tree"].get_children())
        f["find_map"] = {f'{r.get("expense_number") or r["id"]} | {_dd(r["expense_date"])} | {r["description"]} | {r["total"]:,.2f} {r["currency"]}': r["id"] for r in rows}; f["find_box"]["values"] = list(f["find_map"])
        if not getattr(self, "_expense_accounts", None):
            try:
                accounts = self.client.accounts()
                def in_range(code): code = str(code); return code[:3] in ("626", "627", "628", "629") or code[:2] in ("63", "64", "65", "66", "67", "68", "69")
                self._expense_accounts = [f'{a["code"]} - {a["name_en"]}' for a in accounts if in_range(a["code"]) and str(a["code"]).isdigit()]
                self._cash_accounts = self._cash_accounts if getattr(self, "_cash_accounts",
                        None) else [f'{a["code"]} - {a["name_en"]}' for a in accounts if str(a["code"]).startswith(("511", "512", "519", "53"))]
            except Exception: self._expense_accounts = []
        f["account_box"]["values"] = self._expense_accounts; f["no_vat_account_box"]["values"] = self._expense_accounts; f["payment_account_box"]["values"] = getattr(self, "_cash_accounts", [])
        for r in rows:
            f["tree"].insert("", "end", iid=str(r["id"]), values=(r.get("expense_number") or f"EXP-{r['id']}", _dd(r["expense_date"]), r["description"], r.get("category") or "", r["currency"],
                f'{r.get("with_vat_subtotal") or 0:,.2f}', f'{r.get("without_vat_subtotal") or 0:,.2f}', f'{r["vat"]:,.2f}', f'{r["total"]:,.2f}',
                "Yes" if r.get("vat_recoverable", 1) else "NO", r.get("attachment_count") or "", " / ".join(x for x in (departments.get(r.get("department_id")),
                        projects.get(r.get("project_id"))) if x)))

    def suggest_expense_account(self):
        from ai_mapper import suggest_account
        form = self.expense_form["vars"]
        suggestion = suggest_account(form["description"].get(), getattr(self, "_expense_accounts", []))
        if not suggestion:
            messagebox.showinfo("Account suggestion", "Enter a more specific expense description and choose an account manually.")
            return
        if messagebox.askyesno("Account suggestion",
                               f"Use {suggestion['code']} - {suggestion['name']}?\nPlease verify the account before saving."):
            form["account"].set(suggestion["code"])

    def ai_suggest_expense_account(self):
        from ai_service import suggest_account
        form=self.expense_form["vars"]
        description=form["description"].get().strip()
        accounts=list(getattr(self,"_expense_accounts",[]))
        def show(suggestion):
            if messagebox.askyesno("AI account suggestion",f"{suggestion['code']} - {suggestion['name']}\n{suggestion['reason']}\n\nUse this account?"):
                form["account"].set(suggestion["code"])
        self.run_ai_task(lambda key:suggest_account(description,accounts,key),show)

    def filter_found_expenses(self):
        from desktop import row_matches_search
        f=self.expense_form
        f["find_box"]["values"]=[label for label in f.get("find_map",{}) if row_matches_search((label,),f["find"].get())]

    def expense_found(self):
        f = self.expense_form; expense_id = f.get("find_map", {}).get(f["find"].get())
        if not expense_id:
            matches=list(f["find_box"]["values"])
            if len(matches)==1: f["find"].set(matches[0]); expense_id=f.get("find_map",{}).get(matches[0])
        if expense_id: f["tree"].selection_set(str(expense_id)); self.edit_expense()

    def edit_expense(self):
        f = self.expense_form; selected = f["tree"].selection()
        if not selected: return
        r = f["rows"][selected[0]]; v = f["vars"]; f["id"] = r["id"]; f["pdf"] = None; f["vat_typed"] = True
        for key, value in (("date", _dd(r["expense_date"])), ("description", r["description"]), ("category", r.get("category") or ""), ("currency", r["currency"]),
                           ("with_vat", f'{r.get("with_vat_subtotal") or 0:.2f}'), ("without_vat", f'{r.get("without_vat_subtotal") or 0:.2f}'), ("vat", f'{r["vat"]:.2f}'),
                           ("reference", r.get("reference") or ""), ("account", r["expense_account"]), ("no_vat_account", r.get("expense_without_vat_account") or "601100001"),
                           ("vat_account", r["vat_account"]), ("payment_account", r["payment_account"])):
            v[key].set(value)
        f["non_deductible"].set(not r.get("vat_recoverable", 1)); lists = self.dimension_lists()
        f["tax_non_deductible"].set(not int(r.get("tax_deductible", 1) if r.get("tax_deductible") is not None else 1))
        f["use"].set(next((k for k, val in PURCHASE_USES.items() if val == (r.get("vat_use") or "mixed")), "Mixed (partial deduction)"))
        f["department"].set(next((f'{d["code"]} - {d["name"]}' for d in lists["departments"] if d["id"] == r.get("department_id")), "(none)"))
        f["project"].set(next((f'{p["code"]} - {p["name"]}' for p in lists["projects"] if p["id"] == r.get("project_id")), "(none)"))
        f["number_label"].config(text=f"Editing {r.get('expense_number') or r['id']}"); f["pdf_label"].config(text=f"{r.get('attachment_count') or 0} document(s) attached", fg=NAVY)
        self.expense_amounts_changed("none")

    def delete_expense(self):
        f = self.expense_form; selected = f["tree"].selection()
        if len(selected) > 1:  # 2.9.69: several selected
            items = [(f["rows"][iid]["id"], f["rows"][iid].get("expense_number") or iid) for iid in selected if iid in f["rows"]]
            if not messagebox.askyesno("Expenses", f"Delete {len(items)} expenses and their journal entries?"): return
            bulk_action("Expenses", items, self.client.delete_expense)
            self.new_expense(); self.load_expenses(); self.load_journal(); self.load_trial(); return
        target = f["id"] or (f["rows"][selected[0]]["id"] if selected else None)
        if not target: return messagebox.showwarning("Expenses", "Select an expense first")
        if not messagebox.askyesno("Expenses", "Delete this expense and its journal entry?"): return
        try: self.client.delete_expense(target)
        except Exception as exc: return messagebox.showerror("Expenses", str(exc))
        self.new_expense(); self.load_expenses(); self.load_journal(); self.load_trial()

    def expense_attachments_window(self):
        f = self.expense_form; selected = f["tree"].selection()
        target = f["id"] or (f["rows"][selected[0]]["id"] if selected else None)
        if not target: return messagebox.showwarning("Expenses", "Select an expense first")
        try: items = self.client.expense_attachments(target)
        except Exception as exc: return messagebox.showerror("Expenses", str(exc))
        from desktop_attachments import attachments_window  # 2.9.97: see the document inside the program
        attachments_window(self, "this expense", items, lambda record: self.client.download_expense_attachment(record["id"])["content"])

    def import_expenses_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xlsm")])
        if not path: return
        self.select_main_tab(self.import_tab.master.master)
        self.import_type.set("Expenses")
        self.choose_import(path)
