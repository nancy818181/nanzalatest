"""2.9.95: one design system: buttons by role, white cards, inputs with a focus line, rows that fit a laptop screen."""
import unittest


class DesignTest(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.tk = tk; self.root = tk.Tk(); self.root.geometry("1366x768")
        except Exception as exc: self.skipTest(f"no screen: {exc}")

    def tearDown(self):
        self.root.destroy()

    def test_buttons_cards_inputs(self):
        tk = self.tk
        import desktop_theme
        from desktop_common import GOLD, LIGHT, NAVY
        page = tk.Frame(self.root, bg=LIGHT); page.pack(fill="both", expand=True)
        card = tk.LabelFrame(page, text="Invoice", bg=LIGHT); card.pack()
        label = tk.Label(card, text="Supplier", bg=LIGHT); label.pack()
        save = tk.Button(card, text="Save", bg=GOLD, fg=NAVY); save.pack()
        delete = tk.Button(card, text="Delete", bg="#8B1E1E", fg="white"); delete.pack()
        other = tk.Button(card, text="Export", bg=NAVY, fg="white"); other.pack()
        chip = tk.Button(card, text="status", bg="#2E7D5B"); chip.pack()
        entry = tk.Entry(card); entry.pack()
        desktop_theme.polish(page)
        self.assertEqual((save._saber_kind, delete._saber_kind, other._saber_kind), ("primary", "danger", "secondary"))
        self.assertFalse(hasattr(chip, "_saber_kind"))  # a colour chosen on purpose is kept
        self.assertEqual(card.cget("background").lower(), "#ffffff"); self.assertEqual(label.cget("background").lower(), "#ffffff")
        self.assertEqual(str(entry.cget("highlightcolor")).lower(), GOLD.lower())
        desktop_theme.polish(page)  # safe to run again
        self.assertEqual(save._saber_kind, "primary")

    def test_wide_rows_wrap(self):
        tk = self.tk
        import desktop_theme
        page = tk.Frame(self.root); page.pack(fill="both", expand=True)
        row = tk.Frame(page); row.pack(fill="x")
        for i in range(14): tk.Button(row, text=f"A long button name {i}", bg="#102A43").pack(side="left")
        long = tk.Label(page, text="x " * 400); long.pack()
        desktop_theme.polish(page); self.root.update()
        self.assertTrue(getattr(row, "_saber_flow", False))  # the row wraps onto more lines
        self.assertLessEqual(row.winfo_reqwidth(), 1366)
        self.assertGreater(int(str(long.cget("wraplength"))), 0)


if __name__ == "__main__":
    unittest.main()
