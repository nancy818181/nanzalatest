"""2.9.134: small building blocks for a calmer, clearer layout (cards, section headers, banners, status chips, stat tiles).

Every function only creates ordinary Tk widgets with the colours of desktop_theme (navy / gold / light grey-blue), so the
design system of 2.9.94-2.9.116 (polish(), fold_toolbars(), the Arabic mirror) keeps working on them unchanged.
Nothing here touches data: it is layout only."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

FONT = "Segoe UI"
NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
CARD, BORDER, MUTED = "#FFFFFF", "#D5DEE8", "#5F6B76"
# kind -> (background, text colour, edge colour)
TONES = {
    "info":    ("#EAF2FB", "#1D4E89", "#C5D9EE"),
    "warning": ("#FBF1DC", "#8A5A00", "#EBD3A0"),
    "success": ("#E4F3EC", "#1F6B4B", "#BFE0CF"),
    "danger":  ("#FBE9E9", "#8B1E1E", "#EBC3C3"),
    "neutral": ("#EEF2F6", "#33475B", "#D5DEE8"),
}
log = logging.getLogger("saber.design")


def card(parent, title="", subtitle="", padx=14, pady=10):
    """A white card with a thin border and an optional title line. Returns (outer, body): pack/grid `outer`, put widgets in `body`."""
    outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
    if title:
        head = tk.Frame(outer, bg=CARD); head.pack(fill="x", padx=padx, pady=(pady, 2))
        tk.Frame(head, bg=GOLD, width=3, height=16).pack(side="left", padx=(0, 8))  # the gold marker of the design system
        tk.Label(head, text=title, bg=CARD, fg=NAVY, font=(FONT, 11, "bold"), anchor="w").pack(side="left")
        if subtitle: tk.Label(head, text=subtitle, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w").pack(side="left", padx=(12, 0))
    body = tk.Frame(outer, bg=CARD); body.pack(fill="both", expand=True, padx=padx, pady=(4, pady))
    return outer, body


def panel(parent, title="", subtitle="", bg=LIGHT, padx=14, pady=10):
    """Like card(), but the body keeps the page colour (bg), so older helpers that paint their own LIGHT background (department /
    project selectors, tick boxes) sit on it without a colour clash. Returns (outer, body)."""
    outer = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
    if title:
        head = tk.Frame(outer, bg=bg); head.pack(fill="x", padx=padx, pady=(pady, 2))
        tk.Frame(head, bg=GOLD, width=3, height=16).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, bg=bg, fg=NAVY, font=(FONT, 11, "bold"), anchor="w").pack(side="left")
        if subtitle: tk.Label(head, text=subtitle, bg=bg, fg=MUTED, font=(FONT, 9), anchor="w").pack(side="left", padx=(12, 0))
    body = tk.Frame(outer, bg=bg); body.pack(fill="both", expand=True, padx=padx, pady=(4, pady))
    return outer, body


def section_label(parent, text, row, columns=6, bg=LIGHT):
    """A small caps-style heading that spans a whole grid row (used to split a long form into groups)."""
    cell = tk.Frame(parent, bg=bg); cell.grid(row=row, column=0, columnspan=columns, sticky="we", pady=(8, 2))
    tk.Label(cell, text=text.upper(), bg=bg, fg=MUTED, font=(FONT, 8, "bold")).pack(side="left")
    tk.Frame(cell, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=1)
    return cell


def banner(parent, text="", kind="info", wraplength=900):
    """A one-line (or wrapped) message strip: info / warning / success / danger / neutral. Returns the Label; call .set(text, kind) to change it."""
    bg, fg, edge = TONES.get(kind, TONES["info"])
    label = tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT, 9, "bold"), anchor="w", justify="left", wraplength=wraplength,
                     padx=12, pady=7, highlightthickness=1, highlightbackground=edge)

    def set_text(new_text, new_kind=None):
        tone = TONES.get(new_kind or kind, TONES["info"])
        label.configure(text=new_text, bg=tone[0], fg=tone[1], highlightbackground=tone[2])
    label.set = set_text
    return label


def chip(parent, text, kind="neutral", bg=None):
    """A small rounded-looking status label (Taxable, Not taxable, Posted ...)."""
    tone = TONES.get(kind, TONES["neutral"])
    return tk.Label(parent, text=text, bg=tone[0], fg=tone[1], font=(FONT, 8, "bold"), padx=8, pady=2,
                    highlightthickness=1, highlightbackground=tone[2])


def stat_tile(parent, caption, value="0.00", kind="neutral", width=18):
    """A figure with a small caption above it (Gross, Tax, NSSF, Net ...). Returns (frame, value_label)."""
    tone = TONES.get(kind, TONES["neutral"])
    frame = tk.Frame(parent, bg=tone[0], highlightthickness=1, highlightbackground=tone[2], padx=12, pady=6)
    tk.Label(frame, text=caption, bg=tone[0], fg=tone[1], font=(FONT, 8, "bold"), anchor="w").pack(fill="x")
    number = tk.Label(frame, text=value, bg=tone[0], fg=NAVY, font=(FONT, 13, "bold"), anchor="w", width=width)
    number.pack(fill="x")
    return frame, number


def caption(parent, text, bg=None):
    """The small grey label above or beside a field."""
    return tk.Label(parent, text=text, bg=bg or parent.cget("background"), fg=MUTED, font=(FONT, 9), anchor="w")


def divider(parent, bg=BORDER):
    return tk.Frame(parent, bg=bg, height=1)


def tab_bar(notebook, min_tabs=7):
    """A tab strip that never cuts a tab off: when a Notebook has many tabs, its own strip (which cannot scroll) is replaced by
    a bar with the tabs in a row, ‹ › arrows and an "All tabs" list. The Notebook itself keeps working (select, add, hide, text),
    so every other part of the program is unchanged. If anything goes wrong the Notebook keeps its normal tabs.
    Returns the bar object, or None when it was not needed."""
    done = getattr(notebook, "_saber_tabbar", None)
    if done is not None: return done
    try:
        if len(notebook.tabs()) < min_tabs or notebook.winfo_manager() != "pack": return None
        bar = _TabBar(notebook); notebook._saber_tabbar = bar
        return bar
    except (tk.TclError, ValueError, RuntimeError, AttributeError):
        log.warning("Tab bar not installed; the normal tabs stay", exc_info=True)
        try: notebook.configure(style="TNotebook")
        except tk.TclError: pass
        return None


class _Strip(tk.Frame):
    """A plain Frame by another type, so desktop_theme._fit_width / fold_toolbars (which act on exact tk.Frame rows) leave it alone."""


class _TabBar:
    PAD = (14, 8)

    def __init__(self, notebook):
        self.nb = notebook; self.buttons = {}
        style = ttk.Style(notebook)
        style.layout("Strip.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        style.layout("Strip.TNotebook.Tab", [])  # the native tabs take no room: this bar replaces them
        style.configure("Strip.TNotebook", background=LIGHT, borderwidth=0, tabmargins=0)
        notebook.configure(style="Strip.TNotebook")
        parent = notebook.master
        self.bar = _Strip(parent, bg=LIGHT)
        self.left = tk.Button(self.bar, text="‹", command=lambda: self.scroll(-1), bd=0, bg=LIGHT, fg=NAVY, font=(FONT, 14, "bold"), width=2, cursor="hand2")
        self.right = tk.Button(self.bar, text="›", command=lambda: self.scroll(1), bd=0, bg=LIGHT, fg=NAVY, font=(FONT, 14, "bold"), width=2, cursor="hand2")
        self.more = tk.Button(self.bar, text="All tabs ▾", command=self.menu, bd=0, bg=LIGHT, fg=NAVY, font=(FONT, 9, "bold"), cursor="hand2", padx=8)
        self.canvas = tk.Canvas(self.bar, bg=LIGHT, height=36, highlightthickness=0, bd=0)
        self.inner = _Strip(self.canvas, bg=LIGHT)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        # Tabs wrap onto additional rows so every report stays readable on a small display.
        # Keep the menu as a keyboard/mouse fallback; the horizontal arrows remain available
        # to the existing callers but are hidden when the wrapped strip is active.
        self.more.pack(side="right"); self.canvas.pack(side="left", fill="x", expand=True)
        # sit just above the notebook, in the same place in the layout
        info = notebook.pack_info(); self.bar.pack(before=notebook, fill="x", padx=info.get("padx", 0), pady=(4, 0))
        self.canvas.bind("<Configure>", lambda _e: self._resize())
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self.rebuild(), add="+")
        self.bar.bind("<Map>", lambda _e: self.rebuild(), add="+")
        self.signature = None
        self.rebuild()
        self._watch()

    def _watch(self):
        """Tabs added, renamed (language), hidden or shown after the bar was built are picked up within a second."""
        try:
            if not self.bar.winfo_exists(): return
            signature = tuple((t, self.nb.tab(t, "text"), self.nb.tab(t, "state")) for t in self.nb.tabs())
            if signature != self.signature: self.rebuild()
            self.bar.after(1000, self._watch)
        except tk.TclError:
            pass

    def _resize(self):
        """Lay every tab out in readable rows sized to the available window width."""
        try:
            width = max(1, self.canvas.winfo_width())
            self.canvas.itemconfigure(self.window, width=width)
            x = y = row_height = 0
            gap_x, gap_y = 3, 2
            for button in self.buttons.values():
                needed = button.winfo_reqwidth() or 120
                height = button.winfo_reqheight() or 32
                if x and x + needed > width:
                    y += row_height + gap_y; x = 0; row_height = 0
                button.place(x=x, y=y)
                x += needed + gap_x
                row_height = max(row_height, height)
            height = max(36, y + row_height + 2)
            self.canvas.configure(height=height, scrollregion=(0, 0, width, height))
            self.canvas.itemconfigure(self.window, width=width, height=height)
            self.canvas.xview_moveto(0)
            self.refresh_arrows()
        except tk.TclError:
            pass

    def rebuild(self):
        """Re-read the tabs (a tab may have been added, renamed - e.g. translated - hidden or shown)."""
        try:
            self.signature = tuple((t, self.nb.tab(t, "text"), self.nb.tab(t, "state")) for t in self.nb.tabs())
            tabs = [t for t in self.nb.tabs() if self.nb.tab(t, "state") != "hidden"]
            current = self.nb.select()
            for widget in self.inner.winfo_children(): widget.destroy()
            self.buttons = {}
            for tab in tabs:
                active = tab == current; disabled = self.nb.tab(tab, "state") == "disabled"
                text = self.nb.tab(tab, "text")
                button = tk.Label(self.inner, text=text, padx=self.PAD[0], pady=self.PAD[1], cursor="arrow" if disabled else "hand2",
                                  bg="white" if active else "#EAF0F6", fg="#9AA8B6" if disabled else NAVY, font=(FONT, 9, "bold"))
                if not disabled:
                    button.bind("<Button-1>", lambda _e, t=tab: self.nb.select(t))
                    if not active:
                        button.bind("<Enter>", lambda _e, b=button: b.configure(bg="#F5EBD4")); button.bind("<Leave>", lambda _e, b=button: b.configure(bg="#EAF0F6"))
                self.buttons[tab] = button
            self.inner.update_idletasks(); self._resize()
            if current in self.buttons: self.reveal(self.buttons[current])
            self._underline(current)
        except tk.TclError:
            pass

    def _underline(self, current):
        button = self.buttons.get(current)
        if button is None: return
        try:
            line = tk.Frame(button, bg=GOLD, height=2); line.place(relx=0, rely=1.0, relwidth=1.0, height=2, anchor="sw")
        except tk.TclError: pass

    def reveal(self, button):
        """All tabs are laid out in visible rows; keep the active row in the viewport."""
        try:
            self.canvas.xview_moveto(0); self.canvas.yview_moveto(0); self.refresh_arrows()
        except tk.TclError:
            pass

    def scroll(self, direction):
        try:
            self.canvas.xview_moveto(min(1.0, max(0.0, self.canvas.xview()[0] + direction * 0.25)))
            self.refresh_arrows()
        except tk.TclError:
            pass

    def refresh_arrows(self):
        try:
            first, last = self.canvas.xview()
            self.left.configure(state="normal" if first > 0.001 else "disabled", fg=NAVY if first > 0.001 else "#B9C6D3")
            self.right.configure(state="normal" if last < 0.999 else "disabled", fg=NAVY if last < 0.999 else "#B9C6D3")
        except tk.TclError:
            pass

    def menu(self):
        menu = tk.Menu(self.more, tearoff=0, font=(FONT, 10), bg="white", fg=NAVY, activebackground="#E8EEF5", activeforeground=NAVY)
        for tab in self.nb.tabs():
            if self.nb.tab(tab, "state") == "hidden": continue
            menu.add_command(label=self.nb.tab(tab, "text"), command=lambda t=tab: self.nb.select(t),
                             state="disabled" if self.nb.tab(tab, "state") == "disabled" else "normal")
        try: menu.tk_popup(self.more.winfo_rootx(), self.more.winfo_rooty() + self.more.winfo_height())
        finally: menu.grab_release()
