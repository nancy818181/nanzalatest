"""2.9.82: stock vs ledger, monthly stock variation, landed cost in item cost, end-of-service provision, leave balances,
payslips of a month, management pack, drill-down and budget alerts."""
import tests_setup  # noqa: F401  the sample company of the window tests
import socket
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import inventory
import management_pack
import payroll_extras
import server
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


class StockTest(_Book):
    def setUp(self):
        super().setUp()
        self.panel = inventory.save_item(self.db, {"name": "Panel"}, 1); self.steel = inventory.save_item(self.db, {"name": "Steel", "stock_account": "311"}, 1)
        self.purchase = self.db.create_manual_invoice({"invoice_number": "P-1", "invoice_date": "10-01-2025", "party_name": "S", "kind": "purchases", "currency": "USD", "status": "posted"},
            [{"description": "Panel", "quantity": 10, "unit_price": 100, "vat_rate": 0, "item_code": self.panel["sku"]},
             {"description": "Steel", "quantity": 100, "unit_price": 10, "vat_rate": 0, "item_code": self.steel["sku"]}], 1)

    def cost(self, sku): return next(i["average_cost"] for i in inventory.list_items(self.db) if i["sku"] == sku)

    def test_landed_cost_goes_into_the_item_cost_by_value(self):
        self.db.add_landed_cost(self.purchase, {"freight": "200", "customs_duties": "100", "import_vat": "33"}, 1)
        self.assertEqual((self.cost(self.panel["sku"]), self.cost(self.steel["sku"])), (115.0, 11.5))  # 300 spread 1,000 : 1,000

    def test_monthly_variation_and_stock_vs_ledger(self):
        self.db.create_manual_invoice({"invoice_date": "15-02-2025", "party_name": "C", "kind": "sales", "currency": "USD", "status": "posted"},
                                      [{"description": "Panel", "quantity": 4, "unit_price": 200, "vat_rate": 0, "item_code": self.panel["sku"]}], 1)
        before = inventory.stock_ledger_check(self.db, "2025-01-31")
        self.assertEqual((before["valuation"], before["ledger"], before["posted"]), (Decimal("2000.00"), Decimal("0.00"), False))
        inventory.post_monthly_stock_variation(self.db, "31-01-2025", 1); inventory.post_monthly_stock_variation(self.db, "28-02-2025", 1)
        again = inventory.post_monthly_stock_variation(self.db, "31-01-2025", 1)  # January again: February is posted again after it
        self.assertEqual(again["reposted"], ["2025-02"])
        feb = {r["code"]: r["amount"] for r in self.db.profit_and_loss("2025-02-01", "2025-02-28", "USD")}
        self.assertEqual((feb["6051"], feb["6052"]), (1000.0, -600.0))  # cost of sales of February = 4 x 100
        after = inventory.stock_ledger_check(self.db, "2025-02-28")
        self.assertTrue(after["posted"]); self.assertEqual(after["difference"], Decimal("0.00"))
        year = inventory.post_stock_variation(self.db, 2025, 1)  # the year end cancels and books the same stock
        self.assertEqual((year["opening"], year["closing"]), (1600.0, 1600.0))
        self.assertIn("Stock vs Ledger", inventory.build_report(self.db, "ledger_check", {"date_to": "31-12-2025"})["title"])


