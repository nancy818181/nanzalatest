"""2.9.79: account number + name everywhere, chosen commission / exchange accounts on receipts and payments,
stock account linked to the cost account, VAT check against the ledger and VAT settlement voucher, budget and cash budget
from a chosen year and %."""
import tests_setup  # noqa: F401  the sample company of the window tests
import socket
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import financial_projection as fp
import inventory
import server
import vat_return
from database import Database

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


def new_db(folder):
    db = Database(Path(folder) / "books.db"); db.initialize("secret")
    user = db.user_for_token(db.login("admin", "secret")["token"])["id"]
    return db, user


def entry_lines(db, number):
    return sorted((r["account_code"], round(float(r["debit"]), 2), round(float(r["credit"]), 2)) for r in db.journal() if r["entry_number"] == number)


class PaymentAccountsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, self.user = new_db(self.folder.name)
        self.client = self.db.save_party({"name": "Client Bank", "kind": "customer", "currency": "USD"}, self.user)
        self.supplier = self.db.save_party({"name": "Supplier Bank", "kind": "supplier", "currency": "USD"}, self.user)

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.folder.cleanup()

    def pay(self, **extra):
        item = {"kind": "customer_receipt", "party_id": self.client["id"], "payment_date": "10-03-2026", "currency": "USD", "amount": "100",
                "cash_account": "512", **extra}
        payment_id = self.db.add_payment(item, self.user)
        return next(p for p in self.db.list_payments() if p["id"] == payment_id)

    def test_receipt_books_commission_and_loss_on_the_chosen_accounts(self):
        payment = self.pay(bank_commission="2", commission_account="6751 - Exchange Losses", exchange_difference="3",
                           exchange_gain_account="7751", exchange_loss_account="6751")
        lines = entry_lines(self.db, payment["payment_number"])
        account = self.client["account_number"]
        self.assertEqual(lines, sorted([("512", 98.0, 0.0), (account, 0.0, 103.0), ("6751", 2.0, 0.0), ("6751", 3.0, 0.0)]))
        self.assertEqual((payment["commission_account"], payment["exchange_gain_account"], payment["exchange_loss_account"]), ("6751", "7751", "6751"))

    def test_supplier_payment_gain_goes_to_the_chosen_gain_account(self):
        payment_id = self.db.add_payment({"kind": "supplier_payment", "party_id": self.supplier["id"], "payment_date": "11-03-2026", "currency": "USD",
                                          "amount": "100", "cash_account": "512", "exchange_difference": "4", "exchange_gain_account": "7751"}, self.user)
        payment = next(p for p in self.db.list_payments() if p["id"] == payment_id)
        self.assertEqual(entry_lines(self.db, payment["payment_number"]),
                         sorted([(self.supplier["account_number"], 104.0, 0.0), ("512", 0.0, 100.0), ("7751", 0.0, 4.0)]))

    def test_default_accounts_when_none_is_chosen(self):
        payment = self.pay(bank_commission="1.5", exchange_difference="-2")
        lines = entry_lines(self.db, payment["payment_number"])
        self.assertIn(("673900000", 1.5, 0.0), lines)
        self.assertIn(("775100000", 0.0, 2.0), lines)

    def test_wrong_accounts_are_refused(self):
        with self.assertRaisesRegex(ValueError, "class 6"): self.pay(bank_commission="2", commission_account="4011")
        with self.assertRaisesRegex(ValueError, "class 7"): self.pay(exchange_difference="2", exchange_gain_account="6751")
        with self.assertRaisesRegex(ValueError, "class 6"): self.pay(exchange_difference="2", exchange_loss_account="7751")
        with self.assertRaisesRegex(ValueError, "not found"): self.pay(bank_commission="2", commission_account="679999999")

    def test_edit_keeps_the_chosen_accounts(self):
        payment = self.pay(bank_commission="2", commission_account="6751")
        self.db.update_payment(payment["id"], {"party_id": self.client["id"], "payment_date": "10-03-2026", "currency": "USD", "amount": "120",
                                               "cash_account": "512", "bank_commission": "2", "commission_account": "6751"}, self.user)
        edited = self.db.list_payments()[0]
        self.assertIn(("6751", 2.0, 0.0), entry_lines(self.db, edited["payment_number"]))


