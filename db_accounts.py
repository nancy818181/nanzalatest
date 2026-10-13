"""Chart of accounts tools (2.9.66): which accounts are used, delete accounts that have no transactions (one or many,
any kind: clients, suppliers, expenses...), move all the transactions of an account to another one, or transfer its
balance with a journal voucher.

Part of the Database class: Database inherits from AccountsStore."""
from __future__ import annotations

import re

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    Decimal, DEFAULT_LEBANESE_ACCOUNTS, display_date, EXPENSE_ACCOUNT_9, EXPENSE_NO_VAT_ACCOUNT_9, iso_date, json,
    LEBANESE_ACCOUNTS, utcnow, VAT_ACCOUNT_9
)
from database_common import _soft_iso  # noqa: F401

# text columns that hold an account code (table, column)
ACCOUNT_COLUMNS = (
    ("invoices", "supplier_account"), ("invoices", "vat_account"), ("invoices", "expense_account"), ("invoices", "expense_no_vat_account"), ("invoices", "payment_account"),
    ("document_cases", "supplier_account"), ("document_cases", "expense_account"), ("document_cases", "vat_account"),
    ("inventory_items", "cost_account"), ("inventory_items", "stock_account"),
    ("payments", "cash_account"), ("payments", "party_account"), ("payments", "commission_account"), ("payments", "exchange_account"),
    ("payments", "exchange_gain_account"), ("payments", "exchange_loss_account"),
    ("expenses", "expense_account"), ("expenses", "expense_without_vat_account"), ("expenses", "vat_account"), ("expenses", "payment_account"),
    ("employees", "salary_account"), ("employees", "payable_account"),
    ("payroll_settings", "salary_account"), ("payroll_settings", "salary_payable_account"), ("payroll_settings", "payroll_tax_account"), ("payroll_settings", "nssf_payable_account"),
    ("budgets", "account_code"), ("fixed_assets", "asset_account"), ("fixed_assets", "depreciation_account"), ("fixed_assets", "accumulated_account"),
    ("bank_statement_lines", "account_code"),
)
LABELS = {"invoices": "invoice", "document_cases": "document case", "inventory_items": "inventory item", "payments": "payment", "expenses": "expense",
          "employees": "employee", "payroll_settings": "payroll setting", "budgets": "budget", "fixed_assets": "fixed asset", "bank_statement_lines": "bank statement line"}
# tables that make a customer / supplier "used"
PARTY_TABLES = (("invoices", "party_id"), ("payments", "party_id"), ("journal_lines", "party_id"), ("stock_documents", "party_id"),
                ("party_documents", "party_id"), ("projects", "party_id"))
SCOPES = {"all": (), "clients": ("411",), "suppliers": ("401", "403", "404", "408"), "expenses": ("6",), "income": ("7",),
          "cash_bank": ("5",), "other_payables": ("46",)}


def _code(value):
    return str(value or "").split(" - ", 1)[0].strip()


