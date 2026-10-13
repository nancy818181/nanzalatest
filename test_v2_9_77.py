"""2.9.77: sales are booked on the customer's own account, a class 7 revenue account and output VAT (4427), whatever
the way they come in (Excel import, sales screen, sales import); older wrongly booked sales can be checked and corrected."""
import os
import tempfile
import unittest
from unittest import mock
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

import importer
from company_manager import CompanyManager
from database import Database


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)

    def lines(self, invoice_id):
        with self.db.connect() as db:
            return {r["code"]: (Decimal(r["debit"]), Decimal(r["credit"])) for r in db.execute(
                """SELECT a.code,j.debit,j.credit FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
                   WHERE e.source_type='invoice' AND e.source_id=?""", (invoice_id,))}

    def party_account(self, name):
        with self.db.connect() as db:
            return db.execute("SELECT account_number FROM parties WHERE name=?", (name,)).fetchone()[0]


class ExcelSalesTest(_Book):
    def test_excel_sale_is_booked_to_the_customer_revenue_and_output_vat(self):
        book = Workbook(); sheet = book.active
        sheet.append(["Invoice Number", "Date", "Customer", "Before VAT", "VAT", "Total", "Currency"])
        sheet.append(["S-100", "10-02-2026", "Client Excel", 1000, 110, 1110, "USD"])
        path = Path(self.folder.name) / "sales.xlsx"; book.save(path)
        row = importer.read_invoices(path, default_currency="USD", default_kind="sale", allowed_currencies=["USD", "LBP"])[0]
        self.assertEqual((row["supplier_account"], row["expense_account"], row["vat_account"]), ("", "713", "4427"))
        invoice_id = self.db.import_invoice({**row, "entry_type": "sales", "kind": "sale"}, 1)
        invoice_id = invoice_id["id"] if isinstance(invoice_id, dict) else invoice_id
        own = self.party_account("Client Excel")
        self.assertTrue(own.startswith("411"))
        self.assertEqual(self.lines(invoice_id), {own: (Decimal("1110.0"), Decimal("0")), "713": (Decimal("0"), Decimal("1000.0")), "4427": (Decimal("0"), Decimal("110.0"))})

    def test_a_sale_sent_with_the_old_wrong_defaults_is_corrected(self):
        invoice_id = self.db.import_invoice({"invoice_number": "S-1", "invoice_date": "10-02-2026", "party_name": "Old Style", "kind": "sale", "entry_type": "sales",
            "currency": "USD", "subtotal": 100, "vat": 11, "total": 111, "supplier_account": "4011", "expense_account": "601100000", "vat_account": "442660000"}, 1)
        invoice_id = invoice_id["id"] if isinstance(invoice_id, dict) else invoice_id
        self.assertEqual(set(self.lines(invoice_id)), {self.party_account("Old Style"), "713", "4427"})

    def test_purchases_are_unchanged(self):
        invoice_id = self.db.import_invoice({"invoice_number": "P-1", "invoice_date": "10-02-2026", "party_name": "Supplier", "kind": "purchase",
            "currency": "USD", "subtotal": 100, "vat": 11, "total": 111, "supplier_account": "4011", "expense_account": "601100000", "vat_account": "44210"}, 1)
        invoice_id = invoice_id["id"] if isinstance(invoice_id, dict) else invoice_id
        self.assertEqual(set(self.lines(invoice_id)), {self.party_account("Supplier"), "601100000", "44210"})


class RepairOldSalesTest(_Book):
    def test_old_wrong_sale_is_listed_and_corrected_without_changing_amounts(self):
        invoice_id = self.db.import_invoice({"invoice_number": "S-OLD", "invoice_date": "10-02-2026", "party_name": "Client Old", "kind": "sale", "entry_type": "sales",
            "currency": "USD", "subtotal": 1000, "vat": 110, "total": 1110}, 1)
        invoice_id = invoice_id["id"] if isinstance(invoice_id, dict) else invoice_id
        with self.db.connect() as db:  # as an earlier version booked an Excel sale
            for good, bad in ((self.party_account("Client Old"), "4011"), ("713", "601100000"), ("4427", "442660000")):
                db.execute("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)", (bad, bad, "asset"))
                db.execute("UPDATE journal_lines SET account_id=(SELECT id FROM accounts WHERE code=?) WHERE account_id=(SELECT id FROM accounts WHERE code=?)", (bad, good))
            db.execute("UPDATE invoices SET supplier_account='4011',expense_account='601100000',vat_account='442660000' WHERE id=?", (invoice_id,))
        problems = self.db.sales_account_problems()
        self.assertEqual([p["invoice_number"] for p in problems], ["S-OLD"])
        self.assertEqual(set(problems[0]["fixes"]), {"supplier_account", "expense_account", "vat_account"})
        result = self.db.fix_sales_accounts([invoice_id], 1)
        self.assertEqual(result, {"done": ["S-OLD"], "skipped": []})
        own = self.party_account("Client Old")
        self.assertEqual(self.lines(invoice_id), {own: (Decimal("1110.0"), Decimal("0")), "713": (Decimal("0"), Decimal("1000.0")), "4427": (Decimal("0"), Decimal("110.0"))})
        self.assertEqual(self.db.sales_account_problems(), [])

    def test_correct_sales_are_not_listed(self):
        self.db.import_invoice({"invoice_number": "S-OK", "invoice_date": "10-02-2026", "party_name": "Client Fine", "kind": "sale", "entry_type": "sales",
            "currency": "USD", "subtotal": 10, "vat": 1.1, "total": 11.1}, 1)
        self.assertEqual(self.db.sales_account_problems(), [])


class OpeningWithNewCustomerTest(unittest.TestCase):
    def test_customer_opened_last_year_after_the_new_year_reaches_the_opening(self):
        environment = dict(os.environ); environment.pop("SABER_FIRST_COMPANY", None)
        with mock.patch.dict(os.environ, environment, clear=True), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder); master = Database(root / "saber_accounting.db"); master.initialize("secret")
            manager = CompanyManager(root / "saber_accounting.db")
            company = manager.create_company({"name": "Opening Test SAL", "year": 2025}, master)
            manager.create_year(company["id"], 2026, 1)  # the new year exists before the sale below
            old = manager.database(company["id"], 2025)
            old.import_invoice({"invoice_number": "S-1", "invoice_date": "15-12-2025", "party_name": "Late Client", "kind": "sale", "entry_type": "sales",
                                "currency": "USD", "subtotal": 100, "vat": 11, "total": 111}, 1)
            with old.connect() as db: code = db.execute("SELECT account_number FROM parties WHERE name='Late Client'").fetchone()[0]
            manager.refresh_opening(company["id"], 2025, 1)
            new = manager.database(company["id"], 2026)
            with new.connect() as db:
                self.assertTrue(db.execute("SELECT 1 FROM accounts WHERE code=?", (code,)).fetchone())
                self.assertTrue(db.execute("SELECT 1 FROM parties WHERE account_number=?", (code,)).fetchone())
                debit = db.execute("""SELECT SUM(CAST(j.debit AS REAL)) FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
                                      WHERE a.code=? AND e.source_type='opening'""", (code,)).fetchone()[0]
            self.assertEqual(debit, 111)
            for path in list(manager._cache): manager._cache.pop(path).release()
            master.release()


if __name__ == "__main__":
    unittest.main()
