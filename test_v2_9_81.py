"""2.9.81: Accounting Settings (what the company / each user sees, default posting accounts) and the Year-End Check."""
import tests_setup  # noqa: F401  the sample company of the window tests
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import accounting_setup
import server
import vat_return
from database import Database

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "books.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)


class SetupTest(_Book):
    def test_hidden_modules_company_and_user(self):
        saved = accounting_setup.save_setup(self.db, {"hidden": ["payroll", "report:Cash Budget", "nonsense"]}, 1)
        self.assertEqual(saved["hidden"], ["payroll", "report:Cash Budget"])
        self.assertEqual(accounting_setup.save_user_hidden(self.db, 1, ["inventory", "x"]), ["inventory"])
        self.assertEqual(accounting_setup.setup(self.db, self.db, 1)["user_hidden"], ["inventory"])

    def test_default_accounts_are_checked_and_used(self):
        with self.assertRaisesRegex(ValueError, "must start with 6"): accounting_setup.save_setup(self.db, {"defaults": {"bank_commission": "4011"}}, 1)
        with self.assertRaisesRegex(ValueError, "not in the chart"): accounting_setup.save_setup(self.db, {"defaults": {"bank_commission": "679999999"}}, 1)
        accounting_setup.save_setup(self.db, {"defaults": {"bank_commission": "6739 - Bank Commissions & Other Charges", "expenses_import": "6263.1", "vat_payable": "4425.1"}}, 1)
        self.assertEqual(self.db.default_account("bank_commission"), "6739")
        listing = {row["key"]: row for row in accounting_setup.default_accounts_listing(self.db)}
        self.assertEqual((listing["expenses_import"]["account"], listing["purchases"]["account"]), ("6263.1", "601100000"))
        # an expense without an account and a receipt with a commission use them
        self.db.add_expense({"expense_date": "05-03-2025", "description": "Rent", "currency": "USD", "with_vat_subtotal": "100", "vat": "11"}, 1)
        self.assertIn("6263.1", {r["account_code"] for r in self.db.journal() if r["source_type"] == "expense"})
        party = self.db.save_party({"kind": "customer", "name": "C", "currency": "USD"}, 1)
        self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "06-03-2025", "currency": "USD", "amount": "50", "cash_account": "512", "bank_commission": "1"}, 1)
        self.assertIn("6739", {r["account_code"] for r in self.db.journal() if r["source_type"] == "payment"})
        # the VAT settlement proposes the chosen payable account
        self.db.import_invoice({"invoice_number": "S-1", "invoice_date": "15-02-2025", "party_name": "C", "kind": "sale", "currency": "LBP",
                "subtotal": 100000000, "vat": 11000000, "total": 111000000}, 1)
        plan = vat_return.settlement_lines(self.db, vat_return.build_vat_return(self.db, 2025, 1))
        self.assertIn("4425.1", {line["account_code"] for line in plan["lines"]})
        # and back to the program defaults
        accounting_setup.save_setup(self.db, {"defaults": {key: "" for key in accounting_setup.DEFAULT_ACCOUNTS}}, 1)
        self.assertEqual(self.db.default_account("bank_commission"), "673900000")

    def test_doe_accepts_the_chosen_gain_account(self):
        accounting_setup.save_setup(self.db, {"defaults": {"exchange_gain": "7751"}}, 1)
        self.db.save_journal_voucher({"entry_date": "30-09-2025", "description": "DOE", "currency": "LBP", "voucher_type": "07"},
                                     [{"account_code": "4011", "debit": "1000"}, {"account_code": "7751", "credit": "1000"}], 1)


