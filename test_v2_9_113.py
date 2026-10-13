"""2.9.113: the "not deductible for income tax" tick on journal vouchers (and purchases / payments, same table)."""
import tempfile
import unittest
from pathlib import Path

import ledger_reports
from database import Database


class TaxFlagEverywhereTest(unittest.TestCase):
    def test_ticked_voucher_is_added_back_and_left_out_of_the_tax_basis_only(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret12345")
            ticked = db.save_journal_voucher({"entry_date": "10-03-2026", "description": "Cash gift - no invoice", "currency": "USD", "voucher_type": "01"},
                                             [{"account_code": "6250", "debit": "80"}, {"account_code": "531", "credit": "80"}], 1)
            db.save_journal_voucher({"entry_date": "11-03-2026", "description": "Rent", "currency": "USD", "voucher_type": "01"},
                                    [{"account_code": "6250", "debit": "300"}, {"account_code": "531", "credit": "300"}], 1)
            entry_id = ticked["voucher"]["id"]
            db.set_tax_flag("journal_voucher", entry_id, True)
            self.assertEqual(db.tax_flag_ids("journal_voucher"), [entry_id])
            listed = db.non_deductible_expenses(2026)
            self.assertEqual([(r["category"], r["total"]) for r in listed], [("Journal voucher", 80.0)])

            def class6(**extra):
                lines = ledger_reports._load_lines(db, dict({"profit_loss_only": True}, **extra))
                return sum(float(l["debit"] or 0) - float(l["credit"] or 0) for l in lines if str(l["code"]).startswith("6"))
            self.assertAlmostEqual(class6(), 380)
            self.assertAlmostEqual(class6(tax_basis=True), 300)
            everything = ledger_reports._load_lines(db, {"tax_basis": True})  # trial balance: untouched and balanced
            self.assertAlmostEqual(sum(float(l["debit"] or 0) for l in everything if str(l["code"]).startswith("6")), 380)

            db.set_tax_flag("journal_voucher", entry_id, False)  # untick
            self.assertEqual(db.tax_flag_ids("journal_voucher"), [])
            self.assertAlmostEqual(class6(tax_basis=True), 380)
            with self.assertRaises(ValueError): db.set_tax_flag("sale", 1, True)
            db.set_tax_flag("journal_voucher", entry_id, True)
            db.save_settings({"show_tax_tick": "0"}, 1)  # Settings hides the tick: the saved tick and its effect stay
            self.assertEqual(db.settings().get("show_tax_tick"), "0")
            self.assertAlmostEqual(class6(tax_basis=True), 300)
            db.release()


if __name__ == "__main__":
    unittest.main()