class AccountLabelsTest(unittest.TestCase):
    def test_server_keeps_only_the_account_number(self):
        payload = {"cash_account": "512 - Banks", "lines": [{"account_code": "601100000 - Purchases", "description": "5 - 6"}],
                   "account_from": "4011 - Suppliers", "description": "12 - text", "party_account": "Customer - A"}
        self.assertEqual(server._account_codes(payload), {"cash_account": "512", "lines": [{"account_code": "601100000", "description": "5 - 6"}],
                                                          "account_from": "4011", "description": "12 - text", "party_account": "Customer - A"})

    def test_account_label_helper(self):
        from desktop_common import account_label, account_code
        class App: _all_accounts = {"512": "Banks"}
        self.assertEqual(account_label(App(), "512"), "512 - Banks")
        self.assertEqual(account_label(App(), "512 - Banks"), "512 - Banks")
        self.assertEqual(account_label(App(), "999"), "999")
        self.assertEqual(account_code("512 - Banks"), "512")


class StockAccountTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.db, self.user = new_db(self.folder.name)

    def tearDown(self):
        try: self.db.release()
        except Exception: pass
        self.folder.cleanup()

    def test_links(self):
        self.assertEqual(inventory.stock_link("37")[:3], ("601100000", "6051", "6052"))
        self.assertEqual(inventory.stock_link("311 - Stock of Raw Materials")[:3], ("611100000", "6151", "6152"))
        self.assertEqual(inventory.stock_link("35")[1:3], ("7255", "7255"))
        with self.assertRaises(ValueError): inventory.stock_link("4011")

    def test_item_stock_account_and_linked_cost(self):
        goods = inventory.save_item(self.db, {"name": "Goods"}, self.user)
        self.assertEqual((goods["stock_account"], goods["cost_account"]), ("37", None))  # goods keep the purchase screen account
        raw = inventory.save_item(self.db, {"name": "Steel", "stock_account": "311 - Stock of Raw Materials"}, self.user)
        self.assertEqual((raw["stock_account"], raw["cost_account"]), ("311", "611100000"))
        chosen = inventory.save_item(self.db, {"name": "Paint", "stock_account": "311", "cost_account": "611100000 - Raw"}, self.user)
        self.assertEqual(chosen["cost_account"], "611100000")
        for wrong in ("39", "4011", "x"):
            with self.assertRaisesRegex(ValueError, "class 3"): inventory.save_item(self.db, {"name": "Bad", "stock_account": wrong}, self.user)

    def test_year_end_variation_by_stock_account(self):
        goods = inventory.save_item(self.db, {"name": "Goods"}, self.user)
        raw = inventory.save_item(self.db, {"name": "Steel", "stock_account": "311"}, self.user)
        inventory.save_document(self.db, {"doc_type": "receipt", "doc_date": "2026-03-01", "warehouse_id": "MAIN"},
                                [{"sku": goods["sku"], "quantity": 10, "unit_cost": 5}, {"sku": raw["sku"], "quantity": 4, "unit_cost": 25}], self.user)
        result = inventory.post_stock_variation(self.db, 2026, self.user)
        self.assertEqual((result["opening"], result["closing"]), (0.0, 150.0))
        lines = sorted((r["account_code"], r["debit"], r["credit"]) for r in self.db.journal() if (r["description"] or "").startswith("STOCK VARIATION"))
        self.assertEqual(lines, sorted([("37", 50.0, 0.0), ("6052", 0.0, 50.0), ("311", 100.0, 0.0), ("6152", 0.0, 100.0)]))
        # a second run cancels what is now in the ledger, account by account
        again = inventory.post_stock_variation(self.db, 2026, self.user)
        self.assertEqual({g["stock_account"]: g["closing"] for g in again["groups"]}, {"37": 50.0, "311": 100.0})


class VatCheckAndSettlementTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "company.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        for number, kind, currency, subtotal, vat in (("S-1", "sale", "LBP", 1000000, 110000), ("P-1", "purchase", "LBP", 500000, 55000), ("S-2", "sale", "USD", 100, 11)):
            self.db.import_invoice({"invoice_number": number, "invoice_date": "15-02-2026", "party_name": f"Party {kind}", "kind": kind, "currency": currency,
                                    "subtotal": subtotal, "vat": vat, "total": subtotal + vat}, 1)

    def test_return_agrees_with_the_books(self):
        check = vat_return.ledger_check(self.db, vat_return.build_vat_return(self.db, 2026, 1))
        self.assertTrue(check["agreed"])
        self.assertEqual((check["ledger_output"], check["ledger_input"]), (Decimal("1094500"), Decimal("55000")))  # 110,000 + 11 USD x 89,500
        accounts = [row[0] for row in check["sections"][0]["rows"]]
        self.assertTrue(any(a.startswith("4427 - ") for a in accounts) and any(a.startswith("44210 - ") for a in accounts))

    def test_a_voucher_on_a_vat_account_is_reported(self):
        self.db.save_journal_voucher({"entry_date": "20-02-2026", "description": "Correction", "currency": "LBP"},
                                     [{"account_code": "44210", "line_currency": "LBP", "side": "D", "amount": "1000"},
                                      {"account_code": "531", "line_currency": "LBP", "side": "C", "amount": "1000"}], 1)
        check = vat_return.ledger_check(self.db, vat_return.build_vat_return(self.db, 2026, 1))
        self.assertFalse(check["agreed"])
        self.assertEqual(check["sections"][1]["rows"][1][3], Decimal("-1000"))
        self.assertTrue(any("1,000.00" in note for note in check["notes"]))

    def test_settlement_needs_a_saved_return_then_closes_the_vat_accounts(self):
        with self.assertRaisesRegex(ValueError, "Save the Q1 2026"): vat_return.post_settlement(self.db, 2026, 1, 1)
        vat_return.save_return(self.db, 2026, 1, 1)
        posted = vat_return.post_settlement(self.db, 2026, 1, 1)
        lines = sorted((l["account_code"], l["side"], l["amount"]) for l in posted["lines"])
        self.assertEqual(lines, sorted([("4425", "C", "1039500"), ("4427", "D", "1094500"), ("44210", "C", "55000")]))
        self.assertEqual(posted["return_payable"], Decimal("1040000"))  # the return rounds up to LBP 10,000
        vat_return.post_settlement(self.db, 2026, 1, 1)  # posting again replaces the voucher
        entries = {r["entry_number"] for r in self.db.journal() if (r["description"] or "").startswith(vat_return.SETTLEMENT_PREFIX)}
        self.assertEqual(len(entries), 1)
        self.assertTrue(vat_return.ledger_check(self.db, vat_return.build_vat_return(self.db, 2026, 1))["agreed"])  # the settlement is not VAT of the quarter

    def test_credit_brought_forward_and_non_deductible_vat(self):
        result = vat_return.build_vat_return(self.db, 2026, 1)
        result = {**result, "credit_brought_forward_lbp": Decimal("39500"), "totals_lbp": {**result["totals_lbp"], "prorata": Decimal("-5000"), "annual_adjustment": Decimal("0")}}
        plan = vat_return.settlement_lines(self.db, result)
        lines = sorted((l["account_code"], l["side"], l["amount"]) for l in plan["lines"])
        self.assertEqual(lines, sorted([("4425", "C", "1005000"), ("4427", "D", "1094500"), ("44210", "C", "55000"), ("4429", "C", "39500"), ("6459", "D", "5000")]))
        with self.assertRaisesRegex(ValueError, "class 6"): vat_return.settlement_lines(self.db, result, non_deductible_account="4011")

    def test_roles(self):
        self.assertEqual([vat_return.vat_account_role(c) for c in ("4427", "442700001", "44210", "442660000", "4425", "4425.1", "4429", "4011")],
                         ["output", "output", "input", "input", None, None, None, None])


