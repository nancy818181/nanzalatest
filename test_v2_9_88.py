"""2.9.88: several users at the same time on one company (the shared data service), with a second program writing
to the same file, and the start-up on Windows with the -shm file held by another program."""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path

import server
from client import ApiClient


class MultiUserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; cls.database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(cls.database), "admin_password": "Admin-2025!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(200):
            try: ApiClient(cls.url).login("admin", "Admin-2025!"); break
            except Exception: time.sleep(0.05)
        admin = ApiClient(cls.url); admin.login("admin", "Admin-2025!")
        cls.company = admin.create_company({"name": "Shared Co", "year": 2025, "main_currency_1": "USD", "main_currency_2": "LBP"})
        admin.select_company_year(cls.company["id"], 2025)
        admin.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        for name in ("rita", "omar", "lina"):
            admin.save_user({"username": name, "password": f"{name.title()}-2025!", "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True, "delete": True}})
        cls.admin = admin

    @classmethod
    def tearDownClass(cls):
        import gc; gc.collect(); cls.folder.cleanup()

    def test_four_users_and_a_second_program_at_the_same_time(self):
        errors, numbers = [], []
        from company_manager import CompanyManager
        company_file = str(CompanyManager(self.database).year_file(next(c for c in CompanyManager(self.database).list_companies(True) if c["id"] == self.company["id"]), 2025))

        def user(name, password):
            try:
                api = ApiClient(self.url); api.login(name, password); api.select_company_year(self.company["id"], 2025)
                party = api.save_party({"kind": "customer", "name": f"Client of {name}", "currency": "USD", "account_category": "client"})
                for i in range(20):
                    created = api.create_manual_invoice({"invoice_date": f"{i % 28 + 1:02d}-03-2025", "party_name": party["name"], "kind": "sales", "currency": "USD", "status": "posted"},
                                                        [{"description": "Service", "quantity": 1, "unit_price": 100 + i, "vat_rate": 11}])
                    numbers.append(created.get("invoice_number") or created.get("invoice_id"))
                    if i % 4 == 0:
                        api.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": f"{i % 28 + 1:02d}-03-2025", "currency": "USD",
                                         "amount": "50", "cash_account": "531", "payment_method": "Cash"})
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")

        writer = ("import sys,time\nsys.path.insert(0,%r)\nfrom database import Database\ndb=Database(%r)\n"
                  "for i in range(15):\n    db.save_journal_voucher({'entry_date':'15-03-2025','description':'second program','currency':'USD','voucher_type':'01'},"
                  "[{'account_code':'531','debit':'10'},{'account_code':'101','credit':'10'}],1)\n    time.sleep(0.02)\n") % (str(Path(__file__).parent), company_file)
        second = subprocess.Popen([sys.executable, "-c", writer], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        threads = [threading.Thread(target=user, args=args) for args in (("admin", "Admin-2025!"), ("rita", "Rita-2025!"), ("omar", "Omar-2025!"), ("lina", "Lina-2025!"))]
        for t in threads: t.start()
        for t in threads: t.join(300)
        out, err = second.communicate(timeout=300)
        self.assertEqual(errors, []); self.assertEqual(second.returncode, 0, err[-800:])
        invoices = [i for i in self.admin.invoices() if i["kind"] == "sale"]
        self.assertEqual(len(invoices), 80)
        self.assertEqual(len({i["invoice_number"] for i in invoices}), 80)  # no number given twice
        journal = self.admin.journal()
        self.assertEqual(sum(1 for r in journal if r.get("description") == "second program" and r["account_code"] == "531"), 15)
        entries = {}
        for r in journal: entries.setdefault(r["entry_number"], Decimal("0")); entries[r["entry_number"]] += Decimal(str(r["debit"] or 0)) - Decimal(str(r["credit"] or 0))
        self.assertFalse({k: v for k, v in entries.items() if abs(v) > Decimal("0.005")})  # every entry balanced
        import sqlite3 as _sqlite
        with _sqlite.connect(company_file) as raw:
            numbers_used = raw.execute("SELECT entry_number,COUNT(*) FROM journal_entries GROUP BY entry_number HAVING COUNT(*)>1").fetchall()
            payments = raw.execute("SELECT COUNT(*),COUNT(DISTINCT payment_number) FROM payments").fetchone()
        self.assertEqual(numbers_used, [])  # no voucher number twice, even with the second program writing
        self.assertEqual(payments, (20, 20))
        rows = self.admin.trial_balance(to_date="31-12-2025")
        self.assertLess(abs(sum(Decimal(str(r.get("debit") or 0)) - Decimal(str(r.get("credit") or 0)) for r in rows)), Decimal("0.01"))


@unittest.skipUnless(os.name == "nt", "Windows only: a file held by another program")
class WindowsStartTest(unittest.TestCase):
    def test_start_while_the_shm_file_is_held(self):
        import ctypes
        from ctypes import wintypes
        from database import Database
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "held.db"
        first = Database(path); first.initialize("secret12345"); first.release()
        Path(str(path) + "-shm").write_bytes(b"\0" * 32768)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path) + "-shm", 0xC0000000, 0, None, 3, 0x80, None)  # no sharing: like an antivirus scan
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        threading.Timer(1.5, lambda: kernel.CloseHandle(handle)).start()  # the other program lets go after 1.5 s
        started = time.monotonic()
        again = Database(path)
        with again.connect() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] > 0, True)
        again.release()
        self.assertLess(time.monotonic() - started, 15)

    def test_speed_on_windows(self):
        from database import Database
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        db = Database(Path(folder.name) / "speed.db"); db.initialize("secret12345"); self.addCleanup(db.release)
        db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        started = time.monotonic()
        for i in range(300):
            db.create_manual_invoice({"invoice_date": f"{i % 28 + 1:02d}-{i % 12 + 1:02d}-2025", "party_name": f"Client {i % 20}", "kind": "sales", "currency": "USD", "status": "posted"},
                                     [{"description": "S", "quantity": 1, "unit_price": 100 + i, "vat_rate": 11}], 1)
        saving = time.monotonic() - started
        started = time.monotonic(); db.journal(); db.trial_balance(None, None); reports = time.monotonic() - started
        print(f"\nWindows speed: 300 invoices saved in {saving:.1f} s ({saving / 300 * 1000:.0f} ms each); journal + trial balance {reports:.2f} s")
        self.assertLess(saving / 300, 1.0); self.assertLess(reports, 10)


if __name__ == "__main__":
    unittest.main()