class YearEndCheckTest(_Book):
    def status(self, check, name): return next(r["status"] for r in check["results"] if r["check"] == name)

    def test_clean_books_are_ready(self):
        check = accounting_setup.year_end_check(self.db, 2025)
        self.assertEqual((check["errors"], check["warnings"], check["summary"]), (0, 0, "Ready to close"))

    def test_problems_are_found(self):
        self.db.save_journal_voucher({"entry_date": "10-03-2025", "description": "Overdrawn", "currency": "USD"},
                                     [{"account_code": "601100000", "debit": "100"}, {"account_code": "531", "credit": "100"}], 1)
        self.db.save_journal_voucher({"entry_date": "11-03-2025", "description": "Unknown", "currency": "USD"},
                                     [{"account_code": "471", "debit": "50"}, {"account_code": "101", "credit": "50"}], 1)
        self.db.import_invoice({"invoice_number": "S-1", "invoice_date": "15-02-2025", "party_name": "C", "kind": "sale", "currency": "LBP", "subtotal": 1000000, "vat": 110000, "total": 1110000}, 1)
        party = self.db.save_party({"kind": "customer", "name": "Payer", "currency": "USD"}, 1)
        self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "06-03-2025", "currency": "USD", "amount": "50", "cash_account": "512"}, 1)
        check = accounting_setup.year_end_check(self.db, 2025)
        self.assertEqual(self.status(check, "Cash and bank not negative"), "ERROR")
        self.assertEqual(self.status(check, "Suspense accounts (47) cleared"), "WARNING")
        self.assertEqual(self.status(check, "Quarterly VAT"), "WARNING")
        self.assertEqual(self.status(check, "VAT accounts settled"), "WARNING")
        self.assertEqual(self.status(check, "Receipts / payments allocated"), "WARNING")
        self.assertEqual(self.status(check, "Customers / suppliers on the right side"), "WARNING")  # the payer is in credit
        self.assertEqual(self.status(check, "Trial balance"), "OK")
        self.assertTrue(accounting_setup.year_end_sections(check)[0]["rows"])


@unittest.skipUnless(HAVE_DISPLAY, "needs a display for the program window")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from client import ApiClient
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database), "admin_password": "admin12345"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: ApiClient(cls.url).login("admin", "admin12345"); break
            except Exception: time.sleep(0.1)
        api = ApiClient(cls.url); api.login("admin", "admin12345")
        cls.company = api.companies()[0]; api.select_company_year(cls.company["id"], cls.company["years"][0]["year"])
        api.save_accounting_setup({"hidden": ["inventory", "report:Cash Budget"]})
        cls.api = api

    @classmethod
    def tearDownClass(cls):
        cls.api.save_accounting_setup({"hidden": []})
        import gc; gc.collect(); cls.folder.cleanup()

    def setUp(self):
        self.messages = []
        for name in ("showerror", "showwarning", "showinfo", "askyesno"):
            patch = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, n=name, **k: self.messages.append((n, a)) or True)
            patch.start(); self.addCleanup(patch.stop)
        import desktop, gc
        self.addCleanup(gc.collect)
        self.app = desktop.SaberApp(); self.addCleanup(self.app.destroy)
        self.app.server.set(self.url); self.app.password.set("admin12345"); self.app.login()
        year = self.company["years"][0]["year"]
        self.app.client.select_company_year(self.company["id"], year); self.app.current_company = self.company; self.app.current_fiscal_year = int(year)
        self.app.main_screen(); self.app.update()

    def test_hidden_screen_and_report(self):
        app = self.app
        self.assertNotIn("inventory_tab", app._page_attributes); self.assertIn("settings_tab", app._page_attributes)
        app.select_main_tab(app.inventory_tab)
        self.assertTrue(any("hidden" in str(args) for kind, args in self.messages))
        page = app.reports_tab
        while page not in app.main_tab_pages: page = page.master
        app.select_main_tab(page); app.update()
        nb = app.financial_notebook
        states = {nb.tab(t, "text"): nb.tab(t, "state") for t in nb.tabs()}
        self.assertEqual(states["Cash Budget"], "hidden"); self.assertEqual(states["Cash Flow Outlook"], "normal")

    def test_settings_page_and_year_end_check_window(self):
        page = self.app.settings_tab
        while page not in self.app.main_tab_pages: page = page.master
        self.app.select_main_tab(page); self.app.update()
        self.assertIn("bank_commission", self.app.setup_default_vars)
        self.assertTrue(self.app.setup_default_vars["bank_commission"].get().startswith("673900000 - "))
        self.assertFalse(self.app.setup_company_vars["inventory"].get())
        self.assertTrue(self.app.show_year_end_check())
        windows = [w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel) and w.title().startswith("Year-End Check")]
        self.assertTrue(windows); windows[0].destroy()


if __name__ == "__main__":
    unittest.main()