class PayrollExtrasTest(_Book):
    def setUp(self):
        super().setUp(); self.db.apply_lebanese_payroll_rules(1)
        self.rami = self.db.save_employee({"employee_number": "1000", "full_name": "Rami", "currency": "LBP", "base_salary": "89500000", "hire_date": "01-01-2015",
                                           "eos_paid_before": "500000000", "leave_carried": "5"}, 1)
        self.maya = self.db.save_employee({"employee_number": "1001", "full_name": "Maya", "currency": "USD", "base_salary": "1000", "hire_date": "01-07-2024"}, 1)
        for employee in (self.rami, self.maya):
            saved = self.db.save_payroll({"employee_id": employee["id"], "period_date": "31-01-2025"}, 1); self.db.post_payroll(saved["id"], 1)

    def test_end_of_service_provision_and_its_entry(self):
        result = payroll_extras.eos_provision(self.db, "31-12-2025")
        rami = next(r for r in result["rows"] if r["employee"] == "Rami")
        self.assertEqual(rami["years"], Decimal("11.00"))
        self.assertEqual(rami["provision_lbp"], rami["indemnity_lbp"] - rami["contributions_lbp"])
        self.assertGreater(rami["contributions_lbp"], Decimal("500000000"))  # before Saber + January's 8.5%
        posted = payroll_extras.post_eos_provision(self.db, "31-12-2025", 1)
        lines = sorted((r["account_code"], r["debit"], r["credit"]) for r in self.db.journal() if r["entry_number"] == posted["voucher"])
        self.assertEqual([code for code, _d, _c in lines], ["1552.1", "6355"])
        self.assertEqual(payroll_extras.eos_provision(self.db, "31-12-2025")["change_lbp"], 0)
        with self.assertRaisesRegex(ValueError, "already equals"): payroll_extras.post_eos_provision(self.db, "31-12-2025", 1)

    def test_leave_balance(self):
        payroll_extras.save_leave(self.db, {"employee_id": self.rami["id"], "date_from": "03-03-2025", "date_to": "07-03-2025"}, 1)
        payroll_extras.save_leave(self.db, {"employee_id": self.rami["id"], "date_from": "10-03-2025", "date_to": "10-03-2025", "leave_type": "sick"}, 1)
        rami = next(r for r in payroll_extras.leave_balances(self.db, "30-06-2025")["rows"] if r["employee"] == "Rami")
        self.assertEqual((rami["carried"], rami["earned"], rami["taken"]), (Decimal("5"), Decimal("7.44"), Decimal("5")))  # sick leave is not annual leave; 2.9.84: 181 / 365 days x 15 (was / 365.25)
        self.assertEqual(rami["value"], (rami["balance"] * Decimal("89500000") / 30).quantize(Decimal("0.01")))
        with self.assertRaisesRegex(ValueError, "before"): payroll_extras.save_leave(self.db, {"employee_id": self.rami["id"], "date_from": "10-03-2025", "date_to": "01-03-2025"}, 1)

    def test_payslips_of_the_month(self):
        sections = payroll_extras.payslip_sections(self.db, "31-01-2025")
        self.assertEqual(len(sections), 2); self.assertTrue(all(s.get("page_break") for s in sections))
        self.assertTrue(any(row[0] == "NET SALARY" for row in sections[0]["rows"]))
        with self.assertRaisesRegex(ValueError, "No payroll"): payroll_extras.payslip_sections(self.db, "28-02-2025")


class ManagementPackTest(_Book):
    def test_pack_balances_and_budget_alerts(self):
        self.db.save_journal_voucher({"entry_date": "01-01-2025", "description": "Open", "currency": "USD", "voucher_type": "04"},
                                     [{"account_code": "512", "debit": "10000"}, {"account_code": "101", "credit": "10000"}], 1)
        self.db.create_manual_invoice({"invoice_date": "10-03-2025", "party_name": "C", "kind": "sales", "currency": "USD", "status": "posted"},
                [{"description": "S", "quantity": 1, "unit_price": 5000, "vat_rate": 11}], 1)
        self.db.add_expense({"expense_date": "15-03-2025", "description": "Rent", "currency": "LBP", "with_vat_subtotal": "89500000", "vat": "0",
                "expense_account": "6263.1", "payment_account": "531"}, 1)
        self.db.save_budget({"year": 2025, "currency": "USD", "lines": [{"account_code": "6263.1", "annual": 1200, "months": [100] * 12},
                {"account_code": "713", "annual": 60000, "months": [5000] * 12}]}, 1)
        pack = management_pack.build(self.db, "31-03-2025", "USD")
        results = {row[0]: row for row in pack["sections"][0]["rows"]}
        self.assertEqual(results["Revenue"][1:4], [5000.0, 5000.0, 0.0]); self.assertEqual(results["Operating expenses"][1], 1000.0)  # the LBP rent, converted
        balance = {row[0]: row[1] for row in pack["sections"][1]["rows"]}
        self.assertEqual(balance["Check (should be 0)"], 0.0)
        alerts = {a["account"]: a for a in management_pack.budget_variances(self.db, 2025, 3, "USD", 10)}
        self.assertEqual(set(alerts), {"6263.1", "713"})  # rent 1,000 vs 300; sales 5,000 vs 15,000
        self.assertEqual(alerts["6263.1"]["percent"], 233.3)


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

    @classmethod
    def tearDownClass(cls):
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

    def open(self, attribute):
        page = getattr(self.app, attribute)
        while page not in self.app.main_tab_pages: page = page.master
        self.app.select_main_tab(page); self.app.update()

    def test_new_screens(self):
        self.open("payroll_tab")
        tabs = [self.app.payroll_notebook.tab(t, "text") for t in self.app.payroll_notebook.tabs()]
        self.assertIn("End of Service & Leave", tabs)
        self.app.show_eos_provision(); self.app.show_leave_balances(); self.app.update()
        self.open("reports_tab")
        names = [self.app.financial_notebook.tab(t, "text") for t in self.app.financial_notebook.tabs()]
        self.assertIn("Management Pack", names)
        self.app.build_management_pack(); self.app.update()
        self.assertTrue(self.app.mp_result["sections"])
        window = self.app.open_account_entries("531", "2020-01-01", "2030-12-31"); self.app.update()
        self.assertTrue(window.winfo_exists()); window.destroy()
        self.assertIsNone(self.app.budget_alert_item())  # no budget: no alert


if __name__ == "__main__":
    unittest.main()
