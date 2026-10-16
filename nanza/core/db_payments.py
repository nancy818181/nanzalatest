"""Customers / suppliers, branches, payments and receipts, expenses, allocations.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from PaymentsStore."""
from __future__ import annotations
from database_common import atomic  # 2.9.121

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    closing, datetime, Decimal, DEFAULT_LEBANESE_ACCOUNTS, display_date, iso_date, json, Path, sqlite3, tempfile,
    timedelta, utcnow
)
from database_common import _soft_iso  # noqa: F401


class PaymentsStore:
    def list_parties(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,kind,name,tax_number,mof_number,address,contact_number,currency,account_number,due_days,COALESCE(account_category,CASE WHEN kind='customer' THEN 'client' ELSE 'supplier' END) account_category FROM parties ORDER BY name,kind")]

    @staticmethod
    def _invoice_due_date(item, party):
        explicit = str(item.get("due_date") or "").strip()
        if explicit: return display_date(iso_date(explicit))
        days = int(party["due_days"] or 0)
        return display_date((datetime.strptime(iso_date(item["invoice_date"]), "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d"))

    def list_branches(self):
        with self.connect() as db: return [dict(row) for row in db.execute("SELECT id,name,active FROM branches WHERE active=1 ORDER BY name")]

    def save_branch(self,item,user_id):
        name=str(item.get("name") or "").strip()
        if not name: raise ValueError("Branch name is required")
        with self.connect() as db:
            db.execute("INSERT INTO branches(name,active) VALUES(?,1) ON CONFLICT(name) DO UPDATE SET active=1",(name,))
            row=db.execute("SELECT id,name,active FROM branches WHERE name=?",(name,)).fetchone()
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",(user_id,"save","branch",row["id"],json.dumps({"name":name}),utcnow()))
            return dict(row)

    def save_party(self, item, user_id):
        name=str(item.get("name") or "").strip(); category=str(item.get("account_category") or item.get("kind") or "client").strip().lower().replace(" ","_")
        if category not in ("client","customer","supplier","asset_supplier","other_payable","both"): raise ValueError("Invalid client/supplier account type")
        kind="customer" if category in ("client","customer") else "both" if category=="both" else "supplier"
        category="client" if category=="customer" else category
        currency=str(item.get("currency") or "USD").upper(); tax_number=str(item.get("tax_number") or "").strip() or None
        mof_number=str(item.get("mof_number") or "").strip() or None; address=str(item.get("address") or "").strip() or None; contact_number=str(item.get("contact_number") or "").strip() or None
        requested_account=str(item.get("account_number") or "").strip() or None
        try: due_days=int(str(item.get("due_days") if item.get("due_days") not in (None, "") else 0).strip())
        except ValueError as exc: raise ValueError("Due days must be a whole number") from exc
        if not 0 <= due_days <= 3650: raise ValueError("Due days must be between 0 and 3650")
        if requested_account and (not requested_account.isdigit() or len(requested_account) not in (4,
                9)): raise ValueError("Enter the first 4 digits for automatic numbering, or the full 9-digit account number")
        if not name or kind not in ("customer","supplier","both") or currency not in self.currency_codes():
            raise ValueError("Enter a valid name, type, and currency")
        with self.connect() as db:
            if requested_account and len(requested_account)==4:
                prefix=requested_account
                last=db.execute("SELECT account_number FROM parties WHERE account_number LIKE ? AND length(account_number)=9 ORDER BY CAST(account_number AS INTEGER) DESC LIMIT 1",
                        (prefix+"%",)).fetchone()
                next_suffix=(int(last["account_number"][4:])+1) if last else 1
                if next_suffix>99999: raise ValueError(f"No account numbers remain under prefix {prefix}")
                requested_account=f"{prefix}{next_suffix:05d}"
            party_id=item.get("id")
            if party_id:
                if not db.execute("SELECT 1 FROM parties WHERE id=?",(int(party_id),)).fetchone(): raise KeyError(party_id)
                duplicate=db.execute("SELECT 1 FROM parties WHERE kind=? AND name=? AND id<>?",(kind,name,int(party_id))).fetchone()
                if duplicate: raise ValueError("A customer/supplier with this name and type already exists")
                if requested_account and db.execute("SELECT 1 FROM parties WHERE account_number=? AND id<>?",(requested_account,
                        int(party_id))).fetchone(): raise ValueError("Account number already exists")
                db.execute("UPDATE parties SET kind=?,name=?,tax_number=?,mof_number=?,address=?,contact_number=?,currency=?,account_number=COALESCE(?,account_number),account_category=?,due_days=? WHERE id=?",
                        (kind,name,tax_number,mof_number,address,contact_number,currency,requested_account,category,due_days,int(party_id)))
                row=db.execute("SELECT * FROM parties WHERE id=?",(int(party_id),)).fetchone()
            else:
                db.execute("""INSERT INTO parties(kind,name,tax_number,mof_number,address,contact_number,currency,due_days) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(kind,name) DO UPDATE SET tax_number=excluded.tax_number,mof_number=excluded.mof_number,address=excluded.address,contact_number=excluded.contact_number,currency=excluded.currency,due_days=excluded.due_days""",
                    (kind,name,tax_number,mof_number,address,contact_number,currency,due_days))
                row=db.execute("SELECT * FROM parties WHERE kind=? AND name=?",(kind,name)).fetchone()
                db.execute("UPDATE parties SET account_category=? WHERE id=?",(category,row["id"])); row=db.execute("SELECT * FROM parties WHERE id=?",(row["id"],)).fetchone()
                if requested_account:
                    if db.execute("SELECT 1 FROM parties WHERE account_number=? AND id<>?",(requested_account,row["id"])).fetchone(): raise ValueError("Account number already exists")
                    db.execute("UPDATE parties SET account_number=? WHERE id=?",(requested_account,row["id"])); row=db.execute("SELECT * FROM parties WHERE id=?",(row["id"],)).fetchone()
            account_number=self._ensure_party_account(db,row)
            if account_number: row=db.execute("SELECT * FROM parties WHERE id=?",(row["id"],)).fetchone()
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"save","party",row["id"],json.dumps({"name":name,"kind":kind}),utcnow()))
            return dict(row)

    @atomic  # 2.9.121
    def add_payment(self, item, user_id):
        self.require_eur_rate(item.get("currency"), item.get("payment_date"))
        kind=str(item.get("kind") or "").strip(); date=str(item.get("payment_date") or "").strip()
        self._assert_period_open(date)
        if kind not in ("customer_receipt","supplier_payment"): raise ValueError("Invalid payment type")
        try: amount=Decimal(str(item.get("amount") or 0))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Invalid payment amount") from exc
        if amount<=0: raise ValueError("Payment amount must be above zero")
        currency=str(item.get("currency") or "USD").upper()
        defaults=self.default_accounts()  # 2.9.81: Settings > Accounting Settings
        cash_account=str(item.get("cash_account") or defaults["cash"]).strip()
        try: commission=Decimal(str(item.get("bank_commission") or 0))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Invalid bank commission amount") from exc
        if commission<0: raise ValueError("Bank commission cannot be negative")
        try: exchange_diff=Decimal(str(item.get("exchange_difference") or 0))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Invalid exchange difference amount") from exc
        import chart_extra
        # 2.9.79: the bank commission and the exchange gain / loss go to the accounts chosen on the receipt / payment
        # (673900000 / 775100000 / 675100000 when none is chosen).
        def chosen(key, default):
            return str(item.get(key) or default).split(" - ",1)[0].strip() or default
        commission_account=chosen("commission_account",defaults["bank_commission"])
        gain_account=chosen("exchange_gain_account",defaults["exchange_gain"])
        loss_account=chosen("exchange_loss_account",defaults["exchange_loss"])
        if not commission_account.isdigit() or not commission_account.startswith("6"):
            raise ValueError("Bank commission account must be an expense account (class 6), for example 673900000")
        if not gain_account.isdigit() or not gain_account.startswith("7"):
            raise ValueError("Exchange gain account must be a revenue account (class 7), for example 775100000")
        if not loss_account.isdigit() or not loss_account.startswith("6"):
            raise ValueError("Exchange loss account must be an expense account (class 6), for example 675100000")
        party_account=str(item.get("party_account") or (DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"] if kind=="customer_receipt" else DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"])).strip()
        party_id=int(item.get("party_id"))
        with self.connect() as db:
            party=db.execute("SELECT * FROM parties WHERE id=?",(party_id,)).fetchone()
            if not party: raise KeyError(party_id)
            supplier_account=self._ensure_party_account(db,party)
            if kind=="supplier_payment" and party_account==DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"] and supplier_account:
                party_account=supplier_account
            if kind=="customer_receipt" and party_account==DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"] and supplier_account:
                party_account=supplier_account
            number=str(item.get("payment_number") or "").strip() or self._next_payment_number(db,kind,date)
            if db.execute("SELECT 1 FROM payments WHERE payment_number=?",(number,)).fetchone(): raise ValueError(f"Number {number} is already used")
            department_id,project_id=self._dimension_ids(db,item)
            db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(cash_account,"Cash / Bank Account","asset"))
            db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(party_account,"Party Control Account","asset" if kind=="customer_receipt" else "liability"))
            program_accounts={chart_extra.BANK_COMMISSION_ACCOUNT:("Bank Commissions","expense"),chart_extra.EXCHANGE_GAIN_ACCOUNT:("Gain on Exchange Difference","income"),
                      chart_extra.EXCHANGE_LOSS_ACCOUNT:("Loss on Exchange Difference","expense")}
            for code,used in ((commission_account,commission),(gain_account,exchange_diff),(loss_account,exchange_diff)):
                if not used: continue
                if code in program_accounts: db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(code,)+program_accounts[code])
                elif not db.execute("SELECT 1 FROM accounts WHERE code=?",(code,)).fetchone():
                    raise ValueError(f"Account {code} was not found in the chart of accounts")
            result=db.execute("""INSERT INTO payments(kind,party_id,payment_date,currency,amount,cash_account,party_account,reference,description,bank_commission,commission_account,exchange_difference,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(kind,party_id,date,currency,str(amount),cash_account,party_account,
                str(item.get("reference") or "").strip(),str(item.get("description") or "").strip(),str(commission),commission_account,str(exchange_diff),user_id,utcnow()))
            payment_id=result.lastrowid
            db.execute("UPDATE payments SET payment_number=?,payment_method=?,department_id=?,project_id=?,exchange_gain_account=?,exchange_loss_account=? WHERE id=?",
                (number,str(item.get("payment_method") or "Cash").strip(),department_id,project_id,gain_account,loss_account,payment_id))
            entry=db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",(number,date,
                        str(item.get("description") or (("Receipt from " if kind=="customer_receipt" else "Payment to ")+party["name"])).strip(),"payment",
                        payment_id,currency,user_id,utcnow()))
            party_settlement=amount+exchange_diff
            if kind=="customer_receipt": lines=[(cash_account,amount-commission,Decimal("0")),(party_account,Decimal("0"),party_settlement)]
            else: lines=[(party_account,party_settlement,Decimal("0")),(cash_account,Decimal("0"),amount+commission)]
            if commission: lines.append((commission_account,commission,Decimal("0")))
            balance=sum(d for _c,d,_cr in lines)-sum(cr for _c,_d,cr in lines)
            if balance>0: lines.append((gain_account,Decimal("0"),balance))
            elif balance<0: lines.append((loss_account,-balance,Decimal("0")))
            lines=[(code,debit,credit) for code,debit,credit in lines if Decimal(str(debit)) or Decimal(str(credit))]
            for code,debit,credit in lines:
                db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,debit,credit,department_id,project_id) VALUES(?,?,?,?,?,?,?)",
                    (entry.lastrowid,self._account_id(db,code),party_id,str(debit),str(credit),department_id,project_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"create","payment",payment_id,json.dumps({"kind":kind,"number":number,"amount":str(amount),"currency":currency}),utcnow()))
            return payment_id

    def list_payments(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT x.id,x.kind,x.payment_number,x.payment_date,x.party_id,p.name party_name,x.currency,
                CAST(x.amount AS REAL) amount,x.cash_account,x.party_account,x.reference,x.description,x.payment_method,
                CAST(x.bank_commission AS REAL) bank_commission,x.commission_account,CAST(x.exchange_difference AS REAL) exchange_difference,
                x.exchange_gain_account,x.exchange_loss_account,
                d.code department,pr.code project
                FROM payments x JOIN parties p ON p.id=x.party_id LEFT JOIN departments d ON d.id=x.department_id LEFT JOIN projects pr ON pr.id=x.project_id
                ORDER BY x.id DESC""")]

    @atomic  # 2.9.121
    def add_expense(self, item, user_id):
        self.require_eur_rate(item.get("currency"), item.get("expense_date"))
        date=str(item.get("expense_date") or "").strip(); self._assert_period_open(date); self._assert_vat_open(date)
        description=str(item.get("description") or "").strip()
        if not description: raise ValueError("Expense description is required")
        legacy=Decimal(str(item.get("subtotal") or 0)); with_vat=Decimal(str(item.get("with_vat_subtotal") if item.get("with_vat_subtotal") not in (None,
                "") else legacy)); without_vat=Decimal(str(item.get("without_vat_subtotal") or 0)); subtotal=with_vat+without_vat
        vat=Decimal(str(item.get("vat") or 0)); total=subtotal+vat
        if min(with_vat,without_vat,vat)<0 or total<=0: raise ValueError("Expense amounts must be valid")
        defaults=self.default_accounts()  # 2.9.81
        currency=str(item.get("currency") or "USD").upper(); expense_account=str(item.get("expense_account") or defaults["expenses_import"]).strip()
        expense_without_vat_account=str(item.get("expense_without_vat_account") or defaults["purchases_no_vat"]).strip()
        import chart_extra
        vat_account=str(item.get("vat_account") or defaults["expense_vat"]).strip(); payment_account=str(item.get("payment_account") or defaults["cash"]).strip()
        expense_side=self._side(item.get("expense_side"),"D"); expense_without_vat_side=self._side(item.get("expense_without_vat_side"),"D")
        vat_side=self._side(item.get("vat_side"),"D"); payment_side=self._side(item.get("payment_side"),"C")
        with self.connect() as db:
            for code,name,typ in ((expense_account,"Expense with VAT","expense"),(expense_without_vat_account,"Expense without VAT","expense"),(vat_account,
                    "VAT Receivable","asset"),(payment_account,"Cash / Bank Account","asset")):
                db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(code,name,typ))
            result=db.execute("""INSERT INTO expenses(expense_date,description,category,currency,subtotal,with_vat_subtotal,without_vat_subtotal,vat,total,expense_account,expense_without_vat_account,vat_account,payment_account,expense_side,expense_without_vat_side,vat_side,payment_side,reference,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(date,description,str(item.get("category") or "").strip(),currency,str(subtotal),
                        str(with_vat),str(without_vat),str(vat),str(total),expense_account,expense_without_vat_account,vat_account,payment_account,expense_side,
                        expense_without_vat_side,vat_side,payment_side,str(item.get("reference") or "").strip(),user_id,utcnow()))
            expense_id=result.lastrowid
            import numbering  # 2.9.116
            number=str(item.get("expense_number") or "").strip() or self._next_number(db,"expenses","expense_number",numbering.series(db,"expense"),date)
            db.execute("UPDATE expenses SET expense_number=? WHERE id=?",(number,expense_id))
            entry=db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",(number if not db.execute("SELECT 1 FROM journal_entries WHERE entry_number=?",(number,)).fetchone() else f"EXP-{expense_id}",date,
                description+(f" - {str(item.get('reference')).strip()}" if str(item.get("reference") or "").strip() and str(item.get("reference")).strip() not in description else ""),  # 2.9.87: the supplier's invoice number in the entry
                "expense",expense_id,currency,user_id,utcnow()))
            lines=[self._line_for_side(expense_account,with_vat,expense_side),self._line_for_side(expense_without_vat_account,without_vat,
                    expense_without_vat_side),self._line_for_side(vat_account,vat,vat_side),self._line_for_side(payment_account,total,payment_side)]
            difference=sum(Decimal(str(line[1]))-Decimal(str(line[2])) for line in lines)
            if difference>0: lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"],Decimal("0"),difference))
            elif difference<0: lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"],-difference,Decimal("0")))
            for code,debit,credit in lines:
                if Decimal(str(debit or credit)):
                    db.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)",(entry.lastrowid,self._account_id(db,code),str(debit),str(credit)))
            db.execute("UPDATE expenses SET vat_use=? WHERE id=?",(self._vat_classification(item,"purchase")[1],expense_id))
            department_id,project_id=self._dimension_ids(db,item)
            if department_id or project_id:
                db.execute("UPDATE expenses SET department_id=?,project_id=? WHERE id=?",(department_id,project_id,expense_id))
                db.execute("UPDATE journal_lines SET department_id=?,project_id=? WHERE entry_id=?",(department_id,project_id,entry.lastrowid))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"create","expense",expense_id,json.dumps({"total":str(total),"currency":currency}),utcnow()))
        if str(item.get("vat_recoverable",True)).strip().lower() in ("0","false","no"):
            self.set_vat_recoverable("expense",expense_id,False,user_id)
        deductible=0 if str(item.get("tax_deductible",True)).strip().lower() in ("0","false","no") else 1  # 2.9.110
        with self.connect() as db: db.execute("UPDATE expenses SET tax_deductible=? WHERE id=?",(deductible,expense_id))
        return expense_id

    def list_expenses(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT id,expense_date,description,category,currency,
                CAST(subtotal AS REAL) subtotal,CAST(with_vat_subtotal AS REAL) with_vat_subtotal,CAST(without_vat_subtotal AS REAL) without_vat_subtotal,CAST(vat AS REAL) vat,CAST(total AS REAL) total,
                expense_account,expense_without_vat_account,vat_account,payment_account,expense_side,expense_without_vat_side,vat_side,payment_side,reference,vat_recoverable,
                expense_number,department_id,project_id,vat_use,tax_deductible,
                (SELECT COUNT(*) FROM expense_attachments a WHERE a.expense_id=expenses.id) attachment_count FROM expenses ORDER BY id DESC""")]

    TAX_FLAG_SOURCES = ("journal_voucher", "invoice", "payment")  # 2.9.113

    def set_tax_flag(self, source_type, source_id, not_deductible):
        """2.9.113: tick / untick "not deductible for income tax" on a journal voucher, purchase or payment (the entry stays in the books)."""
        if source_type not in self.TAX_FLAG_SOURCES: raise ValueError("Unknown entry type")
        with self.connect() as db:
            if not_deductible: db.execute("INSERT OR IGNORE INTO tax_flags(source_type,source_id) VALUES(?,?)", (source_type, int(source_id)))
            else: db.execute("DELETE FROM tax_flags WHERE source_type=? AND source_id=?", (source_type, int(source_id)))
        return {"source_type": source_type, "source_id": int(source_id), "not_deductible": bool(not_deductible)}

    def tax_flag_ids(self, source_type):
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT source_id FROM tax_flags WHERE source_type=?", (source_type,))]

    def set_income_exemption(self, source_id, reason, article=""):
        """2.9.113: a sales invoice whose income is not subject to income tax (already taxed / exempt by law) - the reason is required."""
        from tax_adjustments import reason_text
        text = reason_text(reason, article)
        with self.connect() as db:
            if text: db.execute("INSERT OR REPLACE INTO income_exemptions(source_type,source_id,reason) VALUES('invoice',?,?)", (int(source_id), text))
            else: db.execute("DELETE FROM income_exemptions WHERE source_type='invoice' AND source_id=?", (int(source_id),))
        return {"source_id": int(source_id), "reason": text}

    def income_exemptions(self):
        with self.connect() as db:
            return [{"source_id": r[0], "reason": r[1]} for r in db.execute("SELECT source_id,reason FROM income_exemptions WHERE source_type='invoice'")]

    def exempt_income(self, year=None):
        """The income (class 7 lines) of the sales invoices marked not subject to income tax, with the legal reason."""
        with self.connect() as db:
            rows = [{"entry_number": r[0], "date": r[1], "description": r[2], "account": r[3], "currency": r[4], "amount": round(r[5] or 0, 2), "reason": r[6]}
                    for r in db.execute("""SELECT e.entry_number,e.entry_date,e.description,a.code,e.currency,
                        SUM(CAST(j.credit AS REAL)-CAST(j.debit AS REAL)),x.reason FROM journal_entries e JOIN journal_lines j ON j.entry_id=e.id
                        JOIN accounts a ON a.id=j.account_id JOIN income_exemptions x ON x.source_type='invoice' AND x.source_id=e.source_id
                        WHERE e.source_type='invoice' AND substr(a.code,1,1)='7' GROUP BY e.id,a.code ORDER BY e.entry_date,e.id""")]
        if year: rows = [r for r in rows if str(r["date"])[:4] == str(year) or str(r["date"])[6:10] == str(year)]
        return rows

    def non_deductible_expenses(self, year=None):
        """2.9.110: expenses marked not deductible for income tax (no official invoice ...), to add back to the taxable profit.
        2.9.113: with the expense lines (class 6) of the journal vouchers, purchases and payments ticked the same way."""
        with self.connect() as db:
            rows=[dict(row) for row in db.execute("""SELECT id,expense_number,expense_date,description,category,currency,CAST(subtotal AS REAL) subtotal,
                CAST(vat AS REAL) vat,CAST(total AS REAL) total,expense_account,reference FROM expenses WHERE tax_deductible=0 ORDER BY expense_date,id""")]
            for row in db.execute("""SELECT e.id,e.entry_number,e.entry_date,e.description,e.source_type,e.currency,a.code,
                    SUM(CAST(j.debit AS REAL)-CAST(j.credit AS REAL)) amount FROM journal_entries e JOIN journal_lines j ON j.entry_id=e.id
                    JOIN accounts a ON a.id=j.account_id JOIN tax_flags t ON t.source_type=e.source_type
                    AND t.source_id=CASE WHEN e.source_type='journal_voucher' THEN e.id ELSE e.source_id END
                    WHERE substr(a.code,1,1)='6' GROUP BY e.id,a.code ORDER BY e.entry_date,e.id"""):
                label = {"journal_voucher": "Journal voucher", "invoice": "Purchase", "payment": "Payment"}.get(row["source_type"], row["source_type"])
                rows.append({"id": None, "entry_id": row["id"], "expense_number": row["entry_number"], "expense_date": row["entry_date"],
                             "description": row["description"], "category": label, "currency": row["currency"], "subtotal": round(row["amount"] or 0, 2),
                             "vat": 0.0, "total": round(row["amount"] or 0, 2), "expense_account": row["code"], "reference": ""})
        if year: rows=[r for r in rows if str(r["expense_date"])[:4]==str(year) or str(r["expense_date"])[6:10]==str(year)]
        return rows

    def _next_payment_number(self, db, kind, date):
        import numbering  # 2.9.116: the prefix chosen in Settings > Numbering (RV / PV by default)
        return self._next_number(db, "payments", "payment_number", numbering.series(db, "customer_receipt" if kind == "customer_receipt" else "supplier_payment"), date)

    # ---------------------------------------------------------------- receipts and payments: edit / delete
    def _remove_entries(self, db, source_type, source_id, extra_numbers=()):
        db.execute("DELETE FROM journal_entries WHERE source_type=? AND source_id=?", (source_type, int(source_id)))
        for number in extra_numbers: db.execute("DELETE FROM journal_entries WHERE entry_number=?", (number,))

    @atomic  # 2.9.121
    def delete_payment(self, payment_id, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM payments WHERE id=?", (int(payment_id),)).fetchone()
            if not row: raise KeyError("Payment not found")
        self._assert_period_open(row["payment_date"])
        with self.connect() as db:
            self._remove_entries(db, "payment", payment_id); db.execute("DELETE FROM payments WHERE id=?", (int(payment_id),))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "delete", "payment", int(payment_id), json.dumps({"number": row["payment_number"], "amount": row["amount"]}), utcnow()))
        return {"deleted": int(payment_id)}

    def update_payment(self, payment_id, item, user_id):
        return self._safe_replacement("payment", payment_id, item, user_id)

    def _replace_payment_on_stage(self, payment_id, item, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM payments WHERE id=?", (int(payment_id),)).fetchone()
            if not row: raise KeyError("Payment not found")
        item = {**item, "kind": row["kind"], "payment_number": row["payment_number"]}
        self._assert_period_open(row["payment_date"])
        self.delete_payment(payment_id, user_id)
        return self.add_payment(item, user_id)

    def _safe_replacement(self, kind, record_id, item, user_id):
        """Validate destructive edits on a snapshot; publish only a complete result."""
        with self._lock, tempfile.TemporaryDirectory() as directory:
            stage_path=Path(directory)/"edited.db"
            with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(stage_path)) as stage:
                source.backup(stage)
            stage_db=type(self)(stage_path)
            operation=stage_db._replace_payment_on_stage if kind=="payment" else stage_db._replace_expense_on_stage
            new_id=operation(record_id,item,user_id)
            self.backup("safety")
            with closing(sqlite3.connect(stage_path)) as source, closing(sqlite3.connect(self.path)) as target:
                source.backup(target)
            return new_id

    # ---------------------------------------------------------------- expenses: edit / delete / attachments
    @atomic  # 2.9.121
    def delete_expense(self, expense_id, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM expenses WHERE id=?", (int(expense_id),)).fetchone()
            if not row: raise KeyError("Expense not found")
        self._assert_period_open(row["expense_date"]); self._assert_vat_open(row["expense_date"])
        with self.connect() as db:
            self._remove_entries(db, "expense", expense_id, (f"VATND-EXP-{int(expense_id)}",)); db.execute("DELETE FROM expenses WHERE id=?", (int(expense_id),))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "delete", "expense", int(expense_id), json.dumps({"number": row["expense_number"], "total": row["total"]}), utcnow()))
        return {"deleted": int(expense_id)}

    def update_expense(self, expense_id, item, user_id):
        return self._safe_replacement("expense", expense_id, item, user_id)

    def _replace_expense_on_stage(self, expense_id, item, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM expenses WHERE id=?", (int(expense_id),)).fetchone()
            if not row: raise KeyError("Expense not found")
            files = [dict(r) for r in db.execute("SELECT file_name,mime_type,content FROM expense_attachments WHERE expense_id=?", (int(expense_id),))]
        self._assert_period_open(row["expense_date"]); self._assert_vat_open(row["expense_date"], item.get("expense_date"))
        self.delete_expense(expense_id, user_id)
        new_id = self.add_expense({**item, "expense_number": row["expense_number"]}, user_id)
        for f in files: self.add_expense_attachment(new_id, f["file_name"], f["mime_type"], f["content"], user_id)
        return new_id

    def add_expense_attachment(self, expense_id, file_name, mime_type, content, user_id):
        if not file_name or not content: raise ValueError("Attachment file is required")
        if len(content) > 15 * 1024 * 1024: raise ValueError("Attachment cannot exceed 15 MB")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM expenses WHERE id=?", (int(expense_id),)).fetchone(): raise KeyError("Expense not found")
            return db.execute("INSERT INTO expense_attachments(expense_id,file_name,mime_type,content,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?)",
                (int(expense_id), file_name, mime_type or "application/octet-stream", content, user_id, utcnow())).lastrowid

    def list_expense_attachments(self, expense_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,file_name,mime_type,length(content) size,uploaded_at FROM expense_attachments WHERE expense_id=? ORDER BY id DESC", (int(expense_id),))]

    def get_expense_attachment(self, attachment_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM expense_attachments WHERE id=?", (int(attachment_id),)).fetchone()
        if not row: raise KeyError("Attachment not found")
        return dict(row)

    def open_documents(self, party_id):
        """Invoices of a customer / supplier with what is still unpaid (after amounts paid and allocations)."""
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,i.kind,i.doc_subtype,i.currency,CAST(i.total AS REAL) total,
                CAST(COALESCE(i.amount_paid,'0') AS REAL) paid,(SELECT COALESCE(DSUM(CAST(a.amount AS REAL)),0) FROM payment_allocations a WHERE a.invoice_id=i.id) allocated
                FROM invoices i WHERE i.party_id=? AND i.status NOT IN ('cancelled','deleted') ORDER BY i.id""", (int(party_id),))]
        for row in rows:
            sign = -1 if row.get("doc_subtype") == "credit_note" else 1
            row["open_amount"] = round(sign * (row["total"] - row["paid"] - row["allocated"]), 2)
        return [r for r in rows if abs(r["open_amount"]) >= 0.01]

    @atomic  # 2.9.121
    def save_allocations(self, payment_id, allocations, user_id):
        # An offset between documents needs its own party-control journal entry;
        # payment allocations represent cash settlement only.
        settlement_kind = {
            ("sale", False): "customer_receipt",
            ("sale", True): "supplier_payment",
            ("purchase", False): "supplier_payment",
            ("purchase", True): "customer_receipt",
        }
        with self.connect() as db:
            payment = db.execute("SELECT * FROM payments WHERE id=?", (int(payment_id),)).fetchone()
            if not payment: raise KeyError("Payment not found")
            db.execute("DELETE FROM payment_allocations WHERE payment_id=?", (int(payment_id),))
            total = Decimal("0")
            for entry in allocations or []:
                amount = Decimal(str(entry.get("amount") or 0).replace(",", ""))
                if amount <= 0: continue
                invoice = db.execute("SELECT * FROM invoices WHERE id=?", (int(entry["invoice_id"]),)).fetchone()
                if not invoice or invoice["party_id"] != payment["party_id"]: raise ValueError("Allocate only to documents of the same customer / supplier")
                if invoice["currency"] != payment["currency"]: raise ValueError(f"{invoice['invoice_number']} is in {invoice['currency']}; the payment is in {payment['currency']}")
                expected = settlement_kind.get((invoice["kind"], invoice["doc_subtype"] == "credit_note"))
                if expected != payment["kind"]:
                    action = "an outgoing payment/refund" if expected == "supplier_payment" else "an incoming receipt/refund"
                    raise ValueError(f"{invoice['invoice_number']} cannot be settled with this payment type; use {action}. To offset a credit note against an invoice, record a separate journal adjustment.")
                total += amount
                db.execute("INSERT INTO payment_allocations(payment_id,invoice_id,amount,created_at) VALUES(?,?,?,?)", (int(payment_id), invoice["id"], str(amount), utcnow()))
                # 2.9.121: never more than what is still open on the document (all payments together) - the rest stays unapplied
                allocated = Decimal(str(db.execute("SELECT COALESCE(DSUM(amount),0) FROM payment_allocations WHERE invoice_id=?", (invoice["id"],)).fetchone()[0] or 0))
                open_amount = Decimal(str(invoice["total"] or 0)) - Decimal(str(invoice["amount_paid"] or 0))
                if allocated > open_amount + Decimal("0.005"):
                    left = max(Decimal("0"), open_amount - (allocated - amount))
                    raise ValueError(f"{invoice['invoice_number']}: only {left:,.2f} {invoice['currency']} is still open - allocate at most that; "
                                     "the rest of the payment stays unapplied (an advance) on the account")
            if total > Decimal(str(payment["amount"])) + Decimal("0.005"): raise ValueError(f"Allocated {total:,.2f} is more than the payment {Decimal(str(payment['amount'])):,.2f}")
        return self.payment_allocations(payment_id)

    def payment_allocations(self, payment_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("""SELECT a.invoice_id,i.invoice_number,i.invoice_date,CAST(a.amount AS REAL) amount FROM payment_allocations a
                JOIN invoices i ON i.id=a.invoice_id WHERE a.payment_id=? ORDER BY a.id""", (int(payment_id),))]
