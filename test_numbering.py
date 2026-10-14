"""2.9.116: naming series - prefix per kind of document, branch in the number; default unchanged."""
import secrets
import tempfile
import unittest
from pathlib import Path

import numbering
import resequence
from database import Database


class NumberingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.folder.name) / "company.db")
        password = secrets.token_hex(16); self.db.initialize(password)
        self.user = self.db.user_for_token(self.db.login("admin", password)["token"])["id"]
        self.party = self.db.save_party({"kind": "customer", "name": "Client", "currency": "USD"}, self.user)

    def tearDown(self):
        self.folder.cleanup()

    def receipt(self, day):
        pid = self.db.add_payment({"kind": "customer_receipt", "payment_date": day, "party_id": self.party["id"], "currency": "USD", "amount": "5",
                                   "cash_account": "531", "party_account": self.party["account_number"]}, self.user)
        with self.db.connect() as db: return db.execute("SELECT payment_number FROM payments WHERE id=?", (pid,)).fetchone()[0]

    def test_default_numbers_are_unchanged(self):
        self.assertEqual(self.receipt("01-02-2026"), "RV-2026-000001")
        self.assertEqual(self.db.next_invoice_number("sale", "01-02-2026"), "SAL-2026-000001")
        self.assertEqual(self.db.next_document_number("expense", "01-02-2026"), "EXP-2026-000001")
        self.assertEqual(self.db.next_document_number("journal_voucher", "01-02-2026"), "JV-2026-000001")

    def test_own_prefix_and_branch_in_the_number(self):
        numbering.save_settings(self.db, {"customer_receipt": {"prefix": "rec"}, "sale": {"prefix": "INV2", "branch": True},
                                          "journal_voucher": {"prefix": "JV", "branch": True}}, self.user)
        self.assertEqual(self.receipt("01-02-2026"), "REC-2026-000001")
        self.assertEqual(self.db.next_invoice_number("sale", "01-02-2026", "Beirut"), "INV2-BEI-2026-000001")
        self.assertEqual(self.db.next_invoice_number("sale", "01-02-2026"), "INV2-HO-2026-000001")
        self.assertEqual(self.db.next_invoice_number("credit_note", "01-02-2026"), "CN-2026-000001")  # other documents keep theirs
        lines = [{"account_code": "511", "debit": 5, "credit": 0}, {"account_code": "512", "debit": 0, "credit": 5}]
        saved = self.db.save_journal_voucher({"entry_date": "02-02-2026", "description": "x", "currency": "USD", "branch": "Jounieh Main"}, lines, self.user)
        self.assertEqual(saved["voucher"]["entry_number"], "JV-JM-2026-000001")
        later = self.receipt("10-03-2026"); earlier = self.receipt("05-01-2026")
        preview = resequence.plan(self.db, "customer_receipt", 2026)
        self.assertEqual(preview["prefix"], "REC"); self.assertEqual(preview["changes"], 3)
        resequence.apply(self.db, "customer_receipt", 2026, preview["token"], self.user)
        with self.db.connect() as db:
            numbers = [r[0] for r in db.execute("SELECT payment_number FROM payments ORDER BY payment_date")]
        self.assertEqual(sorted(numbers), ["REC-2026-000001", "REC-2026-000002", "REC-2026-000003"])

    def test_rules(self):
        with self.assertRaisesRegex(ValueError, "own prefix"): numbering.save_settings(self.db, {"sale": {"prefix": "PV"}}, self.user)
        with self.assertRaisesRegex(ValueError, "used by the program"): numbering.save_settings(self.db, {"sale": {"prefix": "CN"}}, self.user)
        self.assertEqual(numbering.branch_code("Head Office"), "HO"); self.assertEqual(numbering.branch_code("Beirut"), "BEI")
        import server
        self.assertTrue(server.admin_only("POST", "/api/numbering"))


if __name__ == "__main__":
    unittest.main()
