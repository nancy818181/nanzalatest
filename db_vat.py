"""VAT classification of invoices, recoverable VAT and the provisional ratio.

Part of the Database class (split out of database.py in 2.9.63, code unchanged): Database inherits from VatStore."""
from __future__ import annotations

from database_common import (  # 2.9.102: the names this module uses (no more 'import *')
    Decimal, json, utcnow
)
from database_common import _soft_iso  # noqa: F401


class VatStore:
    # ---------------------------------------------------------------- VAT recoverability
    def set_vat_recoverable(self, source, document_id, recoverable, user_id):
        """Mark purchase/expense VAT as deductible or non-deductible.

        Non-deductible VAT is a cost, so a reclassification entry moves it from the VAT
        receivable account to the expense/asset account; marking it deductible again removes it."""
        source=str(source or "").lower(); document_id=int(document_id); recoverable=1 if recoverable else 0
        if source not in ("invoice","expense"): raise ValueError("VAT status can only be changed on invoices or expenses")
        with self.connect() as db:
            if source=="invoice":
                row=db.execute("SELECT * FROM invoices WHERE id=?",(document_id,)).fetchone()
                if not row: raise KeyError("Invoice not found")
                if row["kind"]!="purchase": raise ValueError("Only purchase and expense VAT can be non-deductible")
                if row["status"]=="cancelled": raise ValueError("Cancelled invoices cannot be changed")
                date=row["invoice_date"]; vat=Decimal(str(row["vat"] or 0)); cost_account=row["expense_account"]; vat_account=row["vat_account"]
                number=row["invoice_number"]; currency=row["currency"]; branch_id=row["branch_id"]; party_id=row["party_id"]
            else:
                row=db.execute("SELECT * FROM expenses WHERE id=?",(document_id,)).fetchone()
                if not row: raise KeyError("Expense not found")
                date=row["expense_date"]; vat=Decimal(str(row["vat"] or 0)); cost_account=row["expense_account"]; vat_account=row["vat_account"]
                number=row["reference"] or f"EXP-{document_id}"; currency=row["currency"]; branch_id=None; party_id=None
        self._assert_period_open(date); self._assert_vat_open(date)
        with self.connect() as db:
            table="invoices" if source=="invoice" else "expenses"
            old=db.execute("SELECT id FROM journal_entries WHERE source_type='vat_reclass' AND entry_number=?",(f"VATND-{source[:3].upper()}-{document_id}",)).fetchone()
            if old:
                db.execute("DELETE FROM journal_lines WHERE entry_id=?",(old["id"],)); db.execute("DELETE FROM journal_entries WHERE id=?",(old["id"],))
            db.execute(f"UPDATE {table} SET vat_recoverable=? WHERE id=?",(recoverable,document_id))
            if not recoverable and vat>0:
                entry=db.execute("""INSERT INTO journal_entries(entry_number,entry_date,description,source_type,source_id,currency,branch_id,created_by,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",(f"VATND-{source[:3].upper()}-{document_id}",date,f"Non-deductible VAT {number}","vat_reclass",document_id,
                            currency,branch_id,user_id,utcnow())).lastrowid
                for code,debit,credit in ((cost_account,vat,Decimal("0")),(vat_account,Decimal("0"),vat)):
                    db.execute("INSERT INTO journal_lines(entry_id,account_id,party_id,description,debit,credit) VALUES(?,?,?,?,?,?)",
                        (entry,self._account_id(db,code),party_id,"Non-deductible VAT reclassification",str(debit),str(credit)))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id,"vat_status",source,document_id,json.dumps({"vat_recoverable":recoverable,"vat":str(vat)}),utcnow()))
        return {"source":source,"id":document_id,"vat_recoverable":recoverable}

    # ---------------------------------------------------------------- Lebanese VAT classification
    SALE_TREATMENTS = ("standard", "zero_rated", "exempt", "out_of_scope")
    PURCHASE_TREATMENTS = ("standard", "reverse_charge")
    VAT_USES = ("taxable", "mixed", "exempt", "export", "utilities", "passenger_car")  # 2.9.92: Budget Law 2026 Art. 30

    def _vat_classification(self, item, kind):
        """VAT treatment of a sale (standard 11% / zero-rated / exempt / out of scope) or purchase (standard / reverse charge),
        and for purchases what the input VAT is used for (taxable sales only, mixed = partial deduction, exempt sales only)."""
        treatment = str(item.get("vat_treatment") or "standard").lower().replace(" ", "_").replace("-", "_")
        treatment = {"taxable": "standard", "zero": "zero_rated", "export": "zero_rated", "outside": "out_of_scope"}.get(treatment, treatment)
        allowed = self.SALE_TREATMENTS if kind in ("sale", "sales") else self.PURCHASE_TREATMENTS
        if treatment not in allowed: raise ValueError("VAT treatment must be one of: " + ", ".join(t.replace("_", " ") for t in allowed))
        use = str(item.get("vat_use") or "mixed").lower()
        if use not in self.VAT_USES: raise ValueError("VAT use must be taxable, mixed, exempt, export, utilities or passenger car")
        return treatment, use

    def set_vat_classification(self, source, document_id, treatment=None, use=None, user_id=None):
        source = str(source or "").lower(); document_id = int(document_id)
        table = {"invoice": "invoices", "expense": "expenses"}.get(source)
        if not table: raise ValueError("VAT classification can only be changed on invoices or expenses")
        with self.connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (document_id,)).fetchone()
            if not row: raise KeyError("Document not found")
        self._assert_period_open(row["invoice_date"] if table == "invoices" else row["expense_date"])
        self._assert_vat_open(row["invoice_date"] if table == "invoices" else row["expense_date"])
        kind = row["kind"] if table == "invoices" else "purchase"
        current = {"vat_treatment": row["vat_treatment"] if table == "invoices" else "standard", "vat_use": row["vat_use"]}
        new_treatment, new_use = self._vat_classification({"vat_treatment": treatment or current["vat_treatment"], "vat_use": use or current["vat_use"]}, kind)
        with self.connect() as db:
            if table == "invoices": db.execute("UPDATE invoices SET vat_treatment=?,vat_use=? WHERE id=?", (new_treatment, new_use, document_id))
            else: db.execute("UPDATE expenses SET vat_use=? WHERE id=?", (new_use, document_id))
            db.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, "vat_classification", source, document_id, json.dumps({"vat_treatment": new_treatment, "vat_use": new_use}), utcnow()))
        return {"source": source, "id": document_id, "vat_treatment": new_treatment, "vat_use": new_use}

    def vat_provisional_ratio(self, year):
        with self.connect() as db:
            row = db.execute("SELECT provisional_ratio FROM vat_settings WHERE year=?", (int(year),)).fetchone()
        return Decimal(str(row["provisional_ratio"])) if row and row["provisional_ratio"] not in (None, "") else None

    def save_vat_provisional_ratio(self, year, ratio, user_id):
        if ratio in (None, ""):
            with self.connect() as db: db.execute("DELETE FROM vat_settings WHERE year=?", (int(year),))
            return None
        try: value = Decimal(str(ratio).replace("%", "").replace(",", ""))
        except Exception as exc: raise ValueError("The deduction ratio must be a percentage, for example 85") from exc
        if value > 1: value = value / 100
        if value < 0 or value > 1: raise ValueError("The deduction ratio must be between 0% and 100%")
        with self.connect() as db:
            db.execute("""INSERT INTO vat_settings(year,provisional_ratio,updated_by,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(year) DO UPDATE SET provisional_ratio=excluded.provisional_ratio,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (int(year), str(value), user_id, utcnow()))
        return value
