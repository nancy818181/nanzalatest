import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch

from database import Database
from client import ApiClient
import management_pack


class DashboardBriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "brief.db")
        self.db.initialize("Brief-Test-2026!")
        self.addCleanup(self.db.release)

    def voucher(self, day, debit, credit, amount):
        self.db.save_journal_voucher(
            {"entry_date": day, "currency": "USD", "description": "Summary test"},
            [{"account_code": debit, "debit": amount}, {"account_code": credit, "credit": amount}],
            1,
        )

    def test_cash_profit_and_missing_comparison_are_distinct(self):
        self.voucher("01-01-2026", "531", "10", 1000)
        self.voucher("10-01-2026", "531", "7011", 100)
        self.voucher("11-01-2026", "6263.1", "531", 20)
        report = management_pack.brief(self.db, "01-01-2026", "31-01-2026", "USD")
        self.assertEqual(report["metrics"]["cash"], 1080)
        self.assertEqual(report["metrics"]["profit"], 80)
        self.assertIsNone(report["metrics"]["prior_profit"])
        self.assertFalse(report["prior_available"])
        self.assertEqual(report["sections"][0]["rows"][-1][1], "")

    def test_customer_advance_does_not_hide_another_customers_overdue_balance(self):
        a = self.db.save_party({"kind": "customer", "name": "Debtor", "currency": "USD"}, 1)
        b = self.db.save_party({"kind": "customer", "name": "Advance customer", "currency": "USD"}, 1)
        self.db.import_invoice(
            {
                "invoice_number": "DUE",
                "invoice_date": "01-01-2026",
                "due_date": "02-01-2026",
                "party_name": a["name"],
                "kind": "sale",
                "currency": "USD",
                "subtotal": 100,
                "vat": 0,
                "total": 100,
                "status": "posted",
            },
            1,
        )
        self.db.add_payment(
            {
                "kind": "customer_receipt",
                "payment_date": "03-01-2026",
                "party_id": b["id"],
                "amount": 200,
                "currency": "USD",
                "cash_account": "531",
                "party_account": b["account_number"],
            },
            1,
        )
        report = management_pack.brief(self.db, "01-01-2026", "31-01-2026", "USD")
        self.assertEqual(report["metrics"]["overdue_receivables"], 100)

    def test_prior_profit_and_leap_day_comparison(self):
        self.voucher("28-02-2027", "531", "7011", 40)
        self.voucher("29-02-2028", "531", "7011", 70)
        report = management_pack.brief(self.db, "29-02-2028", "29-02-2028", "USD", self.db, "ar")
        self.assertEqual(report["metrics"]["prior_profit"], 40)
        self.assertEqual(report["metrics"]["profit_variance"], 30)
        self.assertTrue(report["rtl"])

    def test_client_restores_exact_decimal_cells_for_exports(self):
        client = ApiClient()
        with patch.object(
            client,
            "request",
            return_value={
                "metrics": {"cash": "9007199254740993.25", "prior_profit": None},
                "sections": [{"rows": [["Cash", "9007199254740993.25"], ["Prior", ""]]}],
            },
        ):
            result = client.dashboard_brief("01-01-2026", "31-01-2026")
        self.assertEqual(result["metrics"]["cash"], Decimal("9007199254740993.25"))
        self.assertEqual(result["sections"][0]["rows"][0][1], Decimal("9007199254740993.25"))


if __name__ == "__main__":
    unittest.main()