class AccountsStore:
    def _system_account_codes(self):
        """Accounts of the official Lebanese chart and the ones the program needs: never deleted."""
        import chart_extra
        codes = {row[0] for row in LEBANESE_ACCOUNTS} | {str(v) for v in DEFAULT_LEBANESE_ACCOUNTS.values()}
        codes |= {row[0] for row in getattr(chart_extra, "EXTRA_ACCOUNTS", ())}
        codes |= {EXPENSE_ACCOUNT_9, VAT_ACCOUNT_9, EXPENSE_NO_VAT_ACCOUNT_9}
        def collect(code):
            for constant in code.co_consts:
                if isinstance(constant, str) and re.fullmatch(r"\d{3,9}(\.\d+)?", constant): codes.add(constant)
                elif hasattr(constant, "co_consts"): collect(constant)
        collect(type(self)._initialize.__code__)
        return codes

    def _existing_columns(self, db):
        result = []
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, column in ACCOUNT_COLUMNS:
            if table in tables and column in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}: result.append((table, column))
        return result

    def _party_used(self, db, party_id):
        tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, column in PARTY_TABLES:
            if table in tables and column in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                if db.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (party_id,)).fetchone(): return table
        if db.execute("SELECT 1 FROM inventory_items WHERE CAST(supplier_id AS INTEGER)=? LIMIT 1", (party_id,)).fetchone(): return "inventory_items"
        return None

    def account_usage(self, codes=None):
        """{code: {"name", "type", "lines", "children", "references": [...], "party": name or None, "system": bool, "free": bool}}"""
        system = self._system_account_codes()
        with self.connect() as db:
            accounts = {r["code"]: dict(r) for r in db.execute("SELECT a.id,a.code,a.name_en,a.type,(SELECT COUNT(*) FROM accounts c WHERE c.parent_id=a.id) children FROM accounts a")}
            wanted = [c for c in (codes or accounts) if c in accounts]
            lines = {r["account_id"]: r["n"] for r in db.execute("SELECT account_id,COUNT(*) n FROM journal_lines GROUP BY account_id")}
            references = {}
            for table, column in self._existing_columns(db):
                for row in db.execute(f"SELECT {column} code,COUNT(*) n FROM {table} WHERE {column} IS NOT NULL AND {column}<>'' GROUP BY {column}"):
                    code = _code(row["code"])
                    if code: references.setdefault(code, []).append(f'{row["n"]} {LABELS[table]}(s)')
            parties = {}
            for row in db.execute("SELECT id,name,account_number FROM parties WHERE account_number IS NOT NULL AND account_number<>''"):
                parties.setdefault(row["account_number"], []).append(dict(row))
            result = {}
            for code in wanted:
                account = accounts[code]; owners = parties.get(code, [])
                used_party = next((f'{p["name"]} has {self._party_used(db, p["id"])} records' for p in owners if self._party_used(db, p["id"])), None)
                info = {"code": code, "name": account["name_en"], "type": account["type"], "lines": lines.get(account["id"], 0), "children": account["children"],
                        "references": references.get(code, []), "party": ", ".join(p["name"] for p in owners) or None, "system": code in system}
                reasons = []
                if info["system"]: reasons.append("official chart account")
                if info["lines"]: reasons.append(f'{info["lines"]} journal line(s)')
                if info["children"]: reasons.append(f'{info["children"]} sub-account(s)')
                if info["references"]: reasons.append("used by " + ", ".join(info["references"]))
                if used_party: reasons.append(used_party)
                info["reasons"] = reasons; info["free"] = not reasons
                result[code] = info
        return result

    def unused_accounts(self, scope="all"):
        prefixes = SCOPES.get(scope, (str(scope),) if str(scope).isdigit() else ())
        return [info for code, info in sorted(self.account_usage().items())
                if info["free"] and (not prefixes or any(code.startswith(p) for p in prefixes))]

    def delete_accounts(self, codes, user_id):
        """Delete accounts without transactions. A customer / supplier file that only holds that account is deleted with it."""
        codes = [_code(c) for c in codes or [] if _code(c)]
        if not codes: raise ValueError("Choose the accounts to delete")
        usage = self.account_usage(codes); deleted = []; kept = []
        with self.connect() as db:
            for code in codes:
                info = usage.get(code)
                if not info: kept.append({"code": code, "reason": "not found"}); continue
                if not info["free"]: kept.append({"code": code, "reason": "; ".join(info["reasons"])}); continue
                parties = [dict(r) for r in db.execute("SELECT id,name FROM parties WHERE account_number=?", (code,))]
                for party in parties: db.execute("DELETE FROM parties WHERE id=?", (party["id"],))
                db.execute("DELETE FROM accounts WHERE code=?", (code,))
                db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                           (user_id, "delete", "account", json.dumps({"code": code, "name": info["name"], "parties": [p["name"] for p in parties]}, ensure_ascii=False), utcnow()))
                deleted.append({"code": code, "name": info["name"], "parties": [p["name"] for p in parties]})
        return {"deleted": deleted, "kept": kept}

    def _account_row(self, db, code, label):
        row = db.execute("SELECT * FROM accounts WHERE code=?", (_code(code),)).fetchone()
        if not row: raise ValueError(f"{label} account {_code(code) or '(empty)'} was not found")
        return row

    def move_account(self, source, target, user_id, merge_party=False):
        """Every transaction of `source` moves to `target` (journal lines and the documents that name the account).
        With merge_party, the customer / supplier of `source` is merged into the one of `target` and deleted."""
        with self.connect() as db:
            old = self._account_row(db, source, "From"); new = self._account_row(db, target, "To")
            if old["id"] == new["id"]: raise ValueError("Choose two different accounts")
            if db.execute("SELECT 1 FROM accounts WHERE parent_id=? LIMIT 1", (new["id"],)).fetchone() and len(new["code"]) < 9:
                raise ValueError(f"{new['code']} is a heading account (it has sub-accounts): choose a detail account")
            days = [r["entry_date"] for r in db.execute("SELECT DISTINCT e.entry_date FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id WHERE j.account_id=?", (old["id"],))]
        for day in days: self._assert_period_open(day)
        with self.connect() as db:
            moved = db.execute("UPDATE journal_lines SET account_id=? WHERE account_id=?", (new["id"], old["id"])).rowcount
            documents = 0
            for table, column in self._existing_columns(db):
                documents += db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=? OR {column} LIKE ?", (new["code"], old["code"], old["code"] + " - %")).rowcount
            merged = None
            old_party = db.execute("SELECT * FROM parties WHERE account_number=? ORDER BY id LIMIT 1", (old["code"],)).fetchone()
            new_party = db.execute("SELECT * FROM parties WHERE account_number=? ORDER BY id LIMIT 1", (new["code"],)).fetchone()
            if merge_party and old_party and new_party and old_party["id"] != new_party["id"]:
                tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, column in PARTY_TABLES:
                    if table in tables: db.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new_party["id"], old_party["id"]))
                db.execute("UPDATE inventory_items SET supplier_id=? WHERE CAST(supplier_id AS INTEGER)=?", (str(new_party["id"]), old_party["id"]))
                db.execute("DELETE FROM parties WHERE id=?", (old_party["id"],)); merged = old_party["name"]
            elif old_party:
                db.execute("UPDATE parties SET account_number=? WHERE account_number=?", (new["code"], old["code"]))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                       (user_id, "move", "account", json.dumps({"from": old["code"], "to": new["code"], "lines": moved, "documents": documents, "merged_party": merged}, ensure_ascii=False), utcnow()))
        return {"from": old["code"], "to": new["code"], "lines": moved, "documents": documents, "merged_party": merged}

    def transfer_balance(self, source, target, date, user_id, description=""):
        """Transfer the balance of `source` (on `date`, per currency) to `target` with a journal voucher; history stays."""
        day = iso_date(date, "Transfer date")
        with self.connect() as db:
            old = self._account_row(db, source, "From"); new = self._account_row(db, target, "To")
            if old["id"] == new["id"]: raise ValueError("Choose two different accounts")
            balances = [dict(r) for r in db.execute("""SELECT e.currency,DSUM(CAST(j.debit AS REAL))-DSUM(CAST(j.credit AS REAL)) balance
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id WHERE j.account_id=? AND
                (CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END)<=?
                GROUP BY e.currency""", (old["id"], day))]
        vouchers = []
        for row in balances:
            amount = Decimal(str(row["balance"] or 0)).quantize(Decimal("0.01"))
            if not amount: continue
            side_new, side_old = ("D", "C") if amount > 0 else ("C", "D")
            text = description or f"Transfer of balance {old['code']} -> {new['code']}"
            saved = self.save_journal_voucher({"entry_date": display_date(day), "description": text, "currency": row["currency"], "voucher_type": "06"},
                                              [{"account_code": new["code"], "side": side_new, "amount": str(abs(amount))},
                                               {"account_code": old["code"], "side": side_old, "amount": str(abs(amount))}], user_id)
            vouchers.append({"currency": row["currency"], "amount": float(amount), "voucher": saved["voucher"]["entry_number"]})
        if not vouchers: raise ValueError(f"{old['code']} has no balance on {display_date(day)}")
        return {"from": old["code"], "to": new["code"], "vouchers": vouchers}

    # ------------------------------------------------------------ 2.9.67: move chosen transactions only
    SOURCE_TABLES = {"invoice": "invoices", "invoice_payment": "invoices", "vat_reclass": "invoices", "payment": "payments", "expense": "expenses"}

    def account_lines(self, code, date_from=None, date_to=None):
        """The journal lines of one account (newest last), to choose which ones move to another account."""
        day = """CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"""
        conditions = ["a.code=?"]; parameters = [_code(code)]
        if date_from: conditions.append(f"{day}>=?"); parameters.append(iso_date(date_from))
        if date_to: conditions.append(f"{day}<=?"); parameters.append(iso_date(date_to))
        with self.connect() as db:
            self._account_row(db, code, "From")
            rows = [dict(r) for r in db.execute(f"""SELECT j.id,{day} entry_date,e.entry_number,e.description,COALESCE(j.description,'') line_description,e.currency,
                CAST(j.debit AS REAL) debit,CAST(j.credit AS REAL) credit,COALESCE(p.name,'') party_name,e.source_type,e.source_id,e.id entry_id
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id LEFT JOIN parties p ON p.id=j.party_id
                WHERE {' AND '.join(conditions)} ORDER BY {day},e.id,j.id""", parameters)]
        return rows

    INVOICE_ACCOUNT_FIELDS = {"expense_account": "Purchases / Expense / Sales account", "vat_account": "VAT account",
                              "expense_no_vat_account": "Non-deductible account", "supplier_account": "Customer / Supplier account",
                              "payment_account": "Cash / Bank account (paid invoices)"}  # 2.9.78

    def set_invoices_account(self, invoice_ids, field, code, user_id):
        """2.9.71 (Uploaded Data, one account for all the selected rows): the chosen account replaces, on every selected invoice,
        the account of `field` - in the invoice and on its own journal lines (invoice, payment on the spot, VAT reclass).
        The other lines (stock, branch, department, project, amounts) stay exactly as they were. Returns done / skipped."""
        if field not in self.INVOICE_ACCOUNT_FIELDS: raise ValueError("Choose which account to change")
        new_code = _code(code)
        ids = sorted({int(i) for i in invoice_ids or [] if str(i).strip().isdigit()})
        if not ids: raise ValueError("Select the invoice rows first")
        with self.connect() as db:
            new = self._account_row(db, new_code, "New")
            if db.execute("SELECT 1 FROM accounts WHERE parent_id=? LIMIT 1", (new["id"],)).fetchone() and len(new["code"]) < 9:
                raise ValueError(f"{new['code']} is a heading account (it has sub-accounts): choose a detail account")
            invoices = {r["id"]: dict(r) for r in db.execute(f"SELECT * FROM invoices WHERE id IN ({','.join('?' * len(ids))})", ids)}
        done, skipped = [], []
        for invoice_id in ids:
            invoice = invoices.get(invoice_id)
            if not invoice: skipped.append(f"#{invoice_id}: not found"); continue
            number = invoice.get("invoice_number") or f"#{invoice_id}"
            if invoice.get("status") in ("cancelled", "deleted"): skipped.append(f"{number}: {invoice['status']}"); continue
            try: self._assert_vat_open(invoice.get("invoice_date"))  # 2.9.84: the saved VAT return keeps its documents
            except ValueError as exc: skipped.append(f"{number}: {exc}"); continue
            old_code = str(invoice.get(field) or "").split(" - ", 1)[0].strip()
            if field == "payment_account":  # 2.9.78: only paid invoices have a cash / bank line; without a stored one it is the method's default
                if not Decimal(str(invoice.get("amount_paid") or 0)): skipped.append(f"{number}: not paid (no cash / bank line)"); continue
                old_code = old_code or self._payment_account(invoice.get("payment_method"), None)
            if old_code == new["code"]: skipped.append(f"{number}: already {new['code']}"); continue
            if not old_code: skipped.append(f"{number}: has no {self.INVOICE_ACCOUNT_FIELDS[field].lower()}"); continue
            others = [f for f in list(self.INVOICE_ACCOUNT_FIELDS) + ["payment_account"]
                      if f != field and str(invoice.get(f) or "").split(" - ", 1)[0].strip() == old_code]
            if others:
                skipped.append(f"{number}: {old_code} is also its {others[0].replace('_', ' ')} - edit this invoice alone"); continue
            with self.connect() as db:
                lines = [r["id"] for r in db.execute("""SELECT j.id FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                    JOIN accounts a ON a.id=j.account_id WHERE e.source_id=? AND e.source_type IN ('invoice','journal_voucher','invoice_payment','vat_reclass')
                    AND a.code=?""", (invoice_id, old_code))]
            try:
                if lines: self.move_lines(old_code, new["code"], lines, user_id, change_party=False)
                with self.connect() as db:
                    db.execute(f"UPDATE invoices SET {field}=? WHERE id=?", (new["code"], invoice_id))
                done.append(number)
            except Exception as exc:
                skipped.append(f"{number}: {exc}")
        return {"field": field, "account": new["code"], "done": done, "skipped": skipped}

    def sales_account_problems(self):
        """2.9.77: sales booked on the wrong accounts by earlier versions (Excel import): the customer on a SUPPLIERS account
        (40...) or on the general 4111 instead of his own account, the revenue on a non-class-7 account, the VAT on deductible
        (input) VAT. One row per invoice with the corrections it needs."""
        import chart_extra
        problems = []
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.party_id,p.name party_name,i.currency,i.total,
                i.supplier_account,i.expense_account,i.vat_account FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
                WHERE i.kind='sale' AND i.status NOT IN ('cancelled','deleted') ORDER BY i.id""")]
            for row in rows:
                fixes = {}; reasons = []
                party = db.execute("SELECT * FROM parties WHERE id=?", (row["party_id"],)).fetchone() if row["party_id"] else None
                own = self._ensure_party_account(db, party) if party else None
                customer = _code(row["supplier_account"])
                if own and own != customer and (customer.startswith("40") or customer == DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"]):
                    fixes["supplier_account"] = own
                    reasons.append(f"customer on {customer}{' (suppliers!)' if customer.startswith('40') else ' (general customers)'} -> {own}")
                revenue = _code(row["expense_account"])
                if not revenue.startswith("7"):
                    fixes["expense_account"] = DEFAULT_LEBANESE_ACCOUNTS["sales"]; reasons.append(f"revenue on {revenue} -> {DEFAULT_LEBANESE_ACCOUNTS['sales']}")
                vat = _code(row["vat_account"])
                if vat.startswith(("4426", "4421")) or vat in (chart_extra.PURCHASE_VAT, chart_extra.EXPORT_VAT, chart_extra.EXPENSE_VAT):
                    fixes["vat_account"] = chart_extra.SALES_VAT; reasons.append(f"VAT on {vat} (deductible VAT) -> {chart_extra.SALES_VAT}")
                if fixes: problems.append({**row, "fixes": fixes, "reasons": reasons})
        return problems

    def fix_sales_accounts(self, invoice_ids, user_id):
        """2.9.77: apply the corrections of sales_account_problems to the chosen invoices (journal lines moved, nothing else)."""
        chosen = {int(i) for i in invoice_ids or [] if str(i).strip().isdigit()}
        done, skipped = [], []
        for problem in self.sales_account_problems():
            if problem["id"] not in chosen: continue
            failed = []
            for field, code in problem["fixes"].items():
                result = self.set_invoices_account([problem["id"]], field, code, user_id)
                failed += [text.split(": ", 1)[-1] for text in result["skipped"] if "already" not in text]
            (skipped.append(f"{problem['invoice_number']}: {'; '.join(failed)}") if failed else done.append(problem["invoice_number"]))
        return {"done": done, "skipped": skipped}

    def move_lines(self, source, target, line_ids, user_id, change_party=True):
        """The chosen lines of `source` are booked on `target` instead (a replacement, no new voucher). The document
        behind each line (invoice, payment, expense) gets the new account too, so editing it later keeps the change.
        With change_party, when both accounts belong to a customer / supplier, those documents move to the new one."""
        ids = sorted({int(i) for i in line_ids or [] if str(i).strip().lstrip("-").isdigit()})
        if not ids: raise ValueError("Select the transactions to move")
        with self.connect() as db:
            old = self._account_row(db, source, "From"); new = self._account_row(db, target, "To")
            if old["id"] == new["id"]: raise ValueError("Choose two different accounts")
            if db.execute("SELECT 1 FROM accounts WHERE parent_id=? LIMIT 1", (new["id"],)).fetchone() and len(new["code"]) < 9:
                raise ValueError(f"{new['code']} is a heading account (it has sub-accounts): choose a detail account")
            marks = ",".join("?" * len(ids))
            rows = [dict(r) for r in db.execute(f"""SELECT j.id,j.account_id,j.party_id,e.entry_date,e.source_type,e.source_id FROM journal_lines j
                JOIN journal_entries e ON e.id=j.entry_id WHERE j.id IN ({marks})""", ids)]
            if len(rows) != len(ids) or any(r["account_id"] != old["id"] for r in rows):
                raise ValueError(f"Some of the chosen lines are not on account {old['code']} any more: refresh the list")
        for day in sorted({r["entry_date"] for r in rows}): self._assert_period_open(day)
        with self.connect() as db:
            old_party = db.execute("SELECT * FROM parties WHERE account_number=? ORDER BY id LIMIT 1", (old["code"],)).fetchone()
            new_party = db.execute("SELECT * FROM parties WHERE account_number=? ORDER BY id LIMIT 1", (new["code"],)).fetchone()
            swap_party = bool(change_party and old_party and new_party and old_party["id"] != new_party["id"])
            db.execute(f"UPDATE journal_lines SET account_id=? WHERE id IN ({marks})", [new["id"]] + ids)
            if swap_party: db.execute(f"UPDATE journal_lines SET party_id=? WHERE id IN ({marks}) AND party_id=?", [new_party["id"]] + ids + [old_party["id"]])
            columns = {}
            for table, column in self._existing_columns(db): columns.setdefault(table, []).append(column)
            documents = set()
            for row in rows:
                table = self.SOURCE_TABLES.get(row["source_type"])
                if not table or not row["source_id"] or (table, row["source_id"]) in documents: continue
                documents.add((table, row["source_id"]))
                for column in columns.get(table, []):
                    db.execute(f"UPDATE {table} SET {column}=? WHERE id=? AND ({column}=? OR {column} LIKE ?)", (new["code"], row["source_id"], old["code"], old["code"] + " - %"))
                if swap_party and table in ("invoices", "payments"):
                    db.execute(f"UPDATE {table} SET party_id=? WHERE id=? AND party_id=?", (new_party["id"], row["source_id"], old_party["id"]))
                    # the other lines of that document (VAT, cash...) name the customer / supplier too
                    db.execute("""UPDATE journal_lines SET party_id=? WHERE party_id=? AND entry_id IN (SELECT id FROM journal_entries WHERE source_type=? AND source_id=?)""",
                               (new_party["id"], old_party["id"], row["source_type"], row["source_id"]))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                       (user_id, "move-lines", "account", json.dumps({"from": old["code"], "to": new["code"], "lines": ids, "documents": len(documents),
                                                                     "party": [old_party["name"], new_party["name"]] if swap_party else None}, ensure_ascii=False), utcnow()))
        return {"from": old["code"], "to": new["code"], "lines": len(ids), "documents": len(documents),
                "party_changed": f'{old_party["name"]} -> {new_party["name"]}' if swap_party else None}
