"""2.9.120: big companies stay fast - no work that grows with the square of the number of lines."""
import tests_setup  # noqa: F401
import unittest
from unittest import mock

try:
    import tkinter as tk
    from tkinter import ttk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except (ImportError, RuntimeError, tk.TclError):
    HAVE_DISPLAY = False

import desktop_common  # noqa: F401  installs the table helpers


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class BigTablesTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)

    def test_rows_are_not_counted_again_at_each_insert(self):
        tree = ttk.Treeview(self.root, columns=("a",), show="headings"); tree.heading("a", text="A")  # the column fit follows this table
        calls = []
        real = ttk.Treeview.get_children
        with mock.patch.object(ttk.Treeview, "get_children", lambda self, item=None: calls.append(1) or real(self, item)):
            for n in range(3000): tree.insert("", "end", values=(n,))
        self.assertLessEqual(len(calls), 2)
        self.assertEqual(len(tree.get_children()), 3000)
        tree.delete(*tree.get_children()); tree.insert("", "end", values=("x",))
        self.assertEqual(tree.__dict__["_fit_rows"], 1)  # counted again after the table was cleared

    def test_fill_tree_inserts_every_row(self):
        tree = ttk.Treeview(self.root, columns=("a",), show="headings")
        desktop_common.fill_tree(tree, [(("", "end"), {"values": (n,)}) for n in range(5000)], first=100, step=700)
        self.assertEqual(len(tree.get_children()), 100)  # the first rows at once
        import time
        for _ in range(400):
            self.root.update(); time.sleep(0.005)
            if len(tree.get_children()) == 5000: break
        self.assertEqual(len(tree.get_children()), 5000)
        desktop_common.fill_tree(tree, [], first=100)  # a new fill stops the old one


class RatesLookupTest(unittest.TestCase):
    def test_same_rate_as_before(self):
        from desktop_sales_invoice import SalesInvoiceMixin
        rates = [{"from_currency": "EUR", "to_currency": "USD", "rate": "1.1"}, {"from_currency": "USD", "to_currency": "LBP", "rate": "89500"},
                 {"from_currency": "EUR", "to_currency": "USD", "rate": "1.2"}]
        app = type("App", (), {})(); convert = SalesInvoiceMixin.exchange_equivalents
        self.assertEqual(convert(app, 10, "EUR", rates), (None if False else 10 * 1.1 * 89500, 10 * 1.1))
        self.assertEqual(convert(app, 89500, "LBP", rates), (89500, 1.0))
        self.assertEqual(convert(app, 5, "EUR", rates)[1], 5 * 1.1)  # the first row of the list, as before


if __name__ == "__main__":
    unittest.main()
