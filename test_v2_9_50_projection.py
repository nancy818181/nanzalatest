"""2.9.50: projection & budget from the books, growth % per year, scenarios, 3D charts in PDF / Excel / screen."""
import tempfile
import unittest
from pathlib import Path

import chart3d
import projection_model as pm
from database import Database


def base_accounts():
    rows = {m: [{"code": "701100001", "name_en": "Goods Sales", "type": "income", "amount": 1000 + 100 * m},
                {"code": "601100000", "name_en": "Purchases", "type": "expense", "amount": 600 + 60 * m},
                {"code": "631000000", "name_en": "Salaries", "type": "expense", "amount": 200},
                {"code": "626000000", "name_en": "Rent", "type": "expense", "amount": 50},
                {"code": "651000000", "name_en": "Depreciation", "type": "expense", "amount": 10}] for m in range(1, 13)}
    return pm.collect_base(rows, 12)


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.accounts = base_accounts()
        self.assumptions = pm.default_assumptions(2025, 3)
        self.assumptions["per_year"]["2026"].update(revenue=20, payroll=10, operating=0, capex=1200, financing=500)
        self.assumptions["per_year"]["2027"].update(revenue=10, cost_of_sales=5)
        self.balances = {"cash": 5000.0, "receivables": 1950.0, "payables": 1170.0}

    def test_lines_and_growth_per_year(self):
        self.assertEqual({k: v["line"] for k, v in self.accounts.items()},
                         {"701100001": "revenue", "601100000": "cost_of_sales", "631000000": "payroll", "626000000": "operating", "651000000": "depreciation"})
        p = pm.project(self.accounts, self.assumptions, self.balances)
        base = p["base"]["revenue"]; self.assertEqual(base, 19800)
        self.assertAlmostEqual(p["rows"][2026]["revenue"], base * 1.2)
        self.assertAlmostEqual(p["rows"][2026]["cost_of_sales"], p["base"]["cost_of_sales"] * 1.2)    # follows revenue
        self.assertAlmostEqual(p["rows"][2027]["cost_of_sales"], p["base"]["cost_of_sales"] * 1.2 * 1.05)  # own rate
        self.assertAlmostEqual(p["rows"][2026]["payroll"], 2400 * 1.1)
        self.assertAlmostEqual(p["rows"][2026]["depreciation"], 120 + 1200 / 5 / 2)
        self.assertAlmostEqual(p["rows"][2027]["depreciation"], 120 + 1200 / 5)
        self.assertAlmostEqual(p["dso"], 1950 / 19800 * 365)
        c = p["cash"][2026]
        self.assertAlmostEqual(c["closing"], 5000 + c["operating"] - 1200 + 500)
        self.assertAlmostEqual(p["cash"][2027]["opening"], c["closing"])
        t = p["rows"][2026]
        self.assertAlmostEqual(t["income_tax"], max(0, t["profit_before_tax"]) * 0.17)

    def test_scenarios_move_revenue_by_the_spread(self):
        low = pm.project(self.accounts, self.assumptions, self.balances, "Pessimistic")["rows"][2026]["revenue"]
        high = pm.project(self.accounts, self.assumptions, self.balances, "Optimistic")["rows"][2026]["revenue"]
        self.assertAlmostEqual(low, 19800 * 1.10); self.assertAlmostEqual(high, 19800 * 1.30)

    def test_monthly_budget_keeps_seasonality_and_totals(self):
        p = pm.project(self.accounts, self.assumptions, self.balances)
        months = pm.monthly_budget(self.accounts, p, 2026)["701100001"]
        self.assertAlmostEqual(sum(months), p["accounts"][2026]["701100001"], places=2)
        self.assertLess(months[0], months[11])                                    # December sells more, as in the base year
        lines = pm.budget_lines(self.accounts, p, 2026)
        self.assertEqual(len(lines), 5); self.assertTrue(all(len(l["months"]) == 12 for l in lines))

    def test_partial_year_is_annualised(self):
        rows = {1: [{"code": "7011", "name_en": "S", "type": "income", "amount": 100}], 2: [{"code": "7011", "name_en": "S", "type": "income", "amount": 300}]}
        self.assertEqual(pm.collect_base(rows, 2)["7011"]["annual"], 100 + 300 + 200 * 10)
        from datetime import datetime
        self.assertEqual(pm.base_period(2026, datetime(2026, 3, 15)), (2, "2026 annualised (Jan-Feb)"))
        with self.assertRaises(ValueError): pm.base_period(2026, datetime(2026, 1, 5))

    def test_reports_and_exports_with_3d_charts(self):
        _projections, sections = pm.report_sections(self.accounts, self.assumptions, self.balances, "Actual 2025", "USD", "Base", 2026)
        headings = [s["heading"] for s in sections]
        for word in ("Projected income statement", "Projected cash flow", "Key indicators", "Scenario comparison", "Budget projection by account", "Monthly budget 2026", "Monthly cash plan"):
            self.assertTrue(any(word in h for h in headings), word)
        self.assertGreaterEqual(sum(1 for s in sections if s.get("chart")), 4)
        from report_export import export_sections_excel, export_sections_pdf
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "p.pdf"; xlsx = Path(folder) / "p.xlsx"
            export_sections_pdf(pdf, "Projection", ["x"], sections); export_sections_excel(xlsx, "Projection", ["x"], sections)
            self.assertGreater(pdf.stat().st_size, 5000)
            from openpyxl import load_workbook
            self.assertGreaterEqual(len(load_workbook(xlsx).active._charts), 4)

    def test_chart_geometry(self):
        chart = chart3d.bar3d(["A", "B"], ["2026", "2027"], [[10, -5], [3, 4]], "T")
        self.assertGreater(len(chart["polygons"]), 12); self.assertIn("T", [t[2] for t in chart["texts"]])
        self.assertEqual(chart3d.compact(1250000), "1.2M"); self.assertEqual(chart3d.nice_ticks(0, 95)[-1], 100)
        self.assertEqual(chart3d.bar3d([], [], [])["texts"][0][2], "No data")


