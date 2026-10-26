"""Invoices: import, manual invoices, edits, cancellations, voids, approvals, invoice list.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from InvoicesStore.
2.9.138 consolidation: returns (db_invoice_returns), attachments and history (db_invoice_attachments), number identity and
duplicates (db_invoice_numbers) and landed costs (db_landed_costs) are base classes of InvoicesStore, moved unchanged."""
from __future__ import annotations
from database_common import atomic  # 2.9.121
import logging
import sqlite3

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    datetime, Decimal, DEFAULT_LEBANESE_ACCOUNTS, EXPENSE_NO_VAT_ACCOUNT_9, hashlib, iso_date, json, utcnow
)
from database_common import _soft_iso  # noqa: F401
from settlements import posted_payment_sql
# 2.9.138 consolidation: cohesive parts of the invoice store in their own modules (same Database object and methods)
from db_invoice_attachments import InvoiceAttachmentsStore
from db_invoice_numbers import InvoiceNumbersStore
from db_invoice_returns import InvoiceReturnsStore
from db_landed_costs import LandedCostStore


class InvoicesStore(InvoiceReturnsStore, InvoiceAttachmentsStore, InvoiceNumbersStore, LandedCostStore):
    def next_invoice_number(self, kind="sale", invoice_date=None, branch=None):
        prefix = {"sale":"SAL","sales":"SAL","credit_note":"CN","debit_note":"DN","supplier_credit_note":"SCN","supplier_debit_note":"SDN"}.get(str(kind).lower(),"PUR")
        if prefix in ("SAL", "PUR"):  # 2.9.116: the prefix (and branch) chosen in Settings > Numbering
            import numbering
            with self.connect() as db: prefix = numbering.series(db, "sale" if prefix == "SAL" else "purchase", branch)
        year = str(invoice_date or datetime.now().year)
        if "-" in year:
            year = year[-4:] if year[:4].isdigit() is False else year[:4]
        if not year.isdigit() or len(year) != 4:
            year = str(datetime.now().year)
        pattern = f"{prefix}-{year}-%"
        with self.connect() as db:
            values = [row["invoice_number"] for row in db.execute(
                "SELECT invoice_number FROM invoices WHERE invoice_number LIKE ?", (pattern,))]
        sequence = 1
        for value in values:
            try: sequence = max(sequence, int(value.rsplit("-", 1)[-1]) + 1)
            except (TypeError, ValueError): pass
        return f"{prefix}-{year}-{sequence:06d}"

    def clear_invoices(self, user_id, make_backup=True):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM payment_allocations LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked while payments are allocated to existing invoices")
            if db.execute("SELECT 1 FROM stock_documents WHERE invoice_id IS NOT NULL LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked while stock documents are linked to invoices")
            if db.execute("SELECT 1 FROM vat_returns LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked after a quarterly VAT return has been saved")
            if db.execute("SELECT 1 FROM fiscal_years WHERE status='closed' LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked while a fiscal year is closed")
            if db.execute("SELECT 1 FROM fixed_assets a JOIN invoices i ON i.id=a.invoice_id WHERE a.status='active' LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked while invoices are linked to active fixed assets")
            if db.execute("SELECT 1 FROM invoices WHERE CAST(COALESCE(amount_paid,'0') AS REAL)>0 LIMIT 1").fetchone():
                raise ValueError("Invoice replacement is blocked while existing invoices have payments recorded")
        backup_path = self.backup("safety") if make_backup else None
        with self.connect() as db:
            entry_ids = [r["id"] for r in db.execute((
                "SELECT id FROM journal_entries WHERE source_type IN ('invoice','invoice_reversal','vat_reclass') AND "
                "(source_type!='vat_reclass' OR entry_number LIKE 'VATND-INV-%')"
            ))]
            if entry_ids:
                marks = ",".join("?" for _ in entry_ids)
                db.execute(f"DELETE FROM journal_lines WHERE entry_id IN ({marks})", entry_ids)
                db.execute(f"DELETE FROM journal_entries WHERE id IN ({marks})", entry_ids)
            deleted = db.execute("SELECT COUNT(*) n FROM invoices").fetchone()["n"]
            db.execute("DELETE FROM invoices")
            db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)", (user_id,"replace","invoice_import",
                    json.dumps({"deleted":deleted,"backup":backup_path}),utcnow()))
            return {"deleted": deleted, "backup": backup_path}

    def import_invoice(self, item, user_id):
        self.require_eur_rate(item.get("currency"), item.get("invoice_date"))
        # 2.9.134 (D3): a duplicate invoice identity is refused below (_assert_unique_invoice_number); an administrator can allow one on purpose.
        self._assert_period_open(item.get("invoice_date")); self._assert_vat_open(item.get("invoice_date"))
        defaults=self.default_accounts()  # 2.9.81: Settings > Accounting Settings
        with self.connect() as db:
            entry_type=self._entry_type(item); kind="sale" if entry_type=="sales" else "purchase"
            party_kind = "customer" if kind == "sale" else "supplier"
            source_party = item.get("commercial_party_id")
            if source_party is not None:
                party = db.execute("SELECT * FROM parties WHERE id=?", (int(source_party),)).fetchone()
                if not party or party["kind"] not in (party_kind, "both") or party["name"] != item.get("party_name"):
                    raise ValueError("Commercial document party does not match the invoice direction")
            else:
                db.execute("INSERT OR IGNORE INTO parties(kind,name,currency) VALUES(?,?,?)", (party_kind, item.get("party_name") or "Unspecified", item.get("currency", "USD")))
                party = db.execute("SELECT * FROM parties WHERE kind=? AND name=?", (party_kind, item.get("party_name") or "Unspecified")).fetchone()
            self._assert_unique_invoice_number(db, item, kind, party["id"])  # 2.9.134 (D3)
            # 2.9.132 (H-03, owner rule): amounts with 2 decimals, the third rounded half up, before any posting or check
            from decimal import ROUND_HALF_UP as half_up
            cent=lambda value: Decimal(str(value)).quantize(Decimal("0.01"),rounding=half_up)
            raw_subtotal=cent(item.get("subtotal") or 0)
            deductible=cent(item.get("deductible_subtotal") if item.get("deductible_subtotal") not in (None,"") else raw_subtotal)
            non_deductible=cent(item.get("non_deductible_subtotal") or 0); subtotal=deductible+non_deductible
            vat = cent(item.get("vat") or 0); total = cent(item.get("total") or subtotal + vat)
            currency_issue = str(item.get("currency_issue") or "")
            requested_status=str(item.get("status") or "").strip().lower()
            status=requested_status if requested_status in ("posted",
                    "review") else ("posted" if total == subtotal + vat and not currency_issue.startswith(("conflicting:", "unsupported:")) else "review")
            default_party_account=DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"] if kind=="sale" else DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"]
            supplier_account = str(item.get("supplier_account") or default_party_account).strip()
            party_account=self._ensure_party_account(db,party)
            if kind=="purchase" and (not item.get("supplier_account") or supplier_account==DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"]):
                supplier_account=party_account
            elif kind=="sale" and (not item.get("supplier_account") or supplier_account.split(" - ",1)[0].strip().startswith("40")):
                # 2.9.77: a sale is owed by the customer's own account (was: the general 4111, or the SUPPLIERS account 4011
                # that the Excel import put on every row); an account chosen on purpose (41...) is kept
                supplier_account=party_account
            import chart_extra
            default_vat = defaults["output_vat"] if kind=="sale" else chart_extra.EXPORT_VAT if item.get("vat_use")=="export" else \
                defaults["expense_vat"] if self._entry_type(item)=="expenses" else defaults["purchase_vat"]
            vat_account = str(item.get("vat_account") or default_vat).strip()
            expense_account = str(item.get("expense_account") or (defaults["sales"] if kind=="sale" else defaults["purchases"])).strip()
            if entry_type=="assets" and not expense_account.split(" - ",1)[0].strip().startswith("2"):
                # 2.9.132: as the purchase screen already requires - an Assets invoice (Excel import, API) never goes to a purchase / expense account
                raise ValueError(f"Invoice {item.get('invoice_number')}: an Assets purchase needs a class 2 fixed-asset account (got {expense_account})")
            if kind=="sale":  # 2.9.77: a sale never posts to an expense account or to deductible (input) VAT
                if not expense_account.split(" - ",1)[0].strip().startswith("7"): expense_account=defaults["sales"]
                vat_code=vat_account.split(" - ",1)[0].strip()
                if vat_code.startswith(("4426","4421")) or vat_code in (chart_extra.PURCHASE_VAT,chart_extra.EXPORT_VAT,chart_extra.EXPENSE_VAT,defaults["purchase_vat"],defaults["expense_vat"]):
                    vat_account=defaults["output_vat"]
            import vat_ledgers  # 2.9.97: the party's own VAT account (442100025 for supplier 401100025) when the rule is on
            vat_account=vat_ledgers.party_vat_account(db,supplier_account,vat_account,kind)
            expense_no_vat_account=str(item.get("expense_no_vat_account") or defaults["purchases_no_vat"]).strip()
            supplier_side=self._side(item.get("supplier_side"),"D" if kind=="sale" else "C")
            vat_side=self._side(item.get("vat_side"),"C" if kind=="sale" else "D")
            expense_side=self._side(item.get("expense_side"),"C" if kind=="sale" else "D")
            expense_no_vat_side=self._side(item.get("expense_no_vat_side"),"D")
            account_definitions = [
                (supplier_account, "Client Account" if kind=="sale" else "Supplier Account", "asset" if kind=="sale" else "liability"),
                (vat_account, "Output VAT Account" if kind=="sale" else "VAT Account", "liability" if kind=="sale" else "asset"),
                (expense_account, "Sales Revenue Account" if kind=="sale" else ("Asset Account" if entry_type=="assets" else "Expense Account"),
                        "income" if kind=="sale" else ("asset" if entry_type=="assets" else "expense")),
                (expense_no_vat_account,"Expenses without VAT","expense"),
            ]
            for code, name, account_type in account_definitions:
                db.execute(
                    "INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",
                    (code, name, account_type),
                )
            due_date = self._invoice_due_date(item, party)
            amount_paid = total if str(item.get("amount_paid") or "").strip().lower() == "full" else Decimal(str(item.get("amount_paid") or 0))  # 2.9.55: "full" = paid in full
            if amount_paid < 0 or amount_paid > total:
                raise ValueError("Amount paid must be between zero and invoice total")
            payment_status = "paid" if amount_paid == total and total > 0 else "partial" if amount_paid > 0 else "unpaid"
            debit_override=item.get("debit"); credit_override=item.get("credit")
            cur = db.execute("""INSERT INTO invoices(invoice_number,kind,invoice_date,party_id,currency,exchange_rate,subtotal,deductible_subtotal,non_deductible_subtotal,vat,total,status,currency_issue,supplier_account,vat_account,expense_account,entry_type,debit_override,credit_override,supplier_side,vat_side,expense_side,expense_no_vat_account,expense_no_vat_side,source_file,source_row,due_date,payment_status,amount_paid,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                str(item["invoice_number"]), kind, item.get("invoice_date"), party["id"], item.get("currency", "USD"),
                str(item.get("exchange_rate", 1)), str(subtotal),str(deductible),str(non_deductible),str(vat), str(total),
                status, currency_issue, supplier_account, vat_account, expense_account,entry_type,
                None if debit_override in (None,"") else str(Decimal(str(debit_override))),None if credit_override in (None,"") else str(Decimal(str(credit_override))),
                supplier_side,vat_side,expense_side,expense_no_vat_account,expense_no_vat_side,
                item.get("source_file"), item.get("source_row"), due_date, payment_status, str(amount_paid), user_id, utcnow()))
            invoice_id = cur.lastrowid
            if status == "posted":
                db.execute("UPDATE invoices SET posted_at=?,posted_by=? WHERE id=?",
                           (utcnow(),user_id,invoice_id))
            branch_id=self._branch_id(db,item)
            db.execute("UPDATE invoices SET payment_method=?,description=?,branch_id=? WHERE id=?",(str(item.get("payment_method") or "").strip() or None,
                    str(item.get("description") or "").strip() or None,branch_id,invoice_id))
            entry_number = f"INV-{invoice_id}"
            posting_status="posted" if status=="posted" else "draft"
            entry = db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,
                currency,branch_id,created_by,created_at,posting_status,posted_at,posted_by)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry_number, item.get("invoice_date"), f"{entry_type.replace('_',' ').title()} {item['invoice_number']}", "invoice", invoice_id,
                        item.get("currency", "USD"),branch_id, user_id, utcnow(),posting_status,
                 utcnow() if posting_status=="posted" else None,user_id if posting_status=="posted" else None))
            if kind == "sale":
                revenue=[(str(a).strip(),Decimal(str(v))) for a,v in (item.get("revenue_splits") or [])]
                if revenue and abs(sum(v for _a,v in revenue)-Decimal(str(subtotal)))<Decimal("0.01"):  # 2.9.90
                    revenue_lines=[self._line_for_side(a,v,self._side(item.get("expense_side"),"C")) for a,v in revenue if v]
                else: revenue_lines=[self._line_for_side(expense_account,subtotal,self._side(item.get("expense_side"),"C"))]
                lines = [self._line_for_side(supplier_account,total,self._side(item.get("supplier_side"),"D"))]+revenue_lines+[
                         self._line_for_side(vat_account,vat,self._side(item.get("vat_side"),"C"))]
            else:
                splits=item.get("expense_splits")
                if splits:
                    expense_lines=[]
                    for acct,amt in splits:
                        code=str(acct).strip(); value=Decimal(str(amt))
                        if not value: continue
                        db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)",(code,"Expense Account","expense"))
                        expense_lines.append(self._line_for_side(code,value,expense_side))
                    lines = expense_lines+[self._line_for_side(expense_no_vat_account,non_deductible,expense_no_vat_side),self._line_for_side(vat_account,vat,
                            vat_side),self._line_for_side(supplier_account,total,supplier_side)]
                else:
                    lines = [self._line_for_side(expense_account,deductible,expense_side),self._line_for_side(expense_no_vat_account,non_deductible,
                            expense_no_vat_side),self._line_for_side(vat_account,vat,vat_side),self._line_for_side(supplier_account,total,supplier_side)]
            lines=[line for line in lines if Decimal(str(line[1])) or Decimal(str(line[2]))]
            difference = sum(x[1] for x in lines) - sum(x[2] for x in lines)
            if kind=="sale" and any(item.get(key) for key in ("supplier_side","expense_side","vat_side")) and difference:
                raise ValueError("Sales posting accounts are unbalanced. Check their Debit/Credit selections.")
            if status=="posted" and abs(difference)>Decimal("1"):
                # 2.9.132: a POSTED invoice whose total is not subtotal + VAT is refused (it was balanced silently on 6851.6);
                # a rounding difference up to 1 unit still goes to the import-variance account, a Review invoice is unchanged
                raise ValueError(f"Invoice {item['invoice_number']}: total {total} is not subtotal + VAT ({subtotal + vat}); difference {difference} - "
                                 "correct the amounts or import it in Review")
            if difference > 0:
                lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"], 0, difference))
            elif difference < 0:
                lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"], -difference, 0))
            for code, debit, credit in lines:
                db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,debit,credit) VALUES(?,?,?,?,?)", (entry.lastrowid, self._account_id(db,
                        code), party["id"], str(debit), str(credit)))
            debit_total = sum(x[1] for x in lines); credit_total = sum(x[2] for x in lines)
            if debit_total != credit_total:
                raise ValueError(f"Unbalanced journal entry for invoice {item['invoice_number']}")
            treatment,use=self._vat_classification(item,kind)
            db.execute("UPDATE invoices SET vat_treatment=?,vat_use=? WHERE id=?",(treatment,use,invoice_id))
            department_id,project_id=self._dimension_ids(db,item)
            if department_id or project_id:
                db.execute("UPDATE invoices SET department_id=?,project_id=? WHERE id=?",(department_id,project_id,invoice_id))
                db.execute("UPDATE journal_lines SET department_id=?,project_id=? WHERE entry_id=?",(department_id,project_id,entry.lastrowid))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (user_id, "import", "invoice",
                    invoice_id, json.dumps({"source_file": item.get("source_file"), "source_row": item.get("source_row")}), utcnow()))
            self._post_invoice_payment(db, invoice_id, user_id, item.get("cash_account"))
            return invoice_id

    # 2.9.47: an invoice paid on the spot (Cash, Bank Transfer, Cheque, Card ...) gets its settlement entry:
    # sale  Dr cash / bank - Cr customer;  purchase  Dr supplier - Cr cash / bank. Its own entry PINV-<id>.
    PAYMENT_ACCOUNTS = {"cash": "531"}
    BANK_ACCOUNT = "512"

    def _payment_account(self, method, override=None):
        code = str(override or "").split(" - ", 1)[0].strip()
        if code: return code
        return self.PAYMENT_ACCOUNTS.get(str(method or "").strip().lower(), self.BANK_ACCOUNT)

    def _post_invoice_payment(self, db, invoice_id, user_id, cash_account=None):
        db.execute("DELETE FROM journal_entries WHERE source_type='invoice_payment' AND source_id=?", (int(invoice_id),))
        invoice = db.execute("SELECT * FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
        if not invoice or invoice["status"] in ("cancelled", "deleted", "void"): return None
        method = str(invoice["payment_method"] or "").strip()
        paid = Decimal(str(invoice["amount_paid"] or 0))
        if paid <= 0 or not method or method.lower().startswith("on account"): return None
        if "doc_subtype" in invoice.keys() and invoice["doc_subtype"] == "credit_note": return None
        if str(cash_account or "").strip():
            db.execute("UPDATE invoices SET payment_account=? WHERE id=?", (str(cash_account).split(" - ", 1)[0].strip(), int(invoice_id)))
        stored = invoice["payment_account"] if "payment_account" in invoice.keys() else None
        cash = self._payment_account(method, cash_account or stored)
        db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)", (cash, "Cash" if cash == "531" else "Bank", "asset"))
        sale = invoice["kind"] == "sale"
        entry = db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,branch_id,created_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""", (f"PINV-{int(invoice_id)}", invoice["invoice_date"], f"{method} {'received' if sale else 'paid'} - invoice {invoice['invoice_number']}",
            "invoice_payment", int(invoice_id), invoice["currency"], invoice["branch_id"], user_id, utcnow())).lastrowid
        lines = ((cash, paid, Decimal("0")), (invoice["supplier_account"], Decimal("0"), paid)) if sale else \
                ((invoice["supplier_account"], paid, Decimal("0")), (cash, Decimal("0"), paid))
        for code, debit, credit in lines:
            db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,description,debit,credit) VALUES(?,?,?,?,?,?)",
                (entry, self._account_id(db, code), invoice["party_id"], f"Payment {invoice['invoice_number']}", str(debit), str(credit)))
        return entry

    @atomic  # 2.9.121
    def create_missing_invoice_payments(self, user_id):
        """Invoices saved before 2.9.47 as paid (Cash, Bank ...) but without a settlement entry: create it now.
        Each invoice is done on its own; one in a locked or closed period is skipped and reported."""
        with self.connect() as db:
            ids = [r["id"] for r in db.execute("""SELECT i.id FROM invoices i WHERE i.status NOT IN ('cancelled','deleted','void')
                AND CAST(COALESCE(i.amount_paid,'0') AS REAL)>0 AND COALESCE(i.payment_method,'')<>'' AND LOWER(i.payment_method) NOT LIKE 'on account%'
                AND COALESCE(i.doc_subtype,'invoice')<>'credit_note'
                AND NOT EXISTS(SELECT 1 FROM journal_entries e WHERE e.source_type='invoice_payment' AND e.source_id=i.id) ORDER BY i.id""")]
        created, skipped = [], []
        for invoice_id in ids:
            try:
                with self.connect() as db:
                    row = db.execute("SELECT invoice_number,invoice_date FROM invoices WHERE id=?", (invoice_id,)).fetchone()
                    self._assert_period_open(row["invoice_date"])
                    if self._post_invoice_payment(db, invoice_id, user_id): created.append(row["invoice_number"])
            except Exception as exc:
                skipped.append({"invoice_number": row["invoice_number"] if row else str(invoice_id), "reason": str(exc)})
        if created:
            with self.connect() as db:
                db.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                    (user_id, "create_missing_payments", "invoice", json.dumps({"created": created, "skipped": skipped}), utcnow()))
        return {"created": created, "skipped": skipped}

    @atomic  # 2.9.121
    def create_manual_invoice(self, item, line_items, user_id):
        exemption = item.get("income_exemption")
        if exemption is not None:
            from tax_adjustments import reason_text
            if not isinstance(exemption, dict): raise ValueError("Invalid income-tax exemption")
            if self._entry_type(item) != "sales": raise ValueError("Income-tax exemptions apply to sales only")
            reason_text(exemption.get("reason"), exemption.get("article", ""))
        self.require_eur_rate(item.get("currency"), item.get("invoice_date"))
        if not isinstance(line_items, list) or not line_items:
            raise ValueError("Add at least one invoice item")
        normalized = []
        item_cost_accounts = {}
        if self._entry_type(item) not in ("sales", "assets") and any(line.get("item_code") for line in line_items):
            try:
                with self.connect() as db:
                    item_cost_accounts = {str(r["sku"]).upper(): r["cost_account"] for r in db.execute("SELECT sku,cost_account FROM inventory_items WHERE COALESCE(cost_account,'')<>''")}
            except sqlite3.Error:  # 2.9.119: an older file without the column; said in the log
                logging.getLogger("saber").warning("Item cost accounts not read - the invoice accounts are used", exc_info=True); item_cost_accounts = {}
        elif self._entry_type(item) == "sales" and any(line.get("item_code") for line in line_items):  # 2.9.90: the item's sales account
            try:
                with self.connect() as db:
                    item_cost_accounts = {str(r["sku"]).upper(): r["sales_account"] for r in db.execute("SELECT sku,sales_account FROM inventory_items WHERE COALESCE(sales_account,'')<>''")}
            except sqlite3.Error:
                logging.getLogger("saber").warning("Item sales accounts not read - the invoice accounts are used", exc_info=True); item_cost_accounts = {}
        deductible_total = Decimal("0"); non_deductible_total=Decimal("0")
        vat_total = Decimal("0"); expense_splits={}
        for index, line in enumerate(line_items, start=1):
            description = str(line.get("description") or "").strip()
            if not description:
                raise ValueError(f"Item {index}: description is required")
            try:
                quantity = Decimal(str(line.get("quantity") or 0))
                unit_price = Decimal(str(line.get("unit_price") or 0))
                vat_rate = Decimal(str(line.get("vat_rate") if line.get("vat_rate") not in (None, "") else self.vat_rate_percent()))
            except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"Item {index}: invalid quantity, price, or VAT rate") from exc
            if quantity <= 0 or unit_price < 0 or vat_rate < 0:
                raise ValueError(f"Item {index}: values cannot be negative and quantity must be above zero")
            calculated_subtotal = (quantity * unit_price).quantize(Decimal("0.01"))
            supplied_deductible=line.get("deductible_subtotal") if line.get("deductible_subtotal") not in (None,"") else line.get("subtotal")
            deductible=calculated_subtotal if supplied_deductible in (None,"") else Decimal(str(supplied_deductible)).quantize(Decimal("0.01"))
            non_deductible=Decimal(str(line.get("non_deductible_subtotal") or 0)).quantize(Decimal("0.01")); subtotal=deductible+non_deductible
            if min(deductible,non_deductible) < 0:
                raise ValueError(f"Item {index}: total before VAT cannot be negative")
            supplied_vat = line.get("vat")
            vat = (deductible * vat_rate / Decimal("100")).quantize(Decimal("0.01")) if supplied_vat in (None, "") else Decimal(str(supplied_vat)).quantize(Decimal("0.01"))
            if vat < 0:
                raise ValueError(f"Item {index}: VAT cannot be negative")
            total = subtotal + vat
            line_expense_account=str(line.get("expense_account") or "").split(" - ",1)[0].strip() or None
            if not line_expense_account and line.get("item_code") and item_cost_accounts:  # 2.9.80: the item's cost account on every path
                line_expense_account=item_cost_accounts.get(str(line.get("item_code")).strip().upper())
            normalized.append((description, quantity, unit_price, subtotal,deductible,non_deductible,vat_rate,vat,total,str(line.get("item_code") or "").strip() or None))
            deductible_total+=deductible; non_deductible_total+=non_deductible
            vat_total += vat
            if line_expense_account and deductible:
                expense_splits[line_expense_account]=expense_splits.get(line_expense_account,Decimal("0"))+deductible
        invoice = dict(item)
        if self._entry_type(invoice)=="sales" and not str(invoice.get("expense_account") or "").strip() and any(line[9] for line in normalized):
            invoice["expense_account"]=self.default_account("sales_goods")  # 2.9.77: items from stock -> sales of goods (2.9.81: Accounting Settings)
        if not str(invoice.get("invoice_number") or "").strip():
            invoice["invoice_number"] = self.next_invoice_number(invoice.get("kind", "sale"), invoice.get("invoice_date"))
        # 2.9.132: exact decimal text, not float (import_invoice reads them with Decimal(str(...)))
        invoice["deductible_subtotal"]=str(deductible_total); invoice["non_deductible_subtotal"]=str(non_deductible_total)
        invoice["subtotal"] = str(deductible_total+non_deductible_total)
        invoice["vat"] = str(vat_total)
        invoice["total"] = str(deductible_total+non_deductible_total+vat_total)
        defaults=self.default_accounts()  # 2.9.81
        # per-item cost-account routing: split the expense side by each line's own account, remainder on the invoice default
        if expense_splits and self._entry_type(invoice)!="sales":
            default_account=str(invoice.get("expense_account") or defaults["purchases"]).strip()
            routed=sum(expense_splits.values()); remainder=deductible_total-routed
            splits=[(acct,amount) for acct,amount in expense_splits.items()]
            if remainder>Decimal("0.005") or remainder<Decimal("-0.005"):
                splits.append((default_account,remainder))
            invoice["expense_splits"]=[(acct,str(amount)) for acct,amount in splits if amount]
        elif expense_splits:  # 2.9.90: sales lines of items with their own sales account
            default_account=str(invoice.get("expense_account") or defaults.get("sales") or "").strip()
            routed=sum(expense_splits.values()); remainder=deductible_total+non_deductible_total-routed
            splits=list(expense_splits.items())+([(default_account,remainder)] if abs(remainder)>Decimal("0.005") else [])
            invoice["revenue_splits"]=[(acct,str(amount)) for acct,amount in splits if amount]
        if self._entry_type(invoice)!="sales":
            raw_lines=[self._line_for_side(invoice.get("expense_account") or defaults["purchases"],deductible_total,self._side(invoice.get("expense_side"),"D")),
                self._line_for_side(invoice.get("expense_no_vat_account") or defaults["purchases_no_vat"],non_deductible_total,self._side(invoice.get("expense_no_vat_side"),"D")),
                self._line_for_side(invoice.get("vat_account") or defaults["purchase_vat"],vat_total,self._side(invoice.get("vat_side"),"D")),
                self._line_for_side(invoice.get("supplier_account") or DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"],
                        deductible_total+non_deductible_total+vat_total,self._side(invoice.get("supplier_side"),"C"))]
            debit=sum(Decimal(str(line[1])) for line in raw_lines); credit=sum(Decimal(str(line[2])) for line in raw_lines)
            if abs(debit-credit)>=Decimal("0.005"):
                needed=f"Credit {debit-credit}" if debit>credit else f"Debit {credit-debit}"
                raise ValueError(f"Journal Voucher is unbalanced. Total Debit {debit}; Total Credit {credit}; Remaining {needed}")
        invoice_id = self.import_invoice(invoice, user_id)
        with self.connect() as db:
            if str(invoice.get("source_file") or "")=="Journal Voucher":
                db.execute("UPDATE journal_entries SET source_type='journal_voucher' WHERE source_type='invoice' AND source_id=?",(invoice_id,))
            if invoice.get("linked_invoice_id"):
                db.execute("UPDATE invoices SET linked_invoice_id=? WHERE id=?",(int(invoice["linked_invoice_id"]),invoice_id))
            db.executemany("""INSERT INTO invoice_items(invoice_id,description,quantity,unit_price,subtotal,deductible_subtotal,non_deductible_subtotal,vat_rate,vat,total,item_code)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", [
                (invoice_id,description,str(quantity),str(unit_price),str(subtotal),str(deductible),str(non_deductible),str(vat_rate),str(vat),str(total),item_code)
                for description,quantity,unit_price,subtotal,deductible,non_deductible,vat_rate,vat,total,item_code in normalized
            ])
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "manual_entry", "invoice", invoice_id, json.dumps({"items": len(normalized)}), utcnow()))
        self._store_invoice_format(invoice_id, item, line_items)
        if exemption is not None:
            self.set_income_exemption(invoice_id, exemption.get("reason"), exemption.get("article", ""), user_id)
        subtype=str(item.get("doc_subtype") or "invoice").lower(); is_return=bool(item.get("is_return")) and subtype=="credit_note"
        with self.connect() as db: db.execute("UPDATE invoices SET is_return=? WHERE id=?",(1 if is_return else 0,invoice_id))
        # Stock moves for invoices and returns only. A credit note or a debit note is a discount / price
        # adjustment: it never moves goods, even when its lines name items.
        if any(line.get("item_code") for line in line_items) and (subtype=="invoice" or is_return):
            import inventory
            inventory.issue_for_invoice(self, invoice_id, line_items, user_id)
        # Preserve the supplier's invoiced VAT for the quarterly declaration.
        # An exempt-use purchase has no input deduction: transfer that VAT from
        # the receivable account into cost with a separate balanced entry.
        if self._entry_type(invoice) != "sales" and invoice.get("vat_use") == "exempt" and vat_total and not invoice.get("skip_vat_reclass"):
            self.set_vat_recoverable("invoice", invoice_id, False, user_id)
        return invoice_id

    @staticmethod
    def _assert_no_active_linked_assets(db, invoice_id, action):
        asset=db.execute("SELECT asset_code FROM fixed_assets WHERE invoice_id=? AND status='active' LIMIT 1",(int(invoice_id),)).fetchone()
        if asset:
            raise ValueError(f"Cannot {action} invoice: it is linked to active fixed asset {asset['asset_code']}; correct the asset link first")

    @staticmethod
    def _assert_no_active_linked_returns(db,invoice_id,action):
        linked=db.execute("""SELECT invoice_number FROM invoices WHERE linked_invoice_id=?
            AND doc_subtype='credit_note' AND status NOT IN ('cancelled','deleted','void') LIMIT 1""",(int(invoice_id),)).fetchone()
        if linked:
            raise ValueError(f"Cannot {action} this invoice while active linked credit note {linked['invoice_number']} exists; cancel that credit note first")

    @staticmethod
    def _assert_credit_note_not_edited(db,invoice_id):
        row=db.execute("SELECT doc_subtype,status FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
        if row and row["doc_subtype"]=="credit_note" and row["status"] not in ("cancelled","deleted","void"):
            raise ValueError("A posted credit note cannot be edited; cancel it and create a new reviewed return instead")

    @atomic  # 2.9.121
    def delete_invoice(self,invoice_id,user_id,reason=None,role="admin"):
        with self.connect() as db:
            existing = db.execute("SELECT status FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
        if existing and existing["status"] in ("posted", "cancelled", "void"):
            return self.mark_invoice_deleted(invoice_id, user_id, reason=reason, role=role)
        return self._delete_invoice_physical(invoice_id, user_id)

    def _delete_invoice_physical(self, invoice_id, user_id):
        """Legacy physical replacement path used only by the existing posted-invoice edit workflow and draft cleanup."""
        import commercial_documents
        commercial_documents.guard_invoice_edit(self, invoice_id)
        with self.connect() as db:
            invoice=db.execute("SELECT * FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
            if not invoice: raise KeyError(invoice_id)
            self._assert_no_active_linked_returns(db,invoice_id,"delete")
            self._assert_no_active_linked_assets(db,invoice_id,"delete")
            self._assert_period_open(invoice["invoice_date"]); self._assert_vat_open(invoice["invoice_date"])
            details=dict(invoice)
            # 2.9.133: the audit trail keeps every journal line this delete removes (as mark_invoice_deleted does since 2.9.132),
            # so a deleted POSTED invoice can be rebuilt from the audit trail alone
            removed=[dict(r) for r in db.execute("""SELECT e.entry_number,e.entry_date,e.source_type,e.posting_status,e.currency,a.code account,
                j.debit,j.credit,j.line_currency,j.amount,j.amount_lbp,j.amount_usd FROM journal_entries e JOIN journal_lines j ON j.entry_id=e.id
                JOIN accounts a ON a.id=j.account_id WHERE e.source_id=? AND (e.source_type IN ('invoice','journal_voucher','invoice_payment')
                OR (e.source_type='vat_reclass' AND e.entry_number=?)) ORDER BY e.id,j.id""",(int(invoice_id),f"VATND-INV-{int(invoice_id)}"))]
            db.execute("DELETE FROM journal_entries WHERE source_type IN ('invoice','journal_voucher','invoice_payment') AND source_id=?",(int(invoice_id),))
            db.execute("DELETE FROM journal_entries WHERE source_type='vat_reclass' AND entry_number=?",(f"VATND-INV-{int(invoice_id)}",))
            import inventory
            inventory.remove_invoice_documents(db,invoice_id)
            inventory._assert_nonnegative_history(db)
            db.execute("DELETE FROM invoices WHERE id=?",(int(invoice_id),))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"delete","invoice",int(invoice_id),json.dumps({"invoice_number":details.get("invoice_number"),"party_id":details.get("party_id"),"total":details.get("total"),
                "status":details.get("status"),"invoice_date":details.get("invoice_date"),"journal_lines_removed":removed},default=str),utcnow()))
        return {"deleted":int(invoice_id)}

    @atomic
    def mark_invoice_deleted(self, invoice_id, user_id, reason=None, role="admin", void_date=None):
        """Delete drafts; void posted invoices with linked, balanced accounting and stock reversals."""
        import inventory
        invoice_id = int(invoice_id)
        void_date = iso_date(void_date or datetime.now().date().isoformat())
        with self.connect() as db:
            invoice = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if not invoice: raise KeyError(invoice_id)
            if invoice["status"] in ("deleted", "void"): raise ValueError("Invoice is already deleted or void")
            if invoice["status"] == "cancelled": raise ValueError("Cancelled invoice history cannot be deleted")
            posted = invoice["status"] == "posted"
            if posted:
                if role != "admin": raise PermissionError("Only an administrator can void a posted invoice")
                reason = str(reason or "").strip()
            self._assert_no_active_linked_returns(db, invoice_id, "void" if posted else "delete")
            self._assert_no_active_linked_assets(db, invoice_id, "void" if posted else "delete")
            self._assert_period_open(invoice["invoice_date"])
            self._assert_vat_open(invoice["invoice_date"])
            if posted:
                self._assert_period_open(void_date)
                self._assert_books_unlocked(invoice["invoice_date"])
                self._assert_books_unlocked(void_date)
            if db.execute("SELECT 1 FROM payment_allocations WHERE invoice_id=? LIMIT 1", (invoice_id,)).fetchone():
                raise ValueError("Invoice has allocated payments. Remove the allocation before deleting it")
            if db.execute("SELECT 1 FROM invoices WHERE linked_invoice_id=? AND status NOT IN ('cancelled','deleted','void') LIMIT 1", (invoice_id,)).fetchone():
                raise ValueError("Invoice has linked documents. Resolve them before deleting it")
            if posted and not reason: raise ValueError("A reason is required to void a posted invoice")
            invoice = dict(invoice)
            entries = [dict(row) for row in db.execute("""SELECT * FROM journal_entries WHERE
                (source_id=? AND source_type IN ('invoice','invoice_payment')) OR
                (source_type='vat_reclass' AND entry_number=?) ORDER BY id""", (invoice_id, f"VATND-INV-{invoice_id}"))]
            journal_snapshot = []; journal_lines_snapshot = []
            for entry in entries:
                columns = [row["name"] for row in db.execute("PRAGMA table_info(journal_lines)") if row["name"] not in ("id", "entry_id")]
                select_columns = ",".join(f'j."{name}"' for name in columns)
                lines = [dict(row) for row in db.execute(f"SELECT j.id line_id,{select_columns},a.code account_code FROM journal_lines j JOIN accounts a ON a.id=j.account_id WHERE j.entry_id=? ORDER BY j.id", (entry["id"],))]
                journal_snapshot.append({"entry": entry, "lines": lines})
                journal_lines_snapshot.extend({"entry": entry, **line} for line in lines)
                if not posted or entry.get("posting_status") != "posted": continue
                number = f"VOID-INV-{invoice_id}-{entry['id']}"
                if db.execute("SELECT 1 FROM journal_entries WHERE entry_number=?", (number,)).fetchone():
                    raise ValueError(f"Void reversal {number} already exists")
                reversal = dict(entry)
                reversal.update(entry_number=number, entry_date=void_date, description=f"Void {entry.get('entry_number')}: {reason}",
                                source_type="invoice_void", source_id=invoice_id, reversal_of=entry["id"], posting_status="posted",
                                posted_at=utcnow(), posted_by=user_id, rejection_reason=None, created_by=user_id, created_at=utcnow())
                entry_cols = [row["name"] for row in db.execute("PRAGMA table_info(journal_entries)") if row["name"] != "id"]
                db.execute(f"INSERT INTO journal_entries({','.join(entry_cols)}) VALUES({','.join('?' for _ in entry_cols)})",
                           [reversal.get(name) for name in entry_cols])
                reversal_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                reversal_lines = []
                for line in lines:
                    values = {name: line.get(name) for name in columns}
                    values["debit"], values["credit"] = line.get("credit"), line.get("debit")
                    db.execute(f"INSERT INTO journal_lines(entry_id,{','.join(columns)}) VALUES(?,{','.join('?' for _ in columns)})",
                               [reversal_id] + [values.get(name) for name in columns])
                    reversal_lines.append({"entry": {**reversal, "id": reversal_id}, **values,
                                           "line_id": db.execute("SELECT last_insert_rowid()").fetchone()[0],
                                           "account_code": line.get("account_code")})
                journal_lines_snapshot.extend(reversal_lines)
            stock_snapshot = []
            docs = [dict(r) for r in db.execute("SELECT * FROM stock_documents WHERE invoice_id=? ORDER BY id", (invoice_id,))]
            for doc in docs:
                movements = [dict(r) for r in db.execute("SELECT * FROM stock_movements WHERE document_id=? ORDER BY id", (doc["id"],))]
                stock_record = {"document": doc, "movements": movements, "reversal_documents": []}
                stock_snapshot.append(stock_record)
                if not posted: continue
                for movement in movements:
                    qty = Decimal(str(movement["quantity"]))
                    reverse_type = "issue" if qty > 0 else "receipt"
                    movement_type = "purchase_return" if qty > 0 and invoice["kind"] == "purchase" else reverse_type
                    number = f"VOID-INV-{invoice_id}-STK-{doc['id']}-{movement['id']}"
                    reversal_doc = db.execute("""INSERT INTO stock_documents(number,doc_type,doc_date,warehouse_id,party_id,reference,notes,created_by,created_at,project_id,branch_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (number, reverse_type, void_date, movement["warehouse_id"], doc.get("party_id"),
                        invoice["invoice_number"], f"Void invoice {invoice['invoice_number']}: {reason}", user_id, utcnow(), doc.get("project_id"), doc.get("branch_id"))).lastrowid
                    move_cols = [row["name"] for row in db.execute("PRAGMA table_info(stock_movements)") if row["name"] != "id"]
                    values = {name: movement.get(name) for name in move_cols}
                    values.update(movement_date=void_date, quantity=str(-qty), source_type="stock", source_id=reversal_doc,
                                  document_id=reversal_doc, movement_type=movement_type)
                    try: original_layers = json.loads(movement.get("cost_layers") or "[]")
                    except (TypeError, ValueError): original_layers = []
                    if original_layers and qty < 0:
                        layer_value = sum((Decimal(str(part.get("quantity") or 0)) * Decimal(str(part.get("unit_cost") or part.get("cost") or 0))
                                           for part in original_layers), Decimal("0"))
                        if abs(qty): values["unit_cost"] = str(layer_value / abs(qty))
                    if movement_type == "purchase_return":
                        values["cost_layers"] = json.dumps([{"quantity": str(abs(qty)), "unit_cost": str(movement["unit_cost"]),
                            "source_document_id": doc["id"], "source_line_no": movement.get("line_no")}])
                    db.execute(f"INSERT INTO stock_movements({','.join(move_cols)}) VALUES({','.join('?' for _ in move_cols)})",
                               [values.get(name) for name in move_cols])
                    reversal_movement = {**values, "id": db.execute("SELECT last_insert_rowid()").fetchone()[0]}
                    stock_record["reversal_documents"].append({
                        "document": dict(db.execute("SELECT * FROM stock_documents WHERE id=?", (reversal_doc,)).fetchone()),
                        "movement": reversal_movement})
            snapshot = {key: invoice.get(key) for key in ("invoice_number", "kind", "invoice_date", "party_id", "currency", "subtotal", "vat", "total", "status")}
            if posted:
                inventory._assert_nonnegative_history(db)
                inventory.run_costing(self)
                db.execute("UPDATE invoices SET status='void',voided_at=?,voided_by=?,void_reason=? WHERE id=?",
                           (utcnow(), user_id, reason, invoice_id))
                action = "void"
            else:
                inventory.remove_invoice_documents(db, invoice_id)
                inventory._assert_nonnegative_history(db)
                db.execute("DELETE FROM journal_entries WHERE source_type IN ('invoice','journal_voucher','invoice_reversal','invoice_payment') AND source_id=?", (invoice_id,))
                db.execute("DELETE FROM journal_entries WHERE source_type='vat_reclass' AND entry_number=?", (f"VATND-INV-{invoice_id}",))
                db.execute("UPDATE invoices SET status='deleted',cancelled_at=?,cancellation_reason='Deleted' WHERE id=?", (utcnow(), invoice_id))
                action = "mark_deleted"
            details = {"invoice_number": invoice["invoice_number"], "invoice": snapshot, "reason": reason if posted else None,
                       "journal_entries": journal_snapshot, "journal_lines": journal_lines_snapshot, "stock_movements": stock_snapshot}
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id, action, "invoice", invoice_id, json.dumps(details, default=str), utcnow()))
        return {"voided" if posted else "deleted": invoice_id, "invoice_number": invoice["invoice_number"]}

    @atomic  # 2.9.121
    def approve_invoices(self, invoice_ids, user, require_other=True):
        """2.9.93: approval - the selected drafts (review) are posted by a user with the "approve" permission; a draft is
        never approved by the user who prepared it (administrators excepted). Each approval is in the audit trail."""
        approved, skipped = [], []
        for invoice_id in [int(i) for i in invoice_ids or []]:
            with self.connect() as db:
                row = db.execute("SELECT id,invoice_number,invoice_date,status,created_by FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if not row: skipped.append(f"#{invoice_id}: not found"); continue
            if row["status"] != "review": skipped.append(f"{row['invoice_number']}: not a draft ({row['status']})"); continue
            if require_other and row["created_by"] == user["id"]: skipped.append(f"{row['invoice_number']}: prepared by you - another user must approve it"); continue
            try: self._assert_period_open(row["invoice_date"]); self._assert_vat_open(row["invoice_date"])
            except ValueError as exc: skipped.append(f"{row['invoice_number']}: {exc}"); continue
            with self.connect() as db:
                db.execute("""UPDATE invoices SET status='posted',posted_at=?,posted_by=?,rejection_reason=NULL
                    WHERE id=? AND status='review'""", (utcnow(),user["id"],invoice_id))
                db.execute("""UPDATE journal_entries SET posting_status='posted',posted_at=?,posted_by=?,
                    rejection_reason=NULL WHERE source_type='invoice' AND source_id=?""",
                    (utcnow(),user["id"],invoice_id))
                db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                           (user["id"], "approve", "invoice", invoice_id, json.dumps({"invoice_number": row["invoice_number"], "prepared_by": row["created_by"],
                                   "before": "review", "after": "posted"}), utcnow()))
            approved.append(row["invoice_number"])
        return {"approved": approved, "skipped": skipped}

    SNAPSHOT_FIELDS = ("invoice_number", "invoice_date", "party_id", "currency", "subtotal", "vat", "total", "status", "expense_account", "vat_account", "supplier_account", "due_date", "amount_paid")

    def _invoice_snapshot(self, invoice_id):
        with self.connect() as db:
            row = db.execute(f"SELECT {','.join(self.SNAPSHOT_FIELDS)} FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
        return {k: row[k] for k in self.SNAPSHOT_FIELDS} if row else {}

    def _log_change(self, user_id, invoice_id, before, after, entity_id=None):
        """2.9.93: the audit trail keeps what each field was before and after a change."""
        changed = {k: {"before": before.get(k), "after": after.get(k)} for k in self.SNAPSHOT_FIELDS if str(before.get(k)) != str(after.get(k))}
        if not changed: return
        with self.connect() as db:
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id, "change", "invoice", int(entity_id or invoice_id),
                               json.dumps({"invoice_number": after.get("invoice_number") or before.get("invoice_number"), "changes": changed}), utcnow()))

    def update_invoice(self, invoice_id, item, user_id):
        before = self._invoice_snapshot(invoice_id)
        result = self._update_invoice_with_vat(invoice_id, item, user_id)
        try: self._log_change(user_id, invoice_id, before, self._invoice_snapshot(invoice_id))
        except (sqlite3.Error, ValueError, KeyError, TypeError):  # 2.9.119: a change missing from the audit trail is a warning, not silent
            logging.getLogger("saber").warning("Change of invoice %s not written to the audit trail", invoice_id, exc_info=True)
        return result

    def _update_invoice_with_vat(self, invoice_id, item, user_id):
        with self.connect() as db:
            old=db.execute("SELECT invoice_date FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
        self._assert_vat_open(old["invoice_date"] if old else None, item.get("invoice_date"))
        result=self._update_invoice_base(invoice_id, item, user_id)
        with self.connect() as db:
            row=db.execute("SELECT kind,vat_recoverable,status FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
        if row and row["kind"]=="purchase" and not row["vat_recoverable"] and row["status"] not in ("cancelled","deleted","void"):
            self.set_vat_recoverable("invoice",invoice_id,False,user_id)
        return result

    def _update_invoice_base(self, invoice_id, item, user_id):
        import commercial_documents
        commercial_documents.guard_invoice_edit(self, invoice_id, item)
        required = ("invoice_number", "invoice_date", "party_name", "kind", "currency")
        missing = [field for field in required if not str(item.get(field) or "").strip()]
        if missing:
            raise ValueError("Missing fields: " + ", ".join(missing))
        self._assert_period_open(item.get("invoice_date"))
        entry_type=self._entry_type(item); kind = "sale" if entry_type=="sales" else "purchase"
        currency = str(item["currency"]).upper()
        if currency not in self.currency_codes():
            raise ValueError("Currency must be USD, EUR, LBP, or AED")
        try:
            raw_subtotal=Decimal(str(item.get("subtotal") or 0))
            deductible=Decimal(str(item.get("deductible_subtotal") if item.get("deductible_subtotal") not in (None,"") else raw_subtotal))
            non_deductible=Decimal(str(item.get("non_deductible_subtotal") or 0)); subtotal=deductible+non_deductible
            vat = Decimal(str(item.get("vat") or 0))
            total = Decimal(str(item.get("total") or 0))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
            raise ValueError("Before VAT, VAT, and Total must be valid numbers") from exc
        if min(subtotal, vat, total) < 0:
            raise ValueError("Amounts cannot be negative")
        if total != subtotal + vat:
            raise ValueError("Total must equal Before VAT plus VAT")
        supplier_account = str(item.get("supplier_account") or DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"]).strip()
        import chart_extra
        defaults=self.default_accounts()  # 2.9.81
        vat_account = str(item.get("vat_account") or (defaults["output_vat"] if str(item.get("kind","")).lower() in ("sale",
                "sales") else defaults["expense_vat"] if self._entry_type(item)=="expenses" else defaults["purchase_vat"])).strip()
        expense_account = str(item.get("expense_account") or defaults["purchases"]).strip()
        expense_no_vat_account=str(item.get("expense_no_vat_account") or defaults["purchases_no_vat"]).strip()
        supplier_side=self._side(item.get("supplier_side"),"C"); vat_side=self._side(item.get("vat_side"),
                "D"); expense_side=self._side(item.get("expense_side"),"D"); expense_no_vat_side=self._side(item.get("expense_no_vat_side"),"D")
        debit_override=Decimal(str(item.get("debit") or 0)); credit_override=Decimal(str(item.get("credit") or 0))
        if debit_override<0 or credit_override<0: raise ValueError("D and C cannot be negative")
        status = str(item.get("status") or "posted").strip().lower()
        if status not in ("posted", "review"):
            raise ValueError("Status must be posted or review")
        due_date = None
        amount_paid = Decimal(str(item.get("amount_paid") or 0))
        if amount_paid < 0 or amount_paid > total:
            raise ValueError("Amount paid must be between zero and invoice total")
        payment_status = "paid" if amount_paid == total and total > 0 else "partial" if amount_paid > 0 else "unpaid"
        with self.connect() as db:
            existing = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if not existing:
                raise KeyError(invoice_id)
            if existing["status"] in ("cancelled","deleted","void"):
                raise ValueError("Cancelled, deleted, or void invoices cannot be edited")
            self._assert_credit_note_not_edited(db,invoice_id)
            self._assert_no_active_linked_returns(db,invoice_id,"edit")
            self._assert_no_active_linked_assets(db,invoice_id,"edit")
            party_kind = "customer" if kind == "sale" else "supplier"
            party_name = str(item["party_name"]).strip()
            db.execute("INSERT OR IGNORE INTO parties(kind,name,currency) VALUES(?,?,?)", (party_kind, party_name, currency))
            party = db.execute("SELECT * FROM parties WHERE kind=? AND name=?", (party_kind, party_name)).fetchone()
            # 2.9.134 (D3): only when the identity changes - an older file may already hold a duplicate that must stay editable
            if (self.invoice_number_key(item["invoice_number"]) != self.invoice_number_key(existing["invoice_number"])
                    or kind != existing["kind"] or (kind == "purchase" and party["id"] != existing["party_id"])):
                self._assert_unique_invoice_number(db, {**item, "doc_subtype": existing["doc_subtype"] if "doc_subtype" in existing.keys() else item.get("doc_subtype")}, kind, party["id"], exclude_id=invoice_id)
            due_date = self._invoice_due_date(item, party)
            party_account = self._ensure_party_account(db, party)
            if kind == "purchase" and supplier_account == DEFAULT_LEBANESE_ACCOUNTS["accounts_payable"] and party_account:
                supplier_account = party_account
            elif kind == "sale" and (not item.get("supplier_account") or supplier_account==DEFAULT_LEBANESE_ACCOUNTS["accounts_receivable"]):
                supplier_account = party_account
            import vat_ledgers  # 2.9.97: the party's own VAT account
            vat_account = vat_ledgers.party_vat_account(db, supplier_account, vat_account, kind)
            for code, name, account_type in (
                (supplier_account, "Client Account" if kind=="sale" else "Supplier Account", "asset" if kind=="sale" else "liability"),
                (vat_account, "Output VAT Account" if kind=="sale" else "VAT Account", "liability" if kind=="sale" else "asset"),
                (expense_account, "Sales Revenue Account" if kind=="sale" else ("Asset Account" if entry_type=="assets" else "Expense Account"),
                        "income" if kind=="sale" else ("asset" if entry_type=="assets" else "expense")),
                (expense_no_vat_account,"Expenses without VAT","expense"),
            ):
                db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)", (code, name, account_type))
            branch_id=self._branch_id(db,item)
            db.execute("""UPDATE invoices SET invoice_number=?,kind=?,invoice_date=?,party_id=?,currency=?,
                subtotal=?,deductible_subtotal=?,non_deductible_subtotal=?,vat=?,total=?,status=?,supplier_account=?,vat_account=?,expense_account=?,entry_type=?,
                debit_override=?,credit_override=?,supplier_side=?,vat_side=?,expense_side=?,expense_no_vat_account=?,expense_no_vat_side=?,due_date=?,payment_status=?,amount_paid=?,payment_method=?,description=?,branch_id=? WHERE id=?""",
                (str(item["invoice_number"]).strip(), kind, str(item["invoice_date"]).strip(), party["id"], currency,
                 str(subtotal),str(deductible),str(non_deductible),str(vat), str(total), status, supplier_account, vat_account, expense_account,
                 entry_type,str(debit_override),str(credit_override),supplier_side,vat_side,expense_side,expense_no_vat_account,expense_no_vat_side,due_date,
                         payment_status, str(amount_paid),str(item.get("payment_method") or "").strip() or None,
                         str(item.get("description") or "").strip() or None,branch_id, invoice_id))
            entry = db.execute("SELECT id FROM journal_entries WHERE source_type IN ('invoice','journal_voucher') AND source_id=?", (invoice_id,)).fetchone()
            description = f"{entry_type.replace('_',' ').title()} {str(item['invoice_number']).strip()}"
            if entry:
                entry_id = entry["id"]
                db.execute("DELETE FROM journal_lines WHERE entry_id=?", (entry_id,))
                db.execute("UPDATE journal_entries SET entry_date=?,description=?,currency=?,branch_id=? WHERE id=?",
                           (str(item["invoice_date"]).strip(), description, currency,branch_id, entry_id))
            else:
                created = db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,branch_id,created_by,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (f"INV-{invoice_id}", str(item["invoice_date"]).strip(), description,
                    "invoice", invoice_id, currency,branch_id, user_id, utcnow()))
                entry_id = created.lastrowid
            if kind == "sale":
                lines = [(supplier_account, total, Decimal("0")), (expense_account, Decimal("0"), subtotal), (vat_account, Decimal("0"), vat)]
            else:
                lines=[self._line_for_side(expense_account,deductible,expense_side),self._line_for_side(expense_no_vat_account,non_deductible,
                        expense_no_vat_side),self._line_for_side(vat_account,vat,vat_side),self._line_for_side(supplier_account,total,supplier_side)]
            lines=[line for line in lines if Decimal(str(line[1])) or Decimal(str(line[2]))]
            difference=sum(line[1] for line in lines)-sum(line[2] for line in lines)
            if difference>0: lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"],Decimal("0"),difference))
            elif difference<0: lines.append((DEFAULT_LEBANESE_ACCOUNTS["import_variance"],-difference,Decimal("0")))
            for code, debit, credit in lines:
                db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,debit,credit) VALUES(?,?,?,?,?)",
                           (entry_id, self._account_id(db, code), party["id"], str(debit), str(credit)))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id, "update", "invoice", invoice_id, json.dumps({"fields": sorted(item.keys())}), utcnow()))
            self._post_invoice_payment(db, invoice_id, user_id, item.get("cash_account"))
            row = db.execute("""SELECT i.id,i.invoice_number,i.invoice_date,p.name party_name,i.kind,i.currency,
                i.subtotal,i.deductible_subtotal,i.non_deductible_subtotal,i.vat,i.total,i.status,i.currency_issue,i.supplier_account,i.vat_account,
                i.expense_account,i.entry_type,i.debit_override,i.credit_override,i.supplier_side,i.vat_side,i.expense_side,i.expense_no_vat_account,i.expense_no_vat_side,i.source_row,i.due_date,i.payment_status,i.amount_paid,
                CAST(i.total AS REAL)-CAST(i.amount_paid AS REAL) outstanding
                FROM invoices i LEFT JOIN parties p ON p.id=i.party_id WHERE i.id=?""",
                (invoice_id,)).fetchone()
            return dict(row)

    @atomic  # 2.9.121
    def add_invoice_item(self, invoice_id, line, user_id):
        import commercial_documents
        commercial_documents.guard_invoice_edit(self, invoice_id)
        with self.connect() as db:
            old=db.execute("SELECT invoice_date FROM invoices WHERE id=?",(int(invoice_id),)).fetchone()
        if old: self._assert_vat_open(old["invoice_date"])
        description = str(line.get("description") or "").strip()
        if not description:
            raise ValueError("Description is required")
        try:
            quantity = Decimal(str(line.get("quantity") or 0))
            unit_price = Decimal(str(line.get("unit_price") or 0))
            subtotal = Decimal(str(line.get("subtotal") if line.get("subtotal") not in (None, "") else quantity * unit_price))
            vat_rate = Decimal(str(line.get("vat_rate") if line.get("vat_rate") not in (None, "") else self.vat_rate_percent()))
            vat = Decimal(str(line.get("vat") if line.get("vat") not in (None, "") else subtotal * vat_rate / Decimal("100")))
        except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
            raise ValueError("Invalid item amount") from exc
        if quantity <= 0 or min(unit_price, subtotal, vat, vat_rate) < 0:
            raise ValueError("Item values cannot be negative and quantity must be above zero")
        subtotal = subtotal.quantize(Decimal("0.01")); vat = vat.quantize(Decimal("0.01"))
        total = subtotal + vat
        with self.connect() as db:
            row = db.execute("""SELECT i.*,p.name party_name FROM invoices i
                LEFT JOIN parties p ON p.id=i.party_id WHERE i.id=?""", (invoice_id,)).fetchone()
            if not row:
                raise KeyError(invoice_id)
            invoice = dict(row)
        updated_values = {
            "invoice_number": invoice["invoice_number"], "invoice_date": invoice["invoice_date"],
            "party_name": invoice["party_name"], "kind": invoice["kind"], "entry_type":invoice.get("entry_type") or invoice["kind"], "currency": invoice["currency"],
            "subtotal": str(Decimal(str(invoice["subtotal"] or 0)) + subtotal),
            "deductible_subtotal":str(Decimal(str(invoice.get("deductible_subtotal") or 0))+subtotal),
            "non_deductible_subtotal":str(Decimal(str(invoice.get("non_deductible_subtotal") or 0))),
            "vat": str(Decimal(str(invoice["vat"] or 0)) + vat),
            "total": str(Decimal(str(invoice["total"] or 0)) + total),
            "supplier_account": invoice["supplier_account"], "vat_account": invoice["vat_account"],
            "expense_account": invoice["expense_account"], "status": "posted",
            "expense_no_vat_account":invoice.get("expense_no_vat_account",EXPENSE_NO_VAT_ACCOUNT_9),
            "supplier_side":invoice.get("supplier_side","C"),"vat_side":invoice.get("vat_side","D"),"expense_side":invoice.get("expense_side","D"),
                    "expense_no_vat_side":invoice.get("expense_no_vat_side","D"),"payment_method":invoice.get("payment_method",""),
            "due_date": invoice.get("due_date"), "amount_paid": invoice.get("amount_paid", 0),"debit":invoice.get("debit",0),"credit":invoice.get("credit",0),
        }
        updated = self.update_invoice(invoice_id, updated_values, user_id)
        with self.connect() as db:
            db.execute("""INSERT INTO invoice_items(invoice_id,description,quantity,unit_price,subtotal,deductible_subtotal,non_deductible_subtotal,vat_rate,vat,total)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (invoice_id,description,str(quantity),str(unit_price),str(subtotal),str(subtotal),"0",str(vat_rate),str(vat),str(total)))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id, "add_item", "invoice", invoice_id, json.dumps({"description": description}), utcnow()))
        return updated

    @atomic  # 2.9.121
    def cancel_invoice(self, invoice_id, reason, user_id):
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("Cancellation reason is required")
        with self.connect() as db:
            invoice = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if not invoice:
                raise KeyError(invoice_id)
            if invoice["status"] in ("cancelled","deleted","void"):
                raise ValueError("Cancelled, deleted, or void invoices cannot be cancelled")
            self._assert_no_active_linked_returns(db,invoice_id,"cancel")
            self._assert_no_active_linked_assets(db,invoice_id,"cancel")
            self._assert_period_open(invoice["invoice_date"]); self._assert_vat_open(invoice["invoice_date"])
            original = db.execute("SELECT * FROM journal_entries WHERE source_type IN ('invoice','journal_voucher') AND source_id=?", (invoice_id,)).fetchone()
            if not original:
                raise ValueError("Invoice journal entry was not found")
            reverse = db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (f"REV-{invoice_id}", invoice["invoice_date"],
                f"Cancellation of invoice {invoice['invoice_number']}", "invoice_reversal", invoice_id,
                invoice["currency"], user_id, utcnow()))
            lines = db.execute("SELECT account_id,party_id,debit,credit FROM journal_lines WHERE entry_id=?", (original["id"],)).fetchall()
            for line in lines:
                db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,debit,credit) VALUES(?,?,?,?,?)",
                    (reverse.lastrowid, line["account_id"], line["party_id"], line["credit"], line["debit"]))
            db.execute("UPDATE invoices SET status='cancelled',cancelled_at=?,cancellation_reason=? WHERE id=?",
                       (utcnow(), reason, invoice_id))
            db.execute("DELETE FROM journal_entries WHERE source_type='invoice_payment' AND source_id=?", (invoice_id,))  # a void invoice has no payment
            db.execute("DELETE FROM journal_entries WHERE source_type='vat_reclass' AND entry_number=?",(f"VATND-INV-{int(invoice_id)}",))
            import inventory
            inventory.remove_invoice_documents(db,invoice_id)
            inventory._assert_nonnegative_history(db)
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id,"cancel","invoice",invoice_id,json.dumps({"reason":reason}),utcnow()))
        return self.get_invoice(invoice_id)

    @atomic  # 2.9.121
    def duplicate_invoice(self, invoice_id, user_id):
        with self.connect() as db:
            row = db.execute("""SELECT i.*,p.name party_name FROM invoices i
                LEFT JOIN parties p ON p.id=i.party_id WHERE i.id=?""", (invoice_id,)).fetchone()
            if not row:
                raise KeyError(invoice_id)
            source = dict(row)
            items = [dict(item) for item in db.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id", (invoice_id,))]
        new_number = self.next_invoice_number(source["kind"], source["invoice_date"])
        payload = {key:source.get(key) for key in ("invoice_date","party_name","kind","entry_type","currency","exchange_rate",
            "subtotal","vat","total","supplier_account","vat_account","expense_account","expense_no_vat_account","supplier_side","vat_side","expense_side",
                    "expense_no_vat_side","due_date","payment_method")}
        payload.update({"debit":source.get("debit_override"),"credit":source.get("credit_override")})
        payload.update({"invoice_number":new_number,"amount_paid":0,"source_file":"Duplicated invoice","source_row":None})
        new_id = self.import_invoice(payload, user_id)
        if items:
            with self.connect() as db:
                db.executemany("""INSERT INTO invoice_items(invoice_id,description,quantity,unit_price,subtotal,deductible_subtotal,non_deductible_subtotal,vat_rate,vat,total)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""", [(new_id,item["description"],item["quantity"],item["unit_price"],item["subtotal"],
                    item.get("deductible_subtotal",item["subtotal"]),item.get("non_deductible_subtotal",0),item["vat_rate"],item["vat"],item["total"]) for item in items])
                db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                    (user_id,"duplicate","invoice",new_id,json.dumps({"source_invoice_id":invoice_id}),utcnow()))
        return self.get_invoice(new_id)

    def get_invoice(self, invoice_id):
        rows = self.list_invoices(limit=1, _invoice_id=int(invoice_id))
        if not rows:
            raise KeyError(invoice_id)
        return rows[0]

    def invoice_detail(self, invoice_id):
        invoice=self.get_invoice(invoice_id)
        with self.connect() as db:
            items=[dict(row) for row in db.execute("""SELECT ii.id,ii.description,ii.quantity,ii.unit_price,ii.subtotal,ii.deductible_subtotal,ii.non_deductible_subtotal,
                ii.vat_rate,ii.vat,ii.total,ii.item_code,ii.unit,ii.discount_percent,ii.discount_amount,ii.gross_amount,
                COALESCE((SELECT DSUM(CAST(ret.quantity AS REAL)) FROM invoice_items ret JOIN invoices ri ON ri.id=ret.invoice_id
                    WHERE ri.linked_invoice_id=? AND ri.status NOT IN ('cancelled','deleted','void') AND ret.origin_item_id=ii.id),0) returned_quantity,
                COALESCE((SELECT DSUM(CAST(ret.deductible_subtotal AS REAL)) FROM invoice_items ret JOIN invoices ri ON ri.id=ret.invoice_id
                    WHERE ri.linked_invoice_id=? AND ri.status NOT IN ('cancelled','deleted','void') AND ret.origin_item_id=ii.id),0) returned_deductible_subtotal,
                COALESCE((SELECT DSUM(CAST(ret.non_deductible_subtotal AS REAL)) FROM invoice_items ret JOIN invoices ri ON ri.id=ret.invoice_id
                    WHERE ri.linked_invoice_id=? AND ri.status NOT IN ('cancelled','deleted','void') AND ret.origin_item_id=ii.id),0) returned_non_deductible_subtotal,
                COALESCE((SELECT DSUM(CAST(ret.vat AS REAL)) FROM invoice_items ret JOIN invoices ri ON ri.id=ret.invoice_id
                    WHERE ri.linked_invoice_id=? AND ri.status NOT IN ('cancelled','deleted','void') AND ret.origin_item_id=ii.id),0) returned_vat
                FROM invoice_items ii WHERE ii.invoice_id=? ORDER BY ii.id""",(invoice_id,invoice_id,invoice_id,invoice_id,invoice_id))]
        return {"invoice":invoice,"items":items}

    def list_invoices(self, limit=None, _invoice_id=None):
        """Every invoice (2.9.58: the list stopped at the newest 500, so with a big file imported invoices, the
        purchases list, opening an entry and other screens could not find older ones)."""
        limit = int(limit) if limit else -1  # SQLite: LIMIT -1 = no limit
        allocation_invoice_filter = " AND a.invoice_id=?" if _invoice_id is not None else ""
        invoice_filter = "WHERE i.id=?" if _invoice_id is not None else ""
        parameters = (int(_invoice_id), int(_invoice_id), limit) if _invoice_id is not None else (limit,)
        with self.connect() as db:
            return [dict(r) for r in db.execute(f"""SELECT i.id,i.invoice_number,i.invoice_date,p.name party_name,
                i.kind,i.entry_type,i.currency,i.exchange_rate,
                CASE WHEN i.status IN ('deleted','void') THEN '0' ELSE i.subtotal END subtotal,
                CASE WHEN i.status IN ('deleted','void') THEN '0' ELSE i.deductible_subtotal END deductible_subtotal,
                CASE WHEN i.status IN ('deleted','void') THEN '0' ELSE i.non_deductible_subtotal END non_deductible_subtotal,
                CASE WHEN i.status IN ('deleted','void') THEN '0' ELSE i.vat END vat,
                CASE WHEN i.status IN ('deleted','void') THEN '0' ELSE i.total END total,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE COALESCE(CAST(i.debit_override AS REAL),CASE WHEN i.kind='sale' THEN CAST(i.total AS REAL) ELSE 0 END) END debit,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE COALESCE(CAST(i.credit_override AS REAL),CASE WHEN i.kind='purchase' THEN CAST(i.total AS REAL) ELSE 0 END) END credit,
                i.status,i.currency_issue,i.supplier_account,i.vat_account,i.expense_account,i.expense_no_vat_account,
                i.supplier_side,i.vat_side,i.expense_side,i.expense_no_vat_side,i.source_row,
                i.due_date,
                CASE WHEN CAST(i.total AS REAL)>0 AND CAST(i.amount_paid AS REAL)+COALESCE(s.allocated,0)>=CAST(i.total AS REAL)-0.005 THEN 'paid'
                     WHEN CAST(i.amount_paid AS REAL)+COALESCE(s.allocated,0)>0 THEN 'partial' ELSE 'unpaid' END payment_status,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE CAST(i.amount_paid AS REAL) END amount_paid,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE COALESCE(s.allocated,0) END allocated_amount,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE CAST(i.amount_paid AS REAL)+COALESCE(s.allocated,0) END settled_amount,
                i.payment_method,i.description,i.branch_id,COALESCE(b.name,'Head Office') branch_name,
                CASE WHEN i.status IN ('deleted','void') THEN 0 ELSE (CASE WHEN i.doc_subtype='credit_note' THEN -1 ELSE 1 END)*(CAST(i.total AS REAL)-CAST(i.amount_paid AS REAL)-COALESCE(s.allocated,0)) END outstanding,i.cancelled_at,i.cancellation_reason,
                (SELECT COUNT(*) FROM invoice_attachments x WHERE x.invoice_id=i.id) attachment_count,i.vat_recoverable,i.department_id,i.project_id,i.vat_treatment,i.vat_use,
                i.doc_subtype,i.invoice_discount_percent,i.invoice_discount_amount,i.notes,i.linked_invoice_id,COALESCE(i.is_return,0) is_return,i.payment_account
                FROM invoices i LEFT JOIN parties p ON p.id=i.party_id LEFT JOIN branches b ON b.id=i.branch_id
                LEFT JOIN (SELECT a.invoice_id,DSUM(a.amount) allocated FROM payment_allocations a JOIN payments x ON x.id=a.payment_id
                           WHERE {posted_payment_sql()}{allocation_invoice_filter} GROUP BY a.invoice_id) s ON s.invoice_id=i.id
                {invoice_filter} ORDER BY i.id DESC LIMIT ?""", parameters)]

    # ---------------------------------------------------------------- invoices: edit keeping attachments, landed cost
    @atomic  # 2.9.121
    def replace_manual_invoice(self, invoice_id, item, line_items, user_id):
        """Replace an invoice and its linked records in one transaction."""
        import commercial_documents
        commercial_documents.guard_invoice_edit(self, invoice_id)
        with self.connect() as db:
            old = db.execute("SELECT * FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
            if not old: raise KeyError("Invoice not found")
            if old["status"] in ("deleted","cancelled","void"): raise ValueError("Deleted, cancelled, or void invoices cannot be edited")
            self._assert_credit_note_not_edited(db,invoice_id)
            self._assert_no_active_linked_returns(db,invoice_id,"edit")
            self._assert_no_active_linked_assets(db,invoice_id,"edit")
            files = [dict(r) for r in db.execute("SELECT file_name,mime_type,content FROM invoice_attachments WHERE invoice_id=?", (int(invoice_id),))]
            linked = [r["id"] for r in db.execute("SELECT id FROM invoices WHERE linked_invoice_id=?", (int(invoice_id),))]
            self._assert_period_open(old["invoice_date"]); self._assert_vat_open(old["invoice_date"], item.get("invoice_date"))
            item = {**item, "invoice_number": item.get("invoice_number") or old["invoice_number"], "replaces_invoice_id": int(invoice_id)}  # 2.9.134 (D3)
            import inventory
            inventory.remove_invoice_documents(db, invoice_id)
            new_id = self.create_manual_invoice(item, line_items, user_id)
            if "income_exemption" not in item:
                db.execute("""INSERT OR REPLACE INTO income_exemptions(source_type,source_id,reason)
                    SELECT source_type,?,reason FROM income_exemptions WHERE source_type='invoice' AND source_id=?""", (new_id, int(invoice_id)))
            for f in files:
                db.execute("INSERT INTO invoice_attachments(invoice_id,file_name,mime_type,content,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?)",
                    (new_id, f["file_name"], f["mime_type"], f["content"], user_id, utcnow()))
            for linked_id in linked: db.execute("UPDATE invoices SET linked_invoice_id=? WHERE id=?", (new_id, linked_id))
            # Keep an explicitly blocked invoice blocked, but do not carry
            # exempt-use automatic blocking into a newly taxable-use invoice.
            if not old["vat_recoverable"] and old["vat_use"] != "exempt" and item.get("vat_use") != "exempt":
                self.set_vat_recoverable("invoice", new_id, False, user_id)
            before = {k: old[k] for k in self.SNAPSHOT_FIELDS}
            self._delete_invoice_physical(invoice_id, user_id)
            try: self._log_change(user_id, invoice_id, before, self._invoice_snapshot(new_id), new_id)  # 2.9.93
            except (sqlite3.Error, ValueError, KeyError, TypeError):
                logging.getLogger("saber").warning("Change of invoice %s not written to the audit trail", invoice_id, exc_info=True)
            return new_id

    # ---------------------------------------------------------------- invoice format, notes, allocations
    def _store_invoice_format(self, invoice_id, item, line_items):
        """Unit, line discount and invoice discount (for the printed invoice), and invoice / debit note / credit note."""
        subtype = str(item.get("doc_subtype") or "invoice").lower()
        if subtype not in ("invoice", "credit_note", "debit_note"): raise ValueError("Document must be an invoice, a debit note or a credit note")
        with self.connect() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM invoice_items WHERE invoice_id=? ORDER BY id", (int(invoice_id),))]
            for item_id, line in zip(ids, line_items):
                db.execute("UPDATE invoice_items SET unit=?,discount_percent=?,discount_amount=?,gross_amount=? WHERE id=?",
                    (str(line.get("unit") or "") or None, str(line.get("discount_percent") or 0), str(line.get("discount_amount") or 0), str(line.get("gross_amount") or ""), item_id))
            db.execute("UPDATE invoices SET doc_subtype=?,invoice_discount_percent=?,invoice_discount_amount=?,gross_before_discount=?,notes=? WHERE id=?",
                (subtype, str(item.get("invoice_discount_percent") or 0), str(item.get("invoice_discount_amount") or 0), str(item.get("gross_before_discount") or ""),
                 str(item.get("notes") or "") or None, int(invoice_id)))
