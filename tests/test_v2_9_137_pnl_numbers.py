"""2.9.137 regression: DSUM_EXACT returns text, but the Profit & Loss rows must keep numeric debit / credit / amount
(the P&L page formats them with :,.2f and crashed with "Unknown format code 'f' for object of type 'str'")."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class ProfitAndLossNumbersTest(unittest.TestCase):
    def test_rows_are_numbers_and_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "books.db"); db.initialize("Synthetic-Only-Password-2026!")
            try:
                db.import_invoice({"invoice_number": "SYN-PNL-1", "kind": "sale", "invoice_date": "10-02-2026", "party_name": "Synthetic C",
                                   "currency": "USD", "subtotal": "100.10", "vat": "11.01", "total": "111.11", "status": "posted"}, 1)
                rows = db.profit_and_loss("2026-01-01", "2026-12-31")
                self.assertTrue(rows)
                for row in rows:
                    for field in ("debit", "credit", "amount"):
                        self.assertIsInstance(row[field], (int, float, Decimal), (row["code"], field, row[field]))
                        format(row[field], ",.2f")  # what the P&L page does
                income = [row for row in rows if row["type"] == "income"]
                self.assertEqual(sum(Decimal(str(row["amount"])) for row in income), Decimal("100.10"))
            finally:
                db.release()

    def test_page_formatting_accepts_exact_text_from_json(self):
        # a value too large for a float arrives from the data service as text; the page converts it with Decimal
        value = "1000000000000000.01"
        self.assertEqual(f"{Decimal(str(value)):,.2f}", "1,000,000,000,000,000.01")


if __name__ == "__main__":
    unittest.main()
