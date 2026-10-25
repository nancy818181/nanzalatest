"""Large-value report sums remain exact without SQLite REAL conversion."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


class ExactReportAggregationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "synthetic-report.db")
        self.db.initialize("Synthetic-Only-2026!")
        self.addCleanup(self.db.release)
        session = self.db.login("admin", "Synthetic-Only-2026!")
        self.user = self.db.user_for_token(session["token"])["id"]

    def test_trial_balance_preserves_lbp_cents_above_float_precision(self):
        amount = Decimal("1000000000000000.01")
        self.db.save_journal_voucher(
            {"entry_number": "F4-LARGE-CENT", "entry_date": "2026-01-02",
             "description": "Synthetic exact report aggregation", "currency": "LBP"},
            [{"account_code": "531", "debit": str(amount), "credit": "0"},
             {"account_code": "4011", "debit": "0", "credit": str(amount)}], self.user)
        rows = self.db.trial_balance(to_date="2026-12-31")
        cash = next(row for row in rows if row["code"] == "531" and row["currency"] == "LBP")
        payable = next(row for row in rows if row["code"] == "4011" and row["currency"] == "LBP")
        self.assertEqual(Decimal(str(cash["debit"])), amount)
        self.assertEqual(Decimal(str(payable["credit"])), amount)

    def test_balance_sheet_uses_exact_decimal_journal_totals(self):
        amount = Decimal("1000000000000000.01")
        self.db.save_journal_voucher(
            {"entry_number": "F4-BS-LARGE-CENT", "entry_date": "2026-01-03",
             "description": "Synthetic exact balance sheet aggregation", "currency": "LBP"},
            [{"account_code": "531", "debit": str(amount), "credit": "0"},
             {"account_code": "4011", "debit": "0", "credit": str(amount)}], self.user)
        rows = self.db.balance_sheet(to_date="2026-12-31", currency="LBP")
        cash = next(row for row in rows if row["code"] == "531")
        payable = next(row for row in rows if row["code"] == "4011")
        self.assertEqual(Decimal(str(cash["balance"])), amount)
        self.assertEqual(Decimal(str(payable["balance"])), -amount)

    def test_profit_and_loss_preserves_large_decimal_values(self):
        amount = Decimal("1000000000000000.01")
        self.db.save_journal_voucher(
            {"entry_number": "F4-PNL-LARGE-CENT", "entry_date": "2026-01-04",
             "description": "Synthetic exact P&L aggregation", "currency": "LBP"},
            [{"account_code": "531", "debit": str(amount), "credit": "0"},
             {"account_code": "701100001", "debit": "0", "credit": str(amount)}], self.user)
        rows = self.db.profit_and_loss("2026-01-01", "2026-12-31", "LBP")
        income = next(row for row in rows if row["code"] == "701100001")
        self.assertEqual(Decimal(str(income["amount"])), amount)

    def test_statement_and_ageing_keep_large_invoice_cents(self):
        amount = Decimal("1000000000000000.01")
        party = self.db.save_party({"name": "F4 Synthetic Customer", "kind": "customer", "currency": "LBP"}, self.user)
        invoice_id = self.db.import_invoice(
            {"invoice_number": "F4-LARGE-INVOICE", "invoice_date": "2026-01-05",
             "due_date": "2026-01-31", "party_name": party["name"],
             "commercial_party_id": party["id"], "kind": "sale", "currency": "LBP",
             "subtotal": str(amount), "vat": "0.00", "total": str(amount), "status": "posted"}, self.user)
        statement = self.db.statement_of_account(party["id"], to_date="2026-12-31", currency="LBP")
        item = next(row for row in statement["items"] if row["id"] == invoice_id)
        self.assertEqual(Decimal(str(item["debit"])), amount)
        ageing = self.db.aging_report("2026-12-31", kind="sale", currency="LBP")
        open_invoice = next(row for row in ageing if row["id"] == invoice_id)
        self.assertEqual(Decimal(str(open_invoice["outstanding"])), amount)


if __name__ == "__main__":
    unittest.main()
