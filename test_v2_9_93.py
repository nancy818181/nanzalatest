"""2.9.93: approval (prepare / approve) and before / after values in the audit trail."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import server
from client import ApiClient


class ApprovalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        database = Path(cls.folder.name) / "saber.db"; cls.database = database
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database), "admin_password": "Admin-2025!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)
        admin = ApiClient(cls.url); admin.login("admin", "Admin-2025!")
        cls.company = admin.create_company({"name": "Control Co", "year": 2025}); admin.select_company_year(cls.company["id"], 2025)
        admin.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        admin.save_user({"username": "maker", "password": "Maker-2025!", "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True, "delete": False}})
        admin.save_user({"username": "checker", "password": "Checker-2025!", "role": "accountant", "language": "en", "permissions": {"approve": True}})
        admin.save_accounting_setup({"approval_required": True}); cls.admin = admin

    @classmethod
    def tearDownClass(cls):
        import gc; gc.collect(); cls.folder.cleanup()

    def login(self, name, password):
        api = ApiClient(self.url); api.login(name, password); api.select_company_year(self.company["id"], 2025); return api

    def test_maker_checker(self):
        maker, checker = self.login("maker", "Maker-2025!"), self.login("checker", "Checker-2025!")
        created = maker.create_manual_invoice({"invoice_date": "10-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                              [{"description": "S", "quantity": 1, "unit_price": 1000, "vat_rate": 11}])
        self.assertIn("approval", created)
        invoice = next(i for i in self.admin.invoices() if i["id"] == created["invoice_id"])
        self.assertEqual(invoice["status"], "review")  # not in the books yet
        self.assertFalse([r for r in self.admin.trial_balance() if str(r.get("code",
                "")).startswith("7") and float(r.get("credit") or 0) >= 1000])  # the 1,000 draft is not posted (the other test posts 150)
        with self.assertRaisesRegex(RuntimeError, "permission to approve"): maker.approve_invoices([created["invoice_id"]])
        mine = checker.create_manual_invoice({"invoice_date": "11-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "review"},
                                             [{"description": "S2", "quantity": 1, "unit_price": 500, "vat_rate": 11}])
        result = checker.approve_invoices([created["invoice_id"], mine["invoice_id"]])
        self.assertEqual(len(result["approved"]), 1); self.assertIn("prepared by you", result["skipped"][0])  # never one's own draft
        self.assertEqual(next(i for i in self.admin.invoices() if i["id"] == created["invoice_id"])["status"], "posted")
        trail = self.admin.audit_log(entity="invoice", action="approve")["items"]
        self.assertEqual(trail[0]["username"], "checker"); self.assertIn("prepared_by", trail[0]["details"])

    def test_before_and_after_in_the_audit_trail(self):
        created = self.admin.create_manual_invoice({"invoice_date": "12-03-2025", "party_name": "Client B", "kind": "sales", "currency": "USD", "status": "posted"},
                                                   [{"description": "S", "quantity": 1, "unit_price": 100, "vat_rate": 11}])
        self.admin.replace_invoice(created["invoice_id"], {"invoice_number": next(i for i in self.admin.invoices() if i["id"] == created["invoice_id"])["invoice_number"],
                                   "invoice_date": "12-03-2025", "party_name": "Client B", "kind": "sales", "currency": "USD", "status": "posted"},
                                   [{"description": "S", "quantity": 1, "unit_price": 150, "vat_rate": 11}])
        change = self.admin.audit_log(entity="invoice", action="change")["items"][0]
        self.assertIn('"total": {"before": "111.0", "after": "166.5"}', change["details"].replace("'", '"'))


if __name__ == "__main__":
    unittest.main()
