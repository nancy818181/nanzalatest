"""2.9.110: expenses without an official invoice stay in the books and are listed to add back to the taxable profit."""
import tempfile
import unittest
from pathlib import Path

from database import Database


class NonDeductibleExpensesTest(unittest.TestCase):
    def test_marked_expense_is_listed_and_still_booked(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret12345")
            base = {"expense_date": "05-03-2026", "currency": "USD", "without_vat_subtotal": 50, "vat": 0, "expense_account": "6261", "payment_account": "5311"}
            kept = db.add_expense(dict(base, description="Taxi - no invoice", tax_deductible=False), 1)
            db.add_expense(dict(base, description="Office rent", tax_deductible=True), 1)
            rows = db.non_deductible_expenses(2026)
            self.assertEqual([r["description"] for r in rows], ["Taxi - no invoice"])
            self.assertEqual(rows[0]["subtotal"], 50.0)
            self.assertEqual(db.non_deductible_expenses(2025), [])
            listed = {r["id"]: r["tax_deductible"] for r in db.list_expenses()}
            self.assertEqual(listed[kept], 0)
            with db.connect() as c:  # still in the books
                self.assertEqual(c.execute("SELECT COUNT(*) FROM journal_entries WHERE source_type='expense' AND source_id=?", (kept,)).fetchone()[0], 1)
            db.release()


if __name__ == "__main__":
    unittest.main()
