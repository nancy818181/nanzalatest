"""2.9.119: Start with Nanza - opening balances, customers / suppliers, open invoices and items from one Excel file."""
import tests_setup  # noqa: F401
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import books_check
import onboarding
from test_final_features import new_db


def fill(path, opening=(), parties=(), invoices=(), items=()):
    from openpyxl import load_workbook
    onboarding.template(path)
    book = load_workbook(path)
    for title, rows in (("Opening balances", opening), ("Customers & Suppliers", parties), ("Open invoices", invoices), ("Items", items)):
        for row in rows: book[title].append(list(row))
    book.save(path)
    return onboarding.read(path)


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        self.path = Path(self.folder.name) / "start.xlsx"

    def good(self):
        return fill(self.path,
                    opening=[("5121", 10000, None, "USD", "Bank"), ("411", 1500, None, "USD", "Customers"), ("401", None, 400, "USD", "Suppliers"),
                             ("37", 2000, None, "USD", "Stock"), ("101", None, 13100, "USD", "Capital")],
                    parties=[("customer", "Cedar Trading", "USD", "123", "", "01 234567", "Beirut", 30), ("supplier", "Byblos Paper", "USD")],
                    invoices=[("sale", "OLD-101", "15-11-2025", "15-12-2025", "Cedar Trading", "USD", 1000),
                              ("sale", "OLD-102", "20-12-2025", "", "Cedar Trading", "USD", 500),
                              ("purchase", "BP-9", "10-12-2025", "", "Byblos Paper", "USD", 400)],
                    items=[("PAP-A4", "Paper A4", "box", 6, 400, 5, "MAIN")])

    def test_check_then_import(self):
        data = self.good()
        check = onboarding.check(self.db, data, "01-01-2026")
        self.assertEqual(check["problems"], [])
        self.assertEqual(check["counts"]["open_invoices"], 3); self.assertEqual(check["counts"]["items"], 1)
        result = onboarding.apply(self.db, data, "01-01-2026", self.user)
        self.assertEqual(result["vouchers"], ["OB-2026-USD"])
        with self.db.connect() as db:
            clearing = db.execute("""SELECT SUM(CAST(l.debit AS REAL)-CAST(l.credit AS REAL)) FROM journal_lines l JOIN accounts a ON a.id=l.account_id
                WHERE a.code=?""", (onboarding.CLEARING,)).fetchone()[0]
            party_account = db.execute("SELECT account_number FROM parties WHERE name='Cedar Trading'").fetchone()[0]
            customer = db.execute("""SELECT SUM(CAST(l.debit AS REAL)-CAST(l.credit AS REAL)) FROM journal_lines l JOIN accounts a ON a.id=l.account_id
                WHERE a.code=?""", (party_account,)).fetchone()[0]
            stock = db.execute("SELECT COUNT(*) FROM stock_documents WHERE doc_type='opening'").fetchone()[0]
        self.assertAlmostEqual(clearing, 0.0)  # open invoices agree with the 40 / 41 balances
        self.assertAlmostEqual(customer, 1500.0)  # the customer's own account carries its open invoices
        self.assertEqual(stock, 1)
        # not a sale of this year: not in the VAT return, nor in the dashboard sales; but in the ageing
        import vat_return
        from business_reports import ageing
        documents = vat_return.build_vat_return(self.db, 2025, 4)["documents"]
        self.assertFalse([d for d in documents if d["number"].startswith("OLD-")])
        self.assertFalse([row for row in self.db.dashboard() if row["kind"] == "sale" and row["subtotal"]])
        report = ageing(self.db, {"date_to": "31-01-2026", "side": "receivables", "basis": "USD"})
        self.assertIn("Decimal('1500.00')", str(report["sections"][1]["rows"][0]))
        self.assertIn("OLD-101", str(report["sections"]))
        check = books_check.run(self.db, 2026)
        bad = [(r["check"], r["detail"]) for r in check["results"] if r["status"] == "ERROR"]
        self.assertEqual(bad, [])
        again = onboarding.check(self.db, data, "01-01-2026")
        self.assertTrue(any("already imported" in p for p in again["problems"]))

    def test_every_wrong_line_is_listed_and_nothing_saved(self):
        data = fill(self.path,
                    opening=[("5121", 100, None, "USD"), ("99999", 5, None, "USD"), ("7011", None, 50, "USD"), ("101", None, 90, "USD")],
                    parties=[("friend", "X")],
                    invoices=[("sale", "N-1", "01-02-2026", "", "Nobody", "USD", 10), ("sale", "N-2", "bad", "", "Nobody", "USD", -1)],
                    items=[("", "", "unit")])
        check = onboarding.check(self.db, data, "01-01-2026")
        text = "\n".join(check["problems"])
        for expected in ("99999", "7011", "Type must be customer or supplier", "Nobody", "not balanced", "item name is empty"):
            self.assertIn(expected, text)
        with self.assertRaises(ValueError): onboarding.apply(self.db, data, "01-01-2026", self.user)
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
