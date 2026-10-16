"""2.9.121: the points confirmed in the review of the posting code (ChatGPT + Claude, checked by Bassam)."""
import tests_setup  # noqa: F401
import sqlite3
import tempfile
import unittest
from decimal import Decimal

import vat_return
from test_final_features import new_db


class ReviewFixesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        self.customer = self.db.save_party({"kind": "customer", "name": "Cedar Trading", "currency": "USD"}, self.user)

    def invoice(self, number, amount):
        saved = self.db.create_manual_invoice({"invoice_number": number, "invoice_date": "10-01-2026", "party_name": "Cedar Trading", "kind": "sale",
                                               "currency": "USD"}, [{"description": "Consulting", "quantity": 1, "unit_price": amount, "vat_rate": 0}], self.user)
        return saved["id"] if isinstance(saved, dict) else int(saved)

    def receipt(self, amount):
        saved = self.db.add_payment({"kind": "customer_receipt", "payment_date": "15-01-2026", "party_id": self.customer["id"], "currency": "USD",
                                     "amount": str(amount), "cash_account": "531", "party_account": self.customer["account_number"]}, self.user)
        return saved["id"] if isinstance(saved, dict) else int(saved)

    def test_an_invoice_is_never_allocated_more_than_is_open(self):
        invoice = self.invoice("SAL-1", 100); big = self.receipt(1000)
        with self.assertRaisesRegex(ValueError, "only 100.00 USD is still open"):
            self.db.save_allocations(big, [{"invoice_id": invoice, "amount": 1000}], self.user)
        self.assertEqual(self.db.payment_allocations(big), [])  # nothing half saved
        self.db.save_allocations(big, [{"invoice_id": invoice, "amount": 100}], self.user)  # the other 900 stay unapplied
        second = self.receipt(50)
        with self.assertRaisesRegex(ValueError, "only 0.00 USD is still open"):
            self.db.save_allocations(second, [{"invoice_id": invoice, "amount": 50}], self.user)
        self.db.save_allocations(big, [{"invoice_id": invoice, "amount": 60}], self.user)  # the same payment changed: its own part is free again
        self.db.save_allocations(second, [{"invoice_id": invoice, "amount": 40}], self.user)
        self.assertEqual(sum(float(a["amount"]) for a in self.db.payment_allocations(second)), 40)

    def test_a_missing_euro_rate_is_never_one_dollar(self):
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' OR to_currency='EUR'")
        self.db.__dict__.pop("_rate_state", None)
        with self.assertRaisesRegex(ValueError, "No EUR exchange rate"):  # an EUR document waits for a real rate
            self.db.create_manual_invoice({"invoice_number": "E-1", "invoice_date": "15-03-2026", "party_name": "Cedar Trading", "kind": "sale",
                                           "currency": "EUR"}, [{"description": "Consulting", "quantity": 1, "unit_price": 1000}], self.user)
        self.db.save_exchange_rate({"rate_date": "20-03-2026", "from_currency": "EUR", "to_currency": "USD", "rate": "1.2"}, self.user)
        self.assertEqual(round(Decimal(str(self.db._converted_amount(Decimal("1000"), "EUR", "USD", "15-03-2026"))), 2), Decimal("1200.00"))
        self.db.save_exchange_rate({"rate_date": "10-03-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, self.user)
        with sqlite3.connect(self.db.path) as connection:  # no EUR/LBP made from a missing EUR/USD
            made = connection.execute("SELECT rate FROM exchange_rates WHERE rate_date IN ('10-03-2026','2026-03-10') AND from_currency='EUR' AND to_currency='LBP'").fetchall()
        self.assertEqual(made, [])

    def test_vat_amounts_are_read_exactly(self):
        self.db.add_expense({"expense_date": "12-02-2026", "description": "Taxi", "currency": "USD", "with_vat_subtotal": "0", "without_vat_subtotal": "100",
                             "vat": "0", "expense_account": "6263.2", "expense_without_vat_account": "6263.2"}, self.user)
        documents, skipped, _ = vat_return._documents(self.db, "2026-01-01", "2026-03-31", None, False)
        taxi = next(d for d in documents if d["source"] == "expense")
        self.assertEqual((taxi["base"], taxi["exempt"]), (Decimal("0.00"), Decimal("100.00")))
        with sqlite3.connect(self.db.path) as connection:
            connection.execute("UPDATE expenses SET vat='110,00'")
        documents, skipped, _ = vat_return._documents(self.db, "2026-01-01", "2026-03-31", None, False)
        self.assertFalse([d for d in documents if d["source"] == "expense"])  # not counted as 0 ...
        self.assertIn("vat '110,00' is not a number", skipped[0])  # ... listed for correction

    def test_vat_settlement_is_replaced_whole(self):
        import inspect
        source = inspect.getsource(vat_return.post_settlement)
        body = source[source.index("with db.connect() as connection:"):]
        self.assertIn("save_journal_voucher", body.split("return {")[0])  # the new vouchers are written inside the same transaction


if __name__ == "__main__":
    unittest.main()
