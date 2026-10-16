"""2.9.121: a document is saved completely or not at all - also when the program stops halfway (power cut, crash)."""
import tests_setup  # noqa: F401
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from test_final_features import new_db

ROOT = Path(__file__).resolve().parents[1]
INVOICE = {"invoice_number": "F-1", "invoice_date": "05-02-2026", "party_name": "Office Supplies", "kind": "purchase", "currency": "USD"}


def counts(path):
    with sqlite3.connect(path) as connection:
        return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("invoices", "invoice_items", "journal_entries", "journal_lines", "payments", "expenses")}


class AtomicSavingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)

    def test_an_error_halfway_leaves_nothing(self):
        before = counts(self.db.path)
        original = type(self.db)._store_invoice_format

        def broken(*_args, **_kwargs): raise RuntimeError("stopped halfway")
        type(self.db)._store_invoice_format = broken
        try:
            with self.assertRaisesRegex(RuntimeError, "halfway"):
                self.db.create_manual_invoice(INVOICE, [{"description": "Paper", "quantity": 2, "unit_price": 30}], self.user)
        finally:
            type(self.db)._store_invoice_format = original
        self.assertEqual(counts(self.db.path), before)
        self.db.create_manual_invoice(INVOICE, [{"description": "Paper", "quantity": 2, "unit_price": 30}], self.user)  # the number is free again
        self.assertEqual(counts(self.db.path)["invoices"], before["invoices"] + 1)

    def test_a_step_that_fails_inside_undoes_only_itself(self):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                               (self.user, "outer", "test", 1, "{}", "2026-01-01"))
            try:
                with self.db.connect() as inner:
                    inner.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                                  (self.user, "inner", "test", 2, "{}", "2026-01-01"))
                    raise ValueError("step refused")
            except ValueError:
                pass
        with sqlite3.connect(self.db.path) as connection:
            actions = [r[0] for r in connection.execute("SELECT action FROM audit_log WHERE entity='test'")]
        self.assertEqual(actions, ["outer"])

    def test_the_program_killed_halfway_leaves_nothing(self):
        """A real stop of the process (as a power cut) between two steps of the invoice: nothing of it is in the file."""
        before = counts(self.db.path)
        script = textwrap.dedent(f"""
            import os, sys
            sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'tests')!r})
            import nanza_paths  # noqa
            from database import Database
            db = Database({self.db.path!r})
            def killed(*_a, **_k): os._exit(9)  # stops at once: no rollback, no clean-up, as a power cut
            Database._store_invoice_format = killed
            db.create_manual_invoice({INVOICE!r}, [{{"description": "Paper", "quantity": 2, "unit_price": 30}}], {self.user})
        """)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env={**os.environ})
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual(counts(self.db.path), before)
        with sqlite3.connect(self.db.path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_payment_and_expense_are_saved_whole(self):
        customer = self.db.save_party({"kind": "customer", "name": "Cedar Trading", "currency": "USD"}, self.user)
        before = counts(self.db.path)
        cls = type(self.db); original = cls._dimension_ids  # read after the payment row is written

        def broken(*_args, **_kwargs): raise RuntimeError("stopped halfway")
        cls._dimension_ids = broken
        try:
            with self.assertRaisesRegex(RuntimeError, "halfway"):
                self.db.add_payment({"kind": "customer_receipt", "payment_date": "20-02-2026", "party_id": customer["id"], "currency": "USD",
                                     "amount": "111", "cash_account": "531", "party_account": customer["account_number"]}, self.user)
        finally:
            cls._dimension_ids = original
        self.assertEqual(counts(self.db.path), before)
        self.db.add_expense({"expense_date": "21-02-2026", "description": "Fuel", "currency": "USD", "with_vat_subtotal": "100", "vat": "11"}, self.user)
        after = counts(self.db.path)
        self.assertEqual((after["expenses"], after["journal_entries"]), (before["expenses"] + 1, before["journal_entries"] + 1))

if __name__ == "__main__":
    unittest.main()


class CompanyAccessTest(unittest.TestCase):
    """2.9.121: an administrator chooses the companies each user may open (none chosen = every company, as before)."""
    @classmethod
    def setUpClass(cls):
        import socket, threading, time
        from client import ApiClient
        from server import run_server
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "app.db"),
                                                    "admin_password": "secret12345"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"; cls.admin = ApiClient(cls.url)
        for _ in range(100):
            try: cls.admin.login("admin", "secret12345"); break
            except (OSError, RuntimeError): time.sleep(.05)

    @classmethod
    def tearDownClass(cls):
        cls.admin.close(); cls.folder.cleanup()

    def test_a_user_opens_only_his_companies(self):
        from client import ApiClient
        first = self.admin.companies()[0]
        second = self.admin.create_company({"name": "Second Client SARL", "year": first["years"][0]["year"]})
        clerk = self.admin.save_user({"username": "clerk1", "password": "Clerk-2025!", "role": "accountant", "companies": [first["id"]]})
        self.assertEqual(clerk["companies"], [str(first["id"])])
        api = ApiClient(self.url); api.login("clerk1", "Clerk-2025!")
        self.assertEqual([c["id"] for c in api.companies()], [first["id"]])
        api.select_company_year(second["id"], second["years"][0]["year"])
        with self.assertRaisesRegex(Exception, "do not have access to this company"): api.invoices()
        api.select_company_year(first["id"], first["years"][0]["year"]); api.invoices()
        self.admin.save_user({"id": clerk["id"], "username": "clerk1", "role": "accountant", "companies": []})  # none = every company
        api2 = ApiClient(self.url); api2.login("clerk1", "Clerk-2025!")
        self.assertEqual(len(api2.companies()), 2)
        api.close(); api2.close()


