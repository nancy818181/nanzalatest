"""2.9.118: the program in Arabic, right to left (Language = ar); English stays exactly as it was."""
import tests_setup  # noqa: F401  the sample company of the tests
import re
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import arabic_texts
import arabic_ui

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    _probe = tk.Tk(); _probe.destroy(); HAVE_DISPLAY = True
except (ImportError, RuntimeError, tk.TclError):
    HAVE_DISPLAY = False


class TextsTest(unittest.TestCase):
    def test_the_list_is_sound(self):
        self.assertGreater(len(arabic_texts.AR), 1600)
        for english, arabic in arabic_texts.AR.items():
            self.assertTrue(arabic_ui.has_arabic(arabic) or not re.search("[A-Za-z]", arabic) or arabic_ui.has_arabic(english), english)
            self.assertEqual(english.count("{"), arabic.count("{"), english)
            self.assertEqual(english.count("\n"), arabic.count("\n"), english)

    def test_translate(self):
        t = arabic_ui.translate
        self.assertEqual(t("Save"), arabic_texts.AR["Save"])
        self.assertEqual(t("SALES"), arabic_texts.AR["Sales"])  # titles in capitals
        self.assertEqual(t("▾  SALES"), "▾  " + arabic_texts.AR["Sales"])  # marks around stay
        self.assertEqual(t("Amount:"), arabic_texts.AR["Amount"] + ":")
        self.assertEqual(t("Saved | تم"), "تم")  # the Arabic half of a two-language text
        self.assertEqual(t("Report: Cash Flow"), "تقرير: " + t("Cash Flow"))
        self.assertEqual(t("Fiscal Year 2026"), "السنة المالية 2026")
        self.assertEqual(t("SAL-2026-000001"), "SAL-2026-000001")  # numbers and codes stay
        self.assertEqual(arabic_ui.english(arabic_texts.AR["Refresh"]), "Refresh")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class RightToLeftTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.addCleanup(self.root.destroy)
        self.addCleanup(arabic_ui.switch, self.root, "en")

    def test_english_unchanged(self):
        arabic_ui.switch(self.root, "en")
        frame = tk.Frame(self.root); frame.pack()
        label = tk.Label(frame, text="Save", anchor="w"); label.pack(side="left", padx=(2, 9))
        box = tk.Frame(self.root); box.pack(); tk.Label(box, text="Date").grid(row=0, column=0, sticky="w")
        self.assertEqual(label.cget("text"), "Save"); self.assertEqual(label.cget("anchor"), "w")
        info = self.root.tk.splitlist(self.root.tk.call("pack", "info", label))
        self.assertEqual(str(dict(zip(info[0::2], info[1::2]))["-side"]), "left")
        self.assertEqual(int(box.grid_slaves()[0].grid_info()["column"]), 0)
        info = self.root.tk.splitlist(self.root.tk.call("grid", "info", box.grid_slaves()[0]))
        self.assertEqual(int(str(dict(zip(info[0::2], info[1::2]))["-column"])), 0)

    def test_arabic_mirrors_and_translates(self):
        arabic_ui.switch(self.root, "ar")
        frame = tk.Frame(self.root); frame.pack(fill="x")
        label = tk.Label(frame, text="Save", anchor="w"); label.pack(side="left", padx=(2, 9))
        self.assertEqual(label.cget("text"), arabic_texts.AR["Save"])
        self.assertEqual(label.cget("anchor"), "e")
        info = self.root.tk.splitlist(self.root.tk.call("pack", "info", label)); real = dict(zip(info[0::2], info[1::2]))
        self.assertEqual(str(real["-side"]), "right")  # on screen: from the right
        self.assertEqual(label.pack_info()["side"], "left")  # what the program asks: as it placed it
        box = tk.Frame(self.root); box.pack(fill="x")
        first = tk.Label(box, text="Date"); first.grid(row=0, column=0, sticky="w")
        second = tk.Entry(box); second.grid(row=0, column=1, columnspan=2, sticky="ew")
        box.grid_columnconfigure(1, weight=1)
        self.assertEqual(int(first.grid_info()["column"]), 0); self.assertEqual(first.grid_info()["sticky"], "w")
        self.assertEqual(box.grid_slaves(row=0, column=0), [first])
        self.root.update()
        self.assertGreater(first.winfo_x(), second.winfo_x())  # the first column is on the right
        notebook = ttk.Notebook(self.root); page = tk.Frame(notebook); notebook.add(page, text="Settings"); notebook.pack()
        self.assertEqual(notebook.tab(page, "text"), "Settings")
        self.assertEqual(self.root.tk.call(notebook._w, "tab", page, "-text"), arabic_texts.AR["Settings"])
        tree = ttk.Treeview(self.root, columns=("a", "b", "c"), show="headings")
        self.assertEqual(list(tree["displaycolumns"]), ["c", "b", "a"])
        tree.configure(displaycolumns=["a", "c"]); self.assertEqual(list(tree["displaycolumns"]), ["c", "a"])
        tree.heading("a", text="Amount"); self.assertEqual(tree.heading("a", "text"), arabic_texts.AR["Amount"])
        shown = []
        with mock.patch.dict(arabic_ui._real, show=lambda title, message, *a, **k: shown.append((title, message)) or "ok"):
            messagebox.showinfo("Saved", "Save")
        self.assertEqual(shown, [(arabic_texts.AR["Saved"], arabic_texts.AR["Save"])])
        arabic_ui.switch(self.root, "en")
        plain = tk.Label(self.root, text="Save"); plain.pack(side="left")
        self.assertEqual(plain.cget("text"), "Save"); self.assertEqual(plain.pack_info()["side"], "left")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class ArabicScreensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from client import ApiClient
        from server import run_server
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        database = Path(cls.folder.name) / "SaberAccounting" / "saber.db"; database.parent.mkdir(parents=True)
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database),
                                                     "admin_password": "admin12345"}, daemon=True).start()
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try: ApiClient(cls.url).login("admin", "admin12345"); break
            except (OSError, RuntimeError, ValueError): time.sleep(0.1)
        api = ApiClient(cls.url); api.login("admin", "admin12345"); cls.company = api.companies()[0]

    def test_every_screen_opens_in_arabic(self):
        import desktop
        messages = []
        for name in ("showerror", "showwarning", "showinfo"):
            patch = mock.patch(f"tkinter.messagebox.{name}", side_effect=lambda *a, n=name, **k: messages.append((n, a)) or True)
            patch.start(); self.addCleanup(patch.stop)
        import gc; self.addCleanup(gc.collect)
        app = desktop.SaberApp(); self.addCleanup(app.destroy); self.addCleanup(arabic_ui.switch, app, "en")
        app.server.set(self.url); app.password.set("admin12345"); app.language.set("ar"); app.login()
        self.assertTrue(arabic_ui.active())
        year = self.company["years"][0]["year"]
        app.client.select_company_year(self.company["id"], year); app.current_company = self.company; app.current_fiscal_year = int(year)
        app.main_screen(); app.update()
        for page in app.main_tab_pages:
            app.select_main_tab(page); app.update()
        self.assertEqual(messages, [])
        self.assertIn("sales_tab", app._page_attributes)
        self.assertEqual(app.tab_names[app._page_attributes.index("sales_tab")], "Sales Invoice")  # the program keeps English names
        texts = []
        stack = [app]
        while stack:
            widget = stack.pop(); stack.extend(widget.winfo_children())
            if isinstance(widget, (tk.Button, tk.Label)):
                texts.append(str(widget.cget("text")))
        arabic = [t for t in texts if arabic_ui.has_arabic(t)]
        self.assertGreater(len(arabic), 300)
        # the English / عربي button: same screen, other language
        app.select_main_tab(app.main_tab_pages[app._page_attributes.index("sales_tab")]); app.update()
        app.switch_language("en"); app.update()
        self.assertFalse(arabic_ui.active()); self.assertEqual(app.language.get(), "en")
        self.assertEqual(str(app.main_notebook.select()), str(app.main_tab_pages[app._page_attributes.index("sales_tab")]))
        app.switch_language("ar"); app.update(); self.assertTrue(arabic_ui.active())
        self.assertEqual(messages, [])
        app.login_screen(); self.assertFalse(arabic_ui.active())  # signing out: English again


if __name__ == "__main__":
    unittest.main()
