"""2.9.103: signed licence instead of a hidden account, administrator checks in one place, 12-hour sessions."""
import re
import socket
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

import licence

from tests import REPO as HERE  # 2.9.117: the program is in nanza/..., the tests in tests/


class SignedLicenceTest(unittest.TestCase):
    """A test seller key replaces the real public key for these tests (the real seller key file is not in the repository)."""

    @classmethod
    def setUpClass(cls):
        import server
        from client import ApiClient
        cls.saved_key = licence.PUBLIC_KEY
        cls.key_file, licence.PUBLIC_KEY = licence.new_key_pair("Seller-Test-Pass")
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(cls.folder.name) / "l.db"),
                                                           "admin_password": "Admin-2025!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        licence.PUBLIC_KEY = cls.saved_key
        import gc; gc.collect(); cls.folder.cleanup()

    def api(self):
        from client import ApiClient
        return ApiClient(self.url)

    def code(self, installation, until, password="Seller-Test-Pass", key=None):
        return licence.make_code(key or self.key_file, password, installation, "Client Co", until)

    def test_trial_code_expiry_and_no_hidden_account(self):
        api = self.api(); state = api.licence()
        self.assertTrue(state["trial"]); self.assertFalse(state["expired"]); self.assertEqual(len(state["installation_id"]), 19)
        ident = state["installation_id"]
        # the 2.9.101 hidden account cannot sign in any more
        with self.assertRaises(Exception): api.login("saber-owner", "anything-at-all")
        # a wrong key password, another installation, a changed code, a code from another seller key: all refused
        with self.assertRaises(ValueError): self.code(ident, "31-12-2027", password="wrong")
        with self.assertRaises(Exception): api.install_licence(self.code("AAAA-BBBB-CCCC-DDDD", "31-12-2027"))
        good = self.code(ident, "31-12-2027")
        prefix, payload, signature = good.split(".")
        forged = licence._b64(licence._unb64(payload).replace(b"2027", b"2099"))
        with self.assertRaises(Exception): api.install_licence(f"{prefix}.{forged}.{signature}")
        other_key, _ = licence.new_key_pair("Another-Seller-1")
        with self.assertRaises(Exception): api.install_licence(self.code(ident, "31-12-2099", "Another-Seller-1", other_key))
        # the genuine code (pasted with spaces / new lines) is accepted
        state = api.install_licence(good[:30] + "\n " + good[30:])
        self.assertTrue(state["licensed"]); self.assertEqual(state["company"], "Client Co"); self.assertEqual(state["valid_until"], "2027-12-31")
        admin = self.api(); session = admin.login("admin", "Admin-2025!")
        self.assertEqual(session["licence"]["valid_until"], "2027-12-31")
        # an ended licence blocks sign-in and open sessions; a new code opens them again
        yesterday = (date.today() - timedelta(days=1)).strftime("%d-%m-%Y")
        api.install_licence(self.code(ident, yesterday))
        with self.assertRaises(Exception) as caught: self.api().login("admin", "Admin-2025!")
        self.assertIn("ended", str(caught.exception))
        with self.assertRaises(Exception): admin.users()
        api.install_licence(self.code(ident, "31-12-2030"))
        self.api().login("admin", "Admin-2025!")

    def test_seller_key_password_can_be_changed(self):
        new = licence.change_key_password(self.key_file, "Seller-Test-Pass", "A-New-Seller-Pass")
        with self.assertRaises(ValueError): licence.make_code(new, "Seller-Test-Pass", "AAAA-BBBB-CCCC-DDDD", "X", "31-12-2030")
        code = licence.make_code(new, "A-New-Seller-Pass", "AAAA-BBBB-CCCC-DDDD", "X", "31-12-2030")
        self.assertEqual(licence.read_code(code)["installation"], "AAAA-BBBB-CCCC-DDDD")  # same key, new password
        with self.assertRaises(ValueError): licence.change_key_password(self.key_file, "Seller-Test-Pass", "short")


class ClockTurnedBackTest(unittest.TestCase):
    """2.9.104: turning the computer's date back does not make the licence last longer."""

    def test_date_turned_back_is_refused(self):
        from database import Database
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret12345")
            with db.connect() as c:
                today = date.today()
                self.assertFalse(licence.status(c, today)["expired"])
                later = today + timedelta(days=20)
                self.assertFalse(licence.status(c, later)["expired"])           # used 20 days later
                self.assertFalse(licence.status(c, later - timedelta(days=1))["expired"])  # a day back: tolerated (time zones)
                back = licence.status(c, later - timedelta(days=10))           # then the date is turned back 10 days
                self.assertTrue(back["expired"] and back["clock_back"]); self.assertIn("Correct the date", back["message"])
                self.assertFalse(licence.status(c, later)["expired"])           # date corrected: works again
                c.execute("DELETE FROM app_settings WHERE key=?", (licence.SEEN_KEY,))  # deleting the saved date does not help:
                future_line = (today + timedelta(days=40)).isoformat() + "T10:00:00+00:00"   # the audit trail keeps the latest date
                c.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(NULL,'test','x','{}',?)", (future_line,))
                self.assertTrue(licence.status(c, today + timedelta(days=30))["clock_back"])