class BudgetFromYearTest(unittest.TestCase):
    def test_budget_keeps_the_months_and_adds_the_percent(self):
        monthly = {"701100001": {1: 100, 6: 300}, "601100000": {1: 50}, "512": {1: 999}}
        types = {"701100001": "income", "601100000": "expense", "512": "asset"}
        lines = {code: (kind, months, annual) for code, kind, months, annual in fp.budget_from_year(monthly, types, 2025, 2026, "10", "5%")}
        self.assertEqual(set(lines), {"701100001", "601100000"})
        self.assertEqual(lines["701100001"][1][0], 110.0); self.assertEqual(lines["701100001"][1][5], 330.0); self.assertEqual(lines["701100001"][2], 440.0)
        self.assertEqual(lines["601100000"][2], 52.5)
        two_years = fp.budget_from_year(monthly, types, 2025, 2027, "10", "0")
        self.assertEqual(next(l for l in two_years if l[0] == "701100001")[3], 484.0)  # 400 x 1.1 x 1.1
        for wrong in ((2026, 2026, "1", "1"), (2020, 2026, "1", "1"), (2025, 2026, "abc", "1"), (2025, 2026, "-100", "0")):
            with self.assertRaises(ValueError): fp.budget_from_year(monthly, types, *wrong)

    def test_cash_budget_month_by_month(self):
        flows = {month: {"inflow": 1000, "outflow": 900} for month in range(1, 13)}
        flows[3] = {"inflow": 0, "outflow": 2000}
        result = fp.cash_budget(flows, 500, 2025, 2026, "10", "0")
        first, march = result["rows"][0], result["rows"][2]
        self.assertEqual((first["opening"], first["inflow"], first["outflow"], first["closing"]), (500, 1100, 900, 700))
        self.assertEqual(march["closing"], -1100)  # 500 + 200 (Jan) + 200 (Feb) - 2000 (Mar)
        self.assertEqual(result["lowest"]["month"], "2026-03")
        self.assertEqual(result["totals"]["inflow"], 12100.0)
        self.assertEqual(result["closing"], round(500 + 12100 - (900 * 11 + 2000), 2))
        later = fp.cash_budget(flows, 500, 2025, 2027, "0", "0")
        self.assertEqual(later["opening"], 500 + 11000 - 11900)  # the year in between is added to the opening cash


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
        api.save_party({"name": "Window Client", "kind": "customer", "currency": "USD"})

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

    def test_receipt_shows_its_accounts_and_journal_preview(self):
        self.open("transactions_tab")
        form = self.app.payment_forms["customer_receipt"]; v = form["vars"]
        self.assertTrue(v["commission_account"].get().startswith("673900000 - "))
        self.assertTrue(v["exchange_gain_account"].get().startswith("775100000 - ") and v["exchange_loss_account"].get().startswith("675100000 - "))
        party = next(name for name in form["party_map"] if name.startswith("Window Client"))
        v["party"].set(party); v["amount"].set("100"); v["bank_commission"].set("2"); v["exchange_difference"].set("3"); self.app.update()
        text = form["preview"].cget("text")
        self.assertIn("673900000 - ", text); self.assertIn("675100000 - ", text); self.assertIn("98.00", text)
        payload = self.app.payment_payload(form)
        self.assertEqual((payload["commission_account"], payload["exchange_gain_account"], payload["exchange_loss_account"]), ("673900000", "775100000", "675100000"))

    def test_item_stock_account_fills_its_cost_account(self):
        self.open("inventory_tab")
        app = self.app
        self.assertTrue(app.item_vars["stock_account"].get().startswith("37 - "))
        app.item_vars["stock_account"].set(app.item_stock_choice("311")); app.item_stock_account_chosen(True)
        self.assertTrue(app.item_vars["cost_account"].get().startswith("611100000 - "))
        self.assertIn("6151", app.item_link_label.cget("text"))

    def test_vat_check_tab_and_budget_tools(self):
        self.open("vat_tab"); self.app.load_vat_return(); self.app.update()
        self.assertTrue(self.app.vat_check_label.cget("text"))
        self.open("reports_tab")
        self.app.build_cash_budget(); self.app.budget_from_year(); self.app.update()
        self.assertTrue(any(kind == "showwarning" and "No " in str(args) for kind, args in self.messages), self.messages)


if __name__ == "__main__":
    unittest.main()
