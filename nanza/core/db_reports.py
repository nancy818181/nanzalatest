"""Chart of accounts and the reports: journal, trial balance, ledger, balance sheet, P&L, cash flow, ageing, VAT report, dashboards, fiscal years.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from ReportsStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, json, utcnow
)
from database_common import _soft_iso  # noqa: F401
from settlements import posted_payment_sql, invoice_kind as payment_invoice_kind, settlement_sign

# 2.9.132 (H-01): the statements read POSTED entries only - the same rule as the trial balance (a draft voucher or the
# entry of an invoice in Review is not in the books yet; a cancelled invoice keeps its posted entry and its reversal).
POSTED_ONLY = ("(COALESCE(e.posting_status,'posted')='posted' AND (e.source_type!='invoice' OR EXISTS("
               "SELECT 1 FROM invoices pi WHERE pi.id=e.source_id AND pi.status IN ('posted','cancelled'))))")


def _present_class4_by_sign(rows):
    """2.9.134 (D5, owner approved): third-party accounts (class 4) are shown as an asset when their balance is a debit and as a
    liability when it is a credit, per account and currency - as the IFRS statements already group them (financial_statements.default_group).
    Provisions on third parties (49) stay with the receivables they correct; an equity row or a zero balance keeps its stored type.
    Only the section changes: no amount does, so assets = liabilities + equity is unaffected."""
    for row in rows:
        code = str(row.get("code") or "")
        if not code.startswith("4") or code.startswith("49") or row.get("type") not in ("asset", "liability"): continue
        balance = Decimal(str(row.get("balance") or 0))
        if balance > 0: row["type"] = "asset"
        elif balance < 0: row["type"] = "liability"
    return rows


def _exact_amount(positive, negative):
    """2.9.133 (MONEY-FLOAT-001): positive - negative worked out as exact Decimals, then turned into a number once.
    Subtracting two floats gave 110.47999999999999 instead of 110.48; both inputs are already exact to 6 decimals (DSUM)."""
    return float(Decimal(str(positive or 0)) - Decimal(str(negative or 0)))


class ReportsStore:
    # ---------------------------------------------------------------- 2.9.80: every currency converted (planning tools)
    def _converted_lines(self, currency, from_date=None, to_date=None, without_opening=False,
                         department_id=None, project_id=None):
        """Posted journal lines with their value in `currency` (USD, LBP or any currency of the company), whatever
        the currency they were entered in. Closing entries are left out."""
        import ledger_reports
        options = {"first_column": currency, "second_column": "none", "posting_status": "posted", "without_closing": True, "exclude_closing": True}
        if without_opening: options["without_opening"] = True
        if department_id is not None: options["department_id"] = department_id
        if project_id is not None: options["project_id"] = project_id
        start = _soft_iso(from_date) or "0000-01-01"; end = _soft_iso(to_date) or "9999-12-31"
        return [row for row in ledger_reports._load_lines(self, options) if start <= row["iso_date"] <= end]

    def profit_and_loss_converted(self, from_date=None, to_date=None, currency="USD",
                                  department_id=None, project_id=None):
        """The P&L of every transaction (LBP payroll, EUR expenses ...) in one currency: same rows as profit_and_loss."""
        totals = {}
        for row in self._converted_lines(currency, from_date, to_date, department_id=department_id,
                                         project_id=project_id):
            if row["account_type"] not in ("income", "expense"): continue
            value = row["signed"].get(currency) or Decimal("0")
            item = totals.setdefault(row["code"], {"currency": currency, "code": row["code"], "name_en": row["name_en"], "type": row["account_type"], "debit": Decimal("0"), "credit": Decimal("0")})
            if value >= 0: item["debit"] += Decimal(str(value))  # 2.9.97: exact, turned into numbers once below
            else: item["credit"] -= Decimal(str(value))
        for item in totals.values(): item["debit"], item["credit"] = float(item["debit"]), float(item["credit"])
        rows = sorted(totals.values(), key=lambda r: r["code"])
        for row in rows: row["amount"] = _exact_amount(row["credit"], row["debit"]) if row["type"] == "income" else _exact_amount(row["debit"], row["credit"])
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

    def cash_flow_monthly(self, from_date=None, to_date=None, currency=None, convert=False):
        """Monthly cash movements by currency and origin, excluding opening and closing entries."""
        from_date = _soft_iso(from_date); to_date = _soft_iso(to_date)
        categories = {"invoice": "Operating - Invoices", "expense": "Operating - Expenses",
                      "payroll": "Operating - Payroll", "payment": "Operating - Receipts / Payments"}
        grouped = {}
        if convert and currency:
            lines = self._converted_lines(currency, from_date, to_date, without_opening=True)
            for row in lines:
                digits = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())
                if not digits.startswith(("51", "53")) or row.get("source_type") in ("opening", "year_close"):
                    continue
                value = float(row["signed"].get(currency) or 0)
                key = (row["iso_date"][:7], currency, row.get("source_type") or "other")
                item = grouped.setdefault(key, {"inflow": 0.0, "outflow": 0.0})
                if value > 0: item["inflow"] += value
                else: item["outflow"] -= value
        else:
            normalized_date = """CASE WHEN e.entry_date GLOB '??-??-????'
                THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
                ELSE e.entry_date END"""
            conditions = ["(a.code LIKE '51%' OR a.code LIKE '53%')",
                          "COALESCE(e.source_type,'other') NOT IN ('opening','year_close')", POSTED_ONLY]
            parameters = []
            if from_date: conditions.append(f"{normalized_date}>=?"); parameters.append(from_date)
            if to_date: conditions.append(f"{normalized_date}<=?"); parameters.append(to_date)
            if currency: conditions.append("e.currency=?"); parameters.append(currency)
            with self.connect() as db:
                rows = db.execute(f"""SELECT substr({normalized_date},1,7) month,e.currency,
                    COALESCE(e.source_type,'other') source,
                    DSUM(CASE WHEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL)>0 THEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL) ELSE 0 END) inflow,
                    DSUM(CASE WHEN CAST(j.debit AS REAL)-CAST(j.credit AS REAL)<0 THEN CAST(j.credit AS REAL)-CAST(j.debit AS REAL) ELSE 0 END) outflow
                    FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                    WHERE {' AND '.join(conditions)} GROUP BY month,e.currency,source ORDER BY month,e.currency,source""", parameters)
                for row in rows:
                    grouped[(row["month"], row["currency"], row["source"])] = {
                        "inflow": float(row["inflow"] or 0), "outflow": float(row["outflow"] or 0)}
        result = []
        for (month, code, source), values in sorted(grouped.items()):
            result.append({"month": month, "currency": code, "source": source,
                           "category": categories.get(source, "Other Cash Movement"),
                           "inflow": round(values["inflow"], 2), "outflow": round(values["outflow"], 2),
                           "net": round(values["inflow"] - values["outflow"], 2)})
        return result

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
        return _present_class4_by_sign(sorted(totals.values(), key=lambda r: r["code"]))

    def profit_and_loss(self, from_date=None, to_date=None, currency=None, department_id=None, project_id=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        # The year-end closing brings 6 & 7 to zero; the P&L must show the year before closing.
        conditions = ["a.type IN ('income','expense')", "NOT (e.source_type='year_close' OR (e.voucher_type='05' AND e.description LIKE 'CLOSING 6&7 - %'))", POSTED_ONLY]
        parameters = []
        normalized_date = """CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        if from_date: conditions.append(f"{normalized_date}>=?"); parameters.append(from_date)
        if to_date: conditions.append(f"{normalized_date}<=?"); parameters.append(to_date)
        if currency: conditions.append("e.currency=?"); parameters.append(currency)
        if department_id is not None: conditions.append("e.department_id=?"); parameters.append(int(department_id))
        if project_id is not None: conditions.append("e.project_id=?"); parameters.append(int(project_id))
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(f"""SELECT e.currency,a.code,a.name_en,a.type,
                DSUM(CAST(j.debit AS REAL)) debit,DSUM(CAST(j.credit AS REAL)) credit
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id JOIN accounts a ON a.id=j.account_id
                WHERE {' AND '.join(conditions)} GROUP BY e.currency,a.id ORDER BY e.currency,a.code""", parameters)]
        for row in rows:
            row["amount"] = _exact_amount(row["credit"], row["debit"]) if row["type"] == "income" else _exact_amount(row["debit"], row["credit"])
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
            # 2.9.119: the open invoices brought in by Start with Nanza are not sales / purchases of the year (still receivables / payables)
            has_source={row[1] for row in db.execute("PRAGMA table_info(invoices)")} >= {"source_file"}
            sales_amount="CASE WHEN COALESCE(source_file,'')='Opening balances' THEN 0 ELSE CAST(subtotal AS REAL) END" if has_source else "CAST(subtotal AS REAL)"
            not_opening=" AND COALESCE(source_file,'')<>'Opening balances'" if has_source else ""
            invoice_rows=db.execute(f"""SELECT kind,currency,
                DSUM({sales_amount}) subtotal,
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
            monthly=[dict(row) for row in db.execute(f"""SELECT substr(CASE WHEN invoice_date GLOB '??-??-????' THEN substr(invoice_date,7,4)||'-'||substr(invoice_date,4,2)||'-'||substr(invoice_date,1,2) ELSE invoice_date END,1,7) month,
                currency,kind,DSUM(CAST(subtotal AS REAL)) amount FROM invoices WHERE status NOT IN ('cancelled','deleted')
                {not_opening} GROUP BY month,currency,kind ORDER BY month""")]  # 2.9.119: not the open invoices brought in
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
                a.active is_active,
                NOT EXISTS (SELECT 1 FROM accounts c WHERE c.parent_id=a.id) is_posting,
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
        name_ar=str(item.get("name_ar") or "").strip()
        name_fr=str(item.get("name_fr") or "").strip()
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
            db.execute("INSERT INTO accounts(code,name_en,name_ar,name_fr,type,parent_id) VALUES(?,?,?,?,?,?)",
                       (code,name,name_ar or None,name_fr or None,account_type,parent_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                (user_id,"save","account",json.dumps({"code":code,"name":name,"name_ar":name_ar,"name_fr":name_fr}),utcnow()))
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
                FROM invoices WHERE status NOT IN ('cancelled','deleted') AND COALESCE(source_file,'')<>'Opening balances' GROUP BY kind,currency""").fetchall()
            return [dict(r) for r in rows]

    def journal(self, from_date=None, to_date=None, currency=None, limit=None, branch_id=None, entry_number=None, account_code=None, source_type=None,
                posted_only=False, running_balance=True):
        """Return journal lines with a running balance per account and currency.
        2.9.51: no line limit any more (5,000 lines used to hide later entries from the journal, the general ledger and
        'open transaction'); one entry, one account or one kind of entry can be asked for directly."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        conditions = []
        parameters = []
        if entry_number: conditions.append("e.entry_number=?"); parameters.append(str(entry_number))
        if account_code: conditions.append("a.code=?"); parameters.append(str(account_code))
        if source_type: conditions.append("e.source_type=?"); parameters.append(str(source_type))
        if posted_only: conditions.append(POSTED_ONLY)  # 2.9.132 (H-01): the general ledger; the journal list itself still shows drafts
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
                COALESCE(p.name,'') party_name,COALESCE(j.description,'') line_description,i.invoice_number,CAST(j.debit AS REAL) debit,CAST(j.credit AS REAL) credit,j.id line_id,
                COALESCE(pr.code,'') project_code,COALESCE(dp.code,'') department_code
                FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
                JOIN accounts a ON a.id=j.account_id LEFT JOIN parties p ON p.id=j.party_id LEFT JOIN branches b ON b.id=e.branch_id
                LEFT JOIN projects pr ON pr.id=j.project_id LEFT JOIN departments dp ON dp.id=j.department_id
                LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                {where_clause}
                ORDER BY {normalized_date},e.id,j.id LIMIT ?""", parameters)]
        balances = {}
        for row in rows:
            row.pop("line_id", None)
            if not running_balance: continue  # 2.9.132 (performance): the general ledger computes its own balances
            key = (row["currency"], row["account_code"])
            balances[key] = balances.get(key, Decimal("0")) + Decimal(str(row["debit"] or 0)) - Decimal(str(row["credit"] or 0))
            row["balance"] = float(balances[key])
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
        if posting_status=="posted": conditions.append("(e.posting_status='posted' AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')))")  # cancelled invoices retain their posted entry and reversal
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
        # 2.9.132 (performance): a day's ISO form and a (currency, day) rate are worked out once per report, not once per row;
        # the values are the same (same strptime rule, same _converted_amount factor, same Decimal products)
        days={}; factors={}
        def iso_day(text):
            if text not in days:
                try: days[text]=datetime.strptime(text,"%d-%m-%Y").strftime("%Y-%m-%d")
                except ValueError: days[text]=text
            return days[text]
        def convert(amount,currency,target,day):
            key=(currency,target,day)
            if key not in factors: factors[key]=self._converted_amount(Decimal("1"),currency,target,day)
            return amount if str(currency or "USD").upper()==target else amount*factors[key]
        for row in raw:
            key=(row["code"],row["name_en"],row["currency"])
            # 2.9.97: added as exact Decimals, turned into numbers once at the end (floats drifted: 600.0000000000002)
            item=totals.get(key)
            if item is None:  # 2.9.132 (performance): the 15 zero totals are made once per account, not once per row
                item=totals[key]={"code":row["code"],"name_en":row["name_en"],"currency":row["currency"],
                    **{field:Decimal("0") for field in ("opening","debit","credit","balance","closing_balance","usd_opening","usd_debit","usd_credit",
                       "usd_balance","usd_closing_balance","lbp_opening","lbp_debit","lbp_credit","lbp_balance","lbp_closing_balance")}}
            date=iso_day(str(row["entry_date"] or ""))
            debit=Decimal(str(row["debit"] or 0)); credit=Decimal(str(row["credit"] or 0))
            usd_d=convert(debit,row["currency"],"USD",date); usd_c=convert(credit,row["currency"],"USD",date)
            lbp_d=convert(debit,row["currency"],"LBP",date); lbp_c=convert(credit,row["currency"],"LBP",date)
            if from_date and date<from_date:
                item["opening"]+=debit-credit; item["usd_opening"]+=usd_d-usd_c; item["lbp_opening"]+=lbp_d-lbp_c  # already exact Decimals
                continue
            for field,value in (("debit",debit),("credit",credit),("usd_debit",usd_d),("usd_credit",usd_c),("lbp_debit",lbp_d),("lbp_credit",lbp_c)): item[field]+=value
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
        rows=self.journal(None,to_date,currency,account_code=account_code,posted_only=True,running_balance=False)
        opening={}; items=[]; balances={}; days={}  # 2.9.132 (performance): each day parsed once
        for row in rows:
            normalized=str(row["entry_date"] or "")
            if normalized not in days:
                try: days[normalized]=datetime.strptime(normalized,"%d-%m-%Y").strftime("%Y-%m-%d")
                except ValueError: days[normalized]=normalized
            normalized=days[normalized]
            key=(row["currency"],row["account_code"])
            movement=Decimal(str(row["debit"] or 0))-Decimal(str(row["credit"] or 0))
            if from_date and normalized<from_date:
                opening[key]=opening.get(key,Decimal("0"))+movement; continue
            balances[key]=balances.get(key,opening.get(key,Decimal("0")))+movement
            row["balance"]=float(balances[key]); items.append(row)
        return {"opening":[{"currency":k[0],"account_code":k[1],"amount":float(v)} for k,v in opening.items()],"items":items}

    def balance_sheet(self, to_date=None, currency=None):
        to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        conditions=["a.type IN ('asset','liability','equity')",POSTED_ONLY]
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
        return _present_class4_by_sign(rows)

    def cash_flow(self,from_date=None,to_date=None,currency=None):
        """Cash and bank movements (classes 51 / 53) by origin. 2.9.51: summed by the database itself - every line
        counts (the report used to read at most 50,000 journal lines and silently miss the rest)."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        normalized_date="""CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"""
        conditions=["(a.code LIKE '51%' OR a.code LIKE '53%')",POSTED_ONLY]; parameters=[]
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
            rows=[dict(row) for row in db.execute(f"""SELECT i.id,i.party_id,i.invoice_number,i.invoice_date,i.due_date,i.kind,i.currency,p.name party_name,p.account_number,
                (CASE WHEN i.doc_subtype='credit_note' THEN -1 ELSE 1 END)*(CAST(i.total AS REAL)-CAST(COALESCE(i.amount_paid,'0') AS REAL)-
                (SELECT COALESCE(DSUM(CAST(a.amount AS REAL)),0) FROM payment_allocations a JOIN payments x ON x.id=a.payment_id
                 WHERE a.invoice_id=i.id AND {payment_day}<=? AND {posted_payment_sql()})) outstanding FROM invoices i LEFT JOIN parties p ON p.id=i.party_id
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
            payments=[dict(r) for r in db.execute(f"""SELECT x.party_id,x.kind,x.currency,x.party_account,p.kind party_kind,p.name party_name,p.account_number,
                CAST(x.amount AS REAL)+CAST(COALESCE(x.exchange_difference,'0') AS REAL)-COALESCE((SELECT DSUM(CAST(a.amount AS REAL)) FROM payment_allocations a WHERE a.payment_id=x.id),0) free
                FROM payments x LEFT JOIN parties p ON p.id=x.party_id WHERE {payment_day}<=? AND {posted_payment_sql()}""",(as_of,))]
            party_of={r["id"]:r["party_id"] for r in rows}
        credits={}  # (party_id, kind, currency) -> amount that settles invoices
        for pay in payments:
            target_kind=payment_invoice_kind(pay)
            if (kind and target_kind!=kind) or (currency and pay["currency"]!=currency) or abs(pay["free"] or 0)<0.005: continue
            key=(pay["party_id"],target_kind,pay["currency"])
            entry=credits.setdefault(key,{"amount":0.0,"party_name":pay["party_name"],"account_number":pay["account_number"]})
            entry["amount"]+=float(pay["free"])*settlement_sign(pay,target_kind)
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

    def _native_trial_balance(self,from_date,to_date,currency=None):
        """2.9.126: balances in each line's own currency, as exact Decimals from the stored text (no exchange rate is
        needed, so a missing EUR rate cannot stop a USD comparison; no REAL cast). Same posted-entries rule as the
        trial balance. A date that cannot be read stops the report with the entry number."""
        from database_common import iso_date
        normalized="""CASE WHEN e.entry_date GLOB '??-??-????'
            THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
            ELSE e.entry_date END"""
        conditions=["(e.posting_status='posted' AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')))"]; parameters=[]
        if currency: conditions.append("e.currency=?"); parameters.append(currency)
        totals={}
        with self.connect() as db:
            for row in db.execute(f"""SELECT a.code,a.name_en,e.currency,e.entry_number,{normalized} day,j.debit,j.credit
                    FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
                    LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
                    WHERE {' AND '.join(conditions)}""",parameters):
                try: day=iso_date(row["day"])
                except ValueError as exc:
                    raise ValueError(f"Invalid date for entry {row['entry_number']}: correct it before reporting") from exc
                if day>to_date: continue
                try: movement=Decimal(str(row["debit"] or 0))-Decimal(str(row["credit"] or 0))
                except ArithmeticError as exc: raise ValueError(f"Invalid amount for entry {row['entry_number']}") from exc
                if not movement.is_finite(): raise ValueError(f"Invalid amount for entry {row['entry_number']}")
                item=totals.setdefault((row["code"],row["currency"]),{"code":row["code"],"name_en":row["name_en"],"currency":row["currency"],
                    "opening":Decimal("0"),"debit":Decimal("0"),"credit":Decimal("0")})
                if day<from_date: item["opening"]+=movement
                else:
                    item["debit"]+=Decimal(str(row["debit"] or 0)); item["credit"]+=Decimal(str(row["credit"] or 0))
        for item in totals.values(): item["closing_balance"]=item["opening"]+item["debit"]-item["credit"]
        return list(totals.values())

    def comparative_trial_balance(self,from_date,to_date,currency=None,prior_db=None):
        """2.9.126: trial balance of the period against the same period one year earlier, account by account:
        opening, movement and closing (closing = every posted movement up to the end date, opening balances included).
        The prior year is read from its own fiscal-year file when the company keeps one file per year."""
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)
        start=datetime.strptime(from_date,"%Y-%m-%d"); end=datetime.strptime(to_date,"%Y-%m-%d")
        if start>end: raise ValueError("From Date cannot be after To Date")
        def year_before(day):
            try: return day.replace(year=day.year-1)
            except ValueError: return day.replace(year=day.year-1,day=28)  # 29 February
        prior_start=year_before(start).strftime("%Y-%m-%d"); prior_end=year_before(end).strftime("%Y-%m-%d")
        current=self._native_trial_balance(from_date,to_date,currency)
        # One file per year: the prior-year file is THE source of the prior year (not a fallback when this file is empty).
        if prior_db is not None and prior_db is not self:
            prior=prior_db._native_trial_balance(prior_start,prior_end,currency); source="prior-year file"
        else:
            prior=self._native_trial_balance(prior_start,prior_end,currency); source="this file"
        prior_available=bool(prior)
        combined={}
        fields=("opening","movement","closing")
        for label,items in (("current",current),("prior",prior)):
            for r in items:
                key=(r["currency"],r["code"])
                item=combined.setdefault(key,{"currency":r["currency"],"code":r["code"],"name_en":r["name_en"],
                    **{f"{period}_{field}":Decimal("0") for period in ("current","prior") for field in fields}})
                if label=="current" or not item["name_en"]: item["name_en"]=r["name_en"]
                item[f"{label}_opening"]+=r["opening"]
                item[f"{label}_movement"]+=r["debit"]-r["credit"]
                item[f"{label}_closing"]+=r["closing_balance"]
        items=[]
        for item in combined.values():
            item["variance"]=item["current_closing"]-item["prior_closing"]  # signed: debit balances positive, credit negative
            if all(item[f"{p}_{f}"]==0 for p in ("current","prior") for f in fields): continue
            items.append(item)
        items.sort(key=lambda r:(r["currency"],r["code"]))
        totals={}
        for r in items:
            t=totals.setdefault(r["currency"],{k:Decimal("0") for k in ("current_closing","prior_closing","variance")})
            for k in t: t[k]+=r[k]
        # exact Decimals here; the API turns them into numbers once (json_ready logs any amount that would lose a cent)
        warning="" if prior_available else (f"Prior period {prior_start} to {prior_end} is unavailable (no posted entries in this file"
                                             +(" or in the prior-year file" if prior_db is not None and prior_db is not self else "")+"): prior columns are blank, not zero balances")
        return {"from_date":from_date,"to_date":to_date,"prior_from":prior_start,"prior_to":prior_end,"prior_available":prior_available,
                "prior_source":source if prior_available else "","warning":warning,"items":items,"totals":totals}

    def vat_report(self, from_date=None, to_date=None, currency=None):
        from_date=_soft_iso(from_date); to_date=_soft_iso(to_date)  # 2.9.63: DD-MM-YYYY or YYYY-MM-DD
        normalized="""CASE WHEN invoice_date GLOB '??-??-????'
            THEN substr(invoice_date,7,4)||'-'||substr(invoice_date,4,2)||'-'||substr(invoice_date,1,2)
            ELSE invoice_date END"""
        conditions=["status='posted'","COALESCE(source_file,'')<>'Opening balances'"]; parameters=[]
        if from_date: conditions.append(f"{normalized}>=?"); parameters.append(from_date)
        if to_date: conditions.append(f"{normalized}<=?"); parameters.append(to_date)
        if currency: conditions.append("currency=?"); parameters.append(currency)
        with self.connect() as db:
            invoice_rows=[dict(row) for row in db.execute(f"""SELECT currency,kind,COUNT(*) invoices,
                DSUM((CASE WHEN doc_subtype='credit_note' THEN -1 ELSE 1 END)*CAST(subtotal AS REAL)) subtotal,
                DSUM((CASE WHEN doc_subtype='credit_note' THEN -1 ELSE 1 END)*CAST(vat AS REAL)) vat,
                DSUM((CASE WHEN doc_subtype='credit_note' THEN -1 ELSE 1 END)*CAST(total AS REAL)) total,
                DSUM(CASE WHEN COALESCE(vat_recoverable,1)=1 AND COALESCE(vat_use,'mixed')<>'exempt'
                     THEN (CASE WHEN doc_subtype='credit_note' THEN -1 ELSE 1 END)*CAST(vat AS REAL) ELSE 0 END) eligible_vat
                FROM invoices WHERE {' AND '.join(conditions)} GROUP BY currency,kind ORDER BY currency,kind""",parameters)]
            expense_conditions=[("EXISTS (SELECT 1 FROM journal_entries ee WHERE ee.source_type='expense' AND ee.source_id=expenses.id "
                                 "AND COALESCE(ee.approval_status,'')<>'review' "
                                 "AND EXISTS (SELECT 1 FROM journal_lines el WHERE el.entry_id=ee.id))")]; expense_parameters=[]
            expense_date="""CASE WHEN expense_date GLOB '??-??-????'
                THEN substr(expense_date,7,4)||'-'||substr(expense_date,4,2)||'-'||substr(expense_date,1,2)
                ELSE expense_date END"""
            if from_date: expense_conditions.append(f"{expense_date}>=?"); expense_parameters.append(from_date)
            if to_date: expense_conditions.append(f"{expense_date}<=?"); expense_parameters.append(to_date)
            if currency: expense_conditions.append("currency=?"); expense_parameters.append(currency)
            where=" WHERE "+" AND ".join(expense_conditions) if expense_conditions else ""
            expenses=[dict(row) for row in db.execute(f"""SELECT currency,COUNT(*) invoices,DSUM(CAST(subtotal AS REAL)) subtotal,
                DSUM(CAST(vat AS REAL)) vat,DSUM(CAST(total AS REAL)) total,
                DSUM(CASE WHEN COALESCE(vat_recoverable,1)=1 AND COALESCE(vat_use,'mixed')<>'exempt'
                     THEN CAST(vat AS REAL) ELSE 0 END) eligible_vat FROM expenses{where} GROUP BY currency""",expense_parameters)]
        for row in expenses: invoice_rows.append({**row,"kind":"expense"})
        totals={}
        for row in invoice_rows:
            totals.setdefault(row["currency"],{"sales_vat":0.0,"purchase_vat":0.0,"expense_vat":0.0})
            key="sales_vat" if row["kind"]=="sale" else "purchase_vat" if row["kind"]=="purchase" else "expense_vat"
            totals[row["currency"]][key]+=float((row["vat"] if key=="sales_vat" else row["eligible_vat"]) or 0)
        summary=[]
        for code,value in totals.items():
            recoverable=value["purchase_vat"]+value["expense_vat"]
            summary.append({"currency":code,**value,"recoverable_vat":recoverable,"vat_payable":value["sales_vat"]-recoverable})
        return {"items":invoice_rows,"summary":summary,"provisional":True,
                "warning":"Document VAT summary only: partial deduction, carry-forward, rounding and settlement adjustments require the quarterly VAT return."}
