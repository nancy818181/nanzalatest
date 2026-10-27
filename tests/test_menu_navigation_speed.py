"""Regression tests for scoped lazy page decoration and empty invoice FX access."""
import unittest
from types import SimpleNamespace
from unittest import mock
import desktop

class MenuNavigationSpeedTest(unittest.TestCase):
    def test_each_builder_scopes_design_to_its_page(self):
        mappings = {
            "build_dashboard": "dashboard_tab", "build_invoices": "invoices_tab",
            "build_sales_invoice": "sales_tab", "build_manual": "manual_tab",
            "build_import": "import_tab", "build_parties": "parties_tab",
            "build_transactions": "transactions_tab",
            "build_purchases_expenses": "purchases_tab",
            "build_inventory": "inventory_tab", "build_payroll": "payroll_tab",
            "build_vat_return": "vat_tab", "build_journal": "journal_tab",
            "build_trial": "account_reports_tab",
            "build_statement": "account_reports_tab",
            "build_accounts": "account_reports_tab",
            "build_profit_loss": "pnl_tab",
            "build_financial_reports": "reports_tab",
            "build_settings": "settings_tab",
        }
        for method, attribute in mappings.items():
            with self.subTest(method=method):
                page = object()
                fallback = object()
                visited = []
                fake = SimpleNamespace(main_notebook=fallback,
                    setup_context_f2=lambda: None,
                    apply_hidden_tabs=lambda root=None: visited.append(root))
                setattr(fake, attribute, page)
                def builder(): pass
                builder.__name__ = method
                with mock.patch.object(desktop, "polish") as polish:
                    desktop.SaberApp._run_page_builder(fake, builder)
                polish.assert_called_once_with(page, fold=True)
                self.assertEqual(visited, [page])

    def test_unregistered_builder_falls_back_safely(self):
        fallback = object()
        visited = []
        fake = SimpleNamespace(main_notebook=fallback,
            setup_context_f2=lambda: None,
            apply_hidden_tabs=lambda root=None: visited.append(root))
        def extra_builder(): pass
        with mock.patch.object(desktop, "polish") as polish:
            desktop.SaberApp._run_page_builder(fake, extra_builder)
        polish.assert_called_once_with(fallback, fold=True)
        self.assertEqual(visited, [None])

    def test_empty_invoice_list_does_not_request_fx_history(self):
        from desktop_invoices import InvoicesMixin
        tree = SimpleNamespace(get_children=lambda: [],
            delete=lambda *a: None, tag_configure=lambda *a, **kw: None)
        client = SimpleNamespace(invoices=mock.Mock(return_value=[]),
            exchange_rates=mock.Mock(side_effect=AssertionError("FX should not be called")))
        setting = lambda v: SimpleNamespace(get=lambda: v)
        fake = SimpleNamespace(client=client, invoice_account_search=setting(""),
            view_currency=setting("All Currencies"),
            invoice_branch=setting("All Branches"),
            invoice_sort_by=setting("Date"),
            invoice_sort_order=setting("Descending"), invoice_tree=tree)
        InvoicesMixin.load_invoices(fake)
        client.exchange_rates.assert_not_called()
        self.assertEqual(fake.invoice_rows, {})

    def test_hidden_subtabs_remain_enforced_on_scoped_page(self):
        import tkinter as tk
        from tkinter import ttk
        import accounting_setup, desktop_common
        try: root = tk.Tk()
        except tk.TclError: self.skipTest("requires display")
        self.addCleanup(root.destroy)
        pages = [tk.Frame(root), tk.Frame(root)]
        books = []
        for page in pages:
            book = ttk.Notebook(page)
            book.add(tk.Frame(book), text="Production")
            book.add(tk.Frame(book), text="Other")
            books.append(book)
        fake = SimpleNamespace(main_tab_pages=pages, financial_notebook=None)
        with mock.patch.object(accounting_setup, "MODULES",
                               {"sample": ("ignored", "tab", "Production")}), \
             mock.patch.object(desktop_common, "hidden_view", return_value={"sample"}):
            desktop.SaberApp.apply_hidden_tabs(fake, pages[0])
            self.assertEqual(books[0].tab(books[0].tabs()[0], "state"), "hidden")
            self.assertNotEqual(books[1].tab(books[1].tabs()[0], "state"), "hidden")
            desktop.SaberApp.apply_hidden_tabs(fake)
            self.assertEqual(books[1].tab(books[1].tabs()[0], "state"), "hidden")


    def test_cached_rate_client_uses_read_only_route(self):
        from client import ApiClient
        client = ApiClient("http://127.0.0.1:1")
        with mock.patch.object(client, "request", return_value={"items":[]}) as request:
            client.exchange_rates(cached=True)
            request.assert_called_once_with("GET", "/api/exchange-rates?cached=1")
            request.reset_mock()
            client.exchange_rates()
            request.assert_called_once_with("GET", "/api/exchange-rates")

    def test_saved_rates_do_not_trigger_network(self):
        from database import Database
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory(prefix="nanza_nav_rate_") as folder:
            db = Database(Path(folder) / "synthetic.db")
            try:
                db.initialize("synthetic-password-2026")
                db.save_exchange_rate({"date_from":"01-10-2026","date_to":"01-10-2026",
                    "from_currency":"EUR","to_currency":"USD","rate":"1.2375"}, 1)
                with mock.patch.object(db, "sync_historical_exchange_rates", side_effect=AssertionError("online sync")), \
                     mock.patch.object(db, "_ensure_automatic_rates", side_effect=AssertionError("online check")):
                    rates = db.list_exchange_rates(refresh=False)
                self.assertTrue(any(r["from_currency"]=="EUR" and r["to_currency"]=="USD"
                                    and abs(r["rate"]-1.2375)<0.000001 for r in rates))
            finally:
                db.release()

    def test_tree_column_fit_deduplicates_repeated_measurements(self):
        import tkinter as tk
        from tkinter import ttk, font as tkfont
        try: root = tk.Tk()
        except tk.TclError: self.skipTest("Tk display unavailable")
        self.addCleanup(root.destroy)
        root.geometry("310x200")
        tree = ttk.Treeview(root, columns=("code", "note"), show="headings")
        tree.pack(fill="both", expand=True)
        tree.heading("code", text="Code")
        tree.heading("note", text="Description")
        tree.column("code", width=70)
        tree.column("note", width=70)
        for n in range(500): tree.insert("", "end", iid=str(n), values=("123456789","Repeated description"))
        actual = tkfont.Font.measure
        calls = []
        def measure(font, label, *args, **kwargs):
            calls.append((str(font),str(label)))
            return actual(font,label,*args,**kwargs)
        with mock.patch.object(tkfont.Font, "measure", measure):
            root.update_idletasks()
        self.assertLessEqual(len(calls),20)
        self.assertEqual(len(tree.get_children()),500)

if __name__ == "__main__":
    unittest.main()
