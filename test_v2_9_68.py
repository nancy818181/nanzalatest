"""2.9.68: Uploaded Data - Branch and Type tick lists, D / C ticks."""
import tests_setup  # noqa: F401  2.9.74: the sample company of the tests (a new installation has none)
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class UploadedDataFiltersTest(unittest.TestCase):
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
        api.select_company_year(cls.company["id"], cls.year); api.save_branch({"name": "Jbeil"})
        api.import_invoices([{"invoice_number": f"N{i}", "invoice_date": f"0{i + 1}-02-{cls.year}", "party_name": f"P{i}", "kind": kind, "entry_type": kind,
                              "currency": "USD", "subtotal": 100, "vat": 0, "total": 100, "branch": branch, "status": "posted"}
                             for i, (kind, branch) in enumerate((("sales", "Head Office"), ("purchases", "Jbeil"), ("purchases", "Head Office"), ("expenses", "Jbeil")))], False)

    def test_filters(self):
        import desktop
        for name in ("showerror", "showwarning", "showinfo"):
            patch = mock.patch(f"tkinter.messagebox.{name}", return_value=True); patch.start(); self.addCleanup(patch.stop)
        import gc; self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy)
        app.server.set(self.url); app.password.set("admin12345"); app.login()
        app.client.select_company_year(self.company["id"], self.year); app.current_company = self.company; app.current_fiscal_year = int(self.year)
        app.main_screen(); app.select_main_tab(app.invoices_tab); app.update()
        numbers = lambda: sorted(app.invoice_tree.item(i, "values")[0] for i in app.invoice_tree.get_children())
        self.assertEqual(numbers(), ["N0", "N1", "N2", "N3"])
        self.assertEqual(tuple(app.invoice_type_box["values"]), ("All", "expenses", "purchases", "sales"))
        app.invoice_branch.set("Jbeil"); app.load_invoices(); self.assertEqual(numbers(), ["N1", "N3"])
        app.invoice_branch.set("All"); app.invoice_type_filter.set("purchases; sales"); app.load_invoices(); self.assertEqual(numbers(), ["N0", "N1", "N2"])
        app.invoice_type_filter.set("All"); app.invoice_show_credit.set(False); app.load_invoices(); self.assertEqual(numbers(), ["N0"])
        app.invoice_show_credit.set(True); app.invoice_show_debit.set(False); app.load_invoices(); self.assertEqual(numbers(), ["N1", "N2", "N3"])


if __name__ == "__main__":
    unittest.main()
