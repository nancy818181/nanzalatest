import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database
import payroll_payments as payments


class SalaryPaymentsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = Database(Path(folder.name) / "books.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.employee = self.db.save_employee({"full_name": "Demo employee", "base_salary": "100000000",
            "currency": "LBP", "hire_date": "01-01-2026"}, 1)

    def posted(self, **extra):
        result = self.db.save_payroll({"employee_id": self.employee["id"], "period_date": "31-01-2026", **extra}, 1)
        return self.db.post_payroll(result["id"], 1)

    def pay(self, row, amount):
        return payments.record(self.db, {"payroll_id": row["id"], "payment_date": "05-02-2026",
            "amount": str(amount), "method": "Bank Transfer", "cash_account": "512"}, 1)

    def test_salary_month_is_separate_from_payment_date_and_partial_payments_reconcile(self):
        row = self.posted()
        result = self.pay(row, "10000000")
        self.assertEqual(result["salary_month"], "01/2026")
        self.assertEqual(payments.outstanding(self.db, row), Decimal(str(row["net_salary"])) - 10000000)
        journal = self.db.journal_voucher_detail(result["entry_id"])["voucher"]
        self.assertIn("01/2026", journal["description"])
        self.assertIn("02", journal["entry_date"])
        self.assertEqual(self.db.unbalanced_entries(), [])

    def test_overpayment_non_finite_amount_and_draft_payroll_are_refused(self):
        draft = self.db.save_payroll({"employee_id": self.employee["id"], "period_date": "31-01-2026"}, 1)
        with self.assertRaisesRegex(ValueError, "posted"): self.pay(draft, 10)
        row = self.db.post_payroll(draft["id"], 1)
        for value in ("NaN", "Infinity", "-1", str(Decimal(str(row["net_salary"])) + 1)):
            with self.subTest(value=value), self.assertRaises(ValueError): self.pay(row, value)
        self.assertEqual(payments.history(self.db, row["id"]), [])

    def test_payment_cannot_be_edited_or_deleted_as_an_unlinked_voucher(self):
        row = self.posted(); payment = self.pay(row, 10)
        with self.assertRaisesRegex(ValueError, "salary payment reversal"):
            self.db.delete_journal_voucher(payment["entry_id"], 1)
        with self.assertRaisesRegex(ValueError, "salary payment reversal"):
            self.db.save_journal_voucher({"entry_date": "05-02-2026", "currency": "LBP", "description": "change"},
                [{"account_code": "512", "debit": 1, "credit": 0}, {"account_code": "531", "debit": 0, "credit": 1}], 1, payment["entry_id"])

    def test_reversal_restores_salary_balance_without_deleting_history(self):
        row = self.posted(); before = Decimal(str(row["net_salary"]))
        payment = self.pay(row, 100)
        payments.reverse(self.db, payment["payment_id"], "06-02-2026", 1)
        self.assertEqual(payments.outstanding(self.db, row), before)
        self.assertEqual(payments.history(self.db, row["id"])[0]["status"], "reversed")
        with self.assertRaises(ValueError): payments.reverse(self.db, payment["payment_id"], "06-02-2026", 1)
        self.assertEqual(self.db.unbalanced_entries(), [])

    def test_pending_approval_reserves_the_salary_but_is_not_a_posted_payment(self):
        import approvals
        row = self.posted(); payment = self.pay(row, Decimal(str(row["net_salary"])))
        approvals.hold(self.db, payment["entry_id"], 1)
        self.assertEqual(payments.outstanding(self.db, row), 0)
        self.assertNotEqual(payments.history(self.db, row["id"])[0]["posting_status"], "posted")
        with self.assertRaises(ValueError): self.pay(row, 1)

    def test_family_allocation_and_additional_payment_have_their_own_accounts(self):
        row = self.posted(family_allowance_override="1000", allowances={"other_taxable": "2000"},
                          allowance_accounts={"other_taxable": "6319"})
        with self.db.connect() as connection:
            amounts = {r["code"]: Decimal(r["debit"]) for r in connection.execute("""SELECT a.code,l.debit FROM journal_lines l
                JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?""", (row["journal_entry_id"],))}
        self.assertEqual(amounts["438"], 1000)
        self.assertEqual(amounts["6319"], 2000)

    def test_monthly_sheet_preserves_the_record_specific_allowance_account(self):
        from desktop_payroll_sheet import sheet_rows, payload_for
        draft = self.db.save_payroll({"employee_id": self.employee["id"], "period_date": "31-01-2026",
            "allowances": {"other_taxable": "2000"}, "allowance_accounts": {"other_taxable": "6319"}}, 1)
        rows = sheet_rows(self.db.list_employees(), [draft], "2026-01-01", "2026-01-31")
        self.assertEqual(payload_for(rows[0], "31-01-2026")["allowance_accounts"], {"other_taxable": "6319"})

    def test_api_salary_payment_obeys_voucher_approval(self):
        import threading
        from http.server import ThreadingHTTPServer
        from server import ApiHandler
        from client import ApiClient
        import approvals
        row = self.posted()
        self.db.save_user({"username": "salary_maker", "password": "Maker-2026!", "role": "accountant",
                           "permissions": {"payroll": True}}, 1)
        approvals.save_types(self.db, ["journal_vouchers"])
        from company_manager import CompanyManager
        manager = CompanyManager(self.db.path, prepare=False)
        handler = type("SalaryTestHandler", (ApiHandler,), {"db": self.db, "master_db": self.db, "company_manager": manager})
        http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        try:
            client = ApiClient(f"http://127.0.0.1:{http.server_port}")
            client.login("salary_maker", "Maker-2026!")
            result = client.record_salary_payment({"payroll_id": row["id"], "payment_date": "05-02-2026",
                "amount": "1000", "method": "Cash", "cash_account": "531"})
            self.assertTrue(result["approval"])
            history = client.salary_payments(row["id"])
            self.assertEqual(history[0]["posting_status"], "review")
            with self.assertRaisesRegex(RuntimeError, "approver"):
                client.reverse_salary_payment(result["payment_id"], "06-02-2026")
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=5)


if __name__ == "__main__": unittest.main()
