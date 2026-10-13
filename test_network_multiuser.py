"""2.9.102: several users on the office network at the same time.

Five users (the administrator and four accountants), each with their own session, save journal vouchers and expenses
into the same company at the same moment while others read the trial balance. Nothing may be lost, no number may be
given twice, no request may fail with "database is locked", and the books must still balance."""
import socket
import tempfile
import threading
import time
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

USERS = [("admin", "Admin-2025!")] + [(f"user{i}", f"User{i}-Pass-2026") for i in range(1, 5)]
VOUCHERS_EACH, EXPENSES_EACH = 12, 4


class MultiUserNetworkTest(unittest.TestCase):
    TLS = False  # the same test over HTTPS with the office certificate: MultiUserHttpsTest below

    @classmethod
    def setUpClass(cls):
        import os, server
        from client import ApiClient
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        options = {"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "n.db"), "admin_password": "Admin-2025!"}
        cls.old_cert = os.environ.get("SABER_SERVER_CERT")
        if cls.TLS:
            try: import cryptography  # noqa: F401
            except ImportError: raise unittest.SkipTest("cryptography is needed to make the office certificate")
            import office_tls
            cert, key = office_tls.make_certificate(Path(cls.folder.name) / "tls", ["localhost", "127.0.0.1"])
            options.update(tls_cert=str(cert), tls_key=str(key)); os.environ["SABER_SERVER_CERT"] = str(cert)
        threading.Thread(target=server.run_server, kwargs=options, daemon=True).start()
        cls.url = f"{'https' if cls.TLS else 'http'}://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)
        admin = ApiClient(cls.url); admin.login("admin", "Admin-2025!")
        cls.company = admin.create_company({"name": "Network Co", "year": 2026}); admin.select_company_year(cls.company["id"], 2026)
        admin.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        for name, password in USERS[1:]:
            admin.save_user({"username": name, "password": password, "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True}})
        cls.admin = admin

    @classmethod
    def tearDownClass(cls):
        import gc, os
        if cls.old_cert is None: os.environ.pop("SABER_SERVER_CERT", None)
        else: os.environ["SABER_SERVER_CERT"] = cls.old_cert
        gc.collect(); cls.folder.cleanup()

    def session(self, name, password):
        from client import ApiClient
        api = ApiClient(self.url); api.login(name, password); api.select_company_year(self.company["id"], 2026); return api

    def test_five_users_save_at_the_same_time(self):
        errors, numbers, amounts = [], [], []
        lock = threading.Lock(); start = threading.Barrier(len(USERS) + 1)

        def work(index, name, password):
            try: api = self.session(name, password)
            except Exception as exc:
                with lock: errors.append(f"{name} sign in: {exc}")
                start.wait(); return
            start.wait()  # everybody starts together
            for n in range(VOUCHERS_EACH):
                amount = Decimal(f"{index + 1}{n:02d}.25")
                try:
                    result = api.request("POST", "/api/journal-vouchers", {
                        "voucher": {"entry_date": f"{(n % 28) + 1:02d}-03-2026", "description": f"{name} voucher {n}", "currency": "USD", "voucher_type": "01"},
                        "lines": [{"account_code": "6262", "debit": str(amount)}, {"account_code": "531", "credit": str(amount)}]})
                    with lock: numbers.append((result.get("voucher") or {}).get("entry_number")); amounts.append(amount)
                except Exception as exc:
                    with lock: errors.append(f"{name} voucher {n}: {exc}")
                if n % 3 == 0:
                    try: api.trial_balance(to_date="31-12-2026")  # reading while the others write
                    except Exception as exc:
                        with lock: errors.append(f"{name} read: {exc}")
            for n in range(EXPENSES_EACH):
                try:
                    api.add_expense({"expense_date": f"{n + 1:02d}-04-2026", "description": f"{name} taxi {n}", "currency": "USD",
                                     "without_vat_subtotal": "10", "vat": "0", "expense_without_vat_account": "6262", "payment_account": "531"})
                    with lock: amounts.append(Decimal("10"))
                except Exception as exc:
                    with lock: errors.append(f"{name} expense {n}: {exc}")

        threads = [threading.Thread(target=work, args=(i, name, password)) for i, (name, password) in enumerate(USERS)]
        for thread in threads: thread.start()
        start.wait(); began = time.time()
        for thread in threads: thread.join(timeout=300)
        self.assertFalse(any(t.is_alive() for t in threads), "a user is still waiting (locked?)")
        self.assertEqual(errors, [])
        expected = len(USERS) * VOUCHERS_EACH
        self.assertEqual(len(numbers), expected)
        duplicated = [n for n, count in Counter(numbers).items() if count > 1]
        self.assertEqual(duplicated, [], "the same voucher number was given twice")
        self.assertNotIn(None, numbers)
        # nothing lost: every amount is in the books, and the books balance
        rows = self.admin.trial_balance(to_date="31-12-2026")
        cost = sum(Decimal(str(r["debit"])) - Decimal(str(r["credit"])) for r in rows if r["code"] == "6262")
        self.assertEqual(cost, sum(amounts))
        self.assertEqual(sum(Decimal(str(r["debit"])) for r in rows), sum(Decimal(str(r["credit"])) for r in rows))
        self.assertEqual(len(self.admin.expenses()), len(USERS) * EXPENSES_EACH)
        self.assertLess(time.time() - began, 240)
        self.assertTrue(self.url.startswith("https://") == self.TLS)


class MultiUserHttpsTest(MultiUserNetworkTest):
    """The same five users at the same time, over HTTPS with the office certificate (data encrypted on the network)."""
    TLS = True


if __name__ == "__main__":
    unittest.main()
