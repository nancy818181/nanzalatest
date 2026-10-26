"""Purchase Invoice header (26-10-2026): one aligned grid of label | field pairs, sized to the visible page width.

Checked on the real program window (skipped without a display): every header control is shown inside the window,
each label is level with its field and on the correct side (left in English, right in Arabic), inputs share one height,
the buttons of each action row share one height, and a purchase typed through these fields still saves balanced."""
import tests_setup  # noqa: F401
import secrets
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

from client import ApiClient
from server import run_server

HEADER = ("Supplier", "Supplier Invoice No.", "Date", "Due", "Currency", "Type", "Document",
          "Cost / Asset A/C", "VAT A/C", "Paid", "Paid from A/C")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display for the program window")
class PurchaseHeaderLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.password = secrets.token_urlsafe(24)
        database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database),
                                                    "admin_password": cls.password}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: ApiClient(cls.url).login("admin", cls.password); break
            except Exception: time.sleep(0.1)
        api = ApiClient(cls.url); api.login("admin", cls.password); cls.company = api.companies()[0]

    @classmethod
    def tearDownClass(cls):
        import gc; gc.collect(); cls.folder.cleanup()

    def open(self, language="en"):
        self.messages = []
        for name in ("showerror", "showwarning", "showinfo", "askyesno"):
            patch = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, n=name, **k: self.messages.append((n, a)) or True)
            patch.start(); self.addCleanup(patch.stop)
        import desktop, arabic_ui, gc
        self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy); self.addCleanup(arabic_ui.switch, app, "en")
        app.server.set(self.url); app.password.set(self.password); app.language.set(language); app.login()
        year = self.company["years"][0]["year"]
        app.client.select_company_year(self.company["id"], year); app.current_company = self.company; app.current_fiscal_year = int(year)
        app.geometry("1366x728+0+0"); app.update(); app.main_screen(); app.update()
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("purchases_tab")]); app.purchase_notebook.select(0)
        for _ in range(4): app.update_idletasks(); app.update()
        return app

    def header(self, app):
        widgets = app.purchase_form["header_widgets"]
        labels = {}
        for label in widgets["Supplier"].master.winfo_children():
            if isinstance(label, tk.Label): labels[label] = label
        import arabic_ui
        shown = {str(label.cget("text")): label for label in labels}
        # several English texts share one Arabic text, so look each label up by the text it should show
        by_text = {text: shown.get(arabic_ui.translate(text) if arabic_ui.active() else text) for text in HEADER}
        return widgets, by_text

    def check_layout(self, app, rtl):
        widgets, labels = self.header(app)
        self.assertEqual(sorted(widgets), sorted(HEADER))
        left, right = app.winfo_rootx(), app.winfo_rootx() + app.winfo_width()
        heights = set()
        for text in HEADER:
            with self.subTest(field=text):
                field, label = widgets[text], labels[text]
                for widget in (field, label):
                    self.assertTrue(widget.winfo_ismapped(), text)
                    self.assertGreaterEqual(widget.winfo_rootx(), left - 1, text)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right + 1, text)
                self.assertLessEqual(label.winfo_reqwidth(), label.winfo_width() + 1, f"label clipped: {text}")
                middle = lambda w: w.winfo_rooty() + w.winfo_height() / 2
                self.assertLessEqual(abs(middle(label) - middle(field)), 2, f"label not level: {text}")
                gap = (label.winfo_rootx() - field.winfo_rootx() - field.winfo_width()) if rtl else \
                      (field.winfo_rootx() - label.winfo_rootx() - label.winfo_width())
                self.assertTrue(0 <= gap <= 24, f"{text}: label {gap}px from its field (wrong side if negative)")
                heights.add(field.winfo_height())
        self.assertLessEqual(max(heights) - min(heights), 2, f"input heights differ: {sorted(heights)}")
        save = next(b for b in self.buttons(app.purchase_form["pdf_label"].master.master) if self.english(b) == "Save Purchase")
        row = [b for b in save.master.winfo_children() if isinstance(b, tk.Button) and b.winfo_ismapped()]
        self.assertEqual(len({b.winfo_height() for b in row}), 1, [(self.english(b), b.winfo_height()) for b in row])

    def english(self, widget):
        import arabic_ui
        return arabic_ui.english(str(widget.cget("text")))

    def buttons(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Button): yield child
            yield from self.buttons(child)

    def test_english_header_is_aligned_and_a_purchase_still_saves(self):
        app = self.open("en")
        self.check_layout(app, rtl=False)
        widgets, _labels = self.header(app)
        v = app.purchase_form["vars"]
        widgets["Supplier"].set("Grid Supplier SARL")
        widgets["Supplier Invoice No."].insert(0, "GRID-1")
        widgets["Currency"].set("USD"); widgets["Type"].set("Purchases"); widgets["Document"].set("Invoice")
        widgets["Document"].event_generate("<<ComboboxSelected>>")
        v["taxable"].set("100"); app.purchase_amounts_changed("taxable"); app.update()
        app.save_purchase(); app.update()
        self.assertFalse([m for m in self.messages if m[0] in ("showerror", "showwarning")], self.messages)
        saved = [i for i in app.client.invoices() if i.get("invoice_number") == "GRID-1"]
        self.assertEqual(len(saved), 1, saved)
        self.assertEqual(saved[0]["party_name"], "Grid Supplier SARL")
        self.assertEqual(round(float(saved[0]["total"]), 2), 111.00)
        trial = app.client.trial_balance()
        rows = trial.get("items", trial) if isinstance(trial, dict) else trial
        debit = sum(float(r.get("debit") or 0) for r in rows); credit = sum(float(r.get("credit") or 0) for r in rows)
        self.assertAlmostEqual(debit, credit, places=2)

    def test_arabic_header_puts_each_label_right_of_its_field(self):
        app = self.open("ar")
        self.check_layout(app, rtl=True)

    def test_icon_and_text_buttons_of_a_row_get_one_height(self):
        """Windows draws an icon button 2 px lower than a text one with the same padding (CI 26-10-2026: 28 vs 30)."""
        from desktop_purchases import PurchasesMixin
        root = tk.Tk(); self.addCleanup(root.destroy)
        row = tk.Frame(root); row.pack()
        icon = tk.PhotoImage(master=root, width=12, height=12)
        short = tk.Button(row, text="New", image=icon, compound="left", pady=1); short.pack(side="left")
        tall = tk.Button(row, text="Cancel Purchase", pady=6); tall.pack(side="left")
        lower = tk.Button(row, text="Auto Calculate", pady=2); lower.pack(side="left")
        root.update()
        self.assertGreater(tall.winfo_reqheight(), short.winfo_reqheight())
        PurchasesMixin._even_button_heights(row); root.update()
        self.assertEqual({b.winfo_height() for b in (short, tall, lower)}, {tall.winfo_height()})

    def test_narrow_window_stacks_pairs_instead_of_hiding_fields(self):
        app = self.open("en")
        app.geometry("1024x700")
        for _ in range(4): app.update_idletasks(); app.update()
        self.check_layout(app, rtl=False)


if __name__ == "__main__":
    unittest.main()
