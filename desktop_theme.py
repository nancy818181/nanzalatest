"""2.9.94: the look of every screen in one place (it was inside desktop.py).

A calmer, more modern look: flat tabs with a gold line under the open one, soft blue selection, striped table rows
(added by the table helper in desktop.py), flat inputs with a gold focus line and buttons that light up under the
mouse. Colours stay the Saber navy / gold, so printed reports and the logo still match."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from desktop_common import GOLD, LIGHT, NAVY

FONT = "Segoe UI"
HEADING = "#23405E"        # table headings
HEADING_ACTIVE = "#2E5277"
SELECTED = "#D3E5F5"       # selected table row
STRIPE = "#F3F6F9"         # every second table row
BORDER = "#C9D3DD"
TAB_IDLE = "#E5ECF2"
TAB_HOVER = "#D6E4ED"


def apply_theme(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background=LIGHT, borderwidth=0, tabmargins=(6, 6, 6, 0))
    style.configure("TNotebook.Tab", padding=(14, 8), font=(FONT, 9, "bold"), background=TAB_IDLE, foreground=NAVY, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", "white"), ("active", TAB_HOVER)], foreground=[("selected", NAVY)],
              lightcolor=[("selected", GOLD)], expand=[("selected", (0, 2, 0, 0))])
    style.configure("Treeview", rowheight=27, font=(FONT, 10), background="white", fieldbackground="white", foreground=NAVY,
                    borderwidth=0, bordercolor=BORDER)  # 2.9.59: 10 pt text in tables
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", NAVY)])
    style.configure("Treeview.Heading", background=HEADING, foreground="white", font=(FONT, 10, "bold"), relief="flat", padding=(4, 6))
    style.map("Treeview.Heading", background=[("active", HEADING_ACTIVE)])
    style.configure("Sales.Treeview", rowheight=28, font=(FONT, 10))
    style.configure("TCombobox", padding=4, arrowsize=13, bordercolor=BORDER, lightcolor="white", darkcolor="white")
    style.map("TCombobox", bordercolor=[("focus", GOLD)], fieldbackground=[("readonly", "white")])
    style.configure("TEntry", padding=4, bordercolor=BORDER); style.map("TEntry", bordercolor=[("focus", GOLD)])
    style.configure("TLabelframe", background=LIGHT, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=LIGHT, foreground=NAVY, font=(FONT, 9, "bold"))
    style.configure("TCheckbutton", background=LIGHT, foreground=NAVY); style.map("TCheckbutton", background=[("active", LIGHT)])
    style.configure("TRadiobutton", background=LIGHT, foreground=NAVY); style.map("TRadiobutton", background=[("active", LIGHT)])
    style.configure("Vertical.TScrollbar", arrowsize=12, troughcolor=LIGHT, borderwidth=0, background="#D5DDE5")
    style.configure("Horizontal.TScrollbar", arrowsize=12, troughcolor=LIGHT, borderwidth=0, background="#D5DDE5")
    style.map("Vertical.TScrollbar", background=[("active", "#B8C6D3")]); style.map("Horizontal.TScrollbar", background=[("active", "#B8C6D3")])
    style.configure("TProgressbar", background=GOLD, troughcolor="#E5ECF2", borderwidth=0)
    root.option_add("*Font", (FONT, 9))
    root.option_add("*Entry.relief", "solid"); root.option_add("*Entry.borderWidth", 1)
    root.option_add("*Entry.highlightThickness", 1); root.option_add("*Entry.highlightColor", GOLD); root.option_add("*Entry.highlightBackground", BORDER)
    root.option_add("*LabelFrame.foreground", NAVY); root.option_add("*LabelFrame.font", (FONT, 9, "bold"))
    root.option_add("*Button.cursor", "hand2"); root.option_add("*Button.relief", "flat")
    root.option_add("*Listbox.selectBackground", SELECTED); root.option_add("*Listbox.selectForeground", NAVY)
    root.option_add("*Text.highlightColor", GOLD); root.option_add("*Text.highlightBackground", BORDER)

    def hover(event, entering):  # buttons light up under the mouse
        widget = event.widget
        try:
            if entering:
                widget._saber_bg = widget.cget("background"); color = widget._saber_bg.lstrip("#")
                if len(color) == 6:
                    lighter = "#" + "".join(f"{min(255, int(color[i:i + 2], 16) + 28):02x}" for i in (0, 2, 4)); widget._saber_hover = lighter; widget.configure(background=lighter)
            elif getattr(widget, "_saber_bg", None) and str(widget.cget("background")).lower() == str(getattr(widget, "_saber_hover", "")).lower():
                widget.configure(background=widget._saber_bg)  # only undo our own highlight
        except Exception: logging.getLogger("saber.ignored").debug("Ignored error", exc_info=True)
    root.bind_class("Button", "<Enter>", lambda e: hover(e, True), add="+"); root.bind_class("Button", "<Leave>", lambda e: hover(e, False), add="+")
    return style


def restripe(tree: ttk.Treeview) -> None:
    """Every second row of a table gets a light background (the row's own colours, e.g. red for an error, win)."""
    for index, item in enumerate(tree.get_children("")):
        tags = tree.item(item, "tags")
        tags = [t for t in ((tags.split() if isinstance(tags, str) else tags) or ()) if t != "stripe"]
        if index % 2: tags.append("stripe")
        tree.item(item, tags=tags)


# ---------------------------------------------------------------- 2.9.95: one design system for every screen
# Applied after a screen or a window is built, so every button, card and input follows the same rules without
# touching the hundreds of places that create them. Same Saber colours: navy, gold, light grey-blue.
CARD = "#FFFFFF"            # content cards on the light page background
PAGE = LIGHT
DANGER = ("#8b1e1e", "#6b1010", "#a32020", "#b00020", "red")
GOLD_HOVER = "#C99D57"
NAVY_HOVER = "#1E4268"
DANGER_HOVER = "#A32A2A"
_BUTTON_FONT = (FONT, 9, "bold")
_TITLE_FONT = (FONT, 10, "bold")


def _lower(value):
    return str(value or "").strip().lower()


def _is_page_bg(widget):
    try: return _lower(widget.cget("background")) in (_lower(PAGE), "#f4f7fa")
    except tk.TclError: return False


def _pixels(widget, option):
    """An option such as padx in pixels ('3m' or '12' both work)."""
    try: return int(round(widget.winfo_fpixels(str(widget.cget(option)) or "0")))
    except (tk.TclError, ValueError): return 0


def _polish_button(button):
    try:
        bg = _lower(button.cget("background"))
        if _lower(button.master.cget("background")) in (_lower(NAVY), "#0b1f33"): return  # menu / top bar: keep
        if button.cget("text") in ("", None) or button.cget("image"): return
        if bg == _lower(GOLD): kind, hover, fg = "primary", GOLD_HOVER, NAVY
        elif bg in DANGER: kind, hover, fg = "danger", DANGER_HOVER, "white"
        elif bg == _lower(NAVY): kind, hover, fg = "secondary", NAVY_HOVER, "white"
        else: return  # a colour chosen on purpose (status chips, colour pickers)
        padx = max(12, _pixels(button, "padx")); pady = 5 if _pixels(button, "pady") >= 4 else _pixels(button, "pady")
        button.configure(font=_BUTTON_FONT, fg=fg, relief="flat", bd=0, highlightthickness=0, padx=padx, pady=pady,
                         activebackground=hover, activeforeground=fg, cursor="hand2")
        button._saber_kind = kind
    except (tk.TclError, ValueError):
        pass


def _into_card(widget):
    """A widget inside a card takes the card's white background (only where it had the page colour)."""
    for child in widget.winfo_children():
        if isinstance(child, (tk.Frame, tk.Label, tk.Checkbutton, tk.Radiobutton)) and not isinstance(child, tk.LabelFrame) and _is_page_bg(child):
            try:
                child.configure(background=CARD)
                if isinstance(child, (tk.Checkbutton, tk.Radiobutton)): child.configure(activebackground=CARD, selectcolor=CARD)
            except tk.TclError: pass
        if not isinstance(child, (tk.LabelFrame, tk.Toplevel, tk.Canvas)): _into_card(child)


def _polish_card(frame):
    try:
        if not _is_page_bg(frame): return  # a coloured box (e.g. totals) keeps its colour
        frame.configure(background=CARD, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
                        fg=NAVY, font=_TITLE_FONT, padx=max(10, _pixels(frame, "padx")), pady=max(6, _pixels(frame, "pady")))
        _into_card(frame)
    except (tk.TclError, ValueError):
        pass


def _polish_entry(entry):
    try:
        entry.configure(relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=GOLD,
                        insertbackground=NAVY, disabledbackground="#EEF2F6", readonlybackground="#F7F9FB")
        if _lower(entry.cget("background")) in ("", "systemwindow", "white", "#ffffff"): entry.configure(background="white")
    except tk.TclError:
        pass


MAX_ROW = 1060  # a laptop screen (1366 px) less the menu and the margins


def _fit_width(widgets):
    """Rows of buttons / fields wider than a laptop screen wrap onto a second line; long text wraps."""
    from desktop_common import flow_toolbar
    try: widgets[0].update_idletasks()
    except (tk.TclError, IndexError): return
    rows = []
    for item in widgets:
        try:
            if item.winfo_reqwidth() <= MAX_ROW: continue
            if isinstance(item, tk.Label) and (not int(str(item.cget("wraplength")) or 0) or int(str(item.cget("wraplength"))) > MAX_ROW) and len(str(item.cget("text"))) > 60:
                item.configure(wraplength=MAX_ROW - 120, justify="left")
            elif type(item) in (tk.Frame, tk.LabelFrame) and not getattr(item, "_saber_flow", False):
                slaves = item.pack_slaves()
                if len(slaves) >= 2 and not item.grid_slaves() and all(s.pack_info().get("side") in ("left", "right") for s in slaves):
                    rows.append(item)
        except tk.TclError:
            pass
    for row in sorted(rows, key=lambda w: -len(str(w))):  # the innermost rows first
        try: flow_toolbar(row)
        except Exception: logging.getLogger("saber.ignored").debug("Row left as it was", exc_info=True)


def polish(widget):
    """Apply the design system to a screen or window and everything in it (safe to call again)."""
    stack = [widget]; seen = []
    while stack:
        item = stack.pop(); seen.append(item)
        if isinstance(item, tk.Button): _polish_button(item)
        elif isinstance(item, tk.LabelFrame): _polish_card(item)
        elif isinstance(item, tk.Entry) and not isinstance(item, ttk.Entry): _polish_entry(item)
        try: stack.extend(item.winfo_children())
        except tk.TclError: pass
    _fit_width([w for w in seen if isinstance(w, (tk.Frame, tk.Label, tk.LabelFrame))])


def page_title_bar(parent):
    """The bar above every screen: SECTION › Screen on the left (the currency filter goes on the right)."""
    bar = tk.Frame(parent, bg=PAGE)
    section = tk.Label(bar, text="", bg=PAGE, fg="#7A8794", font=(FONT, 9, "bold"))
    section.pack(side="left", padx=(2, 6))
    title = tk.Label(bar, text="", bg=PAGE, fg=NAVY, font=(FONT, 15, "bold"))
    title.pack(side="left")
    bar._section, bar._title = section, title
    return bar
