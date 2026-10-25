"""2.9.132 Phase 1 (owner-approved scope): reports and VAT read posted entries only (H-01, H-05), amounts have 2 decimals
and journals balance exactly (H-03), a new user cannot delete by default (H-04), only an administrator removes a posted
invoice and the audit log keeps what was removed (H-02), only an administrator changes a posted sales invoice (M-11).
Synthetic data only."""
import tests_setup  # noqa: F401
import json
import socket
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path

import vat_return
from database import Database


class _Books(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "p1.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.user = self.db.user_for_token(self.db.login("admin", "secret12345")["token"])["id"]
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, self.user)

    def jv(self, day, lines, **extra):
        return self.db.save_journal_voucher({"entry_date": day, "description": "synthetic", "currency": "USD"},
                                            [{"account_code": c, "debit": d, "credit": k} for c, d, k in lines], self.user, **extra)

    def tb_difference(self):
        rows = self.db.trial_balance(None, "31-12-2026")
        return sum(Decimal(str(r["debit"])) for r in rows if r["currency"] == "USD") - sum(Decimal(str(r["credit"])) for r in rows if r["currency"] == "USD")


class PostedOnlyReportsTest(_Books):
    """H-01: a draft voucher is not in the statements (the journal list still shows it)."""
    def test_draft_voucher_is_not_in_the_statements(self):
        self.jv("10-03-2026", [("512", "100", ""), ("101", "", "100")])
        self.jv("11-03-2026", [("6262", "40", ""), ("531", "", "40")], defer_posting=True)  # draft
        self.assertEqual([r for r in self.db.profit_and_loss() if Decimal(str(r["amount"]))], [])
        self.assertNotIn("531", {r["code"] for r in self.db.balance_sheet()})
        self.assertEqual({r["category"]: Decimal(str(r["net"])) for r in self.db.cash_flow()}.get("Other Cash Movement"), Decimal("100"))
        self.assertNotIn("531", {r["account_code"] for r in self.db.general_ledger()["items"]})
        self.assertIn("531", {r["account_code"] for r in self.db.journal()})  # the journal list keeps the draft for review
        import financial_statements
        self.assertNotIn("531", financial_statements.load_period(self.db, "2026-01-01", "2026-12-31", "USD")["closing"])


class VatPostedSourceTest(_Books):
    """H-05: a document whose journal entry is a draft is not on the VAT return."""
    def test_draft_expense_and_draft_invoice_entry(self):
        self.db.add_expense({"expense_date": "10-02-2026", "description": "Draft rent", "currency": "LBP", "with_vat_subtotal": "1000000", "vat": "110000"},
                            self.user, defer_posting=True)
        invoice = self.db.import_invoice({"invoice_number": "S-D", "kind": "sale", "invoice_date": "11-02-2026", "party_name": "C", "currency": "LBP",
                                          "subtotal": "2000000", "vat": "220000", "total": "2220000", "status": "posted"}, self.user)
        with self.db.connect() as connection:
            connection.execute("UPDATE journal_entries SET posting_status='draft' WHERE source_type='invoice' AND source_id=?", (invoice,))
        result = vat_return.build_vat_return(self.db, 2026, 1)
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["totals_lbp"]["net"], Decimal("0"))
        self.assertTrue(any("S-D" in s and "draft" in s for s in result["blocking_documents"]))  # said, and filing is blocked
        with self.assertRaisesRegex(ValueError, "S-D"): vat_return.save_return(self.db, 2026, 1, self.user)


class TwoDecimalsTest(_Books):
    """H-03 (owner rule): 2 decimals, the third rounded half up; debits equal credits exactly after rounding."""
    def test_journal_amounts_are_rounded_and_must_balance_exactly(self):
        self.jv("15-04-2026", [("512", "10.004", ""), ("101", "", "10")])           # 10.00 = 10.00 after rounding
        self.assertEqual(self.tb_difference(), Decimal("0"))
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            self.jv("15-04-2026", [("512", "10.006", ""), ("101", "", "10")])        # 10.01 against 10.00
        with self.db.connect() as connection:
            stored = {r[0] for r in connection.execute("SELECT debit FROM journal_lines WHERE CAST(debit AS REAL)>0")}
        self.assertEqual(stored, {"10.00"})

    def test_invoice_amounts_are_rounded_before_posting(self):
        invoice = self.db.import_invoice({"invoice_number": "S-R", "kind": "sale", "invoice_date": "15-04-2026", "party_name": "C", "currency": "USD",
                                          "subtotal": "0.333", "vat": "0.037", "total": "0.37", "status": "posted"}, self.user)
        with self.db.connect() as connection:
            row = connection.execute("SELECT subtotal,vat,total FROM invoices WHERE id=?", (invoice,)).fetchone()
            lines = {(Decimal(r[0]), Decimal(r[1])) for r in connection.execute(
                "SELECT debit,credit FROM journal_lines WHERE entry_id=(SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?)", (invoice,))}
        self.assertEqual(tuple(Decimal(v) for v in row), (Decimal("0.33"), Decimal("0.04"), Decimal("0.37")))
        self.assertEqual(lines, {(Decimal("0.37"), Decimal("0")), (Decimal("0"), Decimal("0.33")), (Decimal("0"), Decimal("0.04"))})
        self.assertEqual(self.tb_difference(), Decimal("0"))


