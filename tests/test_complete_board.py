"""Board dashboard: posted-book arithmetic, safe abstention and clean exported layout."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from database import Database
from nanza_delivery.complete_board_dashboard import (
    build_board,
    settings,
    save_settings,
    validate_config,
    render_board,
    export_board_pdf,
    GROUPS,
)


class BoardDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "board.db")
        self.db.initialize("Board-fixture-2024!")
        self.addCleanup(self.db.release)
        definitions = [
            ("799910001", "Board revenue", "income"),
            ("109910001", "Board capital", "equity"),
            ("539910001", "Board bank", "asset"),
            ("699910001", "Interest", "expense"),
            ("699910002", "Depreciation", "expense"),
            ("699910003", "Income tax", "expense"),
            ("699910004", "Cost of goods", "expense"),
            ("699910005", "Admin", "expense"),
            ("169910001", "Senior loan", "liability"),
            ("169910002", "Subordinated loan", "liability"),
            ("219910001", "Equipment", "asset"),
        ]
        with self.db.connect() as c:
            c.executemany("INSERT OR IGNORE INTO accounts(code,name_en,type) VALUES(?,?,?)", definitions)
        self.config = {
            "reviewed": True,
            **{key: [] for key in GROUPS},
            "targets": {"debt_ebitda_max": "3.5", "current_ratio_min": "1.5"},
        }
        self.config.update(
            cogs=["699910004"],
            sga=["699910005"],
            interest=["699910001"],
            depreciation=["699910002"],
            tax=["699910003"],
            senior_debt=["169910001"],
            subordinated_debt=["169910002"],
            current_assets=["539910001"],
            current_liabilities=["169910001"],
            operating_cash=["799910001", "699910001", "699910003", "699910004", "699910005"],
            capex=["219910001"],
            financing_cash=["109910001", "169910001", "169910002"],
        )

    def post(self, day, debit, credit, amount):
        self.db.save_journal_voucher(
            {"entry_date": day, "currency": "USD", "description": "Board fixture"},
            [{"account_code": debit, "debit": amount}, {"account_code": credit, "credit": amount}],
            1,
        )

    def model(self, start="2024-01-01", end="2024-12-31"):
        return build_board(self.db, start, end, "USD")

    def populate(self):
        self.post("2024-01-01", "539910001", "109910001", 1000)
        self.post("2024-01-02", "539910001", "169910001", 300)
        self.post("2024-07-01", "539910001", "799910001", 100)
        self.post("2024-08-01", "539910001", "799910001", 100)
        self.post("2024-08-02", "699910004", "539910001", 80)
        self.post("2024-08-03", "699910005", "539910001", 20)
        self.post("2024-08-04", "699910001", "539910001", 10)
        self.post("2024-08-05", "699910003", "539910001", 5)
        self.post("2024-08-06", "699910002", "219910001", 15)
        self.post("2024-08-07", "219910001", "539910001", 50)

    def test_defaults_are_read_only_and_do_not_invent_covenant_or_forecast(self):
        self.assertFalse(settings(self.db)["reviewed"])
        report = self.model(end="2024-10-18")
        self.assertEqual(report["metrics"]["debt_status"], "Unknown")
        for key in ["debt_ebitda", "ebitda", "current_ratio", "roic", "year_end", "dscr", "fcf"]:
            self.assertIsNone(report["metrics"][key], key)
        with self.db.connect() as c:
            self.assertIsNone(
                c.execute("SELECT 1 FROM sqlite_master WHERE name='board_dashboard_settings'").fetchone()
            )

    def test_signed_revenue_profit_cash_and_waterfall_reconcile(self):
        self.populate()
        self.post("2024-08-08", "799910001", "539910001", 20)
        report = self.model()
        m = report["metrics"]
        self.assertEqual(m["revenue"], Decimal("180"))
        self.assertEqual(m["net_income"], Decimal("50"))
        self.assertEqual(m["cash"], Decimal("1315"))
        self.assertEqual(
            report["waterfall"][0]["value"]
            + sum((r["value"] for r in report["waterfall"][1:-1]), Decimal(0)),
            m["cash"],
        )
        self.assertEqual(sum((r["revenue"] for r in report["months"]), Decimal(0)), Decimal("180"))

    def test_reviewed_ebitda_ratios_and_debt_covenant(self):
        self.populate()
        save_settings(self.db, self.config, 1)
        m = self.model()["metrics"]
        self.assertEqual(m["net_income"], Decimal("70"))
        self.assertEqual(m["ebit"], Decimal("85"))
        self.assertEqual(m["ebitda"], Decimal("100"))
        self.assertEqual(m["debt_ebitda"], Decimal("3"))
        self.assertEqual(m["debt_status"], "Compliant")
        self.assertEqual(m["interest_coverage"], Decimal("8.5"))
        self.assertEqual(m["equity"], Decimal("1070"))
        self.assertEqual(m["current_ratio"], Decimal("1335") / 300)
        self.assertEqual(m["roic"], Decimal("80") / Decimal("17.5") * 100)

    def test_breach_is_not_reported_as_compliant(self):
        self.populate()
        self.config["targets"]["debt_ebitda_max"] = "2.5"
        save_settings(self.db, self.config, 1)
        self.assertEqual(self.model()["metrics"]["debt_status"], "Breach")

    def test_partial_year_covenant_and_roic_abstain(self):
        self.populate()
        save_settings(self.db, self.config, 1)
        report = self.model(end="2024-10-18")
        self.assertIsNone(report["metrics"]["debt_ebitda"])
        self.assertIsNone(report["metrics"]["roic"])
        self.assertIsNone(report["metrics"]["year_end"])
        self.assertEqual(report["metrics"]["debt_status"], "Unknown")

    def test_fcf_is_real_operating_plus_capex_cash_not_profit(self):
        self.populate()
        save_settings(self.db, self.config, 1)
        report = self.model()
        self.assertEqual(report["unclassified_cash_entries"], 0)
        self.assertEqual(report["metrics"]["fcf"], Decimal("35"))
        self.assertEqual(sum((r["fcf"] for r in report["months"]), Decimal(0)), Decimal("35"))
        self.assertNotEqual(report["metrics"]["fcf"], report["metrics"]["net_income"])

    def test_unclassified_cash_entries_block_even_when_they_cancel(self):
        self.populate()
        save_settings(self.db, self.config, 1)
        self.post("2024-08-08", "539910001", "6263.1", 10)
        self.post("2024-08-09", "6263.1", "539910001", 10)
        report = self.model()
        self.assertEqual(report["unclassified_cash_entries"], 2)
        self.assertIsNone(report["metrics"]["fcf"])
        self.assertTrue(all(r["fcf"] is None for r in report["months"]))

    def test_mixed_cash_counterparts_cannot_be_guessed(self):
        save_settings(self.db, self.config, 1)
        self.db.save_journal_voucher(
            {"entry_date": "2024-08-01", "currency": "USD", "description": "Mixed cash"},
            [
                {"account_code": "539910001", "credit": 100},
                {"account_code": "699910005", "debit": 40},
                {"account_code": "219910001", "debit": 60},
            ],
            1,
        )
        report = self.model()
        self.assertEqual(report["unclassified_cash_entries"], 1)
        self.assertIsNone(report["metrics"]["fcf"])

    def test_invalid_and_overlapping_company_mappings_refused(self):
        for changes in (
            {"cogs": ["NOT-AN-ACCOUNT"]},
            {"cogs": ["699910001"], "interest": ["699910001"]},
            {"targets": {"debt_ebitda_max": "NaN"}},
            {"senior_debt": ["539910001"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_config(self.db, dict(self.config, **changes))

    def test_retired_accounts_are_not_silently_used(self):
        with self.db.connect() as c:
            c.execute("UPDATE accounts SET active=0 WHERE code='699910001'")
        with self.assertRaises(ValueError):
            validate_config(self.db, self.config)

    def test_missing_prior_data_stays_unknown_and_signed_yoy_is_correct(self):
        self.post("2024-07-01", "539910001", "799910001", 120)
        report = self.model()
        self.assertIsNone(report["metrics"]["revenue_yoy"])
        self.post("2023-07-01", "539910001", "799910001", 100)
        self.assertEqual(self.model()["metrics"]["revenue_yoy"], Decimal("20"))

    def test_prior_year_file_is_authoritative_and_current_model_survives_prior_conversion_error(self):
        self.post("2024-07-01", "539910001", "799910001", 120)
        prior = type(
            "Prior",
            (),
            {"_converted_lines": lambda *args: (_ for _ in ()).throw(ValueError("Missing prior rate"))},
        )()
        report = build_board(self.db, "2024-01-01", "2024-12-31", prior_db=prior)
        self.assertEqual(report["metrics"]["revenue"], Decimal("120"))
        self.assertIsNone(report["metrics"]["revenue_yoy"])
        self.assertIn("Missing prior rate", report["prior_warning"])

    def test_future_year_end_is_never_presented_as_actual(self):
        report = self.model("2090-01-01", "2090-12-31")
        self.assertIsNone(report["metrics"]["year_end"])
        self.assertEqual(report["metrics"]["debt_status"], "Unknown")

    def test_clean_full_board_pdf_and_no_example_balances(self):
        self.populate()
        save_settings(self.db, self.config, 1)
        report = self.model()
        figure = render_board(report)
        self.assertEqual(tuple(round(v, 1) for v in figure.get_size_inches()), (12.8, 8.5))
        texts = " ".join(t.get_text() for ax in figure.axes for t in ax.texts)
        for forbidden in ["LinkedIn", "http", "QR", "10.33M", "549K", "14.2M", "Confidential"]:
            self.assertNotIn(forbidden, texts)
        path = Path(self.tmp.name) / "board.pdf"
        export_board_pdf(report, path)
        from pypdf import PdfReader

        pdf = PdfReader(path)
        self.assertEqual(len(pdf.pages), 1)
        content = pdf.pages[0].extract_text()
        self.assertIn("NANZA", content)
        self.assertIn("The Complete Board Dashboard", content)
        self.assertNotIn("LinkedIn", content)
        figure.clear()

    def test_settings_are_audited_and_do_not_change_accounting(self):
        self.populate()
        with self.db.connect() as c:
            before = c.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
        save_settings(self.db, self.config, 1)
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0], before)
            self.assertEqual(
                c.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE entity='board_dashboard_settings'"
                ).fetchone()[0],
                1,
            )


class BoardApiTest(unittest.TestCase):
    def test_board_routes_are_authenticated_and_mapping_is_admin_only(self):
        from http.server import ThreadingHTTPServer
        import threading
        from company_manager import CompanyManager
        from client import ApiClient
        from server import ApiHandler

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "master.db"
            db = Database(path)
            db.initialize("Board-api-fixture!")
            manager = CompanyManager(path)
            if not manager.list_companies():
                manager.create_company({"name": "Board company", "year": 2024}, db)
            handler = type(
                "BoardApiHandler", (ApiHandler,), dict(db=db, master_db=db, company_manager=manager)
            )
            http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            worker = threading.Thread(target=http.serve_forever, daemon=True)
            worker.start()
            try:
                api = ApiClient(f"http://127.0.0.1:{http.server_port}")
                with self.assertRaises(RuntimeError):
                    api.workbench("board-settings")
                api.login("admin", "Board-api-fixture!")
                company = api.companies()[0]
                year = int(company["years"][0]["year"])
                api.select_company_year(company["id"], year)
                result = api.workbench("board", date_from=f"{year}-01-01", date_to=f"{year}-12-31")
                self.assertEqual(result["metrics"]["debt_status"], "Unknown")
                config = api.workbench("board-settings")
                api.request("POST", "/api/workbench/board-settings", {"config": config})
                db.save_user(
                    {"username": "boarduser", "password": "Board-user-fixture!", "role": "accountant"}, 1
                )
                user = ApiClient(api.base_url)
                user.login("boarduser", "Board-user-fixture!")
                user.select_company_year(company["id"], year)
                with self.assertRaisesRegex(RuntimeError, "Administrator"):
                    user.request("POST", "/api/workbench/board-settings", {"config": config})
                self.assertIn(
                    "metrics", user.workbench("board", date_from=f"{year}-01-01", date_to=f"{year}-12-31")
                )
                registry = manager._read()
                for entry in registry["companies"]:
                    if entry["id"] == company["id"]:
                        for fiscal in entry["years"]:
                            if int(fiscal["year"]) == year:
                                fiscal["status"] = "closed"
                manager._write(registry)
                api.request("POST", "/api/workbench/board-settings", {"config": config})
                self.assertIn(
                    "metrics", api.workbench("board", date_from=f"{year}-01-01", date_to=f"{year}-12-31")
                )
                api.close()
                user.close()
            finally:
                http.shutdown()
                http.server_close()
                worker.join(5)
                for cached in list(manager._cache):
                    manager._cache.pop(cached).release()
                db.release()


class BoardGuiTest(unittest.TestCase):
    def test_customtkinter_window_loads_from_selected_books_and_exports_pdf(self):
        import tkinter as tk

        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError:
            raise unittest.SkipTest("No graphical display")
        from tests.test_workbench_upgrade import WorkbenchGuiTest
        from nanza_delivery.complete_board_dashboard import open_board

        case = WorkbenchGuiTest("test_ageing_filter_drilldown_and_excel_export")
        case.setUp()
        try:
            window = open_board(case.app)
            case.wait(lambda: window.data is not None and window.canvas is not None)
            import customtkinter as ctk

            self.assertIsInstance(window, ctk.CTkToplevel)
            self.assertEqual(Decimal(window.data["metrics"]["revenue"]), Decimal("100"))
            self.assertEqual(window.data["metrics"]["debt_status"], "Unknown")
            self.assertEqual(len(window.figure.axes) >= 10, True)
            target = Path(case.tmp.name) / "board.pdf"
            with patch("tkinter.filedialog.asksaveasfilename", return_value=str(target)):
                window.export()
                case.wait(
                    lambda: target.exists() and str(window.pdf_button.cget("state")) == "normal", timeout=12
                )
            from pypdf import PdfReader

            self.assertEqual(len(PdfReader(target).pages), 1)
            self.assertEqual(case.app.errors, [])
            window.destroy()
            case.app.update()
        finally:
            case.tearDown()
            case.doCleanups()
