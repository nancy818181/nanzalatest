"""2.9.67: move the chosen transactions of an account to another account (replacement on the same entries)."""
import tempfile
import unittest

from test_final_features import new_db


class MoveChosenLinesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, self.user = new_db(self.folder.name)
        for name in ("FRIGO", "FRIGO DUP"): self.db.save_party({"kind": "supplier", "name": name, "account_category": "supplier"}, self.user)
        parties = {p["name"]: p for p in self.db.list_parties()}
        self.src, self.dst = parties["FRIGO DUP"]["account_number"], parties["FRIGO"]["account_number"]
        for i, (name, amount) in enumerate((("FRIGO DUP", 100), ("FRIGO DUP", 200), ("FRIGO", 50))):
            self.db.import_invoice({"invoice_number": f"P{i}", "invoice_date": f"2025-02-1{i}", "party_name": name, "kind": "purchases", "entry_type": "purchases",
                                    "currency": "USD", "subtotal": amount, "vat": round(amount * 0.11, 2), "total": round(amount * 1.11, 2), "status": "posted",
                                    "supplier_account": parties[name]["account_number"]}, self.user)

    def tearDown(self): self.folder.cleanup()

    def test_only_chosen_lines_move_and_the_invoice_follows(self):
        lines = self.db.account_lines(self.src)
        self.assertEqual(len(lines), 2)
        result = self.db.move_lines(self.src, self.dst, [lines[0]["id"]], self.user)
        self.assertEqual((result["lines"], result["documents"], result["party_changed"]), (1, 1, "FRIGO DUP -> FRIGO"))
        self.assertEqual([l["entry_number"] for l in self.db.account_lines(self.src)], [lines[1]["entry_number"]])
        moved = next(i for i in self.db.list_invoices() if i["invoice_number"] == "P0")
        self.assertEqual((moved["party_name"], moved["supplier_account"]), ("FRIGO", self.dst))
        # editing the invoice later rebuilds its entry on the new account
        item = {k: moved[k] for k in ("invoice_number", "party_name", "currency", "subtotal", "vat", "total", "supplier_account", "vat_account", "expense_account", "status")}
        item.update(kind="purchases", invoice_date="16-02-2025"); self.db.update_invoice(moved["id"], item, self.user)
        self.assertEqual(len(self.db.account_lines(self.src)), 1); self.assertEqual(len(self.db.account_lines(self.dst)), 2)

    def test_keep_the_supplier_when_asked(self):
        lines = self.db.account_lines(self.src)
        result = self.db.move_lines(self.src, self.dst, [lines[0]["id"]], self.user, change_party=False)
        self.assertIsNone(result["party_changed"])
        self.assertEqual(next(i for i in self.db.list_invoices() if i["invoice_number"] == "P0")["party_name"], "FRIGO DUP")

    def test_checks(self):
        lines = self.db.account_lines(self.src)
        with self.assertRaisesRegex(ValueError, "Select"): self.db.move_lines(self.src, self.dst, [], self.user)
        with self.assertRaisesRegex(ValueError, "not on account"): self.db.move_lines(self.dst, self.src, [lines[0]["id"]], self.user)
        with self.assertRaisesRegex(ValueError, "different"): self.db.move_lines(self.src, self.src, [lines[0]["id"]], self.user)
        self.assertEqual(len(self.db.account_lines(self.src, "11-02-2025", "28-02-2025")), 1)


if __name__ == "__main__":
    unittest.main()