class NewUserDeleteTest(_Books):
    """H-04: a new user cannot delete unless the administrator ticks it; a saved user keeps what was saved."""
    def test_default_and_explicit(self):
        plain = self.db.save_user({"username": "acc1", "password": "Secret-2026", "role": "accountant", "language": "en",
                                   "permissions": {"payroll": True, "vat": True}}, self.user)
        allowed = self.db.save_user({"username": "acc2", "password": "Secret-2026", "role": "accountant", "language": "en",
                                     "permissions": {"delete": True}}, self.user)
        self.assertFalse(plain["permissions"]["delete"]); self.assertTrue(allowed["permissions"]["delete"])
        again = self.db.save_user({"id": allowed["id"], "username": "acc2", "role": "accountant", "language": "en",
                                   "permissions": {"delete": True, "vat": False}}, self.user)
        self.assertTrue(again["permissions"]["delete"])


class PostedInvoiceDeleteAuditTest(_Books):
    """H-02: a posted invoice is voided and the audit retains its original lines."""
    def test_audit_keeps_what_is_voided(self):
        invoice = self.db.import_invoice({"invoice_number": "S-1", "kind": "sale", "invoice_date": "10-02-2026", "party_name": "C", "currency": "USD",
                                          "subtotal": "100", "vat": "11", "total": "111", "status": "posted"}, self.user)
        self.db.mark_invoice_deleted(invoice, self.user, reason="synthetic test void")
        with self.db.connect() as connection:
            details = json.loads(connection.execute("SELECT details FROM audit_log WHERE action='void'").fetchone()[0])
        self.assertEqual(Decimal(details["invoice"]["total"]), Decimal("111"))
        lines = {(l["account_code"], Decimal(l["debit"]), Decimal(l["credit"])) for l in details["journal_lines"]}
        self.assertIn(("4427", Decimal("0"), Decimal("11")), lines)
        self.assertEqual(len(lines), 6)  # original and reversal snapshots


class ServerControlsTest(unittest.TestCase):
    """H-02 and M-11 through the data service: a non-admin cannot delete or change a posted sales invoice; the admin can."""
    @classmethod
    def setUpClass(cls):
        import server
        from client import ApiClient
        cls.folder = tempfile.TemporaryDirectory()  # strict: an open file left behind must fail on Windows
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "s.db"),
                                                           "admin_password": "Admin-2025!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)
        cls.admin = ApiClient(cls.url); cls.admin.login("admin", "Admin-2025!")
        cls.company = cls.admin.create_company({"name": "Synthetic Co", "year": 2026}); cls.admin.select_company_year(cls.company["id"], 2026)
        cls.admin.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        cls.admin.save_user({"username": "clerk", "password": "Clerk-2026-Pass", "role": "accountant", "language": "en",
                             "permissions": {"delete": True, "approve": True}})
        cls.clerk = ApiClient(cls.url); cls.clerk.login("clerk", "Clerk-2026-Pass"); cls.clerk.select_company_year(cls.company["id"], 2026)
        cls.service = (server.ApiHandler.master_db, server.ApiHandler.company_manager)  # this class's data service

    @classmethod
    def tearDownClass(cls):
        # The data service keeps its files open (pooled); close them before the folder is removed - an open file
        # cannot be deleted on Windows (WinError 32), and ignore_cleanup_errors would only hide it.
        master, companies = cls.service
        for path in list(companies._cache): companies._cache.pop(path).release()
        master.release()
        cls.folder.cleanup()

    def sale(self, number):
        created = self.admin.create_manual_invoice({"invoice_number": number, "invoice_date": "12-03-2026", "party_name": "Client S", "kind": "sales",
                                                   "currency": "USD", "status": "posted"}, [{"description": "S", "quantity": 1, "unit_price": 100, "vat_rate": 11}])
        return created["invoice_id"]

    def test_non_admin_cannot_delete_a_posted_invoice_admin_can(self):
        invoice = self.sale("SYN-DEL-1")
        statuses=[]; send=self.clerk._send
        def record_status(*args,**kwargs):
            result=send(*args,**kwargs); statuses.append(result[0]); return result
        self.clerk._send=record_status
        with self.assertRaisesRegex(Exception, "administrator"): self.clerk.delete_invoice(invoice, reason="synthetic test void")
        self.assertEqual(statuses[-1], 403)
        statuses.clear(); admin_send=self.admin._send
        def record_admin_status(*args,**kwargs):
            result=admin_send(*args,**kwargs); statuses.append(result[0]); return result
        self.admin._send=record_admin_status
        with self.assertRaisesRegex(Exception, "reason"): self.admin.delete_invoice(invoice)
        self.assertEqual(statuses[-1], 400)
        self.admin.delete_invoice(invoice, reason="synthetic test void")
        self.assertEqual(next(i for i in self.admin.invoices() if i["id"] == invoice)["status"], "void")

    def test_non_admin_cannot_change_a_posted_sale(self):
        invoice = self.sale("SYN-EDIT-1")
        with self.assertRaisesRegex(Exception, "administrator"):
            self.clerk.replace_invoice(invoice, {"invoice_number": "SYN-EDIT-1", "invoice_date": "12-03-2026", "party_name": "Client S", "kind": "sales",
                                                 "currency": "USD", "status": "posted"}, [{"description": "S", "quantity": 1, "unit_price": 150, "vat_rate": 11}])
        self.admin.replace_invoice(invoice, {"invoice_number": "SYN-EDIT-1", "invoice_date": "12-03-2026", "party_name": "Client S", "kind": "sales",
                                             "currency": "USD", "status": "posted"}, [{"description": "S", "quantity": 1, "unit_price": 150, "vat_rate": 11}])


if __name__ == "__main__":
    unittest.main()
