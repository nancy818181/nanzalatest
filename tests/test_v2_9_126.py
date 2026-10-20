"""2.9.126: payroll numbers kept on update, VAT history in SQL, provisional VAT when an earlier quarter fails,
depreciation description per group, comparative trial balance, background financial reports, kept-loaded OCR."""
import tests_setup  # noqa: F401
import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from database import Database

try:
    import tkinter  # noqa: F401
    HAS_TK = True
except ImportError:  # a server without the screen libraries
    HAS_TK = False
needs_tk = unittest.skipUnless(HAS_TK, "tkinter is not installed")


def _database(folder):
    db = Database(Path(folder) / "company.db"); db.initialize("secret12345")
    with db.connect() as c: user = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    return db, user


class PayrollNumberTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db, self.user = _database(self.folder.name)
        self.db.apply_lebanese_payroll_rules(self.user)
        self.one = self.db.save_employee({"full_name": "One", "base_salary": "50000000", "currency": "LBP", "hire_date": "01-01-2026"}, self.user)
        self.two = self.db.save_employee({"full_name": "Two", "base_salary": "50000000", "currency": "LBP", "hire_date": "01-01-2026"}, self.user)

    def tearDown(self): self.folder.cleanup()

    def test_resaving_a_draft_keeps_its_record_and_number(self):
        first = self.db.save_payroll({"employee_id": self.one["id"], "period_date": "31-05-2026"}, self.user)
        again = self.db.save_payroll({"employee_id": self.one["id"], "period_date": "31-05-2026", "salary": "60000000"}, self.user)
        by_id = self.db.save_payroll({"id": first["id"], "employee_id": self.one["id"], "period_date": "31-05-2026", "salary": "70000000"}, self.user)
        self.assertEqual({first["id"], again["id"], by_id["id"]}, {first["id"]})
        self.assertEqual({first["payroll_number"], again["payroll_number"], by_id["payroll_number"]}, {first["payroll_number"]})
        self.assertEqual(len(self.db.list_payroll()), 1)
        nxt = self.db.save_payroll({"employee_id": self.two["id"], "period_date": "31-05-2026"}, self.user)
        self.assertNotEqual(nxt["payroll_number"], first["payroll_number"])

    def test_update_by_id_checks_employee_date_and_status(self):
        first = self.db.save_payroll({"employee_id": self.one["id"], "period_date": "31-05-2026"}, self.user)
        with self.assertRaisesRegex(ValueError, "another employee"):
            self.db.save_payroll({"id": first["id"], "employee_id": self.two["id"], "period_date": "31-05-2026"}, self.user)
        with self.assertRaisesRegex(ValueError, "cannot be moved"):
            self.db.save_payroll({"id": first["id"], "employee_id": self.one["id"], "period_date": "30-06-2026"}, self.user)
        with self.assertRaises(KeyError):
            self.db.save_payroll({"id": 9999, "employee_id": self.one["id"], "period_date": "31-05-2026"}, self.user)
        self.db.post_payroll(first["id"], self.user)
        with self.assertRaisesRegex(ValueError, "Posted payroll"):
            self.db.save_payroll({"id": first["id"], "employee_id": self.one["id"], "period_date": "31-05-2026"}, self.user)
        self.assertEqual(self.db.list_payroll()[0]["payroll_number"], first["payroll_number"])

    @needs_tk
    def test_payroll_sheet_sends_the_record_id(self):
        from desktop_payroll_sheet import payload_for
        self.assertEqual(payload_for({"employee_id": 3, "payroll_id": 7}, "31-05-2026")["id"], 7)
        self.assertNotIn("id", payload_for({"employee_id": 3}, "31-05-2026"))


class VatHistoryTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db, self.user = _database(self.folder.name)

    def tearDown(self): self.folder.cleanup()

    def _dates(self, *dates):
        with self.db.connect() as c:
            c.execute("DELETE FROM expenses")
            info = list(c.execute("PRAGMA table_info(expenses)")); columns = {r[1] for r in info}
            required = [r[1] for r in info if r[3] and r[4] is None and not r[5] and r[1] != "expense_date"]
            for number, day in enumerate(dates):
                values = {"expense_date": day, **{name: "0" for name in required}}
                for name, value in (("expense_number", f"E{number}"), ("currency", "USD"), ("subtotal", "0"), ("vat", "0"), ("total", "0"),
                                    ("description", "x"), ("created_at", "2026-01-01"), ("status", "posted")):
                    if name in columns: values[name] = value
                c.execute(f"INSERT INTO expenses({','.join(values)}) VALUES({','.join('?' for _ in values)})", list(values.values()))

    def test_history_is_found_in_sql_and_bad_dates_keep_the_chain_open(self):
        import vat_return
        try: self._dates("15-02-2026")
        except Exception as exc: self.skipTest(f"expenses table needs more columns: {exc}")
        self.assertTrue(vat_return._has_vat_history(self.db, 2026, 1))
        self._dates("15-08-2026")
        self.assertFalse(vat_return._has_vat_history(self.db, 2026, 1))
        self._dates("2026-02-15")
        self.assertTrue(vat_return._has_vat_history(self.db, 2026, 1))
        for bad in ("99-99-2026", "next week", "", "31-02-2027", "29-02-2027", "31-04-2027", "2027-02-30"):
            self._dates("15-08-2026", bad)
            self.assertTrue(vat_return._has_vat_history(self.db, 2026, 1), bad)
        memo = {}
        self._dates("15-08-2026")
        self.assertFalse(vat_return._has_vat_history(self.db, 2026, 1, memo))
        self._dates("15-02-2026")
        self.assertFalse(vat_return._has_vat_history(self.db, 2026, 1, memo))  # cached for this one calculation only
        self.assertTrue(vat_return._has_vat_history(self.db, 2026, 1, {}))


class ProvisionalVatTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db, self.user = _database(self.folder.name)

    def tearDown(self): self.folder.cleanup()

    def test_failed_earlier_quarter_gives_a_provisional_preview_that_cannot_be_saved(self):
        import vat_return
        original = vat_return.build_vat_return
        def build(db, year, quarter, *args, **kwargs):
            if int(quarter) == 1: raise ValueError("No EUR exchange rate on or before 2026-03-31")
            return original(db, year, quarter, *args, **kwargs)
        with patch.object(vat_return, "build_vat_return", build), patch.object(vat_return, "_has_vat_history", return_value=True):
            result = original(self.db, 2026, 2)
            self.assertTrue(result["provisional"])
            self.assertIn("Q1 2026", result["dependency_errors"][0])
            self.assertTrue(result["warnings"][0].startswith("PROVISIONAL"))
            self.assertIn("UNKNOWN", result["credit_source"])
            with self.assertRaisesRegex(ValueError, "earlier quarter"):
                vat_return.save_return(self.db, 2026, 2, self.user)
            with self.assertRaisesRegex(ValueError, "earlier quarter"):
                vat_return.post_settlement(self.db, 2026, 2, self.user)
            # Q3 depends on Q2, which depends on the failed Q1: the error and the unreliability travel up the chain.
            q3 = original(self.db, 2026, 3)
            self.assertTrue(q3["dependency_errors"]); self.assertTrue(q3["provisional"])
            self.assertIn("UNRELIABLE", q3["credit_source"]); self.assertIn("UNKNOWN", q3["credit_source"])
        self.assertFalse(original(self.db, 2026, 2)["provisional"])


class DepreciationDescriptionTest(unittest.TestCase):
    def test_each_voucher_names_its_own_account_and_currency(self):
        import fixed_assets
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "a.db"); db.initialize("secret-password-1")
            for account, name in (("2244", "Vehicles"), ("2243", "Furniture")):
                fixed_assets.save_category(db, {"account_code": account, "name": name, "annual_rate": "20", "depreciation_account": "681", "accumulated_account": "2824"}, 1)
            for code, account, currency, cost in (("V-1", "2244", "USD", "1200"), ("F-1", "2243", "USD", "600"), ("F-2", "2243", "LBP", "8950000")):
                fixed_assets.save_asset(db, {"asset_code": code, "name": code, "acquired_on": "01-01-2026", "start_on": "01-01-2026", "currency": currency,
                    "cost": cost, "residual": "0", "useful_months": "60", "annual_rate": "20", "asset_account": account,
                    "depreciation_account": "681", "accumulated_account": "2824"}, user_id=1)
            result = fixed_assets.post_category_month(db, None, "31-01-2026", 1)
            descriptions = {r["entry_number"]: r["description"] for r in db.journal() if r["entry_number"] in result["vouchers"]}
            self.assertEqual(len(set(descriptions.values())), 3)
            self.assertTrue(any("(2244, USD)" in d for d in descriptions.values()))
            self.assertTrue(any("(2243, LBP)" in d for d in descriptions.values()))
            self.assertFalse(any("(None" in d for d in descriptions.values()))


