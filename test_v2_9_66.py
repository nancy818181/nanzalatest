"""2.9.66: Financial Reports opened first, switching company, account tools, trial balance without opening / closing,
several rows selected with their totals."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import ledger_reports
from test_final_features import new_db

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class AccountToolsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, self.user = new_db(self.folder.name)
        db, user = self.db, self.user
        self.unused = db.save_party({"kind": "customer", "name": "Unused Client", "account_category": "client"}, user)
        self.bfg = db.save_party({"kind": "supplier", "name": "BFG", "account_category": "supplier"}, user)
        self.dup = db.save_party({"kind": "supplier", "name": "BFG dup", "account_category": "supplier"}, user)
        db.add_payment({"kind": "supplier_payment", "payment_date": "15-03-2025", "amount": "100", "currency": "USD", "party_id": self.dup["id"], "cash_account": "531"}, user)
        self.expense = db.save_account({"code": "6011", "name_en": "Old expense", "type": "expense"}, user)

    def tearDown(self): self.folder.cleanup()

    def test_unused_accounts_and_delete(self):
        unused = {a["code"] for a in self.db.unused_accounts("all")}
        self.assertIn(self.unused["account_number"], unused); self.assertIn(self.expense["code"], unused)
        self.assertNotIn(self.dup["account_number"], unused); self.assertNotIn("6011", unused)
        self.assertEqual({a["code"] for a in self.db.unused_accounts("clients")}, {self.unused["account_number"]})
        result = self.db.delete_accounts([self.unused["account_number"], self.dup["account_number"], "6011", self.expense["code"]], self.user)
        self.assertEqual({d["code"] for d in result["deleted"]}, {self.unused["account_number"], self.expense["code"]})
        reasons = {k["code"]: k["reason"] for k in result["kept"]}
        self.assertIn("journal line", reasons[self.dup["account_number"]]); self.assertIn("official chart account", reasons["6011"])
        self.assertNotIn("Unused Client", [p["name"] for p in self.db.list_parties()])  # its file went with its account

    def test_move_and_merge(self):
        result = self.db.move_account(self.dup["account_number"], self.bfg["account_number"], self.user, merge_party=True)
        self.assertEqual((result["lines"], result["merged_party"]), (1, "BFG dup"))
        self.assertEqual([p["name"] for p in self.db.list_parties() if p["name"].startswith("BFG")], ["BFG"])
        self.assertEqual(self.db.list_payments()[0]["party_name"], "BFG")
        self.assertTrue(self.db.account_usage([self.dup["account_number"]])[self.dup["account_number"]]["free"])
        with self.assertRaisesRegex(ValueError, "different"): self.db.move_account("531", "531", self.user)

    def test_transfer_balance(self):
        result = self.db.transfer_balance(self.dup["account_number"], self.bfg["account_number"], "31-03-2025", self.user)
        self.assertEqual(result["vouchers"][0]["amount"], 100.0)
        report = ledger_reports.build_account_report(self.db, {"account_from": "401", "account_to": "401999999", "first_column": "USD", "second_column": "none"})
        balances = {r[0]: float(r[-1]) for r in report["sections"][0]["rows"] if str(r[0]).isdigit()}
        self.assertEqual(balances.get(self.dup["account_number"], 0.0), 0.0); self.assertEqual(balances[self.bfg["account_number"]], 100.0)


class WithoutOpeningClosingTest(unittest.TestCase):
    def test_flags(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = new_db(folder)
            db.save_journal_voucher({"entry_date": "01-01-2025", "description": "Opening", "currency": "USD", "voucher_type": "04"},
                                    [{"account_code": "531", "side": "D", "amount": "1000"}, {"account_code": "101", "side": "C", "amount": "1000"}], user)
            db.save_journal_voucher({"entry_date": "10-01-2025", "description": "x", "currency": "USD"},
                                    [{"account_code": "601100000", "side": "D", "amount": "50"}, {"account_code": "531", "side": "C", "amount": "50"}], user)
            db.save_journal_voucher({"entry_date": "31-12-2025", "description": "Closing", "currency": "USD", "voucher_type": "05"},
                                    [{"account_code": "121", "side": "D", "amount": "50"}, {"account_code": "601100000", "side": "C", "amount": "50"}], user)
            def balances(**options):
                report = ledger_reports.build_account_report(db, {"first_column": "USD", "second_column": "none", **options})
                return {r[0]: float(r[-1]) for r in report["sections"][0]["rows"] if str(r[0]).isdigit()}
            self.assertEqual((balances()["531"], balances().get("601100000", 0.0)), (950.0, 0.0))
            self.assertEqual(balances(without_opening=True)["531"], -50.0)
            self.assertEqual(balances(without_closing=True)["601100000"], 50.0)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SelectionTest(unittest.TestCase):
    def test_totals_and_drag(self):
        from tkinter import ttk
        import desktop_common as dc
        root = tk.Tk(); self.addCleanup(root.destroy)
        columns = [("entry", "Entry", 80), ("debit", "Debit", 80), ("credit", "Credit", 80), ("balance", "Balance", 80)]
        tree = ttk.Treeview(root, columns=[c[0] for c in columns], show="headings", selectmode="extended"); tree.pack()
        for i, (d, c) in enumerate(((100, 0), (0, 100), ("1,250.50", 0))): tree.insert("", "end", iid=f"r{i}", values=(f"E{i}", d, c, 0))
        label = tk.Label(root); update = dc.selection_totals(tree, columns, label); tree._totals_skip = {"balance"}
        tree.selection_set(("r0", "r2")); update()
        self.assertEqual(label.cget("text"), "2 selected   Debit: 1,350.50   Credit: 0.00")
        tree.selection_set(("r0",)); update(); self.assertEqual(label.cget("text"), "")
        dc.enable_drag_select(tree); root.update()
        y0 = tree.bbox("r0")[1] + 3; y2 = tree.bbox("r2")[1] + 3
        tree.event_generate("<ButtonPress-1>", x=10, y=y0); tree.event_generate("<B1-Motion>", x=10, y=y2); root.update()
        self.assertEqual(tree.selection(), ("r0", "r1", "r2"))


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class PagesOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from client import ApiClient
        from server import run_server
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database), "admin_password": "admin12345"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: ApiClient(cls.url).login("admin", "admin12345"); break
            except Exception: time.sleep(0.1)
        api = ApiClient(cls.url); api.login("admin", "admin12345"); cls.company = api.companies()[0]

    def test_financial_reports_first_and_switching_company(self):
        import desktop
        messages = []
        for name in ("showerror", "showwarning", "showinfo"):
            patch = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, n=name, **k: messages.append((n, a)) or True); patch.start(); self.addCleanup(patch.stop)
        import gc; self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy)
        app.server.set(self.url); app.password.set("admin12345"); app.login()
        year = self.company["years"][0]["year"]
        app.client.select_company_year(self.company["id"], year); app.current_company = self.company; app.current_fiscal_year = int(year)
        app.main_screen()
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("reports_tab")]); app.update()
        self.assertEqual(messages, [])
        app.main_screen(); app.update()  # Switch Company / Year while pages were still waiting
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
