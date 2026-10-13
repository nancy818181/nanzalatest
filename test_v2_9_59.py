"""2.9.59 layout: DD-MM-YYYY dates, toolbars that wrap, amounts on the right, one palette."""
import re
import unittest
from pathlib import Path

import desktop_common as dc

HERE = Path(__file__).resolve().parent


class DateDisplayTests(unittest.TestCase):
    def test_display_cells_turns_iso_dates_around(self):
        self.assertEqual(dc.display_cells(("2026-03-05", "x", 5)), ("05-03-2026", "x", 5))
        self.assertEqual(dc.display_cells(["31-12-2025"]), ["31-12-2025"])

    def test_amount_columns(self):
        for key, label in (("debit", "Debit"), ("credit", "Credit"), ("total", "Total"), ("vat", "VAT"), ("balance", "Balance")):
            self.assertTrue(dc.is_amount_column(key, label), key)
        for key, label in (("date", "Date"), ("party", "Customer / Supplier"), ("account", "Account")):
            self.assertFalse(dc.is_amount_column(key, label), key)


class TkLayoutTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try: self.root = tk.Tk()
        except tk.TclError: self.skipTest("no display")
        self.tk = tk

    def tearDown(self):
        self.root.destroy()

    def test_tree_shows_dd_mm_but_program_reads_original(self):
        from tkinter import ttk
        tree = ttk.Treeview(self.root, columns=("date", "amount"))
        iid = tree.insert("", "end", values=("2026-03-05", "1,000.00"))
        shown = self.root.tk.splitlist(self.root.tk.call(str(tree), "item", iid, "-values"))
        self.assertEqual(shown[0], "05-03-2026")
        self.assertEqual(tree.item(iid, "values")[0], "2026-03-05")
        self.assertEqual(tree.set(iid, "date"), "2026-03-05")
        tree.set(iid, "date", "2025-12-31")
        self.assertEqual(tree.item(iid, "values")[0], "2025-12-31")

    def test_toolbar_wraps_instead_of_cutting_off(self):
        self.root.geometry("500x200")
        frame = self.tk.Frame(self.root); frame.pack(fill="x")
        buttons = [self.tk.Button(frame, text=f"Long button number {i}") for i in range(8)]
        for button in buttons: button.pack(side="left", padx=4)
        dc.flow_toolbar(frame)
        for _ in range(6): self.root.update()
        self.assertLessEqual(max(b.winfo_x() + b.winfo_width() for b in buttons), frame.winfo_width() + 1)
        self.assertGreater(len({b.winfo_y() for b in buttons}), 1)


class PaletteTests(unittest.TestCase):
    def test_one_palette(self):
        for name in ("desktop_brains_common", "desktop_dimensions", "desktop_final", "desktop_inventory", "desktop_stage3_common", "desktop_v22"):
            text = (HERE / f"{name}.py").read_text(encoding="utf-8")
            match = re.search(r'NAVY\s*,\s*GOLD\s*,\s*LIGHT\s*=\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"', text)
            if match: self.assertEqual(match.groups(), ("#102A43", "#B78B45", "#F4F7FA"), name)


if __name__ == "__main__":
    unittest.main()