class DuplicateWarningTest(unittest.TestCase):
    """Same supplier and same invoice number: a warning on every screen (the check is in the client used by all of them)."""

    def test_same_supplier_and_number_warns(self):
        import server
        from client import ApiClient
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
            threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(Path(folder) / "d.db"),
                                                               "admin_password": "Admin-2025!"}, daemon=True).start()
            api = ApiClient(f"http://127.0.0.1:{port}")
            for _ in range(200):
                try: api.login("admin", "Admin-2025!"); break
                except Exception: time.sleep(0.05)
            company = api.create_company({"name": "Dup Co", "year": 2026}); api.select_company_year(company["id"], 2026)
            api.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
            asked = []
            invoice = {"invoice_number": "SJ2025-2445", "invoice_date": "05-03-2026", "party_name": "Paper Supplier", "kind": "purchases", "currency": "USD", "status": "posted"}
            lines = [{"description": "Paper", "quantity": 1, "unit_price": 100, "vat_rate": 0}]
            api.confirm_duplicate = lambda text: asked.append(text) or False
            api.create_manual_invoice(invoice, lines)
            self.assertEqual(asked, [])  # the first one: no warning
            with self.assertRaises(RuntimeError): api.create_manual_invoice({**invoice, "invoice_number": "sj2025-2445 "}, lines)
            self.assertIn("already saved", asked[0])
            api.create_manual_invoice({**invoice, "party_name": "Another Supplier"}, lines)  # same number, other supplier: fine
            api.confirm_duplicate = lambda text: True
            api.create_manual_invoice(invoice, lines)  # confirmed: saved again
            api.confirm_duplicate = lambda text: False
            expense = {"expense_date": "06-03-2026", "description": "EDL", "currency": "USD", "without_vat_subtotal": "50", "vat": "0",
                       "expense_without_vat_account": "6262", "payment_account": "531", "reference": "EDL-778"}
            api.add_expense(expense)
            with self.assertRaises(RuntimeError): api.add_expense(expense)
            api.add_expense({**expense, "duplicate_ok": True})


class OldHiddenAccountTest(unittest.TestCase):
    def test_upgrade_switches_off_the_hidden_account(self):
        import owner_access
        from database import Database
        from database_common import hash_password, utcnow
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "o.db"); db.initialize("secret12345")
            with db.connect() as c:
                c.execute("INSERT INTO users(username,password_hash,role,language,active,hidden,created_at) VALUES('saber-owner',?,'admin','en',1,1,?)",
                          (hash_password("Old-Owner-2026"), utcnow()))
                owner_access.migrate(c)
                row = c.execute("SELECT active,password_hash FROM users WHERE username='saber-owner'").fetchone()
            self.assertEqual((row["active"], row["password_hash"]), (0, "!"))
            self.assertIsNone(db.login("saber-owner", "Old-Owner-2026"))
            self.assertNotIn("saber-owner", [u["username"] for u in db.list_users()])


class AdminChecksInOnePlaceTest(unittest.TestCase):
    def test_every_admin_check_is_in_the_central_list(self):
        import server
        lines = (HERE / "server.py").read_text(encoding="utf-8").splitlines()
        method, missing = None, []
        for index, line in enumerate(lines):
            found = re.match(r"\s*def _?do_(GET|POST|PUT|DELETE)\(", line)
            if found: method = found.group(1)
            if re.search(r'if user\["role"\] ?!= ?"admin": return self\._json\(403', line) and "admin_only(" not in line:
                for back in range(index - 1, max(index - 6, 0), -1):
                    paths = re.findall(r'"(/api/[^"]*)"', lines[back])
                    if paths and "path" in lines[back]:
                        for path in paths:
                            probe = path + "1" if path.endswith("/") else path
                            if not server.admin_only(method, probe): missing.append((method, path))
                        break
        self.assertEqual(missing, [], "add these to ADMIN_ONLY in server.py")

    def test_non_admin_is_refused_by_the_central_check(self):
        import server
        self.assertTrue(server.admin_only("PUT", "/api/companies/3"))
        self.assertTrue(server.admin_only("DELETE", "/api/opening-vouchers/9"))
        self.assertFalse(server.admin_only("GET", "/api/invoices"))

    def test_sessions_last_12_hours(self):
        import database_common
        self.assertEqual(database_common.SESSION_HOURS, 12)


if __name__ == "__main__":
    unittest.main()
