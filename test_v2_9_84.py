"""2.9.84: the findings of the audit engagement on 2.9.83, fixed:
1. a DOE of the USD books no longer blocks the year close; 2. Close & Open carries employees, assets, rates;
3. a saved VAT quarter refuses document changes; 4. assets bought before Saber; 5. provisions in operating cash flows;
6. audit trail; 7. negative cash warning; 8. USD salary tax in exact LBP; 9. statement of account with receipts;
10. financial statements in any company currency; Year-End Check of the DOE in the main currency."""
import tests_setup  # noqa: F401  the sample company of the window tests
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock
from decimal import Decimal
from pathlib import Path

import accounting_setup
import financial_statements
import fixed_assets
import ledger_reports
import vat_return
import server
from company_manager import CompanyManager
from database import Database

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class DoeOpeningTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name); master = Database(root / "master.db"); master.initialize("secret")
        self.manager = CompanyManager(root / "master.db")
        company = self.manager.create_company({"name": "Doe Test SARL", "year": 2025}, master); self.company = company["id"]
        self.db = self.manager.database(self.company, 2025)
        for frm, to, rate, d1, d2 in (("USD", "LBP", "89500", "01-01-2025", "31-12-2025"), ("EUR", "USD", "1.05", "01-01-2025", "30-11-2025"), ("EUR", "USD", "1.15", "01-12-2025", "31-12-2025")):
            self.db.save_exchange_rate({"date_from": d1, "date_to": d2, "from_currency": frm, "to_currency": to, "rate": rate}, 1)
        self.db.save_party({"kind": "customer", "name": "Euro Client", "currency": "EUR"}, 1)
        self.db.create_manual_invoice({"invoice_date": "10-09-2025", "party_name": "Euro Client", "kind": "sales", "currency": "EUR", "status": "posted"},
                                      [{"description": "Design", "quantity": 1, "unit_price": 20000, "vat_rate": 0}], 1)
        self.account = next(p for p in self.db.list_parties() if p["name"] == "Euro Client")["account_number"]
        item = next(i for i in self.db.doe_candidates("31-12-2025", "USD")["items"] if i["account"] == self.account)
        difference = (Decimal(item["balance"]) * Decimal(item["suggested_rate"]) - Decimal(item["carrying_usd"])).quantize(Decimal("0.01"))
        self.assertEqual(difference, Decimal("2000.00"))
        self.db.save_journal_voucher({"entry_date": "31-12-2025", "description": "DOE USD books", "currency": "USD", "voucher_type": "07", "doe_basis": "USD"},
                                     [{"account_code": self.account, "debit": "2000", "native_currency": "EUR"}, {"account_code": "775100000", "credit": "2000"}], 1)

    def balance(self, db, code, column):
        return sum((r["signed"][column] for r in ledger_reports._load_lines(db, {"posting_status": "posted", "first_column": "USD", "second_column": "LBP"}) if str(r["code"]) == code), Decimal("0"))

    def test_close_and_next_year_opening(self):
        self.manager.close_and_open_year(self.company, 2025, 1)
        nxt = self.manager.database(self.company, 2026)
        self.assertFalse(nxt.unbalanced_entries())
        self.assertEqual(self.balance(nxt, self.account, "USD"), Decimal("23000"))  # revalued
        self.assertEqual(sum((r["signed"]["account"] for r in ledger_reports._load_lines(nxt, {"posting_status": "posted"}) if str(r["code"]) == self.account), Decimal("0")), Decimal("20000"))
        rows = ledger_reports._load_lines(nxt, {"posting_status": "posted", "first_column": "USD", "second_column": "LBP"})
        self.assertLess(abs(sum((r["signed"]["USD"] for r in rows), Decimal("0"))), Decimal("0.05"))
        self.assertEqual(self.balance(nxt, "138", "USD"), Decimal("-23000"))  # profit 21,000 + exchange gain 2,000
        doe_again = [i for i in nxt.doe_candidates("31-12-2026", "USD")["items"] if i["account"] == self.account]
        self.assertEqual(Decimal(doe_again[0]["carrying_usd"]), Decimal("23000"))  # the next DOE starts from the revalued amount


    def test_year_end_check_doe_in_the_main_currency(self):
        checks = {r["check"]: r for r in accounting_setup.year_end_check(self.db, 2025)["results"]}
        self.assertEqual(checks["Exchange differences (DOE) in USD at 31-12"]["status"], "OK")  # the DOE above is posted
        self.db.create_manual_invoice({"invoice_date": "10-10-2025", "party_name": "Euro Client", "kind": "sales", "currency": "EUR", "status": "posted"},
                                      [{"description": "More", "quantity": 1, "unit_price": 1000, "vat_rate": 0}], 1)
        checks = {r["check"]: r for r in accounting_setup.year_end_check(self.db, 2025)["results"]}
        self.assertEqual(checks["Exchange differences (DOE) in USD at 31-12"]["status"], "WARNING")  # 1,000 EUR at 1.05 vs 1.15

    def test_close_and_open_carries_employees_assets_and_rates(self):
        self.db.apply_lebanese_payroll_rules(1)
        rami = self.db.save_employee({"employee_number": "1000", "full_name": "Rami", "currency": "LBP", "base_salary": "89500000", "hire_date": "01-01-2020",
                                      "eos_paid_before": "100000000", "leave_carried": "2"}, 1)
        posted = self.db.post_payroll(self.db.save_payroll({"employee_id": rami["id"], "period_date": "31-01-2025"}, 1)["id"], 1)
        fixed_assets.save_category(self.db, {"account_code": "2244", "name": "Vehicles", "annual_rate": "20", "depreciation_account": "681", "accumulated_account": "2824"}, 1)
        asset = fixed_assets.save_asset(self.db, {"asset_code": "FA-1", "name": "Truck", "acquired_on": "01-12-2025", "start_on": "01-12-2025", "currency": "USD", "cost": "6000",
                                                  "useful_months": "60", "asset_account": "2244", "depreciation_account": "681", "accumulated_account": "2824"}, user_id=1)
        fixed_assets.post_period(self.db, asset["id"], "31-12-2025", 1, 2025)
        self.manager.close_and_open_year(self.company, 2025, 1)
        nxt = self.manager.database(self.company, 2026)
        employee = next(e for e in nxt.list_employees() if e["full_name"] == "Rami")
        self.assertEqual(Decimal(str(employee["eos_paid_before"])), Decimal("100000000") + Decimal(str(posted["employer_end_service"])))
        self.assertEqual(Decimal(str(employee["leave_carried"])), Decimal("17"))  # 2 carried + 15 earned in 2025, none taken
        self.assertEqual([a["asset_code"] for a in fixed_assets.list_assets(nxt)], ["FA-1"])
        self.assertTrue(next(r for r in fixed_assets.schedule(nxt, fixed_assets.list_assets(nxt)[0]["id"]) if r["period_end"] == "2025-12-31")["posted"])
        self.assertEqual([c["account_code"] for c in fixed_assets.list_categories(nxt)], ["2244"])
        self.assertEqual(nxt._converted_amount(Decimal("1"), "EUR", "USD", "2025-12-31"), Decimal("1.15"))