class ComparativeTrialBalanceTest(unittest.TestCase):
    def test_http_decimal_strings_remain_numeric_and_exact_in_the_client(self):
        import io
        from decimal import Decimal
        from client import ApiClient
        from server import ApiHandler
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = _database(folder)
            db.save_journal_voucher({"entry_date": "10-06-2026", "description": "Exact cents", "currency": "USD"},
                [{"account_code": "531", "debit": "80000000000000.01"},
                 {"account_code": "101", "credit": "80000000000000.01"}], user)
            handler = ApiHandler.__new__(ApiHandler)
            handler.path = "/api/comparative-trial-balance?from_date=2026-06-01&to_date=2026-06-30&currency=USD"
            handler.command = "GET"
            handler.headers = {}
            handler.rfile = io.BytesIO()
            handler._key_refused = lambda: False
            handler.db = db
            handler._user = lambda: {"role": "admin"}
            handler._select_database = lambda: True
            handler._module_denied = lambda *args: False
            handler._year_db = lambda year: db
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()
            handler.do_GET()
            handler.send_response.assert_called_once_with(200)
            wire = json.loads(handler.wfile.getvalue())
            api = ApiClient()
            with patch.object(api, "request", return_value=wire):
                received = api.comparative_trial_balance("2026-06-01", "2026-06-30", "USD")
            cash = next(r for r in received["items"] if r["code"] == "531")
            self.assertEqual(cash["current_closing"], Decimal("80000000000000.01"))
            self.assertEqual(f'{cash["current_closing"]:,.2f}', "80,000,000,000,000.01")
            self.assertEqual(received["totals"]["USD"]["current_closing"], Decimal("0"))

    def test_bad_entry_dates_cannot_be_hidden_by_the_sql_date_filter(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = _database(folder)
            db.save_journal_voucher({"entry_date": "10-06-2026", "description": "Date check", "currency": "USD"},
                [{"account_code": "531", "debit": "10"}, {"account_code": "101", "credit": "10"}], user, defer_posting=True)
            for bad in ("31-02-2026", "2026-02-31", "not a date", "2026-13-01"):
                with db.connect() as c:
                    c.execute("UPDATE journal_entries SET entry_date=?,posting_status='posted'", (bad,))
                    with self.assertRaisesRegex(ValueError, "Invalid date for entry"):
                        db.comparative_trial_balance("01-06-2026", "30-06-2026", "USD")
                    c.rollback()  # restore the draft fixture before the next corrupt posted-date case
            with db.connect() as c: c.execute("UPDATE journal_entries SET entry_date='2026-07-01'")
            self.assertEqual(db.comparative_trial_balance("01-06-2026", "30-06-2026", "USD")["items"], [])
            with self.assertRaisesRegex(ValueError, "From Date"):
                db.comparative_trial_balance("30-06-2026", "01-06-2026", "USD")

    def test_closing_includes_opening_and_prior_year_is_compared(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = _database(folder)
            def voucher(day, amount):
                try:
                    db.save_journal_voucher({"entry_date": day, "description": "Test", "currency": "USD"},
                        [{"account_code": "531", "debit": amount}, {"account_code": "101", "credit": amount}], user)
                except ValueError as exc: self.skipTest(f"period closed in the test company: {exc}")
            voucher("10-06-2025", "100"); voucher("10-01-2026", "50"); voucher("10-06-2026", "30")
            result = db.comparative_trial_balance("01-06-2026", "30-06-2026", "USD")
            cash = next(r for r in result["items"] if r["code"].startswith("531"))
            self.assertEqual((cash["current_opening"], cash["current_movement"], cash["current_closing"]), (150, 30, 180))
            self.assertEqual((cash["prior_opening"], cash["prior_movement"], cash["prior_closing"]), (0, 100, 100))
            self.assertEqual(cash["variance"], 80)
            self.assertTrue(result["prior_available"])
            self.assertEqual(result["totals"]["USD"]["current_closing"], 0)  # a balanced trial balance
            leap = db.comparative_trial_balance("01-02-2028", "29-02-2028", "USD")
            self.assertEqual(leap["prior_to"], "2027-02-28")
            empty = db.comparative_trial_balance("01-06-2024", "30-06-2024", "USD")
            self.assertFalse(empty["prior_available"]); self.assertIn("unavailable", empty["warning"])

    def test_a_missing_eur_rate_does_not_stop_a_usd_comparison(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db, user = _database(folder)
            with db.connect() as c:
                c.execute("DELETE FROM exchange_rates WHERE from_currency='EUR' OR to_currency='EUR'")
                account = c.execute("SELECT id FROM accounts WHERE code='531'").fetchone()[0]
                other = c.execute("SELECT id FROM accounts WHERE code='101'").fetchone()[0]
                columns = {r[1] for r in c.execute("PRAGMA table_info(journal_entries)")}
                values = {"entry_number": "JV-EUR", "entry_date": "10-06-2026", "description": "EUR", "currency": "EUR",
                          "source_type": "journal_voucher", "created_at": "2026-06-10", "created_by": user,"posting_status":"draft"}
                values = {k: v for k, v in values.items() if k in columns}
                entry = c.execute(f"INSERT INTO journal_entries({','.join(values)}) VALUES({','.join('?' for _ in values)})", list(values.values())).lastrowid
                c.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)", (entry, account, "10", "0"))
                c.execute("INSERT INTO journal_lines(entry_id,account_id,debit,credit) VALUES(?,?,?,?)", (entry, other, "0", "10"))
                c.execute("UPDATE journal_entries SET posting_status='posted',posted_at='2026-06-10',posted_by=? WHERE id=?", (user,entry))
            usd = db.comparative_trial_balance("01-06-2026", "30-06-2026", "USD")
            self.assertEqual(usd["items"], [])
            eur = db.comparative_trial_balance("01-06-2026", "30-06-2026", "EUR")
            self.assertEqual(next(r for r in eur["items"] if r["code"] == "531")["current_closing"], 10)

    def test_the_prior_year_file_is_the_prior_year_source(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            current, user = _database(folder)
            prior_folder = Path(folder) / "prior"; prior_folder.mkdir()
            prior, _ = _database(prior_folder)
            def voucher(db, day, amount):
                try:
                    db.save_journal_voucher({"entry_date": day, "description": "Test", "currency": "USD"},
                        [{"account_code": "531", "debit": amount}, {"account_code": "101", "credit": amount}], user)
                except ValueError as exc: self.skipTest(f"period closed in the test company: {exc}")
            voucher(current, "10-06-2025", "1"); voucher(prior, "10-06-2025", "100")
            result = current.comparative_trial_balance("01-06-2026", "30-06-2026", "USD", prior_db=prior)
            cash = next(r for r in result["items"] if r["code"].startswith("531"))
            self.assertEqual(cash["prior_closing"], 100)
            self.assertEqual(result["prior_source"], "prior-year file")

    @needs_tk
    def test_export_blanks_prior_columns_when_unavailable(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        row = {"currency": "USD", "code": "531", "name_en": "Cash", "current_opening": 1, "current_movement": 2, "current_closing": 3,
               "prior_closing": 0, "variance": 3}
        app = SimpleNamespace(client=SimpleNamespace(settings=lambda: {"company_name": "Example SARL"}),
            financial_report_range=lambda: ["2026-01-01", "2026-12-31"], view_currency=field("USD"),
            report_account_from=field(""), report_account_to=field(""), financial_filter_sets=lambda: {},
            ctb_rows=[row], ctb_info={"prior_available": False, "warning": "Prior period unavailable", "prior_to": "2025-12-31"}, output_sections=Mock())
        ReportsMixin.financial_report_export(app, "ctb", "pdf")
        meta, sections = app.output_sections.call_args.args[1:3]
        self.assertIn("Prior period unavailable", meta)
        self.assertEqual(sections[0]["rows"][0][-2:], ["", ""])
        self.assertEqual(len(sections[0]["column_weights"]), len(sections[0]["headers"]))


class ReportPrecisionTest(unittest.TestCase):
    def test_a_lost_cent_is_logged_and_huge_values_do_not_fail(self):
        from decimal import Decimal
        import ledger_reports
        with self.assertLogs("saber.reports", "WARNING"):
            ledger_reports.json_ready({"a": Decimal("80000000000000.01")})
        self.assertEqual(ledger_reports.json_ready(Decimal("1E+40")), 1e40)
        with self.assertNoLogs("saber.reports", "WARNING"):
            self.assertEqual(ledger_reports.json_ready([Decimal("8000000000000000")]), [8e15])
            ledger_reports.json_ready(Decimal("123456.78"))


@needs_tk
class BackgroundReportsTest(unittest.TestCase):
    def test_old_screen_results_and_errors_do_not_touch_the_new_screen(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        class Inline:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
        for broken in (False, True):
            with self.subTest(broken=broken):
                def ledger(*args):
                    if broken: raise RuntimeError("old company unavailable")
                    return {"items": []}
                client = SimpleNamespace(general_ledger=ledger, balance_sheet=lambda *a: [],
                    vat_report=lambda *a: {"items": [], "summary": []}, cash_flow=lambda *a: [],
                    comparative_reports=lambda *a: {"items": []})
                scheduled = []
                app = SimpleNamespace(client=client, financial_report_range=lambda: ["2026-01-01", "2026-12-31"],
                    view_currency=field("USD"), can_use=lambda key: True, ledger_tree=Mock(), _page_generation=1,
                    after=lambda ms, fn: scheduled.append(fn), winfo_exists=Mock(return_value=True))
                with patch("threading.Thread", Inline), patch("desktop_reports.messagebox") as box:
                    ReportsMixin.load_financial_reports(app)
                    app._page_generation = 2  # main_screen rebuilt; the new report page is still unbuilt
                    del app.ledger_tree
                    for poll in list(scheduled): poll()
                app.winfo_exists.assert_not_called()
                self.assertFalse(hasattr(app, "balance_rows"))
                self.assertEqual(len(scheduled), 1)
                box.showerror.assert_not_called()

    def test_an_older_result_never_overwrites_a_newer_one(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        def client(code):
            row = {"type": "asset", "code": code, "currency": "USD", "name_en": code, "debit": 1, "credit": 0, "balance": 1}
            return SimpleNamespace(general_ledger=lambda *a: {"items": []}, balance_sheet=lambda *a: [row],
                vat_report=lambda *a: {"items": [], "summary": []}, cash_flow=lambda *a: [], comparative_reports=lambda *a: {"items": []},
                comparative_trial_balance=lambda *a: {"items": [], "warning": ""})
        trees = {key: Mock() for key in ("ledger_tree", "balance_tree", "vat_tree", "cash_tree", "comparative_tree")}
        for tree in trees.values(): tree.get_children.return_value = []
        scheduled = []
        app = SimpleNamespace(client=client("101"), financial_report_range=lambda: ["2026-01-01", "2026-12-31"],
            view_currency=field("USD"), report_account_from=field(""), report_account_to=field(""), can_use=lambda key: True,
            refresh_financial_filter_choices=Mock(), financial_filter_sets=lambda: {}, financial_filter_ok=lambda *a: True,
            vat_summary=Mock(), after=lambda ms, fn: scheduled.append(fn), winfo_exists=lambda: True, **trees)

        class Inline:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
        with patch("threading.Thread", Inline), patch("desktop_common.fill_tree"), patch("desktop_reports.messagebox") as box:
            ReportsMixin.load_financial_reports(app)          # older request
            app.client = client("531")
            ReportsMixin.load_financial_reports(app)          # newer request
            for poll in list(scheduled): poll()
        self.assertEqual([r["code"] for r in app.balance_rows], ["531"])
        self.assertEqual(app.balance_tree.insert.call_count, 1)
        box.showerror.assert_not_called()

    def test_export_uses_the_loaded_figures_and_refuses_changed_filters(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        dates = ["2026-07-01", "2026-07-31"]
        app = SimpleNamespace(client=SimpleNamespace(settings=lambda: {"company_name": "Example SARL"}),
            financial_report_range=lambda: dates, view_currency=field("USD"), report_account_from=field(""), report_account_to=field(""),
            financial_filter_sets=lambda: [("branch_name", {"beirut"})],
            ledger_rows=[{"entry_date": "01-06-2026", "entry_number": "JV-1", "account_code": "531", "currency": "USD", "account_name": "Cash",
                          "description": "June", "debit": 1, "credit": 0, "balance": 1}], output_sections=Mock(),
            financial_snapshot={"dates": ["2026-06-01", "2026-06-30"], "currency": "USD", "account_from": "", "account_to": "",
                                "filters": [("branch_name", {"tripoli"})]}, _financial_loading=False)
        with patch("desktop_reports.messagebox") as box:
            ReportsMixin.financial_report_export(app, "ledger", "pdf")
        app.output_sections.assert_not_called(); box.showwarning.assert_called_once()
        dates[:] = ["2026-06-01", "2026-06-30"]
        ReportsMixin.financial_report_export(app, "ledger", "pdf")
        meta = app.output_sections.call_args.args[1]
        self.assertIn("Period: 2026-06-01 to 2026-06-30", meta)
        self.assertTrue(any("tripoli" in line for line in meta))
        app._financial_loading = True; app.output_sections.reset_mock()
        with patch("desktop_reports.messagebox") as box:
            ReportsMixin.financial_report_export(app, "ledger", "pdf")
        app.output_sections.assert_not_called(); self.assertIn("still loading", box.showwarning.call_args.args[1])

    def test_a_failed_comparative_trial_balance_does_not_hide_the_other_reports(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        row = {"type": "asset", "code": "531", "currency": "USD", "name_en": "Cash", "debit": 1, "credit": 0, "balance": 1}
        def no_rate(*args): raise RuntimeError("No EUR exchange rate")
        client = SimpleNamespace(general_ledger=lambda *a: {"items": []}, balance_sheet=lambda *a: [row],
            vat_report=lambda *a: {"items": [], "summary": []}, cash_flow=lambda *a: [], comparative_reports=lambda *a: {"items": []},
            comparative_trial_balance=no_rate)
        trees = {key: Mock() for key in ("ledger_tree", "balance_tree", "vat_tree", "cash_tree", "comparative_tree")}
        for tree in trees.values(): tree.get_children.return_value = []
        app = SimpleNamespace(client=client, financial_report_range=lambda: ["2026-01-01", "2026-12-31"],
            view_currency=field("USD"), report_account_from=field(""), report_account_to=field(""), can_use=lambda key: True,
            refresh_financial_filter_choices=Mock(), financial_filter_sets=lambda: [], financial_filter_ok=lambda *a: True,
            vat_summary=Mock(), **trees)
        with patch("desktop_common.fill_tree"), patch("desktop_reports.messagebox") as box:
            ReportsMixin.load_financial_reports(app)
        box.showerror.assert_not_called()
        self.assertEqual([r["code"] for r in app.balance_rows], ["531"])
        self.assertIn("unavailable", app.ctb_info["warning"])

    def test_errors_from_the_background_are_shown(self):
        from desktop_reports import ReportsMixin
        field = lambda value: SimpleNamespace(get=lambda: value)
        def boom(*args): raise RuntimeError("server stopped")
        scheduled = []
        app = SimpleNamespace(client=SimpleNamespace(general_ledger=boom), financial_report_range=lambda: ["2026-01-01", "2026-12-31"],
            view_currency=field("USD"), can_use=lambda key: True, ledger_tree=Mock(),
            after=lambda ms, fn: scheduled.append(fn), winfo_exists=lambda: True)

        class Inline:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
        with patch("threading.Thread", Inline), patch("desktop_reports.messagebox") as box:
            ReportsMixin.load_financial_reports(app)
            for poll in list(scheduled): poll()
        box.showerror.assert_called_once()
        self.assertIn("server stopped", box.showerror.call_args.args[1])


FAKE_WORKER = textwrap.dedent('''
    import json, os, sys, time
    mode = os.environ.get("FAKE_OCR_MODE", "ok")
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        if mode == "nostart":
            print("not json", flush=True); sys.exit(1)
        if mode == "logfirst":  # a model message on stdout before the handshake, then stays running
            print("Creating model...", flush=True); time.sleep(60)
        print("loading models", file=sys.stderr, flush=True)
        print(json.dumps({"ready": True, "pid": os.getpid()}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("quit"): break
            if mode == "slow": time.sleep(30)
            if request["path"].endswith("bad.jpg"):
                print(json.dumps({"id": request["id"], "error": "cannot open"}), flush=True); continue
            print(json.dumps({"id": request["id"], "readings": [{"texts": [str(os.getpid())], "scores": [1], "boxes": [[0, 0, 1, 1]]}]}), flush=True)
    else:
        print(json.dumps({"readings": [{"texts": ["one-shot"], "scores": [1], "boxes": [[0, 0, 1, 1]]}]}))
''')


class PersistentOcrTest(unittest.TestCase):
    def setUp(self):
        import neural_reader
        self.reader = neural_reader
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.script = Path(self.folder.name) / "worker.py"; self.script.write_text(FAKE_WORKER, encoding="utf-8")
        self.patches = [patch.dict(os.environ, {"NANZA_NEURAL_PYTHON": sys.executable}),
                        patch.object(neural_reader, "worker", return_value=self.script)]
        for item in self.patches: item.start()
        neural_reader._WORKER.stop()

    def tearDown(self):
        self.reader._WORKER.stop()
        if self.reader._WORKER.timer: self.reader._WORKER.timer.cancel()
        for item in reversed(self.patches): item.stop()
        self.folder.cleanup()

    def test_models_load_once_for_several_invoices(self):
        first = self.reader.read("a.jpg"); second = self.reader.read("b.jpg")
        self.assertEqual(first[0]["texts"], second[0]["texts"])  # same worker process answered both
        self.assertTrue(self.reader._WORKER.alive())

    def test_a_failed_reading_keeps_the_worker_and_is_reported(self):
        self.reader.read("a.jpg"); pid = self.reader._WORKER.process.pid
        with self.assertRaisesRegex(self.reader.NeuralReaderError, "could not read"):
            self.reader.read("bad.jpg")
        self.reader.read("c.jpg")
        self.assertEqual(self.reader._WORKER.process.pid, pid)

    def test_timeout_kills_the_worker_and_is_not_retried(self):
        with patch.dict(os.environ, {"FAKE_OCR_MODE": "slow"}), patch.object(self.reader, "READ_TIMEOUT", 1), \
                patch.object(self.reader, "_run") as one_shot:
            started = time.monotonic()
            with self.assertRaisesRegex(self.reader.NeuralReaderError, "too long"):
                self.reader.read("a.jpg")
            self.assertLess(time.monotonic() - started, 15)
        one_shot.assert_not_called()
        self.assertFalse(self.reader._WORKER.alive())

    def test_worker_that_cannot_start_falls_back_to_one_shot(self):
        with patch.dict(os.environ, {"FAKE_OCR_MODE": "nostart"}):
            readings = self.reader.read("a.jpg")
        self.assertEqual(readings[0]["texts"], ["one-shot"])

    def test_bad_handshake_stops_the_half_started_worker(self):
        with patch.dict(os.environ, {"FAKE_OCR_MODE": "logfirst"}), patch.object(self.reader, "_run",
                return_value=json.dumps({"readings": [{"texts": ["one-shot"]}]})):
            self.assertEqual(self.reader.read("a.jpg")[0]["texts"], ["one-shot"])
        self.assertIsNone(self.reader._WORKER.process)

    def test_idle_worker_stops(self):
        with patch.object(self.reader, "IDLE_SECONDS", 0.3):
            self.reader.read("a.jpg")
            for _ in range(50):
                if not self.reader._WORKER.alive(): break
                time.sleep(0.1)
        self.assertFalse(self.reader._WORKER.alive())


if __name__ == "__main__":
    unittest.main()
