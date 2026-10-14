"""2.9.58: every invoice is listed (no 500 limit), exchange rates are cached but follow a new rate at once."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class SpeedAndLimitsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "c.db"); self.db.initialize("secret")

    def tearDown(self):
        self.db.release(); self.temp.cleanup()

    def test_more_than_500_invoices_are_listed(self):
        for n in range(620):
            self.db.import_invoice({"invoice_number": f"P{n}", "invoice_date": "05-03-2026", "party_name": "S", "kind": "purchases",
                                    "currency": "USD", "subtotal": 10, "vat": 0, "total": 10}, 1)
        self.assertEqual(len(self.db.list_invoices()), 620)

    def test_cached_rate_follows_a_new_rate(self):
        first = self.db._converted_amount(Decimal("100"), "EUR", "USD", "2026-03-05")
        self.db.save_exchange_rate({"rate_date": "05-03-2026", "from_currency": "EUR", "to_currency": "USD", "rate": "2"}, 1)
        self.assertEqual(self.db._converted_amount(Decimal("100"), "EUR", "USD", "2026-03-05"), Decimal("200"))
        self.assertIsNotNone(first)


if __name__ == "__main__":
    unittest.main()
