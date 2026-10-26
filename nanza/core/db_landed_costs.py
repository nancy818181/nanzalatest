"""Customs / freight / insurance on a purchase (linked Customs Case invoice) and its breakdown.

Part of the Database class through InvoicesStore (moved unchanged from db_invoices.py in the 2.9.138 consolidation):
the methods run on the same Database object, connection and transaction rules as before."""
from __future__ import annotations

from database_common import atomic, Decimal, json, utcnow


class LandedCostStore:
    @atomic  # 2.9.121
    def add_landed_cost(self, purchase_id, item, user_id):
        """Customs / freight / insurance on a purchase, booked as a linked 'Customs Case' invoice so import VAT reaches the VAT return."""
        with self.connect() as db:
            purchase = db.execute("SELECT i.*,p.name party_name FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.id=?", (int(purchase_id),)).fetchone()
        if not purchase or purchase["kind"] != "purchase": raise ValueError("Choose a purchase invoice first")
        from landed_costs import normalize
        item, source_amounts = normalize(item, purchase["currency"])
        components = (("freight", "Freight"), ("insurance", "Insurance"), ("customs_group_1", "Customs per item"), ("customs_duties", "Customs fees"),
                      ("customs_group_2", "Customs - group 2"), ("broker_fees", "Customs broker fees"), ("other_costs", "Other landed costs"))
        lines = []
        for key, label in components:
            try: amount = Decimal(str(item.get(key) or 0).replace(",", ""))
            except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError(f"{label} must be a number") from exc
            if amount < 0: raise ValueError(f"{label} cannot be negative")
            if amount: lines.append({"description": f"{label} - {purchase['invoice_number']}", "quantity": 1, "unit_price": str(amount), "deductible_subtotal": str(amount), "vat_rate": 0, "vat": 0})
        try: import_vat = Decimal(str(item.get("import_vat") or 0).replace(",", ""))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc: raise ValueError("Import VAT must be a number") from exc
        if not lines and not import_vat: raise ValueError("Enter at least one landed-cost amount")
        if not lines: lines.append({"description": f"Import VAT - {purchase['invoice_number']}", "quantity": 1, "unit_price": "0", "deductible_subtotal": "0", "vat_rate": 0, "vat": 0})
        lines[0]["vat"] = str(import_vat)
        import chart_extra
        cost_accounts = {**chart_extra.LANDED_COST_ACCOUNTS, **(item.get("cost_accounts") or {})}
        for key in ("customs_group_1", "customs_group_2"): cost_accounts.setdefault(key, cost_accounts["customs_duties"])  # 2.9.106: same customs account
        with self.connect() as db:
            for key, _label in components:
                code = str(cost_accounts[key]).split(" - ", 1)[0].strip()
                account = db.execute("SELECT type FROM accounts WHERE code=? AND active=1", (code,)).fetchone()
                if not code.isdigit() or len(code) != 9 or not account or account["type"] != "expense":
                    raise ValueError(f"{key.replace('_', ' ').title()} needs an active 9-digit expense account")
                cost_accounts[key] = code
        declaration = str(item.get("customs_declaration_no") or "").strip()
        supplier_account=None; party_name=str(item.get("party_name") or "Lebanese Customs").strip()
        if str(item.get("party_id") or "").strip():
            with self.connect() as db:
                chosen=db.execute("SELECT * FROM parties WHERE id=?",(int(item["party_id"]),)).fetchone()
            if chosen:
                party_name=chosen["name"]
                supplier_account=chosen["account_number"] or None
        invoice = {"invoice_number": declaration or f"LC-{purchase['invoice_number']}", "invoice_date": item.get("date") or purchase["invoice_date"],
                   "party_name": party_name, "kind": "purchases", "currency": item.get("currency") or purchase["currency"],
                   "expense_account": purchase["expense_account"], "status": "posted", "source_file": "Customs Case",
                   "description": f"Landed cost of {purchase['invoice_number']} ({purchase['party_name'] or ''})" + (f" - declaration {declaration}" if declaration else ""),
                   "department_id": purchase["department_id"], "project_id": purchase["project_id"]}
        method = str(item.get("payment_method") or "On Account (Not Cash)")
        if method not in ("On Account (Not Cash)", "Cash", "Bank Transfer", "Cheque", "Card"):
            raise ValueError("Choose a valid cost payment method")
        invoice["payment_method"] = method
        if method != "On Account (Not Cash)":
            cash = str(item.get("cash_account") or "").split(" - ", 1)[0].strip()
            with self.connect() as db:
                account = db.execute("SELECT type FROM accounts WHERE code=? AND active=1", (cash,)).fetchone()
            if not cash.startswith("5") or not account or account["type"] != "asset":
                raise ValueError("Choose an active cash or bank account for the cost payment")
            invoice["cash_account"] = cash
            invoice["amount_paid"] = str(sum((Decimal(line["unit_price"]) for line in lines), Decimal("0")) + import_vat)
        if supplier_account: invoice["supplier_account"]=supplier_account
        invoice_id = self.create_manual_invoice(invoice, lines, user_id)
        # each cost goes to its own 9-digit 6018 account (freight, insurance, duties, broker, other)
        with self.connect() as db:
            db.execute("UPDATE invoices SET linked_invoice_id=? WHERE id=?", (int(purchase_id), invoice_id))
            db.executemany("""INSERT INTO landed_cost_sources(cost_invoice_id,component,currency,amount,conversion_rate,converted_amount)
                VALUES(?,?,?,?,?,?)""", [(invoice_id, *source) for source in source_amounts])
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "landed_cost", "invoice", invoice_id, json.dumps({"purchase_id": int(purchase_id),
                 "currency": item["currency"], "source_amounts": source_amounts, "usd_lbp_rate": item.get("usd_lbp_rate")}), utcnow()))
            for key, _label in components:  # 2.9.106: the parts, so customs of a group go to the items of that group only
                amount = Decimal(str(item.get(key) or 0).replace(",", ""))
                if amount: db.execute("INSERT INTO landed_cost_parts(cost_invoice_id,component,amount) VALUES(?,?,?)", (invoice_id, key, str(amount)))
            entry = db.execute("SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?", (invoice_id,)).fetchone()
            cost_account = self._account_id(db, purchase["expense_account"])
            parts = [(cost_accounts[key], Decimal(str(item.get(key) or 0).replace(",", ""))) for key, _label in components]
            parts = [(code, amount) for code, amount in parts if amount]
            if entry and parts:
                line = db.execute("SELECT * FROM journal_lines WHERE entry_id=? AND account_id=? AND CAST(debit AS REAL)>0 ORDER BY id LIMIT 1", (entry["id"], cost_account)).fetchone()
                if line:
                    db.execute("DELETE FROM journal_lines WHERE id=?", (line["id"],))
                    for code, amount in parts:
                        db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,description,debit,credit,department_id,project_id) VALUES(?,?,?,?,?,?,?,?)",
                            (entry["id"], self._account_id(db, code), line["party_id"], f"Cost on purchase {purchase['invoice_number']}", str(amount), "0", line["department_id"], line["project_id"]))
        return invoice_id

    def landed_costs(self, purchase_id):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,p.name party_name,i.currency,CAST(i.subtotal AS REAL) subtotal,
                CAST(i.vat AS REAL) vat,CAST(i.total AS REAL) total FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.linked_invoice_id=? AND i.source_file='Customs Case'
                AND i.status NOT IN ('cancelled','deleted','void') ORDER BY i.id""",
                        (int(purchase_id),))]
            sources = {}
            for row in db.execute("""SELECT s.* FROM landed_cost_sources s JOIN invoices i ON i.id=s.cost_invoice_id
                WHERE i.linked_invoice_id=? ORDER BY s.id""", (int(purchase_id),)):
                sources.setdefault(row["cost_invoice_id"], []).append(dict(row))
            for row in rows: row["source_amounts"] = sources.get(row["id"], [])
            return rows
