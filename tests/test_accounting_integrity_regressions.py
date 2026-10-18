"""Source/journal/report acceptance cases from the operational accounting audit."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from decimal import Decimal

from database import Database
from business_reports import ageing
from server import ApiHandler
import approvals


class AccountingIntegrityTest(unittest.TestCase):
    def test_physical_integrity_failure_stops_accounting_checks(self):
        import books_check
        connection = unittest.mock.MagicMock()
        connection.execute.return_value = [("corrupt index",)]
        db = unittest.mock.MagicMock()
        db.connect.return_value.__enter__.return_value = connection
        with patch.object(books_check, "_entries") as entries:
            result = books_check.run(db)
        self.assertEqual(result["errors"], 1)
        self.assertIn("integrity failed", result["summary"])
        entries.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "books.db")
        self.db.initialize("Audit-tests-2026!")
        self.addCleanup(self.db.release)
        self.party = self.db.save_party({"kind": "customer", "name": "Audit customer", "currency": "USD"}, 1)

    def invoice(self, amount=100, status="posted", credit=False):
        sides = {"supplier_side": "C - Credit", "vat_side": "D - Debit", "expense_side": "D - Debit"} if credit else {}
        return self.db.create_manual_invoice(
            {
                "invoice_date": "01-01-2026",
                "party_name": self.party["name"],
                "kind": "sales",
                "currency": "USD",
                "status": status,
                "doc_subtype": "credit_note" if credit else "invoice",
                **sides,
            },
            [{"description": "Service", "quantity": 1, "unit_price": amount, "vat_rate": 0}],
            1,
        )

    def payment(self, amount=40, outgoing=False, fx=0, defer_posting=False):
        return self.db.add_payment(
            {
                "kind": "supplier_payment" if outgoing else "customer_receipt",
                "payment_date": "10-01-2026",
                "party_id": self.party["id"],
                "currency": "USD",
                "amount": amount,
                "exchange_difference": fx,
                "cash_account": "531",
                "party_account": self.party["account_number"],
            },
            1,
            defer_posting=defer_posting,
        )

    def balances(self):
        legacy = sum(Decimal(str(r["outstanding"])) for r in self.db.aging_report("31-01-2026", "sale", "USD"))
        report = ageing(self.db, {"date_to": "31-01-2026", "side": "receivables", "basis": "USD"})
        business = next(Decimal(str(r[1])) for r in report["sections"][0]["rows"] if r[0] == "NET BALANCE")
        return legacy, business

    def test_failed_approval_rolls_back_each_document_kind_and_journal(self):
        handler = SimpleNamespace(
            db=self.db, master_db=SimpleNamespace(user_can=lambda *a: False), _approval_required=lambda *a: True
        )
        handler._hold_for_approval = lambda *a: ApiHandler._hold_for_approval(handler, *a)
        saves = {
            "payments": lambda: self.payment(defer_posting=True),
            "expenses": lambda: self.db.add_expense(
                {"expense_date": "10-01-2026", "description": "Office", "currency": "USD", "subtotal": 10, "vat": 0}, 1,
                defer_posting=True
            ),
            "journal_vouchers": lambda: self.db.save_journal_voucher(
                {"entry_date": "10-01-2026", "currency": "USD", "description": "Test"},
                [{"account_code": "531", "debit": 10}, {"account_code": "10", "credit": 10}],
                1,
            ),
        }
        for kind, save in saves.items():
            with self.subTest(kind=kind):
                with self.db.connect() as c:
                    before = {
                        t: c.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
                        for t in ("payments", "expenses", "journal_entries", "journal_lines", "audit_log")
                    }
                with patch("approvals.hold", side_effect=RuntimeError("hold failed")):
                    with self.assertRaisesRegex(RuntimeError, "hold failed"):
                        ApiHandler._save_with_approval(handler, {"id": 1}, kind, save)
                with self.db.connect() as c:
                    self.assertEqual(before, {t: c.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in before})

    def test_held_receipt_and_its_allocation_do_not_reduce_posted_balances(self):
        inv = self.invoice()
        pay = self.payment(defer_posting=True)
        self.db.save_allocations(pay, [{"invoice_id": inv, "amount": 40}], 1)
        approvals.hold(self.db, approvals.entry_of(self.db, "payments", pay), 1)
        self.assertEqual(self.balances(), (100, 100))
        self.assertEqual(self.db.open_documents(self.party["id"])[0]["open_amount"], 100)
        row = next(r for r in self.db.list_invoices() if r["id"] == inv)
        self.assertEqual((row["settled_amount"], row["outstanding"], row["payment_status"]), (0, 100, "unpaid"))
        approvals.approve_entries(self.db, [approvals.entry_of(self.db, "payments", pay)], {"id": 1}, False)
        self.assertEqual(self.balances(), (60, 60))

    def test_refund_increases_receivables_in_both_reports(self):
        self.invoice()
        self.payment(25, outgoing=True)
        self.assertEqual(self.balances(), (125, 125))

    def test_review_invoice_is_separate_from_posted_receivables(self):
        self.invoice()
        self.invoice(200, status="review")
        self.assertEqual(self.balances(), (100, 100))

    def test_invoice_list_preserves_direct_paid_but_includes_approved_allocations(self):
        inv = self.invoice()
        pay = self.payment()
        self.db.save_allocations(pay, [{"invoice_id": inv, "amount": 40}], 1)
        row = next(r for r in self.db.list_invoices() if r["id"] == inv)
        self.assertEqual(
            (
                row["amount_paid"],
                row["allocated_amount"],
                row["settled_amount"],
                row["outstanding"],
                row["payment_status"],
            ),
            (0, 40, 40, 60, "partial"),
        )

    def test_exchange_difference_is_part_of_the_party_settlement(self):
        self.invoice()
        self.payment(fx=5)
        self.assertEqual(self.balances(), (55, 55))

    def test_allocation_cannot_exceed_settlement_after_negative_fx(self):
        inv = self.invoice(40)
        pay = self.payment(fx=-5)
        with self.assertRaisesRegex(ValueError, "party settlement"):
            self.db.save_allocations(pay, [{"invoice_id": inv, "amount": 40}], 1)
        self.assertEqual(self.db.payment_allocations(pay), [])
        self.db.save_allocations(pay, [{"invoice_id": inv, "amount": 35}], 1)
        self.assertEqual(self.db.open_documents(self.party["id"])[0]["open_amount"], 5)
        self.assertEqual(self.balances(), (5, 5))

    def test_vat_summary_credit_note_matches_output_vat_ledger(self):
        for credit, amount in ((False, 100), (True, 20)):
            sides = (
                {"supplier_side": "C - Credit", "vat_side": "D - Debit", "expense_side": "D - Debit"} if credit else {}
            )
            self.db.create_manual_invoice(
                {
                    "invoice_date": "01-01-2026",
                    "party_name": self.party["name"],
                    "kind": "sales",
                    "currency": "USD",
                    "status": "posted",
                    "doc_subtype": "credit_note" if credit else "invoice",
                    **sides,
                },
                [{"description": "Service", "quantity": 1, "unit_price": amount, "vat_rate": 11}],
                1,
            )
        report = self.db.vat_report("01-01-2026", "31-01-2026", "USD")
        self.assertEqual(Decimal(str(report["summary"][0]["sales_vat"])), Decimal("8.8"))
        self.assertEqual(report["items"][0]["subtotal"], 80)
        self.assertTrue(report["provisional"])
        self.assertIn("quarterly", report["warning"])

    def test_held_expense_is_not_in_document_vat_summary(self):
        exp = self.db.add_expense(
            {"expense_date": "10-01-2026", "description": "Office", "currency": "USD", "subtotal": 100, "vat": 11}, 1,
            defer_posting=True)
        approvals.hold(self.db, approvals.entry_of(self.db, "expenses", exp), 1)
        self.assertEqual(self.db.vat_report("01-01-2026", "31-01-2026", "USD")["items"], [])


if __name__ == "__main__":
    unittest.main()
