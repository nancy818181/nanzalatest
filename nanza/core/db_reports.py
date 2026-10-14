"""Chart of accounts and the reports: journal, trial balance, ledger, balance sheet, P&L, cash flow, ageing, VAT report, dashboards, fiscal years.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from ReportsStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, json, utcnow
)
from database_common import _soft_iso  # noqa: F401


class ReportsStore:
    # ---------------------------------------------------------------- 2.9.80: every currency converted (planning tools)
    def _converted_lines(self, currency, from_date=None, to_date=None, without_opening=False):
        """Posted journal lines with their value in `currency` (USD, LBP or any currency of the company), whatever
        the currency they were entered in. Closing entries are left out."""
        import ledger_reports
        options = {"first_column": currency, "second_column": "none", "posting_status": "posted", "without_closing": True, "exclude_closing": True}
        if without_opening: options["without_opening"] = True
        start = _soft_iso(from_date) or "0000-01-01"; end = _soft_iso(to_date) or "9999-12-31"
        return [row for row in ledger_reports._load_lines(self, options) if start <= row["iso_date"] <= end]

    def profit_and_loss_converted(self, from_date=None, to_date=None, currency="USD"):
        """The P&L of every transaction (LBP payroll, EUR expenses ...) in one currency: same rows as profit_and_loss."""
        totals = {}
        for row in self._converted_lines(currency, from_date, to_date):
            if row["account_type"] not in ("income", "expense"): continue
            value = row["signed"].get(currency) or Decimal("0")
            item = totals.setdefault(row["code"], {"currency": currency, "code": row["code"], "name_en": row["name_en"], "type": row["account_type"], "debit": Decimal("0"), "credit": Decimal("0")})
            if value >= 0: item["debit"] += Decimal(str(value))  # 2.9.97: exact, turned into numbers once below
            else: item["credit"] -= Decimal(str(value))
        for item in totals.values(): item["debit"], item["credit"] = float(item["debit"]), float(item["credit"])
        rows = sorted(totals.values(), key=lambda r: r["code"])
        for row in rows: row["amount"] = (row["credit"] - row["debit"]) if row["type"] == "income" else (row["debit"] - row["credit"])
        return rows

    def cash_flow_converted(self, from_date=None, to_date=None, currency="USD"):
        """Cash and bank (51 / 53) movements of every currency in one currency, without the opening / closing entries."""
        categories = {"invoice": "Operating - Invoices", "expense": "Operating - Expenses", "payroll": "Operating - Payroll", "payment": "Operating - Receipts / Payments"}
        grouped = {}
        for row in self._converted_lines(currency, from_date, to_date, without_opening=True):
            digits = "".join(ch for ch in str(row["code"]) if ch.isdigit())
            if not digits.startswith(("51", "53")) or row.get("source_type") == "opening": continue
            value = float(row["signed"].get(currency) or 0); category = categories.get(row.get("source_type"), "Other Cash Movement")
            item = grouped.setdefault(category, {"currency": currency, "category": category, "inflow": 0.0, "outflow": 0.0, "net": 0.0})
            if value > 0: item["inflow"] += value
            else: item["outflow"] -= value
            item["net"] = item["inflow"] - item["outflow"]
        return sorted(grouped.values(), key=lambda r: r["category"])

    def balance_sheet_converted(self, to_date=None, currency="USD"):
        """Balances of classes 1-5 at to_date, every currency converted into one."""
        totals = {}
        for row in self._converted_lines(currency, None, to_date):
            if row["account_type"] not in ("asset", "liability", "equity"): continue
            value = float(row["signed"].get(currency) or 0)
            item = totals.setdefault(row["code"], {"currency": currency, "code": row["code"], "name_en": row["name_en"], "type": row["account_type"], "debit": 0.0, "credit": 0.0, "balance": 0.0})
            if value >= 0: item["debit"] += value
            else: item["credit"] -= value
            item["balance"] += value
        return sorted(totals.values(), key=lambda r: r["code"])

    def profit_and_loss(self, from_date=None, to_date=None, currency=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        # The year-end closing brings 6 & 7 to zero; the P&L must show the year before closing.
        conditions = ["a.type IN ('income','expense')", "NOT (e.source_type='year_close' OR (e.voucher_type='05' AND e.description LIKE 'CLOSING 6&7 - %'))"]
        parameters = []
        normalized_date = """CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        if from_date: conditions.append(f"{normalized_date}>=?"); parameters.append(from_date)
        if to_date: conditions.append(f"{normalized_date}<=?"); parameters.append(to_date)
        if currency: conditions.append("e.currency=?"); parameters.append(currency)
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(f"""SELECT e.currency,a.code,a.name_en,a.type,
                DSUM(CAST(j.debit AS REAL)) debit,DSUM(CAST(j.credit AS REAL)) credit
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                WHERE {' AND '.join(conditions)} GROUP BY e.currency,a.id ORDER BY e.currency,a.code""", parameters)]
        for row in rows:
            row["amount"] = (row["credit"] - row["debit"]) if row["type"] == "income" else (row["debit"] - row["credit"])
        return rows

    def close_fiscal_year(self, year, user_id):
        """Close classes 6 & 7 with a 'CLOSING 6&7' Journal Voucher (type 05) per currency."""
        import year_end
        return year_end.close_year(self, year, user_id)

    def list_fiscal_years(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM fiscal_years ORDER BY year DESC")]

    def reopen_fiscal_year(self,year,user_id):
        """Delete every closing of this year (old and new style) and open it again."""
        import year_end
        return year_end.reopen_year(self, year, user_id)

    def professional_dashboard(self):
        """Aggregate dashboard figures in SQLite instead of loading every expense and invoice."""
        metrics={}
        def metric(code):
            return metrics.setdefault(code,{"currency":code,"sales":0.0,"purchases":0.0,
                "expenses":0.0,"profit":0.0,"receivables":0.0,"payables":0.0,"overdue":0})
        with self.connect() as db:
            invoice_rows=db.execute("""SELECT kind,currency,
                DSUM(CAST(subtotal AS REAL)) subtotal,
                DSUM(CAST(total AS REAL)-CAST(COALESCE(amount_paid,'0') AS REAL)) outstanding
                FROM invoices WHERE status NOT IN ('cancelled','deleted')
                GROUP BY kind,currency""").fetchall()
            expense_rows=db.execute("""SELECT currency,DSUM(CAST(subtotal AS REAL)) subtotal
                FROM expenses GROUP BY currency""").fetchall()
            # Preserve the existing DD-MM-YYYY due date interpretation.
            overdue_rows=db.execute("""SELECT currency,COUNT(*) overdue FROM invoices
                WHERE status NOT IN ('cancelled','deleted')
                  AND CAST(total AS REAL)>CAST(COALESCE(amount_paid,'0') AS REAL)
                  AND due_date GLOB '??-??-????'
                  AND substr(due_date,7,4)||'-'||substr(due_date,4,2)||'-'||substr(due_date,1,2)<?
                GROUP BY currency""",(datetime.now().strftime("%Y-%m-%d"),)).fetchall()
            monthly=[dict(row) for row in db.execute("""SELECT substr(CASE WHEN invoice_date GLOB '??-??-????' THEN substr(invoice_date,7,4)||'-'||substr(invoice_date,4,2)||'-'||substr(invoice_date,1,2) ELSE invoice_date END,1,7) month,
                currency,kind,DSUM(CAST(subtotal AS REAL)) amount FROM invoices WHERE status NOT IN ('cancelled','deleted') GROUP BY month,currency,kind ORDER BY month""")]
        for row in invoice_rows:
            values=metric(row["currency"]); amount=float(row["subtotal"] or 0)
            outstanding=float(row["outstanding"] or 0)
            if row["kind"]=="sale":
                values["sales"]+=amount; values["receivables"]+=outstanding
            else:
                values["purchases"]+=amount; values["payables"]+=outstanding
        for row in expense_rows:
            metric(row["currency"])["expenses"]+=float(row["subtotal"] or 0)
        for row in overdue_rows:
            metric(row["currency"])["overdue"]=int(row["overdue"])
        for values in metrics.values():
            values["profit"]=values["sales"]-values["purchases"]-values["expenses"]
        return {"metrics":list(metrics.values()),"monthly":monthly}

    def statement_of_account(self, party_id, from_date=None, to_date=None, currency=None, include_opening=True, display_currency=None, branch_id=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        normalized_date = """CASE
            WHEN i.invoice_date GLOB '??-??-????'
                THEN substr(i.invoice_date,7,4)||'-'||substr(i.invoice_date,4,2)||'-'||substr(i.invoice_date,1,2)
            ELSE i.invoice_date END"""
        filters = ["i.party_id=?", "i.status='posted'"]  # 2.9.84: cancelled / deleted / review documents are not owed
        parameters = [party_id]
        if currency:
            filters.append("i.currency=?"); parameters.append(currency)
        if branch_id:
            filters.append("i.branch_id=?"); parameters.append(int(branch_id))
        if to_date:
            filters.append(f"{normalized_date} <= ?"); parameters.append(to_date)
        with self.connect() as db:
            party = db.execute("SELECT id,kind,name,currency FROM parties WHERE id=?", (party_id,)).fetchone()
            if not party:
                raise KeyError(party_id)
            rows = [dict(row) for row in db.execute(f"""SELECT i.id,i.invoice_number,i.invoice_date,i.kind,
                i.currency,i.total,i.branch_id,i.doc_subtype FROM invoices i WHERE {' AND '.join(filters)}
                ORDER BY {normalized_date},i.id""", parameters)]
            # 2.9.84: receipts and payments are on the statement too (they were missing, so it showed invoices only)
            if not branch_id:
                pay_filters = ["x.party_id=?"]; pay_parameters = [party_id]
                if currency: pay_filters.append("x.currency=?"); pay_parameters.append(currency)
                for pay in db.execute(f"""SELECT x.id,x.payment_number,x.payment_date,x.kind,x.currency,
                        CAST(x.amount AS REAL)+CAST(COALESCE(x.exchange_difference,'0') AS REAL) total FROM payments x WHERE {' AND '.join(pay_filters)}""", pay_parameters):
                    day = _soft_iso(pay["payment_date"])
                    if to_date and day > to_date: continue
                    rows.append({"id": pay["id"], "invoice_number": pay["payment_number"], "invoice_date": day, "kind": pay["kind"], "currency": pay["currency"],
                                 "total": pay["total"], "branch_id": None, "doc_subtype": "payment"})
                rows.sort(key=lambda r: (_soft_iso(r["invoice_date"]) or "", r["doc_subtype"] == "payment"))
        opening = {}
        items = []
        for row in rows:
            normalized = row["invoice_date"]
            try:
                normalized = datetime.strptime(normalized, "%d-%m-%Y").strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pass
            amount = Decimal(str(row["total"] or 0))
            output_currency=(display_currency or row["currency"]).upper()
            amount=self._converted_amount(amount,row["currency"],output_currency,normalized)
            owed_by_party = row["kind"] in ("sale", "supplier_payment")  # a sale or a payment to the party: debit
            if row.get("doc_subtype") == "credit_note": owed_by_party = not owed_by_party
            debit = amount if owed_by_party else Decimal("0")
            credit = amount if not owed_by_party else Decimal("0")
            if from_date and normalized < from_date:
                if include_opening:
                    opening[output_currency] = opening.get(output_currency, Decimal("0")) + debit - credit
                continue
            items.append({**row, "source_currency":row["currency"],"currency":output_currency,
                          "description": ({"customer_receipt": "Receipt", "supplier_payment": "Payment"}.get(row["kind"]) or
                                          ("Credit note" if row.get("doc_subtype") == "credit_note" else f"{row['kind'].title()} invoice")) + f" {row['invoice_number']}",
                          "debit": float(debit), "credit": float(credit)})
        balances = dict(opening)
        for row in items:
            code = row["currency"]
            balances[code] = balances.get(code, Decimal("0")) + Decimal(str(row["debit"])) - Decimal(str(row["credit"]))
            row["balance"] = float(balances[code])
        return {"party": dict(party), "opening": {key: float(value) for key,value in opening.items()}, "items": items}

    def list_accounts(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("""SELECT a.code,a.name_en,a.name_ar,a.name_fr,a.type,
                p.code parent_code FROM accounts a LEFT JOIN accounts p ON p.id=a.parent_id
                ORDER BY CASE WHEN instr(a.code,'.')>0 THEN replace(a.code,'.','') ELSE a.code END""")]

    def next_party_account_number(self,prefix):
        """Next free 9-digit customer/supplier account under a 4-digit prefix (e.g. 4111 -> 411100007)."""
        prefix="".join(character for character in str(prefix or "") if character.isdigit())
        if len(prefix)!=4: raise ValueError("Enter the first 4 account digits")
        with self.connect() as db:
            used=[int(row["value"]) for row in db.execute("""SELECT account_number value FROM parties WHERE length(account_number)=9 AND account_number LIKE ?
                UNION SELECT code FROM accounts WHERE length(code)=9 AND code GLOB '[0-9]*' AND code LIKE ?""",(prefix+"%",prefix+"%")) if str(row["value"]).isdigit()]
        number=max(used,default=int(prefix+"00000"))+1
        if number>int(prefix+"99999"): raise ValueError(f"No account numbers remain under prefix {prefix}")
        return str(number).zfill(9)

    def next_account_number(self,prefix):
        prefix="".join(character for character in str(prefix or "") if character.isdigit())
        if len(prefix)!=4: raise ValueError("Enter the first 4 account digits")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM accounts WHERE code=?",(prefix,)).fetchone(): raise ValueError("The 4-digit parent account was not found")
            values=[int(row["code"]) for row in db.execute("SELECT code FROM accounts WHERE length(code)=9 AND code GLOB '[0-9]*' AND code LIKE ?",(prefix+"%",))]
        return str(max(values,default=int(prefix+"00000"))+1).zfill(9)

    def save_account(self,item,user_id):
        code=str(item.get("code") or "").strip(); name=str(item.get("name_en") or "").strip()
        account_type=str(item.get("type") or "expense").strip().lower(); parent=str(item.get("parent_code") or "").strip() or None
        if not name or account_type not in ("asset","liability","equity","income","expense"): raise ValueError("Enter a valid account name and type")
        with self.connect() as db:
            if len(code)==4 and code.isdigit():
                parent=parent or code; code=""
            parent_id=None
            if parent:
                row=db.execute("SELECT id FROM accounts WHERE code=?",(parent,)).fetchone()
                if not row: raise ValueError("Parent account was not found")
                parent_id=row["id"]
            if not code:
                prefix="".join(character for character in (parent or "") if character.isdigit())
                if prefix and len(prefix)<9:
                    if len(prefix)==4: code=self.next_account_number(prefix)
                    else:
                        values=[int(row["code"]) for row in db.execute("SELECT code FROM accounts WHERE length(code)=9 AND code GLOB '[0-9]*' AND code LIKE ?",(prefix+"%",))]
                        code=str(max(values,default=int(prefix+"0"*(9-len(prefix))))+1).zfill(9)
                else:
                    values=[int(row["code"]) for row in db.execute("SELECT code FROM accounts WHERE length(code)=9 AND code GLOB '[0-9]*'")]
                    code=str(max(values,default=100000000)+1).zfill(9)
            if len(code)!=9 or not code.isdigit(): raise ValueError("Enter a 4-digit prefix for automatic numbering, a full 9-digit number, or leave it blank")
            if db.execute("SELECT 1 FROM accounts WHERE code=?",(code,)).fetchone(): raise ValueError(f"Account {code} already exists; duplicate accounts are not allowed")
            db.execute("INSERT INTO accounts(code,name_en,type,parent_id) VALUES(?,?,?,?)",(code,name,account_type,parent_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"save","account",json.dumps({"code":code,"name":name}),utcnow()))
        return {"code":code,"name_en":name,"type":account_type,"parent_code":parent}

    def rename_account(self,code,name,user_id,name_fr=None,name_ar=None,account_type=None):
        """Edit an account: English name (required), and when given the French / Arabic names and the type."""
        code=str(code or "").strip(); name=str(name or "").strip()
        if not name: raise ValueError("Account name is required")
        if account_type is not None and str(account_type) not in ("asset","liability","equity","income","expense"):
            raise ValueError("Account type must be asset, liability, equity, income or expense")
        with self.connect() as db:
            row=db.execute("SELECT * FROM accounts WHERE code=?",(code,)).fetchone()
            if not row: raise KeyError(code)
            changes={"name_en":name}
            if name_fr is not None: changes["name_fr"]=str(name_fr).strip() or None
            if name_ar is not None: changes["name_ar"]=str(name_ar).strip() or None
            if account_type is not None: changes["type"]=str(account_type)
            db.execute(f"UPDATE accounts SET {','.join(k+'=?' for k in changes)} WHERE code=?",(*changes.values(),code))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"edit","account",json.dumps({"code":code,"before":{k:row[k] for k in changes},"after":changes},ensure_ascii=False),utcnow()))
            saved=dict(db.execute("SELECT * FROM accounts WHERE code=?",(code,)).fetchone())
        return saved

    def dashboard(self):
        with self.connect() as db:
            rows = db.execute("""SELECT kind,currency,DSUM(CAST(subtotal AS REAL)) subtotal,
                DSUM(CAST(vat AS REAL)) vat,DSUM(CAST(total AS REAL)) total,COUNT(*) count,
                DSUM(CASE WHEN kind='sale' THEN CAST(total AS REAL) ELSE 0 END) debit,
                DSUM(CASE WHEN kind='purchase' THEN CAST(total AS REAL) ELSE 0 END) credit
                FROM invoices WHERE status NOT IN ('cancelled','deleted') GROUP BY kind,currency""").fetchall()
            return [dict(r) for r in rows]

    def journal(self, from_date=None, to_date=None, currency=None, limit=None, branch_id=None, entry_number=None, account_code=None, source_type=None):
        """Return journal lines with a running balance per account and currency.
        2.9.51: no line limit any more (5,000 lines used to hide later entries from the journal, the general ledger and
        'open transaction'); one entry, one account or one kind of entry can be asked for directly."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        conditions = []
        parameters = []
        if entry_number: conditions.append("e.entry_number=?"); parameters.append(str(entry_number))
        if account_code: conditions.append("a.code=?"); parameters.append(str(account_code))
        if source_type: conditions.append("e.source_type=?"); parameters.append(str(source_type))
        normalized_date = """CASE
            WHEN e.entry_date GLOB '??-??-????'
                THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        if from_date:
            conditions.append(f"{normalized_date} >= ?")
            parameters.append(from_date)
        if to_date:
            conditions.append(f"{normalized_date} <= ?")
            parameters.append(to_date)
        if currency:
            conditions.append("e.currency = ?")
            parameters.append(currency)
        if branch_id:
            conditions.append("e.branch_id=?"); parameters.append(int(branch_id))
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        parameters.append(int(limit) if limit else -1)  # SQLite: LIMIT -1 = every line
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(f"""SELECT e.id entry_id,e.entry_number,e.entry_date,
                e.description,e.source_type,e.source_id,e.voucher_type,e.currency,e.branch_id,COALESCE(b.name,'Head Office') branch_name,a.code account_code,a.name_en account_name,
                CASE WHEN e.source_type='payroll' THEN 'Payroll' WHEN e.source_type='expense' THEN 'Expenses'
                     WHEN e.source_type='journal_voucher' AND e.voucher_type='07' THEN 'DOE'
                     WHEN e.source_type='journal_voucher' THEN 'Journal Vouchers' WHEN e.source_type IN ('opening','year_close') THEN 'Opening / Closing'
                     WHEN e.source_type='invoice' AND i.kind='sale' THEN 'Sales'
                     WHEN e.source_type='invoice' AND COALESCE(i.entry_type,i.kind)='expenses' THEN 'Expenses'
                     WHEN e.source_type='invoice' THEN 'Purchases' ELSE 'Other' END journal_category,
                COALESCE(p.name,'') party_name,COALESCE(j.description,'') line_description,CAST(j.debit AS REAL) debit,CAST(j.credit AS REAL) credit,j.id line_id,
                COALESCE(pr.code,'') project_code,COALESCE(dp.code,'') department_code
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                JOIN accounts a ON a.id=j.account_id LEFT JOIN parties p ON p.id=j.party_id LEFT JOIN branches b ON b.id=e.branch_id
                LEFT JOIN projects pr ON pr.id=j.project_id LEFT JOIN departments dp ON dp.id=j.department_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                {where_clause}
                ORDER BY {normalized_date},e.id,j.id LIMIT ?""", parameters)]
        balances = {}
        for row in rows:
            key = (row["currency"], row["account_code"])
            balances[key] = balances.get(key, Decimal("0")) + Decimal(str(row["debit"] or 0)) - Decimal(str(row["credit"] or 0))
            row["balance"] = float(balances[key])
            row.pop("line_id", None)
        return rows

    def trial_balance(self, from_date=None, to_date=None, account_code=None, include_subaccounts=True, account_from=None, account_to=None, branch_id=None, posting_status="posted"):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        conditions = []
        parameters = []
        normalized_date = """CASE
            WHEN e.entry_date GLOB '??-??-????'
                THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        if to_date:
            conditions.append(f"{normalized_date} <= ?")
            parameters.append(to_date)
        if account_code:
            conditions.append("a.code LIKE ?" if include_subaccounts else "a.code=?")
            parameters.append(str(account_code)+"%" if include_subaccounts else str(account_code))
        if account_from:
            conditions.append("CAST(REPLACE(a.code,'.','') AS INTEGER)>=?"); parameters.append(int(''.join(c for c in str(account_from) if c.isdigit())))
        if account_to:
            conditions.append("CAST(REPLACE(a.code,'.','') AS INTEGER)<=?"); parameters.append(int(''.join(c for c in str(account_to) if c.isdigit())))
        if branch_id: conditions.append("e.branch_id=?"); parameters.append(int(branch_id))
        if posting_status=="posted": conditions.append("(e.source_type!='invoice' OR i.status IN ('posted','cancelled'))")  # 2.9.97: a cancelled invoice keeps its entry (its reversal is posted too)
        elif posting_status=="review": conditions.append("(e.source_type='invoice' AND i.status='review')")
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as db:
            # 2.9.58: summed per account, currency and day by the database (one row per day instead of per line)
            raw=[dict(r) for r in db.execute(f"""SELECT a.code,a.name_en,e.currency,e.entry_date,
                DSUM(CAST(j.debit AS REAL)) debit,DSUM(CAST(j.credit AS REAL)) credit
                FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                {where_clause} GROUP BY a.code,a.name_en,e.currency,e.entry_date ORDER BY e.currency,a.code""",parameters)]
        totals={}
        for row in raw:
            key=(row["code"],row["name_en"],row["currency"])
            # 2.9.97: added as exact Decimals, turned into numbers once at the end (floats drifted: 600.0000000000002)
            item=totals.setdefault(key,{"code":row["code"],"name_en":row["name_en"],"currency":row["currency"],
                **{field:Decimal("0") for field in ("opening","debit","credit","balance","closing_balance","usd_opening","usd_debit","usd_credit",
                   "usd_balance","usd_closing_balance","lbp_opening","lbp_debit","lbp_credit","lbp_balance","lbp_closing_balance")}})
            date=str(row["entry_date"] or "")
            try: date=datetime.strptime(date,"%d-%m-%Y").strftime("%Y-%m-%d")
            except ValueError: pass
            debit=Decimal(str(row["debit"] or 0)); credit=Decimal(str(row["credit"] or 0))
            usd_d=self._converted_amount(debit,row["currency"],"USD",date); usd_c=self._converted_amount(credit,row["currency"],"USD",date)
            lbp_d=self._converted_amount(debit,row["currency"],"LBP",date); lbp_c=self._converted_amount(credit,row["currency"],"LBP",date)
            if from_date and date<from_date:
                item["opening"]+=debit-credit; item["usd_opening"]+=Decimal(str(usd_d-usd_c)); item["lbp_opening"]+=Decimal(str(lbp_d-lbp_c))
                continue
            for field,value in (("debit",debit),("credit",credit),("usd_debit",usd_d),("usd_credit",usd_c),("lbp_debit",lbp_d),("lbp_credit",lbp_c)): item[field]+=Decimal(str(value))
        for item in totals.values():
            item["balance"]=item["debit"]-item["credit"]
            item["usd_balance"]=item["usd_debit"]-item["usd_credit"]
            item["lbp_balance"]=item["lbp_debit"]-item["lbp_credit"]
            item["closing_balance"]=item["opening"]+item["balance"]
            item["usd_closing_balance"]=item["usd_opening"]+item["usd_balance"]
            item["lbp_closing_balance"]=item["lbp_opening"]+item["lbp_balance"]
            for field,value in list(item.items()):
                if isinstance(value,Decimal): item[field]=float(value)
        return list(totals.values())

    def general_ledger(self, account_code=None, from_date=None, to_date=None, currency=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        rows=self.journal(None,to_date,currency,account_code=account_code)
        opening={}; items=[]; balances={}
        for row in rows:
            normalized=str(row["entry_date"] or "")
            try: normalized=datetime.strptime(normalized,"%d-%m-%Y").strftime("%Y-%m-%d")
            except ValueError: pass
            key=(row["currency"],row["account_code"])
            movement=Decimal(str(row["debit"] or 0))-Decimal(str(row["credit"] or 0))
            if from_date and normalized<from_date:
                opening[key]=opening.get(key,Decimal("0"))+movement; continue
            balances[key]=balances.get(key,opening.get(key,Decimal("0")))+movement
            row["balance"]=float(balances[key]); items.append(row)
        return {"opening":[{"currency":k[0],"account_code":k[1],"amount":float(v)} for k,v in opening.items()],"items":items}

    def balance_sheet(self, to_date=None, currency=None):
        to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        conditions=["a.type IN ('asset','liability','equity')"]
        parameters=[]
        normalized_date="""CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        if to_date: conditions.append(f"{normalized_date}<=?"); parameters.append(to_date)
        if currency: conditions.append("e.currency=?"); parameters.append(currency)
        with self.connect() as db:
            rows=[dict(row) for row in db.execute(f"""SELECT e.currency,a.code,a.name_en,a.type,
                DSUM(CAST(j.debit AS REAL)) debit,DSUM(CAST(j.credit AS REAL)) credit,
                DSUM(CAST(j.debit AS REAL)-CAST(j.credit AS REAL)) balance
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                WHERE {' AND '.join(conditions)} GROUP BY e.currency,a.id ORDER BY e.currency,a.type,a.code""",parameters)]
        pnl=self.profit_and_loss(None,to_date,currency)
        current_results={}
        for row in pnl:
            current_results.setdefault(row["currency"],Decimal("0"))
            amount=Decimal(str(row["amount"] or 0))
            current_results[row["currency"]]+=amount if row["type"]=="income" else -amount
        for code,result in current_results.items():
            if result:
                rows.append({"currency":code,"code":"13","name_en":"Current Year Net Result","type":"equity",
                    "debit":float(-result) if result<0 else 0.0,"credit":float(result) if result>0 else 0.0,"balance":float(-result)})
        return rows

    def cash_flow(self,from_date=None,to_date=None,currency=None):
        """Cash and bank movements (classes 51 / 53) by origin. 2.9.51: summed by the database itself - every line
        counts (the report used to read at most 50,000 journal lines and silently miss the rest)."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        normalized_date="""CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"""
        conditions=["(a.code LIKE '51%' OR a.code LIKE '53%')"]; parameters=[]
        if from_date: conditions.append(f"{normalized_date}>=?"); parameters.append(from_date)
        if to_date: conditions.append(f"{normalized_date}<=?"); parameters.append(to_date)
        if currency: conditions.append("e.currency=?"); parameters.append(currency)
        with self.connect() as db:
            lines=db.execute(f"""SELECT e.currency,COALESCE(e.source_type,'other') source,
                DSUM(CASE WHEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL)>0 THEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL) ELSE 0 END) inflow,
                DSUM(CASE WHEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL)<0 THEN CAST(j.credit AS REAL)-CAST(j.debit AS REAL) ELSE 0 END) outflow
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                WHERE {' AND '.join(conditions)} GROUP BY e.currency,COALESCE(e.source_type,'other')""",parameters).fetchall()
        grouped={}
        for line in lines:
            category={"invoice":"Operating - Invoices","expense":"Operating - Expenses","payroll":"Operating - Payroll",
                "payment":"Operating - Receipts / Payments","opening":"Opening Balance","year_close":"Year Closing"}.get(line["source"],"Other Cash Movement")
            item=grouped.setdefault((line["currency"],category),{"currency":line["currency"],"category":category,"inflow":Decimal("0"),"outflow":Decimal("0"),"net":Decimal("0")})
            item["inflow"]+=Decimal(str(line["inflow"] or 0)); item["outflow"]+=Decimal(str(line["outflow"] or 0)); item["net"]=item["inflow"]-item["outflow"]
        for item in grouped.values():  # 2.9.97: exact sums, numbers at the end
            for field in ("inflow","outflow","net"): item[field]=float(item[field])
        return sorted(grouped.values(),key=lambda row:(row["currency"],row["category"]))

    def aging_report(self,as_of_date=None,kind=None,currency=None):
        as_of=datetime.now().date()
        if as_of_date:
            parsed=False
            for pattern in ("%Y-%m-%d","%d-%m-%Y"):
                try: as_of=datetime.strptime(as_of_date,pattern).date(); parsed=True; break
                except ValueError: pass
            if not parsed: raise ValueError("As of Date must be DD-MM-YYYY")
        invoice_day="CASE WHEN i.invoice_date GLOB '??-??-????' THEN substr(i.invoice_date,7,4)||'-'||substr(i.invoice_date,4,2)||'-'||substr(i.invoice_date,1,2) ELSE i.invoice_date END"
        payment_day="CASE WHEN x.payment_date GLOB '??-??-????' THEN substr(x.payment_date,7,4)||'-'||substr(x.payment_date,4,2)||'-'||substr(x.payment_date,1,2) ELSE x.payment_date END"
        conditions=["i.status='posted'",f"{invoice_day}<=?"] ; parameters=[as_of.isoformat(),as_of.isoformat()]
        if kind in ("sale","purchase"): conditions.append("i.kind=?"); parameters.append(kind)
        if currency: conditions.append("i.currency=?"); parameters.append(currency)
        with self.connect() as db:
            rows=[dict(row) for row in db.execute(f"""SELECT i.id,i.invoice_number,i.invoice_date,i.due_date,i.kind,i.currency,p.name party_name,p.account_number,
                (CASE WHEN i.doc_subtype='credit_note' THEN -1 ELSE 1 END)*(CAST(i.total AS REAL)-CAST(COALESCE(i.amount_paid,'0') AS REAL)-
                (SELECT COALESCE(DSUM(CAST(a.amount AS REAL)),0) FROM payment_allocations a JOIN payments x ON x.id=a.payment_id
                 WHERE a.invoice_id=i.id AND {payment_day}<=?)) outstanding FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
                WHERE {' AND '.join(conditions)} ORDER BY p.name,i.due_date,i.invoice_date""",parameters)]
        rows=self._apply_unallocated(rows,as_of.isoformat(),kind,currency)  # 2.9.80
        rows=[row for row in rows if abs(row["outstanding"])>=0.01]
        for row in rows:
            raw=row.get("due_date") or row.get("invoice_date"); due=as_of
            for pattern in ("%d-%m-%Y","%Y-%m-%d"):
                try: due=datetime.strptime(str(raw),pattern).date(); break
                except ValueError: pass
            days=max(0,(as_of-due).days); row["days_overdue"]=days
            row["bucket"]="Current" if days==0 else "1-30" if days<=30 else "31-60" if days<=60 else "61-90" if days<=90 else "Over 90"
        return rows

    def _apply_unallocated(self,rows,as_of,kind=None,currency=None):
        """2.9.80: receipts / payments not allocated to an invoice and open credit notes settle the oldest invoices of the
        same customer / supplier and currency (as in the ledger); what is left is shown as one 'On account' line,
        so the ageing of each party agrees with its account balance (invoices and receipts / payments)."""
        payment_day="CASE WHEN x.payment_date GLOB '??-??-????' THEN substr(x.payment_date,7,4)||'-'||substr(x.payment_date,4,2)||'-'||substr(x.payment_date,1,2) ELSE x.payment_date END"
        with self.connect() as db:
            payments=[dict(r) for r in db.execute(f"""SELECT x.party_id,x.kind,x.currency,p.name party_name,p.account_number,
                CAST(x.amount AS REAL)+CAST(COALESCE(x.exchange_difference,'0') AS REAL)-COALESCE((SELECT DSUM(CAST(a.amount AS REAL)) FROM payment_allocations a WHERE a.payment_id=x.id),0) free
                FROM payments x LEFT JOIN parties p ON p.id=x.party_id WHERE {payment_day}<=?""",(as_of,))]
            party_of={r["id"]:r["party_id"] for r in db.execute("SELECT id,party_id FROM invoices")}
        credits={}  # (party_id, kind, currency) -> amount that settles invoices
        for pay in payments:
            invoice_kind="sale" if pay["kind"]=="customer_receipt" else "purchase"
            if (kind and invoice_kind!=kind) or (currency and pay["currency"]!=currency) or abs(pay["free"] or 0)<0.005: continue
            key=(pay["party_id"],invoice_kind,pay["currency"])
            entry=credits.setdefault(key,{"amount":0.0,"party_name":pay["party_name"],"account_number":pay["account_number"]})
            entry["amount"]+=float(pay["free"])
        def day(row):
            for value in (row.get("due_date"),row.get("invoice_date")):
                try: return _soft_iso(value) or ""
                except Exception: continue
            return ""
        def key_of(row): return (party_of.get(row["id"]),row["kind"],row["currency"])
        invoices=sorted([row for row in rows if row["outstanding"]>0],key=day)  # oldest first
        notes=sorted([row for row in rows if row["outstanding"]<0],key=day)
        def settle(key,amount):
            for row in invoices:
                if amount<=0.005: break
                if key_of(row)!=key or row["outstanding"]<=0.005: continue
                used=min(amount,row["outstanding"]); row["outstanding"]=round(row["outstanding"]-used,2); amount-=used
            return amount
        for note in notes:  # an open credit note settles the oldest invoices; what is left stays on the note
            note["outstanding"]=-round(settle(key_of(note),-note["outstanding"]),2)
        kept=list(rows)
        for (party_id,invoice_kind,code),entry in credits.items():  # receipts / payments not allocated
            left=settle((party_id,invoice_kind,code),entry["amount"]) if entry["amount"]>0 else entry["amount"]
            if abs(left)<0.005: continue
            kept.append({"id":None,"invoice_number":"On account (not allocated)","invoice_date":as_of,"due_date":as_of,"kind":invoice_kind,"currency":code,
                         "party_name":entry["party_name"],"account_number":entry["account_number"],"outstanding":-round(left,2)})
        return kept

    def comparative_reports(self,from_date,to_date,currency=None,prior_db=None):
        """Current period against the same period one year earlier. 2.9.52: the prior year is read from its own
        fiscal-year file when the company keeps one file per year (it used to show 0 for every account)."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        start=datetime.strptime(from_date,"%Y-%m-%d"); end=datetime.strptime(to_date,"%Y-%m-%d")
        try: prior_start=start.replace(year=start.year-1).strftime("%Y-%m-%d")
        except ValueError: prior_start=start.replace(year=start.year-1,day=28).strftime("%Y-%m-%d")
        try: prior_end=end.replace(year=end.year-1).strftime("%Y-%m-%d")
        except ValueError: prior_end=end.replace(year=end.year-1,day=28).strftime("%Y-%m-%d")
        current=self.profit_and_loss(from_date,to_date,currency); prior=self.profit_and_loss(prior_start,prior_end,currency)
        if prior_db is not None and prior_db is not self and not prior:
            prior=prior_db.profit_and_loss(prior_start,prior_end,currency)
        combined={}
        for label,rows in (("current",current),("prior",prior)):
            for row in rows:
                key=(row["currency"],row["code"],row["name_en"],row["type"]); item=combined.setdefault(key,{"currency":row["currency"],"code":row["code"],
                        "name_en":row["name_en"],"type":row["type"],"current":0.0,"prior":0.0,"variance":0.0})
                item[label]+=float(row["amount"] or 0)
        for row in combined.values(): row["variance"]=row["current"]-row["prior"]
        return {"from_date":from_date,"to_date":to_date,"prior_from":prior_start,"prior_to":prior_end,"items":sorted(combined.values(),key=lambda row:(row["currency"],row["code"]))}

    def vat_report(self, from_date=None, to_date=None, currency=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        normalized="""CASE WHEN invoice_date GLOB '??-??-????'
            THEN substr(invoice_date,7,4)||'-'||substr(invoice_date,4,2)||'-'||substr(invoice_date,1,2)
            ELSE invoice_date END"""
        conditions=["status NOT IN ('cancelled','deleted')"]; parameters=[]
        if from_date: conditions.append(f"{normalized}>=?"); parameters.append(from_date)
        if to_date: conditions.append(f"{normalized}<=?"); parameters.append(to_date)
        if currency: conditions.append("currency=?"); parameters.append(currency)
        with self.connect() as db:
            invoice_rows=[dict(row) for row in db.execute(f"""SELECT currency,kind,COUNT(*) invoices,
                DSUM(CAST(subtotal AS REAL)) subtotal,DSUM(CAST(vat AS REAL)) vat,DSUM(CAST(total AS REAL)) total
                FROM invoices WHERE {' AND '.join(conditions)} GROUP BY currency,kind ORDER BY currency,kind""",parameters)]
            expense_conditions=[]; expense_parameters=[]
            expense_date="""CASE WHEN expense_date GLOB '??-??-????'
                THEN substr(expense_date,7,4)||'-'||substr(expense_date,4,2)||'-'||substr(expense_date,1,2)
                ELSE expense_date END"""
            if from_date: expense_conditions.append(f"{expense_date}>=?"); expense_parameters.append(from_date)
            if to_date: expense_conditions.append(f"{expense_date}<=?"); expense_parameters.append(to_date)
            if currency: expense_conditions.append("currency=?"); expense_parameters.append(currency)
            where=" WHERE "+" AND ".join(expense_conditions) if expense_conditions else ""
            expenses=[dict(row) for row in db.execute(f"""SELECT currency,COUNT(*) invoices,DSUM(CAST(subtotal AS REAL)) subtotal,
                DSUM(CAST(vat AS REAL)) vat,DSUM(CAST(total AS REAL)) total FROM expenses{where} GROUP BY currency""",expense_parameters)]
        for row in expenses: invoice_rows.append({**row,"kind":"expense"})
        totals={}
        for row in invoice_rows:
            totals.setdefault(row["currency"],{"sales_vat":0.0,"purchase_vat":0.0,"expense_vat":0.0})
            key="sales_vat" if row["kind"]=="sale" else "purchase_vat" if row["kind"]=="purchase" else "expense_vat"
            totals[row["currency"]][key]+=float(row["vat"] or 0)
        summary=[]
        for code,value in totals.items():
            recoverable=value["purchase_vat"]+value["expense_vat"]
            summary.append({"currency":code,**value,"recoverable_vat":recoverable,"vat_payable":value["sales_vat"]-recoverable})
        return {"items":invoice_rows,"summary":summary}
