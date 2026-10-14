"""2.9.69: multi-select delete, show / hide columns, VAT number in top clients / suppliers,
financial statements as an audit report pack (2 years or a period)."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import socket
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from database import Database
import financial_statements as fs

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class AuditPackTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "2025.db"); self.db.initialize("secret12345")
        self.old = Database(Path(self.folder.name) / "2024.db"); self.old.initialize("secret12345")

    def voucher(self, db, amount, debit, credit, date):
        return db.save_journal_voucher(dict(entry_date=date, currency="USD", description="FS"),
                                       [dict(account_code=debit, debit=str(amount), credit=0), dict(account_code=credit, debit=0, credit=str(amount))], 1)

    def test_section_order_and_two_years(self):
        self.voucher(self.db, 1000, "531", "101", "01-01-2025"); self.voucher(self.db, 400, "531", "7011", "10-03-2025")
        pack = fs.build({2025: self.db, 2024: self.old}, {"years": "2024,2025", "basis": "USD"})
        headings = [s["heading"] for s in pack["sections"]]
        self.assertEqual(headings[0], "INDEPENDENT AUDITOR'S REPORT")
        for start in ("STATEMENT OF FINANCIAL POSITION", "STATEMENT OF PROFIT OR LOSS", "STATEMENT OF CHANGES IN EQUITY", "STATEMENT OF CASH FLOWS"):
            self.assertTrue(any(h.startswith(start) for h in headings), start)
        self.assertTrue(any("ACCOUNTING POLICIES" in h for h in headings))
        self.assertTrue(any(h.startswith("NOTES TO THE FINANCIAL STATEMENTS") for h in headings))
        order = [next(i for i, h in enumerate(headings) if h.startswith(s)) for s in ("INDEPENDENT", "STATEMENT OF FINANCIAL", "STATEMENT OF PROFIT",
                "STATEMENT OF CHANGES", "STATEMENT OF CASH", "NOTES")]
        self.assertEqual(order, sorted(order))

    def test_cash_flow_reconciles_and_balance_sheet_balances(self):
        self.voucher(self.db, 1000, "531", "101", "01-01-2025")
        self.voucher(self.db, 600, "411", "7011", "05-02-2025")   # sale on credit
        self.voucher(self.db, 250, "531", "411", "20-02-2025")    # part collected
        self.voucher(self.db, 300, "6311", "531", "01-04-2025")
        pack = fs.build({2025: self.db}, {"years": "2025", "basis": "USD"})
        cf = next(s for s in pack["sections"] if s["heading"].startswith("STATEMENT OF CASH FLOWS"))
        row = {r[0]: r[2] for r in cf["rows"]}
        self.assertEqual(row["NET INCREASE / (DECREASE) IN CASH"] + row["Cash and cash equivalents at start"], row["CASH AND CASH EQUIVALENTS AT END"])
        self.assertEqual(row["CASH AND CASH EQUIVALENTS AT END"], Decimal("950"))
        sfp = pack["sections"][1]; total = {r[0]: r[2] for r in sfp["rows"]}
        self.assertEqual(total["TOTAL ASSETS"], total["TOTAL EQUITY AND LIABILITIES"])

    def test_period_mode_with_comparative(self):
        self.voucher(self.old, 70, "531", "7011", "15-02-2024"); self.voucher(self.old, 900, "531", "7011", "15-10-2024")
        self.voucher(self.db, 120, "531", "7011", "15-03-2025"); self.voucher(self.db, 500, "531", "7011", "15-11-2025")
        options = {"fs_mode": "period", "date_from": "01-01-2025", "date_to": "30-06-2025", "fs_compare": True, "basis": "USD"}
        pack = fs.build({2025: self.db, 2024: self.old}, options)
        pnl = next(s for s in pack["sections"] if s["heading"].startswith("STATEMENT OF PROFIT"))
        self.assertIn("for the period from 01-01-2025 to 30 June 2025", pnl["heading"])
        revenue = next(r for r in pnl["rows"] if r[0] == "Revenue")
        self.assertEqual(revenue[2:], [Decimal("120"), Decimal("70")])
        self.assertEqual(fs.periods_from({"fs_mode": "period", "date_from": "01-01-2025", "date_to": "30-06-2025"}, {2025})[0][1:3], ("2025-01-01", "2025-06-30"))
        with self.assertRaisesRegex(ValueError, "one fiscal year"):
            fs.periods_from({"fs_mode": "period", "date_from": "01-12-2024", "date_to": "30-06-2025"}, {2024, 2025})

    def test_old_placeholder_texts_get_the_new_defaults(self):
        old_text = next(iter(fs.OLD_DEFAULTS))
        fs.save_config(self.db, {"notes": {"Entity and activities": old_text}}, 1)
        self.assertNotIn(old_text, str(fs.build({2025: self.db}, {"years": "2025"})))


class TopPartiesVatTest(unittest.TestCase):
    def test_vat_number_replaces_account(self):
        import business_reports
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Database(Path(folder) / "x.db"); db.initialize("secret12345")
            db.import_invoice({"invoice_number": "S1", "invoice_date": "02-02-2026", "party_name": "Client A", "kind": "sales", "entry_type": "sales",
                                 "currency": "USD", "subtotal": 100, "vat": 11, "total": 111, "status": "posted"}, 1)
            with db.connect() as conn: conn.execute("UPDATE parties SET tax_number='VAT-777' WHERE name='Client A'")
            section = business_reports.build(db, "top_clients", {"date_from": "01-01-2026", "date_to": "31-12-2026", "basis": "USD"})["sections"][0]
            self.assertEqual(section["headers"][2], "VAT Number")
            self.assertEqual(section["rows"][0][1:3], ["Client A", "VAT-777"])


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class MultiDeleteAndColumnsTest(unittest.TestCase):
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
        api = ApiClient(cls.url); api.login("admin", "admin12345"); cls.company = api.companies()[0]; cls.year = cls.company["years"][0]["year"]
        api.select_company_year(cls.company["id"], cls.year)
        api.import_invoices([{"invoice_number": f"N{i}", "invoice_date": f"0{i + 1}-02-{cls.year}", "party_name": f"P{i}", "kind": "sales", "entry_type": "sales",
                              "currency": "USD", "subtotal": 100, "vat": 0, "total": 100, "status": "posted"} for i in range(4)], False)

    def test_delete_selection_and_toggle_columns(self):
        import desktop
        for name in ("showerror", "showwarning", "showinfo", "askyesno"):
            patch = mock.patch(f"tkinter.messagebox.{name}", return_value=True); patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch("app_runtime.data_dir", return_value=Path(self.folder.name)); patch.start(); self.addCleanup(patch.stop)
        import gc; self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy)
        app.server.set(self.url); app.password.set("admin12345"); app.login()
        app.client.select_company_year(self.company["id"], self.year); app.current_company = self.company; app.current_fiscal_year = int(self.year)
        app.main_screen(); app.select_main_tab(app.invoices_tab); app.update()
        tree = app.invoice_tree
        by_number = {tree.item(i, "values")[0]: i for i in tree.get_children()}
        tree.selection_set((by_number["N1"], by_number["N2"]))
        app.delete_selected_invoice()
        status = {r["invoice_number"]: r["status"] for r in app.invoice_rows.values()}
        self.assertEqual((status["N1"], status["N2"]), ("deleted", "deleted"))
        self.assertNotEqual(status["N0"], "deleted"); self.assertNotEqual(status["N3"], "deleted")
        toggles = tree._column_toggles
        self.assertEqual(set(toggles), {"branch", "kind", "debit", "credit"})
        toggles["branch"].set(False); toggles["debit"].set(False)
        # run the checkbutton command the way a click does
        for child in tree._search_bar.winfo_children():
            for box in child.winfo_children():
                if isinstance(box, tk.Checkbutton) and box.cget("text") in (tree._column_titles["branch"],): box.invoke(); box.invoke()
        shown = list(tree["displaycolumns"])
        self.assertNotIn("branch", shown); self.assertNotIn("debit", shown); self.assertIn("credit", shown)
        import desktop_layout
        self.assertEqual(sorted(desktop_layout.layout_settings()["hidden_columns"]["uploaded_data"]), ["branch", "debit"])


if __name__ == "__main__":
    unittest.main()