class RollbackAfterStockTest(unittest.TestCase):
    """2.9.121 (review): an error AFTER the stock and the VAT reclass are posted undoes every record of the invoice."""
    def setUp(self):
        import inventory
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db, self.user = new_db(self.folder.name)
        self.item = inventory.save_item(self.db, {"name": "HPL Sheet", "unit": "sheet", "sales_price": "120"}, self.user)

    def tables(self):
        with sqlite3.connect(self.db.path) as connection:
            names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {n: connection.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names if n not in ("audit_log", "settings")}

    def test_failure_after_stock_and_vat_reclass_leaves_nothing(self):
        before = self.tables()
        cls = type(self.db); original = cls.set_vat_recoverable

        def broken(*_args, **_kwargs): raise RuntimeError("stopped after the stock")
        cls.set_vat_recoverable = broken
        try:
            with self.assertRaisesRegex(RuntimeError, "after the stock"):
                self.db.create_manual_invoice({"invoice_number": "P-1", "invoice_date": "05-03-2026", "party_name": "Supplier", "kind": "purchase",
                                               "currency": "USD", "vat_use": "exempt"},
                                              [{"description": "HPL", "item_code": self.item["sku"], "quantity": 3, "unit_price": 80}], self.user)
        finally:
            cls.set_vat_recoverable = original
        changed = {k: (before.get(k), v) for k, v in self.tables().items() if before.get(k) != v}
        self.assertEqual(changed, {})

    def test_a_released_step_is_still_undone_when_the_save_fails_later(self):
        before = self.tables()
        with self.assertRaises(ValueError):
            with self.db.connect() as connection:
                with self.db.connect() as step:  # the step succeeds (RELEASE) ...
                    step.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?)",
                                 (self.user, "step", "test", 1, "{}", "2026-01-01"))
                    step.execute("INSERT INTO parties(kind,name,currency) VALUES('customer','Step Customer','USD')")
                self.assertTrue(connection.in_transaction)  # ... and RELEASE did not commit the larger save
                raise ValueError("the save fails after the step")
        self.assertEqual(self.tables(), before)


class HistoricalAgeingTest(unittest.TestCase):
    """2.9.121 (review): a receipt dated after the ageing date and a credit note do not change the ageing at that date."""
    def test_later_receipt_and_credit_note(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        db, user = new_db(folder.name)
        customer = db.save_party({"kind": "customer", "name": "Cedar", "currency": "USD"}, user)
        db.create_manual_invoice({"invoice_number": "S1", "invoice_date": "10-01-2026", "due_date": "10-01-2026", "party_name": "Cedar", "kind": "sale",
                                  "currency": "USD"}, [{"description": "x", "quantity": 1, "unit_price": 100, "vat_rate": 0}], user)
        db.add_payment({"kind": "customer_receipt", "payment_date": "20-02-2026", "party_id": customer["id"], "currency": "USD", "amount": "40",
                        "cash_account": "531", "party_account": customer["account_number"]}, user)  # not allocated, after 31-01
        db.create_manual_invoice({"invoice_number": "CN1", "invoice_date": "25-02-2026", "party_name": "Cedar", "kind": "sale", "currency": "USD",
                                  "doc_subtype": "credit_note"}, [{"description": "x", "quantity": 1, "unit_price": 10, "vat_rate": 0}], user)
        at_january = {r["invoice_number"]: r["outstanding"] for r in db.aging_report("31-01-2026", "sale")}
        self.assertEqual(at_january, {"S1": 100.0})
        at_march = sum(r["outstanding"] for r in db.aging_report("31-03-2026", "sale"))
        self.assertAlmostEqual(at_march, 50.0)  # 100 - 40 unallocated - 10 credit note
