"""HTTP coverage for company selection on current and comparative report routes."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import server
from client import ApiClient
from company_manager import CompanyManager


class CompanyYearHttpIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls.folder.cleanup)
        database = Path(cls.folder.name) / "master.db"
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=server.run_server, kwargs={"host": "127.0.0.1", "port": port,
            "database": str(database), "admin_password": "Synthetic-Admin-2026!"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        cls.database_path = database
        cls.admin = ApiClient(cls.url)
        for _ in range(200):
            try:
                cls.admin.login("admin", "Synthetic-Admin-2026!"); break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError("Synthetic test server did not start")
        cls.company_a = cls.admin.create_company({"name": "Synthetic Company A", "year": 2025})["id"]
        cls.company_b = cls.admin.create_company({"name": "Synthetic Company B", "year": 2026})["id"]
        cls.admin.save_user({"username": "limited-a", "password": "Synthetic-Limited-2026!",
            "role": "accountant", "language": "en", "companies": [cls.company_a]})
        # Place a distinctive synthetic marker in B so denied responses can be checked for leakage.
        manager = CompanyManager(database)
        b_db = manager.database(cls.company_b, 2026)
        b_db.save_party({"name": "PRIVATE COMPANY B SYNTHETIC MARKER", "kind": "customer", "currency": "USD"}, 1)
        for db_path in list(manager._cache): manager._cache.pop(db_path).release()
        cls.manager = manager

    @classmethod
    def tearDownClass(cls):
        try:
            for db in list(cls.manager._cache.values()): db.release()
        except Exception:
            pass
        cls.admin.close()

    def setUp(self):
        self.limited = ApiClient(self.url)
        self.limited.login("limited-a", "Synthetic-Limited-2026!")
        self.limited.select_company_year(self.company_a, 2025)

    def tearDown(self):
        self.limited.close()

    def test_mismatched_company_is_denied_on_current_and_multi_year_routes(self):
        routes = (
            ("GET", "/api/parties"),
            ("GET", "/api/commercial?quotations=1&q=paper"),
            ("POST", "/api/commercial/1/convert"),
            ("GET", "/api/dashboard/brief?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/dashboard/executive?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/management-pack?month_end=2026-12-31"),
            ("GET", "/api/analytic-study?date_from=2026-01-01&date_to=2026-12-31"),
            ("GET", "/api/year-end-check?year=2026"),
            ("GET", "/api/reports/accounts?options=%7B%22view_year%22%3A2026%7D"),
            ("GET", "/api/fiscal-year/journal?year=2026"),
            ("GET", "/api/fiscal-year/report-choices?year=2026"),
            ("GET", "/api/fiscal-year/cash-flow?year=2026"),
            ("GET", "/api/fiscal-year/profit-loss?year=2026"),
            ("GET", "/api/fiscal-year/balance-sheet?year=2026"),
            ("GET", "/api/cash-flow/monthly?from_date=2026-01-01&to_date=2026-12-31"),
            ("GET", "/api/comparative-reports?from_date=2026-01-01&to_date=2026-12-31"),
            ("GET", "/api/reports/financial-config?year=2026"),
            ("GET", "/api/reports/business?report=financial_statements&options=%7B%22years%22%3A%5B2026%5D%7D"),
            ("GET", "/api/comparative-trial-balance?from_date=01-01-2026&to_date=31-12-2026"),
            ("GET", "/api/workbench/board?date_from=2026-01-01&date_to=2026-12-31"),
            ("POST", "/api/reports/financial-config"),
            ("POST", "/api/parties"),
        )
        for method, path in routes:
            with self.subTest(method=method, path=path):
                self.limited.company_id = self.company_b
                self.limited.fiscal_year = 2026
                body = {"name": "ATTEMPTED SYNTHETIC WRITE", "kind": "customer", "currency": "USD"} if method == "POST" else None
                with self.assertRaisesRegex(RuntimeError, "do not have access to this company") as denied:
                    self.limited.request(method, path, body)
                self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied.exception))
                self.limited.company_id = self.company_a
                self.limited.fiscal_year = 2025
        b_manager = CompanyManager(self.database_path)
        b_db = b_manager.database(self.company_b, 2026)
        with b_db.connect() as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM parties")}
        self.assertIn("PRIVATE COMPANY B SYNTHETIC MARKER", names)
        self.assertNotIn("ATTEMPTED SYNTHETIC WRITE", names)
        for db_path in list(b_manager._cache): b_manager._cache.pop(db_path).release()

    def seed_historical_books(self):
        company = self.admin.create_company({"name": self._testMethodName, "year": 2024})
        company = self.admin.create_fiscal_year(company["id"], 2025)
        number = "JV-SAME-NUMBER"
        for year, caption, amount in ((2024, "Historical entry", "42.25"), (2025, "Current entry", "93.50")):
            self.admin.select_company_year(company["id"], year)
            self.admin.save_journal_voucher(
                {"entry_number": number, "entry_date": f"11-02-{year}", "description": caption, "currency": "USD"},
                [{"account_code": "531", "side": "D", "amount": amount},
                 {"account_code": "713", "side": "C", "amount": amount}],
            )
            if year == 2024:
                self.admin.save_party({"name": "Prior-year-only customer", "kind": "customer", "currency": "USD"})
        return company, number

    def test_historical_statement_and_entry_from_current_books(self):
        company, number = self.seed_historical_books()
        current = self.admin.journal(entry_number=number)
        history = self.admin.fiscal_year_journal(2024, entry_number=number)
        self.assertEqual({row["description"] for row in history}, {"Historical entry"})
        self.assertEqual(sum(row["debit"] for row in history), 42.25)
        self.assertEqual({row["description"] for row in current}, {"Current entry"})
        choices = self.admin.fiscal_year_report_choices(2024)
        self.assertTrue(choices["read_only"])
        self.assertIn("Prior-year-only customer", {row["name"] for row in choices["parties"]})
        self.assertNotIn("Prior-year-only customer", {row["name"] for row in self.admin.parties()})
        report = self.admin.account_report({"view_year": 2024, "account_from": "531", "account_to": "531",
                                            "statement": True, "detailed": True, "reference": True,
                                            "date_from": "01-01-2024", "date_to": "31-12-2024", "first_column": "USD"})
        self.assertIn("Historical entry", str(report["sections"]))
        self.assertNotIn("Current entry", str(report["sections"]))
        self.assertEqual((self.admin.company_id, self.admin.fiscal_year), (company["id"], 2025))
        with self.assertRaisesRegex(RuntimeError, "FY 2026 unavailable"):
            self.admin.fiscal_year_report_choices(2026)

    def test_historical_journal_and_statement_dialog_are_read_only(self):
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from unittest.mock import patch
        import desktop

        try:
            app = desktop.SaberApp()
        except tk.TclError as exc:
            self.skipTest(f"No display: {exc}")
        self.addCleanup(app.destroy)
        company, number = self.seed_historical_books()
        app.server.set(self.url)
        app.password.set("Synthetic-Admin-2026!")
        app.language.set("en")
        app.login()
        app.client.select_company_year(company["id"], 2025)
        app.current_company, app.current_fiscal_year = company, 2025
        app.journal_view_year.set("2025")
        app.main_screen()
        app.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        def check_dialog(window):
            labels = [widget["text"] for widget in descendants(window) if isinstance(widget, tk.Label)]
            buttons = [widget["text"] for widget in descendants(window) if isinstance(widget, tk.Button)]
            self.assertIn("Read-only", labels)
            self.assertTrue(any("Historical entry" in label for label in labels))
            self.assertNotIn("Edit this entry", buttons)
            self.assertFalse(window.bind("<Return>"))
            window.destroy()

        with patch("tkinter.messagebox.showerror") as errors, patch.object(app, "open_entry_source") as edit:
            app.select_main_tab(app.journal_tab)
            app.update()
            journal_year = next(w for w in descendants(app.journal_tab) if isinstance(w, ttk.Combobox)
                                and w["textvariable"] == str(app.journal_view_year))
            journal_year.set("2024")
            journal_year.event_generate("<<ComboboxSelected>>")
            app.update()
            self.assertEqual(app.journal_delete_button["state"], "disabled")
            self.assertEqual(app.journal_open_button["text"], "View Selected Entry")
            rows = app.journal_tree.get_children()
            self.assertTrue(rows)
            app.journal_tree.selection_set(rows[0])
            with patch("tkinter.messagebox.showwarning") as denied, patch.object(app.client, "delete_journal_voucher") as delete:
                app.delete_selected_journal_voucher()
                delete.assert_not_called()
                denied.assert_called_once()
            app.journal_open_button.invoke()
            window = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == f"Transaction {number}")
            check_dialog(window)

            app.select_main_tab(app.account_reports_tab)
            app.statement_tab.master.select(app.statement_tab)
            app.update()
            state = app.statement_state
            filters = state["vars"]
            statement_year = next(w for w in descendants(app.statement_tab) if isinstance(w, ttk.Combobox)
                                  and w["textvariable"] == str(filters["view_year"]))
            statement_year.set("2024")
            statement_year.event_generate("<<ComboboxSelected>>")
            app.update()
            self.assertTrue(any("Prior-year-only customer" in name for name in filters["party_box"]["values"]))
            filters["account_from"].set("531")
            app.run_balance_report(state)
            historical = state["viewer"]
            state["notebook"].select(state["options_page"])
            statement_year.set("2025")
            statement_year.event_generate("<<ComboboxSelected>>")
            app.update()
            app.run_balance_report(state)
            old_tab = next(tab for tab, (_, viewer) in state["tabs"].items() if viewer is historical)
            state["notebook"].select(old_tab)
            app.update()
            match = next(iid for iid in historical.get_children() if number in historical.item(iid, "values"))
            historical.see(match)
            app.update()
            box = historical.bbox(match)
            check_dialog(app.open_report_line(state, historical, SimpleNamespace(y=box[1] + 2)))
            self.assertEqual(app.client.fiscal_year, 2025)
            self.assertEqual({r["description"] for r in app.client.journal(entry_number=number)}, {"Current entry"})
            edit.assert_not_called()
            errors.assert_not_called()

    def test_missing_or_malformed_fiscal_year_does_not_fall_through_to_another_company(self):
        self.limited.company_id = self.company_a
        self.limited.fiscal_year = 2025
        self.limited.company_id = None
        try:
            fallback = self.limited.request("GET", "/api/parties")
            self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(fallback))
        except RuntimeError as denied:
            self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied))
        self.limited.company_id = "malformed-company-id"
        with self.assertRaisesRegex(RuntimeError, "do not have access to this company"):
            self.limited.request("GET", "/api/parties")
        self.limited.company_id = self.company_a
        # 2026 exists only in Company B; Company A's year selection must not fall through by year number.
        self.limited.fiscal_year = 2026
        with self.assertRaisesRegex(RuntimeError, "Fiscal year not found") as denied:
            self.limited.request("GET", "/api/parties")
        self.assertNotIn("PRIVATE COMPANY B SYNTHETIC MARKER", str(denied.exception))
        self.limited.fiscal_year = "not-a-year"
        with self.assertRaises(RuntimeError):
            self.limited.request("GET", "/api/parties")


if __name__ == "__main__":
    unittest.main()