class _Book(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "books.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        self.db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "EUR", "to_currency": "USD", "rate": "1.10"}, 1)

    def voucher(self, day, lines, currency="USD", kind="01"):
        return self.db.save_journal_voucher({"entry_date": day, "description": "Test", "currency": currency, "voucher_type": kind},
                                            [{"account_code": c, "debit": str(d)} if d else {"account_code": c, "credit": str(k)} for c, d, k in lines], 1)


class VatLockTest(_Book):
    def test_saved_quarter_refuses_document_changes(self):
        invoice = self.db.create_manual_invoice({"invoice_date": "10-02-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                                [{"description": "S", "quantity": 1, "unit_price": 1000, "vat_rate": 11}], 1)
        vat_return.save_return(self.db, 2025, 1, 1)
        with self.assertRaisesRegex(ValueError, "Q1 2025 VAT return is saved"):
            self.db.add_expense({"expense_date": "15-03-2025", "description": "Rent", "currency": "USD", "with_vat_subtotal": "100", "vat": "11",
                                 "expense_account": "6263.1", "payment_account": "531"}, 1)
        with self.assertRaisesRegex(ValueError, "VAT return is saved"): self.db.cancel_invoice(invoice, "late", 1)
        with self.assertRaisesRegex(ValueError, "VAT return is saved"): self.db.delete_invoice(invoice, 1)
        self.db.add_expense({"expense_date": "15-04-2025", "description": "Rent", "currency": "USD", "with_vat_subtotal": "100", "vat": "11",
                             "expense_account": "6263.1", "payment_account": "531"}, 1)  # Q2 is open
        vat_return.reopen_return(self.db, 2025, 1, 1)
        self.db.delete_invoice(invoice, 1)


class AssetBeforeSaberTest(_Book):
    def test_depreciation_booked_before_saber(self):
        fixed_assets.save_category(self.db, {"account_code": "2244", "name": "Vehicles", "annual_rate": "20", "depreciation_account": "681", "accumulated_account": "2824"}, 1)
        with self.assertRaisesRegex(ValueError, "before the depreciation start"):
            fixed_assets.save_asset(self.db, {"asset_code": "OLD", "name": "Old truck", "acquired_on": "01-01-2022", "start_on": "01-01-2022", "currency": "USD", "cost": "6000",
                                              "useful_months": "60", "asset_account": "2244", "depreciation_account": "681", "accumulated_account": "2824", "opening_date": "31-12-2021"}, user_id=1)
        asset = fixed_assets.save_asset(self.db, {"asset_code": "OLD", "name": "Old truck", "acquired_on": "01-01-2022", "start_on": "01-01-2022", "currency": "USD", "cost": "6000",
                                                  "useful_months": "60", "asset_account": "2244", "depreciation_account": "681", "accumulated_account": "2824",
                                                          "opening_date": "31-12-2024"}, user_id=1)
        row = fixed_assets.monthly_table(self.db, "31-01-2025")["groups"][0]["assets"][0]
        self.assertEqual((row["old"], row["current"], row["net"]), (Decimal("3600.00"), Decimal("100.00"), Decimal("2300.00")))
        result = fixed_assets.post_category_month(self.db, "2244", "31-01-2025", 1)  # no "post the earlier months first"
        self.assertEqual(result["amount"], 100)
        roll = fixed_assets.rollforward(self.db, 2025)["items"][0]
        self.assertEqual((roll["opening_accumulated"], roll["depreciation_posted"]), ("3600.00", "100.00"))
        with self.assertRaisesRegex(ValueError, "posted depreciation"):  # January 2025 is posted in Saber
            fixed_assets.save_asset(self.db, {**{k: asset[k] for k in ("asset_code", "name", "currency", "cost", "useful_months", "asset_account", "depreciation_account", "accumulated_account")},
                                              "acquired_on": "01-01-2022", "start_on": "01-01-2022", "opening_date": "30-06-2024"}, asset["id"], 1)


class CashFlowTest(_Book):
    def test_provisions_are_operating_not_financing(self):
        self.voucher("01-01-2025", [("512", 10000, 0), ("101", 0, 10000)], kind="04")
        self.voucher("01-02-2025", [("2244", 5000, 0), ("512", 0, 5000)])
        self.voucher("31-12-2025", [("681", 200, 0), ("2824", 0, 200)])
        self.voucher("31-12-2025", [("6355", 1000, 0), ("1552", 0, 1000)])
        cash = financial_statements.period_data(self.db, "2025-01-01", "2025-12-31", "USD", "2025")["cash"]
        self.assertEqual((cash["profit"], cash["depreciation_only"], cash["provisions"]), (Decimal("-1200"), Decimal("200"), Decimal("1000")))
        self.assertEqual((cash["operating"], cash["investing"], cash["financing"]), (Decimal("0"), Decimal("-5000"), Decimal("0")))

    def test_statements_in_euro(self):
        self.voucher("01-01-2025", [("512", 11000, 0), ("101", 0, 11000)], kind="04")
        self.db.create_manual_invoice({"invoice_date": "10-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                      [{"description": "S", "quantity": 1, "unit_price": 1100, "vat_rate": 0}], 1)
        data = financial_statements.period_data(self.db, "2025-01-01", "2025-12-31", "EUR", "2025")
        self.assertEqual(data["profit"].quantize(Decimal("0.01")), Decimal("1000.00"))  # 1,100 USD at 1.10
        result = financial_statements.build({2025: self.db}, {"years": "2025", "basis": "EUR"})
        self.assertFalse([row for s in result["sections"] for row in s["rows"] if row and "does not balance" in str(row[0])])
        with self.assertRaisesRegex(ValueError, "not a currency"): financial_statements.build({2025: self.db}, {"years": "2025", "basis": "XYZ"})


class PayrollTaxTest(_Book):
    def test_usd_salary_tax_is_booked_in_exact_lbp(self):
        self.db.apply_lebanese_payroll_rules(1)
        maya = self.db.save_employee({"employee_number": "1001", "full_name": "Maya", "currency": "USD", "base_salary": "4321", "hire_date": "01-07-2024"}, 1)
        record = self.db.post_payroll(self.db.save_payroll({"employee_id": maya["id"], "period_date": "31-01-2025"}, 1)["id"], 1)
        self.assertGreater(Decimal(str(record["income_tax"])), 0)
        rows = [r for r in ledger_reports._load_lines(self.db, {"posting_status": "posted", "first_column": "USD", "second_column": "LBP"}) if r["entry_number"] == f"PAYJV-{record['payroll_number']}"]
        tax = next(r for r in rows if r["signed"]["entry"] == -Decimal(str(record["income_tax"])) and r["line_currency"] == "USD")
        self.assertEqual(tax["signed"]["LBP"], -Decimal(str(record["income_tax_lbp"])))
        self.assertLess(abs(sum((r["signed"]["LBP"] for r in rows), Decimal("0"))), Decimal("1"))  # still balanced in LBP
        self.assertEqual(sum((r["signed"]["USD"] for r in rows), Decimal("0")), Decimal("0"))


class StatementAuditCashTest(_Book):
    def test_statement_of_account_with_receipts(self):
        sale = self.db.create_manual_invoice({"invoice_date": "10-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                             [{"description": "S", "quantity": 1, "unit_price": 1000, "vat_rate": 0}], 1)
        party = next(p for p in self.db.list_parties() if p["name"] == "Client")
        cancelled = self.db.create_manual_invoice({"invoice_date": "11-03-2025", "party_name": "Client", "kind": "sales", "currency": "USD", "status": "posted"},
                                                  [{"description": "X", "quantity": 1, "unit_price": 500, "vat_rate": 0}], 1)
        self.db.cancel_invoice(cancelled, "wrong", 1)
        self.db.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "20-03-2025", "currency": "USD", "amount": "400", "cash_account": "531"}, 1)
        statement = self.db.statement_of_account(party["id"])
        self.assertEqual([(r["description"].split()[0], r["debit"], r["credit"]) for r in statement["items"]], [("Sale", 1000.0, 0.0), ("Receipt", 0.0, 400.0)])
        self.assertEqual(statement["items"][-1]["balance"], 600.0)
        self.assertTrue(sale)

    def test_audit_trail_and_cash_check(self):
        self.assertTrue(self.db.cash_check("531", "USD", "31-12-2025", 100)["negative"])
        self.voucher("01-01-2025", [("531", 1000, 0), ("101", 0, 1000)], kind="04")
        check = self.db.cash_check("531", "USD", "31-12-2025", 100)
        self.assertEqual((check["balance"], check["after"], check["negative"]), (1000.0, 900.0, False))
        self.assertFalse(self.db.cash_check("401", "USD", "31-12-2025", 100)["checked"])  # not a cash / bank account
        trail = self.db.audit_trail(entity="journal_voucher")
        self.assertTrue(trail["items"]); self.assertIn("journal_voucher", trail["entities"])
        self.assertFalse(self.db.audit_trail(date_from="01-01-2099")["items"])


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

    def test_audit_trail_tab_and_cash_warning(self):
        rows = self.app.load_audit_trail()
        self.assertTrue(self.app.audit_tree.winfo_exists()); self.assertIsInstance(rows, list)
        self.messages.clear(); self.assertTrue(self.app.confirm_cash_enough("401", "USD", "31-12-2025", 10)); self.assertFalse(self.messages)  # not a cash account: no question
        self.messages.clear()
        self.assertTrue(self.app.confirm_cash_enough("531", "USD", "01-01-2000", 10 ** 9))  # mocked "Yes"
        self.assertEqual([n for n, _a in self.messages], ["askyesno"])


if __name__ == "__main__":
    unittest.main()
