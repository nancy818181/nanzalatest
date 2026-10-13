"""Filters where any combination can be chosen (2.9.50): the 1st and the 3rd, two, five ... or All.

The variable keeps readable text: "All", one value, or several values separated by "; ". chosen_values() turns that
text back into the list of values (an empty list means All), so a filter that used to hold one value keeps working.

2.9.54: the widget keeps only the NAME of the Tk variable (never the Python variable object) and the pick list uses
no Tk variables. Python objects that hold Tk variables inside reference cycles can be freed by the garbage collector
on the data-service thread, which stops the program ("main thread is not in main loop").
"""
from __future__ import annotations
import logging

import tkinter as tk
from tkinter import ttk

SEPARATOR = "; "
ALL = "All"


def chosen_values(text):
    text = str(text or "").strip()
    if not text or text == ALL: return []
    return [part.strip() for part in text.split(SEPARATOR.strip()) if part.strip() and part.strip() != ALL]


def matches(value, text):
    wanted = chosen_values(text)
    return not wanted or str(value or "").strip().casefold() in {w.casefold() for w in wanted}


class MultiSelect(tk.Frame):
    """Looks like a drop-down; opens a list where several lines can be ticked, with a search box, All / Clear and OK."""

    def __init__(self, master, variable, values=(), width=16, on_change=None, title="Choose", before_open=None, **options):
        super().__init__(master, bg=options.pop("bg", master.cget("bg") if hasattr(master, "cget") else None))
        self._var_name = str(variable); self.values = [v for v in values if v not in ("", ALL)]; self.on_change = on_change; self.title = title; self.before_open = before_open
        if not self.text(): self.setvar(self._var_name, ALL)
        self.entry = ttk.Entry(self, textvariable=self._var_name, width=width, state="readonly", cursor="hand2")
        self.entry.pack(side="left")
        self.button = tk.Button(self, text="▾", command=self.open, border=0, padx=4, cursor="hand2")
        self.button.pack(side="left")
        self.entry.bind("<Button-1>", lambda _e: self.open())
        self.entry.bind("<Return>", lambda _e: self.open()); self.entry.bind("<space>", lambda _e: self.open())
        self.popup = None

    def text(self):
        try: return str(self.getvar(self._var_name) or "")
        except tk.TclError: return ""

    # Combobox-like access: box["values"] = [...]
    def __setitem__(self, key, value):
        if key == "values": self.values = [str(v) for v in value if str(v) not in ("", ALL)]
        else: super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "values": return tuple([ALL] + self.values)
        return super().__getitem__(key)

    def set_choices(self, chosen):
        chosen = [c for c in chosen if c]
        self.setvar(self._var_name, ALL if not chosen or len(chosen) == len(self.values) else SEPARATOR.join(chosen))
        if self.on_change: self.on_change()

    def open(self):
        if self.popup is not None and self.popup.winfo_exists(): self.popup.lift(); return "break"
        if self.before_open:  # 2.9.62: e.g. reload the list of departments / projects / branches
            try: self.before_open(self)
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        popup = tk.Toplevel(self); self.popup = popup; popup.title(self.title); popup.transient(self.winfo_toplevel())
        popup.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height()}")
        ticked = {v for v in self.values if v.casefold() in {c.casefold() for c in chosen_values(self.text())}}
        top = tk.Frame(popup); top.pack(fill="x", padx=6, pady=(6, 2))
        tk.Label(top, text="Search").pack(side="left"); search = ttk.Entry(top, width=24); search.pack(side="left", padx=4)
        holder = tk.Frame(popup); holder.pack(fill="both", expand=True, padx=6)
        listbox = tk.Listbox(holder, selectmode="multiple", width=40, height=min(14, max(3, len(self.values))), exportselection=False, activestyle="none")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=listbox.yview); listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        shown = []
        def remember():
            for index, value in enumerate(shown):
                if listbox.selection_includes(index): ticked.add(value)
                else: ticked.discard(value)
        def fill(_event=None):
            if shown: remember()
            query = search.get().strip().casefold()
            shown[:] = [v for v in self.values if not query or query in v.casefold()]
            listbox.delete(0, "end")
            for index, value in enumerate(shown):
                listbox.insert("end", value)
                if value in ticked: listbox.selection_set(index)
        search.bind("<KeyRelease>", fill); fill()
        if not self.values: listbox.insert("end", "Nothing to choose yet")
        def tick(state):
            listbox.selection_set(0, "end") if state else listbox.selection_clear(0, "end")
        def done(_event=None):
            remember(); self.set_choices([v for v in self.values if v in ticked]); popup.destroy()
        def no_filter():
            self.set_choices([]); popup.destroy()
        buttons = tk.Frame(popup); buttons.pack(fill="x", padx=6, pady=6)
        tk.Button(buttons, text="Tick all", command=lambda: tick(True)).pack(side="left")
        tk.Button(buttons, text="Clear", command=lambda: tick(False)).pack(side="left", padx=4)
        tk.Button(buttons, text="OK", command=done, width=8).pack(side="right")
        tk.Button(buttons, text="All (no filter)", command=no_filter).pack(side="right", padx=4)
        popup.bind("<Escape>", lambda _e: popup.destroy()); popup.bind("<Return>", done)
        search.focus_set()
        return "break"
