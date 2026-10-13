"""2.9.63: stability and speed checks, and database.py split into db_*.py parts."""
import random
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import database
from test_final_features import new_db


class SplitTest(unittest.TestCase):
    def test_database_is_still_one_class(self):
        import db_dimensions, db_documents, db_invoices, db_journal, db_payments, db_payroll, db_rates, db_reports, db_vat
        parts = (db_invoices.InvoicesStore, db_journal.JournalStore, db_documents.DocumentsStore, db_payments.PaymentsStore, db_rates.RatesStore,
                 db_reports.ReportsStore, db_payroll.PayrollStore, db_dimensions.DimensionsStore, db_vat.VatStore)
        for part in parts: self.assertTrue(issubclass(database.Database, part), part)
        for name in ("import_invoice", "add_payment", "save_journal_voucher", "trial_balance", "calculate_payroll", "save_department", "set_vat_classification", "backup", "login"):
            self.assertTrue(callable(getattr(database.Database, name)), name)
        # names other modules import from database keep working
        from database import Database, display_date, iso_date, utcnow  # noqa: F401
        self.assertLess(len(Path(database.__file__).read_text(encoding="utf-8").splitlines()), 1500)

    def test_editing_a_payment_still_uses_a_safe_copy(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = new_db(folder)
            party = db.save_party({"kind": "supplier", "name": "BFG"}, user)
            payment = db.add_payment({"kind": "supplier_payment", "payment_date": "15-03-2025", "amount": "100", "currency": "USD", "party_id": party["id"], "cash_account": "531"}, user)
            db.update_payment(payment, {"kind": "supplier_payment", "payment_date": "16-03-2025", "amount": "80", "currency": "USD", "party_id": party["id"], "cash_account": "531"}, user)
            self.assertEqual([float(p["amount"]) for p in db.list_payments()], [80.0])


class DatesTest(unittest.TestCase):
    def test_report_dates_accept_both_formats(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = new_db(folder)
            party = db.save_party({"kind": "supplier", "name": "BFG"}, user)
            for day, amount in (("15-03-2025", "100"), ("2025-03-16", "7")):
                db.add_payment({"kind": "supplier_payment", "payment_date": day, "amount": amount, "currency": "USD", "party_id": party["id"], "cash_account": "531"}, user)
            for start in ("16-03-2025", "2025-03-16"):
                numbers = {r["entry_number"] for r in db.journal(start, "31-03-2025")}
                self.assertEqual(numbers, {"PV-2025-000002"}, start)
                cash = [r for r in db.trial_balance(start, "31-12-2025") if r["code"] == "531"][0]
                self.assertEqual((cash["opening"], cash["credit"]), (-100.0, 7.0))


class RatesTest(unittest.TestCase):
    def test_kept_rates_give_the_same_answer_as_the_database(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, _user = new_db(folder)
            rnd = random.Random(7)
            with db.connect() as c:
                for _ in range(250):
                    pair = rnd.choice([("EUR", "USD"), ("USD", "LBP"), ("LBP", "USD"), ("AED", "USD"), ("USD", "SAR")])
                    day = (date(2024, 1, 1) + timedelta(days=rnd.randint(0, 600))).strftime(rnd.choice(["%Y-%m-%d", "%d-%m-%Y"]))
                    c.execute("INSERT OR IGNORE INTO exchange_rates(from_currency,to_currency,rate_date,rate,created_at) VALUES(?,?,?,?,?)",
                              (*pair, day, rnd.choice([str(round(rnd.uniform(0.5, 2), 4)), str(rnd.randint(85000, 90000)), "0"]), "x"))
            sortable = """CASE WHEN rate_date GLOB '??-??-????' THEN substr(rate_date,7,4)||substr(rate_date,4,2)||substr(rate_date,1,2) ELSE replace(rate_date,'-','') END"""
            def by_sql(frm, to, key):
                with db.connect() as c:
                    row = c.execute(f"SELECT rate FROM exchange_rates WHERE from_currency=? AND to_currency=? AND {sortable}<=? ORDER BY {sortable} DESC,id DESC LIMIT 1", (frm, to, key)).fetchone()
                return Decimal(str(row["rate"])) if row else None
            db._rate_cache(); table = db._rate_table()
            import bisect
            for _ in range(800):
                frm, to = rnd.choice([("EUR", "USD"), ("USD", "LBP"), ("LBP", "USD"), ("USD", "SAR"), ("USD", "EUR")])
                key = (date(2023, 12, 1) + timedelta(days=rnd.randint(0, 700))).strftime("%Y%m%d")
                found = table.get((frm, to)); kept = None
                if found:
                    index = bisect.bisect_right(found[0], key); kept = Decimal(str(found[1][index - 1][2])) if index else None
                self.assertEqual(kept, by_sql(frm, to, key), (frm, to, key))


class NoVatRightTest(unittest.TestCase):
    def test_financial_reports_do_not_ask_vat_without_the_right(self):
        text = (Path(__file__).resolve().parent / "desktop_reports.py").read_text(encoding="utf-8")
        self.assertIn('if self.can_use("vat") else {"items":[],"summary":[],"_hidden":True}', text)


if __name__ == "__main__":
    unittest.main()
