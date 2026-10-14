"""2.9.115: Settings > Renumber Documents - numbers back in date order, safely."""
import json
import secrets
import tempfile
import unittest
from pathlib import Path

import resequence
from database import Database


class RenumberTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.folder.name) / "company.db")
        password = secrets.token_hex(16); self.db.initialize(password)
        self.user = self.db.user_for_token(self.db.login("admin", password)["token"])["id"]
        self.party = self.db.save_party({"kind": "customer", "name": "Cedar Client", "currency": "USD"}, self.user)

    def tearDown(self):
        self.folder.cleanup()

    def receipt(self, day, number=None):
        item = {"kind": "customer_receipt", "payment_date": day, "party_id": self.party["id"], "currency": "USD", "amount": "10",
                "cash_account": "531", "party_account": self.party["account_number"]}
        if number: item["payment_number"] = number
        return self.db.add_payment(item, self.user)

    def numbers(self, table="payments", column="payment_number"):
        with self.db.connect() as db:
            return {r["id"]: r["n"] for r in db.execute(f"SELECT id, {column} n FROM {table}")}

    def entry_number(self, source_type, source_id):
        with self.db.connect() as db:
            return db.execute("SELECT entry_number FROM journal_entries WHERE source_type=? AND source_id=?", (source_type, source_id)).fetchone()[0]

    def test_receipts_follow_the_dates_and_their_journal_entries_follow(self):
        march = self.receipt("10-03-2026"); january = self.receipt("10-01-2026"); february = self.receipt("10-02-2026")
        self.assertEqual(self.numbers()[march], "RV-2026-000001")  # entered first, with a later date
        preview = resequence.plan(self.db, "customer_receipt", 2026)
        self.assertEqual(preview["changes"], 3)
        self.assertEqual(self.numbers()[march], "RV-2026-000001")  # the preview changes nothing
        result = resequence.apply(self.db, "customer_receipt", 2026, preview["token"], self.user)
        self.assertEqual(result["renumbered"], 3)
        after = self.numbers()
        self.assertEqual((after[january], after[february], after[march]), ("RV-2026-000001", "RV-2026-000002", "RV-2026-000003"))
        self.assertEqual(self.entry_number("payment", march), "RV-2026-000003")  # the journal shows the same number
        self.assertEqual(resequence.plan(self.db, "customer_receipt", 2026)["changes"], 0)  # now in order
        with self.db.connect() as db:
            log = db.execute("SELECT details FROM audit_log WHERE action='renumber'").fetchone()
        self.assertIn(["RV-2026-000001", "RV-2026-000003"], json.loads(log["details"])["changes"])

    def test_numbers_typed_by_hand_are_never_touched(self):
        later = self.receipt("10-03-2026"); typed = self.receipt("01-01-2026", "RCPT-77")
        preview = resequence.plan(self.db, "customer_receipt", 2026)
        resequence.apply(self.db, "customer_receipt", 2026, preview["token"], self.user)
        self.assertEqual(self.numbers()[typed], "RCPT-77"); self.assertEqual(self.numbers()[later], "RV-2026-000001")

    def test_locked_books_keep_their_numbers_and_the_rest_follows_on(self):
        a = self.receipt("10-02-2026"); b = self.receipt("10-01-2026"); c = self.receipt("20-03-2026"); d = self.receipt("15-03-2026")
        self.db.set_books_lock("28-02-2026", self.user)
        preview = resequence.plan(self.db, "customer_receipt", 2026)
        self.assertEqual(preview["kept"], 2)  # January and February are locked: unchanged even though out of order
        resequence.apply(self.db, "customer_receipt", 2026, preview["token"], self.user)
        after = self.numbers()
        self.assertEqual((after[a], after[b]), ("RV-2026-000001", "RV-2026-000002"))
        self.assertEqual((after[d], after[c]), ("RV-2026-000003", "RV-2026-000004"))

    def test_a_stale_preview_changes_nothing(self):
        self.receipt("10-03-2026"); self.receipt("10-01-2026")
        preview = resequence.plan(self.db, "customer_receipt", 2026)
        self.receipt("05-01-2026")  # someone adds a receipt after the preview
        with self.assertRaisesRegex(ValueError, "changed since the preview"):
            resequence.apply(self.db, "customer_receipt", 2026, preview["token"], self.user)

    def test_journal_vouchers_expenses_and_invoices(self):
        lines = [{"account_code": "511", "debit": 20, "credit": 0}, {"account_code": "512", "debit": 0, "credit": 20}]
        late = self.db.save_journal_voucher({"entry_date": "20-04-2026", "description": "late", "currency": "USD"}, lines, self.user)["voucher"]["id"]
        early = self.db.save_journal_voucher({"entry_date": "02-04-2026", "description": "early", "currency": "USD"}, lines, self.user)["voucher"]["id"]
        resequence.apply(self.db, "journal_voucher", 2026, resequence.plan(self.db, "journal_voucher", 2026)["token"], self.user)
        jv = self.numbers("journal_entries", "entry_number")
        self.assertEqual((jv[early], jv[late]), ("JV-2026-000001", "JV-2026-000002"))

        late_expense = self.db.add_expense({"expense_date": "20-05-2026", "description": "Fuel", "currency": "USD", "with_vat_subtotal": "100", "vat": "11"}, self.user)
        early_expense = self.db.add_expense({"expense_date": "02-05-2026", "description": "Paper", "currency": "USD", "with_vat_subtotal": "50", "vat": "5.5"}, self.user)
        resequence.apply(self.db, "expense", 2026, resequence.plan(self.db, "expense", 2026)["token"], self.user)
        expenses = self.numbers("expenses", "expense_number")
        self.assertEqual((expenses[early_expense], expenses[late_expense]), ("EXP-2026-000001", "EXP-2026-000002"))
        self.assertEqual(self.entry_number("expense", late_expense), "EXP-2026-000002")

        late_invoice = self.db.create_manual_invoice({"invoice_date": "20-06-2026", "party_name": "Cedar Client", "kind": "sale", "currency": "USD"},
                                                     [{"description": "Service", "quantity": 1, "unit_price": 100}], self.user)
        early_invoice = self.db.create_manual_invoice({"invoice_date": "02-06-2026", "party_name": "Cedar Client", "kind": "sale", "currency": "USD"},
                                                      [{"description": "Service", "quantity": 1, "unit_price": 50}], self.user)
        late_id = late_invoice["id"] if isinstance(late_invoice, dict) else int(late_invoice)
        early_id = early_invoice["id"] if isinstance(early_invoice, dict) else int(early_invoice)
        preview = resequence.plan(self.db, "sale", 2026)
        self.assertTrue(preview["warning"])  # sales invoices may already be with the customer
        resequence.apply(self.db, "sale", 2026, preview["token"], self.user)
        invoices = self.numbers("invoices", "invoice_number")
        self.assertEqual((invoices[early_id], invoices[late_id]), ("SAL-2026-000001", "SAL-2026-000002"))
        with self.db.connect() as db:
            text = db.execute("SELECT description FROM journal_entries WHERE source_type='invoice' AND source_id=?", (late_id,)).fetchone()[0]
        self.assertIn("SAL-2026-000002", text); self.assertNotIn("SAL-2026-000001", text)

    def test_only_the_administrator(self):
        import server
        self.assertTrue(server.admin_only("GET", "/api/renumber")); self.assertTrue(server.admin_only("POST", "/api/renumber"))


if __name__ == "__main__":
    unittest.main()