class FromTheBooksTest(unittest.TestCase):
    def test_base_and_balances_from_a_company(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "c.db"); db.initialize("secret")
            user = db.user_for_token(db.login("admin", "secret")["token"])["id"]
            for month in (1, 2, 3):
                db.create_manual_invoice({"invoice_number": f"S{month}", "invoice_date": f"10-{month:02d}-2025", "party_name": "Client", "kind": "sales", "currency": "USD",
                                          "status": "posted", "supplier_account": "411100001", "vat_account": "4427", "expense_account": "701100001"},
                                         [{"description": "x", "quantity": 1, "unit_price": 1000, "vat_rate": 0}], user)
            monthly = {m: db.profit_and_loss(f"2025-{m:02d}-01", pm.month_end(2025, m), "USD") for m in range(1, 13)}
            accounts = pm.collect_base(monthly, 12)
            self.assertEqual(accounts["701100001"]["annual"], 3000)
            balances = pm.balances_from(db.balance_sheet("2025-12-31", "USD"))
            self.assertEqual(balances["receivables"], 3000)
            db.release()


class ScreenTest(unittest.TestCase):
    def test_tab_builds_and_draws(self):
        try:
            import tkinter as tk
            import desktop
        except ImportError as exc: self.skipTest(str(exc))
        from unittest.mock import MagicMock, patch
        try: root = tk.Tk()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        try:
            root.withdraw()
            chart = chart3d.bar3d(["A", "B"], ["1", "2", "3"], [[1, 2, 3], [3, -2, 1]])
            canvas = tk.Canvas(root, width=900, height=430); chart3d.draw_on_canvas(canvas, chart)
            self.assertGreater(len(canvas.find_all()), 20)
            self.assertTrue(hasattr(desktop.SaberApp, "build_projection_page") and hasattr(desktop.SaberApp, "show_projection_charts"))
        finally: root.destroy()

    def test_projection_screen_end_to_end(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            import desktop
        except ImportError as exc: self.skipTest(str(exc))
        import os
        from unittest.mock import MagicMock, patch
        class App(tk.Tk): pass
        for name in ("build_projection_page", "load_projection_assumptions", "collect_projection_assumptions", "fill_projection_sheet", "_format_projection_row",
                     "projection_cell_changed", "apply_projection_growth_to_all", "save_projection_assumptions", "load_projection_base", "refresh_projection",
                     "_projection_ready", "export_projection", "save_projection_as_budget", "show_projection_charts", "_projection_file", "_projection_key",
                     "report_viewer", "show_sections", "action_button", "save_sections", "suggest_projection_growth", "_year_profit_loss"):
            setattr(App, name, getattr(desktop.SaberApp, name))
        try: app = App()
        except tk.TclError as exc: self.skipTest(f"no display: {exc}")
        folder = tempfile.TemporaryDirectory(); old = os.environ.get("SABER_DATA_DIR"); os.environ["SABER_DATA_DIR"] = folder.name
        try:
            app.withdraw(); app.currency_codes = ["USD", "LBP"]; app.current_fiscal_year = 2025; app.current_company = {"id": 1}
            rows = {m: [{"code": "701100001", "name_en": "Goods Sales", "type": "income", "amount": 1000 + 100 * m},
                        {"code": "601100000", "name_en": "Purchases", "type": "expense", "amount": 600}] for m in range(1, 13)}
            app.client = MagicMock(); app.client.profit_loss.side_effect = lambda a, b, c, **_kw: rows[int(a[5:7])]  # 2.9.80: convert=True
            app.client.balance_sheet.return_value = [{"code": "531", "balance": 4000}, {"code": "411", "balance": 1000}]
            notebook = ttk.Notebook(app); notebook.pack()
            with patch("desktop_projection.messagebox") as box:
                app.build_projection_page(notebook); app.pj["base_year"].set("2025")
                app.pj["all_growth"].set("12"); app.apply_projection_growth_to_all(); app.refresh_projection()
                self.assertEqual(box.showwarning.call_count + box.showerror.call_count, 0)
                self.assertIn("revenue 27,818", app.pj_info.cget("text"))   # 19,800 x 1.12^3
                window = app.show_projection_charts(); app.update()
                box.askyesno.return_value = True; app.pj["budget_year"].set("2026"); app.save_projection_as_budget()
                saved = app.client.save_budget.call_args[0][0]
                self.assertEqual((saved["year"], len(saved["lines"])), (2026, 2))
                window.destroy()
        finally:
            app.destroy()
            if old is None: os.environ.pop("SABER_DATA_DIR", None)
            else: os.environ["SABER_DATA_DIR"] = old
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
