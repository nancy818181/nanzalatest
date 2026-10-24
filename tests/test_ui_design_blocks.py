"""2.9.134: the layout helpers of desktop_design run their Python logic (no Tk needed: a minimal stand-in for tkinter is used).
This checks names, arguments and control flow - NOT how the screen looks; that needs the real Tk on Windows."""
import importlib
import sys
import types
import unittest
from pathlib import Path


class _TclError(Exception):
    pass


class _Widget:
    def __init__(self, master=None, **options):
        self.master = master; self.options = dict(options); self.kids = []; self._after = []
        if isinstance(master, _Widget): master.kids.append(self)

    def __getattr__(self, name):
        if name.startswith("_"): raise AttributeError(name)  # like a real widget: unknown private attributes do not exist
        return lambda *a, **k: None

    def cget(self, key): return self.options.get(key, "")
    def configure(self, **options): self.options.update(options)
    config = configure
    def winfo_children(self): return list(self.kids)
    def winfo_exists(self): return 1
    def winfo_reqwidth(self): return 100
    def winfo_width(self): return 300
    def winfo_x(self): return 0
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_height(self): return 20
    def winfo_manager(self): return "pack"
    def pack_info(self): return {"padx": 4}
    def destroy(self): self.kids = []
    def xview(self): return (0.0, 0.5)
    def after(self, ms, func=None): return None


class _Style:
    def __init__(self, *_a, **_k): pass
    def configure(self, *_a, **_k): return None
    layout = map = theme_use = configure


class _Notebook(_Widget):
    def __init__(self, master=None, titles=(), **options):
        super().__init__(master, **options)
        self._tabs = {f".t{i}": {"text": t, "state": "normal"} for i, t in enumerate(titles)}; self._current = ".t0"
    def tabs(self): return list(self._tabs)
    def tab(self, tab, option=None): return self._tabs[tab][option] if option else dict(self._tabs[tab])
    def select(self, tab=None):
        if tab is None: return self._current
        self._current = tab


def _install_fakes():
    tk = types.ModuleType("tkinter"); ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Canvas", "Menu", "Toplevel", "Entry"): setattr(tk, name, type(name, (_Widget,), {}))
    tk.Misc = _Widget; tk.TclError = _TclError; tk.ttk = ttk
    ttk.Notebook = _Notebook; ttk.Style = _Style
    ttk.Combobox = type("Combobox", (_Widget,), {}); ttk.Treeview = type("Treeview", (_Widget,), {})
    saved = {k: sys.modules.get(k) for k in ("tkinter", "tkinter.ttk", "desktop_design")}
    sys.modules["tkinter"], sys.modules["tkinter.ttk"] = tk, ttk; sys.modules.pop("desktop_design", None)
    return saved


class DesignBlocksTest(unittest.TestCase):
    def setUp(self):
        self.saved = _install_fakes()
        self.addCleanup(self._restore)
        import nanza_paths  # noqa: F401
        self.design = importlib.import_module("desktop_design")

    def _restore(self):
        for key, module in self.saved.items():
            if module is None: sys.modules.pop(key, None)
            else: sys.modules[key] = module

    def test_cards_banners_chips_tiles_build(self):
        import tkinter as tk
        root = tk.Frame()
        outer, body = self.design.card(root, "Title", "subtitle")
        self.assertIsNotNone(outer); self.assertIsNotNone(body)
        banner = self.design.banner(root, "text", "warning"); banner.set("other", "success"); banner.set("again")
        self.assertEqual(banner.cget("text"), "again")
        self.design.chip(root, "Taxable", "warning"); self.design.chip(root, "x", "no-such-kind")
        tile, number = self.design.stat_tile(root, "NET", "1.00", "success"); self.assertIsNotNone(tile)
        self.design.divider(root); self.design.caption(root, "c", bg="white")

    def test_tab_bar_is_for_many_tabs_only_and_follows_the_notebook(self):
        import tkinter as tk
        from tkinter import ttk
        few = ttk.Notebook(tk.Frame(), titles=["a", "b"])
        self.assertIsNone(self.design.tab_bar(few))
        main = ttk.Notebook(tk.Frame(), titles=[f"Page {i}" for i in range(12)])
        main._saber_no_tabbar = True  # the left sidebar already navigates these top-level pages
        self.assertIsNone(self.design.tab_bar(main))
        self.assertFalse(hasattr(main, "_saber_tabbar"))
        many = ttk.Notebook(tk.Frame(), titles=[f"Tab {i}" for i in range(12)])
        bar = self.design.tab_bar(many)
        self.assertIsNotNone(bar); self.assertIs(self.design.tab_bar(many), bar)  # once only
        self.assertEqual(len(bar.buttons), 12)
        many._tabs[".t3"]["state"] = "hidden"; bar.rebuild(); self.assertEqual(len(bar.buttons), 11)
        many._tabs[".new"] = {"text": "Late tab", "state": "normal"}; bar.rebuild(); self.assertEqual(len(bar.buttons), 12)
        bar.scroll(1); bar.scroll(-1); bar.refresh_arrows(); bar.menu()

    def test_every_new_ui_module_compiles(self):
        root = Path(__file__).resolve().parents[1] / "nanza"
        for name in ("ui/desktop_design.py", "ui/desktop_payroll.py", "ui/desktop_theme.py"):
            compile((root / name).read_text(encoding="utf-8"), name, "exec")


if __name__ == "__main__":
    unittest.main()
