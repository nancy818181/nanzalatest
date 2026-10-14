"""2.9.100: Tax & NSSF Settings on paper (Print / PDF), the tax adviser's confirmation, and selective approval per company."""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from database import Database


def company(folder):
    db = Database(Path(folder) / "c.db"); db.initialize("secret12345")
    db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
    return db


class TaxSettingsPaperTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        self.db = company(folder.name); self.addCleanup(self.db.release); self.db.apply_lebanese_payroll_rules(1)

    def test_settings_report_and_adviser(self):
        import tax_review, report_export
        report = tax_review.settings_report(self.db, "31-12-2026")
        headings = [s["heading"] for s in report["sections"]]
        self.assertEqual(headings[:2], ["Values in force", "Salary tax brackets (annual LBP)"])
        values = dict((r[0], r[1]) for r in report["sections"][0]["rows"])
        self.assertEqual(values["Transport exempt / working day"], "450,000")
        self.assertEqual(report["sections"][1]["rows"][-1], ["13,500,000,000", "and above", "25%"])
        self.assertTrue(len(report["sections"][2]["rows"]) >= 9)  # every NSSF period
        self.assertIn("Not yet confirmed", report["meta"][-1])
        before = tax_review.build(self.db, "31-12-2026")["to_confirm"]
        self.assertGreater(before, 0)
        tax_review.save_adviser(self.db, {"name": "Rima Haddad", "licence": "LACPA 4321", "date": "05-10-2026"}, 1)
        after = tax_review.build(self.db, "31-12-2026")
        self.assertEqual(after["to_confirm"], 0)  # the adviser has checked them
        self.assertTrue(any(str(r[4]).startswith("Confirmed by the tax adviser Rima Haddad (LACPA 4321) on 05-10-2026") for r in after["sections"][0]["rows"]))
        self.assertIn("Rima Haddad", tax_review.settings_report(self.db, "31-12-2026")["meta"][-1])
        with self.assertRaises(ValueError): tax_review.save_adviser(self.db, {"name": "", "date": "05-10-2026"})
        path = Path(tempfile.mkdtemp()) / "settings.pdf"
        report_export.export_sections_pdf(path, report["title"], report["meta"], report["sections"])
        self.assertGreater(path.stat().st_size, 2000)



class SelectiveApprovalTest(unittest.TestCase):
    """2.9.100: each company chooses which documents need approval; drafts are in no report until approved by another user."""

    @classmethod
    def setUpClass(cls):
        import socket, threading, time, server
        from client import ApiClient
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "s.db"), "admin_password": "Admin-2025!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)
        admin = ApiClient(cls.url); admin.login("admin", "Admin-2025!")
        cls.company = admin.create_company({"name": "Client Co", "year": 2026}); admin.select_company_year(cls.company["id"], 2026)
        admin.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        admin.save_user({"username": "maker", "password": "Maker-2026!", "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True}})
        admin.save_user({"username": "checker", "password": "Checker-2026!", "role": "accountant", "language": "en", "permissions": {"approve": True}})
        cls.admin = admin

    @classmethod
    def tearDownClass(cls):
        import gc; gc.collect(); cls.folder.cleanup()

    def login(self, name, password):
        from client import ApiClient
        api = ApiClient(self.url); api.login(name, password); api.select_company_year(self.company["id"], 2026); return api

    def balance(self, code):
        return sum(Decimal(str(r["debit"])) - Decimal(str(r["credit"])) for r in self.admin.trial_balance(to_date="31-12-2026") if r["code"] == code)

    def test_selected_kinds_wait_then_post(self):
        self.admin.save_accounting_setup({"approval_types": ["journal_vouchers", "payments"]})  # not expenses, not invoices
        self.assertEqual(self.admin.approvals()["types"], ["journal_vouchers", "payments"])
        maker = self.login("maker", "Maker-2026!")
        jv = maker.request("POST", "/api/journal-vouchers", {"voucher": {"entry_date": "10-03-2026", "description": "Accrual", "currency": "USD", "voucher_type": "01"},
                                                            "lines": [{"account_code": "6262", "debit": "300"}, {"account_code": "531", "credit": "300"}]})
        self.assertIn("approval", jv)
        expense = maker.add_expense({"expense_date": "11-03-2026", "description": "Taxi", "currency": "USD", "without_vat_subtotal": "20", "vat": "0",
                                     "expense_without_vat_account": "6262", "payment_account": "531"})
        self.assertNotIn("approval", expense)  # expenses were not chosen: posted at once
        self.assertEqual(self.balance("6262"), Decimal("20"))  # the voucher waits: not in the trial balance
        waiting = self.admin.approvals()["items"]
        self.assertEqual([(w["kind"], w["amount"]) for w in waiting], [("journal_vouchers", 300.0)])
        with self.assertRaises(Exception): maker.approve_documents([waiting[0]["id"]])  # no permission
        checker = self.login("checker", "Checker-2026!")
        result = checker.approve_documents([waiting[0]["id"]])
        self.assertEqual(len(result["approved"]), 1)
        self.assertEqual(self.balance("6262"), Decimal("320"))  # posted now
        self.assertEqual(self.admin.approvals()["items"], [])
        self.admin.save_accounting_setup({"approval_types": []})  # off again for this company
        self.assertEqual(self.admin.approvals()["types"], [])


if __name__ == "__main__":
    unittest.main()
