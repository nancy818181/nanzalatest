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
HEADING = NAVY
HEADING_ACTIVE = "#142b50"
HEADING_TEXT = "#FFFFFF"
FORM_TEXT = NAVY
SELECTED = "#f7edcf"
STRIPE = "#F7F9FC"
BORDER = "#D5DEE8"
TAB_IDLE = "#EAF0F6"
TAB_HOVER = "#F5EBD4"


def apply_theme(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background=LIGHT, borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.configure("TNotebook.Tab", padding=(12, 7), font=(FONT, 9, "bold"), background=TAB_IDLE, foreground=NAVY, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", "white"), ("active", TAB_HOVER)], foreground=[("selected", NAVY)],
              lightcolor=[("selected", GOLD)], expand=[("selected", (0, 2, 0, 0))])
    style.configure("Treeview", rowheight=29, font=(FONT, 10), background="white", fieldbackground="white", foreground=NAVY,
                    borderwidth=0, bordercolor=BORDER)  # 2.9.59: 10 pt text in tables
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", NAVY)])
    style.configure("Treeview.Heading", background=HEADING, foreground=HEADING_TEXT, font=(FONT, 9, "bold"), relief="flat", padding=(8, 9),
                    borderwidth=0, bordercolor=HEADING, lightcolor=HEADING, darkcolor=HEADING)
    style.map("Treeview.Heading", background=[("active", HEADING_ACTIVE)], foreground=[("active", HEADING_TEXT)])
    style.configure("Sales.Treeview", rowheight=28, font=(FONT, 10))
    style.configure("TCombobox", padding=4, arrowsize=13, bordercolor=BORDER, lightcolor="white", darkcolor="white")
    style.map("TCombobox", bordercolor=[("focus", GOLD)], fieldbackground=[("readonly", "white")])
    style.configure("TEntry", padding=4, bordercolor=BORDER); style.map("TEntry", bordercolor=[("focus", GOLD)])
    style.configure("TLabelframe", background=LIGHT, bordercolor=BORDER, borderwidth=1, relief="flat")
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
    # 2.9.115: no grey focus box around every tick box when it is not in use
    for kind in ("Checkbutton", "Radiobutton"): root.option_add(f"*{kind}.highlightThickness", 0)
    # 2.9.116: form text in a soft navy instead of plain black (a label given its own colour keeps it)
    for kind in ("Label", "Checkbutton", "Radiobutton"): root.option_add(f"*{kind}.foreground", FORM_TEXT)
    root.option_add("*Entry.foreground", NAVY); root.option_add("*Entry.insertWidth", 1)
    root.option_add("*Listbox.selectBackground", SELECTED); root.option_add("*Listbox.selectForeground", NAVY)
    root.option_add("*Text.highlightColor", GOLD); root.option_add("*Text.highlightBackground", BORDER)

    def hover(event, entering):  # buttons light up under the mouse
        widget = event.widget
        try:
            if getattr(widget, "_saber_kind", "") in ("secondary", "outline"):  # 2.9.115: light buttons get a soft grey-blue
                if entering:
                    if _lower(widget.cget("background")) == _lower(OUTLINE_BG): widget.configure(background=OUTLINE_HOVER)
                elif _lower(widget.cget("background")) == _lower(OUTLINE_HOVER): widget.configure(background=OUTLINE_BG)
                return
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
GOLD_HOVER = "#e2b52a"
NAVY_HOVER = "#142b50"
DANGER_HOVER = "#A32A2A"
_BUTTON_FONT = (FONT, 9, "bold")
# 2.9.115: buttons by importance, as in Odoo / Zoho: ONE gold main action (Save ...), red for delete, and every other
# action a light button with a thin border (they were all solid navy, so nothing stood out). Only the look changes.
OUTLINE_BG = "#FFFFFF"
OUTLINE_HOVER = "#E8EEF5"
OUTLINE_BORDER = "#B9C6D3"
_OUTLINE_SOURCES = ("white", "#ffffff", "#fff", "systembuttonface", "#f0f0f0", "#d9d9d9")
_TITLE_FONT = (FONT, 10, "bold")


def _lower(value):
    return str(value or "").strip().lower()


def _is_page_bg(widget):
    try: return _lower(widget.cget("background")) in (_lower(PAGE), "#F4F7FA")
    except tk.TclError: return False


def _pixels(widget, option):
    """An option such as padx in pixels ('3m' or '12' both work)."""
    try: return int(round(widget.winfo_fpixels(str(widget.cget(option)) or "0")))
    except (tk.TclError, ValueError): return 0


def _polish_button(button):
    try:
        if getattr(button, "_saber_keep", False): return  # a button whose colour shows a state (page buttons ...)
        bg = _lower(button.cget("background"))
        if _lower(button.master.cget("background")) in (_lower(NAVY), "#0b1f33"): return  # menu / top bar: keep
        if button.cget("text") in ("", None) or button.cget("image"): return
        done = getattr(button, "_saber_kind", "")
        if done in ("secondary", "outline") and bg in (_lower(OUTLINE_BG), _lower(OUTLINE_HOVER)): kind = done  # polished before
        elif bg == _lower(GOLD) or done == "primary" and bg == _lower(GOLD_HOVER): kind = "primary"
        elif bg in DANGER or done == "danger" and bg == _lower(DANGER_HOVER): kind = "danger"
        elif bg == _lower(NAVY): kind = "secondary"
        elif bg in _OUTLINE_SOURCES: kind = "outline"
        else: return  # a colour chosen on purpose (status chips, colour pickers)
        padx = max(12, _pixels(button, "padx")); pady = 5 if _pixels(button, "pady") >= 4 else _pixels(button, "pady")
        if kind in ("secondary", "outline"):
            button.configure(font=_BUTTON_FONT, bg=OUTLINE_BG, fg=NAVY, relief="flat", bd=0, highlightthickness=1,
                             highlightbackground=OUTLINE_BORDER, highlightcolor=GOLD, padx=padx, pady=max(pady, 4),
                             activebackground=OUTLINE_HOVER, activeforeground=NAVY, cursor="hand2")
        else:
            hover, fg = (GOLD_HOVER, NAVY) if kind == "primary" else (DANGER_HOVER, "white")
            button.configure(font=_BUTTON_FONT, fg=fg, relief="flat", bd=0, highlightthickness=0, padx=padx, pady=pady,
                             activebackground=hover, activeforeground=fg, cursor="hand2")
        button._saber_kind = kind
        _button_icon(button, kind)
    except (tk.TclError, ValueError):
        pass


def _button_icon(button, kind):
    """2.9.116: a small icon before the everyday actions (New, Save, Print, Delete, Excel, PDF, Import)."""
    if getattr(button, "_saber_icon_done", False): return
    button._saber_icon_done = True
    try:
        if str(button.cget("image")) or str(button.cget("compound")) not in ("", "none"): return
        if int(str(button.cget("width")) or 0): return  # a width in letters would turn into pixels with an image
        words = str(button.cget("text")).strip().lower().split()  # "+ Sales Invoice" already shows its +: no icon
        if not words: return
        import icons
        name = icons.BUTTON_ICONS.get(words[0])
        if not name: return
        colour = "#FFFFFF" if kind == "danger" else NAVY
        button._saber_icon = icons.tk_icon(button, name, colour, 12)
        # Tk puts padx between the icon and the text too: a smaller padx keeps the button about as wide as before
        button.configure(image=button._saber_icon, compound="left", padx=max(7, _pixels(button, "padx") // 2))
    except (ImportError, OSError, ValueError, tk.TclError):  # Pillow missing or an unusual button: it simply keeps no icon
        logging.getLogger("saber.ignored").debug("Button icon left out", exc_info=True)


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


# ---------------------------------------------------------------- 2.9.116: toolbars as in Odoo / Zoho
# A row with many light buttons shows the first few and puts the others in a "More" menu (the main gold action and
# the red ones always stay in view). The buttons themselves are kept, only out of sight: the menu runs the same
# button, so every command, shortcut and permission works exactly as before.
FOLD_AT = 6        # light buttons in one row before the row is folded
KEEP_VISIBLE = 4   # light buttons left in view
MORE_TEXT = "More \u25be"
EVERYDAY = {"new", "add", "+", "print", "refresh", "show", "edit", "open", "find", "apply", "run", "build", "create"}


def _row_items(frame):
    """The widgets of a toolbar row in order, and how they are placed ('flow' / 'pack'), or (None, None)."""
    try:
        if getattr(frame, "_saber_flow", False):
            return [w for w, *_rest in getattr(frame, "_flow_order", []) if w.winfo_exists()], "flow"
        if frame.grid_slaves() or frame.place_slaves(): return None, None
        slaves = frame.pack_slaves()
        if any(s.pack_info().get("side") not in ("left",) for s in slaves if isinstance(s, tk.Button)): return None, None
        return slaves, "pack"
    except tk.TclError:
        return None, None


def _more_menu(frame, button):
    menu = tk.Menu(button, tearoff=0, font=(FONT, 10), activebackground=OUTLINE_HOVER, activeforeground=NAVY, bg="white", fg=NAVY, bd=1)
    for hidden in getattr(frame, "_saber_folded", []):
        try:
            if not hidden.winfo_exists(): continue
            menu.add_command(label=str(hidden.cget("text")), command=hidden.invoke, state=str(hidden.cget("state")))
        except tk.TclError: continue
    try: menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
    finally: menu.grab_release()


def _english(button):
    """The English text of a button (2.9.118: in Arabic the screen shows the Arabic one)."""
    text = str(button.cget("text"))
    try:
        import arabic_ui
        return arabic_ui.english(text) if arabic_ui.active() else text
    except ImportError:
        return text


def fold_toolbar(frame):
    """Fold one row (safe to call again; buttons added to the row later are folded too)."""
    items, mode = _row_items(frame)
    if not items: return False
    light = [w for w in items if isinstance(w, tk.Button) and getattr(w, "_saber_kind", "") in ("secondary", "outline")
             and not getattr(w, "_saber_more", False) and not getattr(w, "_flow_hidden", False)]
    folded = [w for w in getattr(frame, "_saber_folded", []) if w.winfo_exists()]
    if len(light) + len(folded) < FOLD_AT or len(light) <= KEEP_VISIBLE: return False
    # the everyday actions stay in view first (New / Add / Print / Refresh ...), then the others in their order
    everyday = [w for w in light if _english(w).strip().split(" ")[0].lower() in EVERYDAY]
    chosen = set((everyday + [w for w in light if w not in everyday])[:KEEP_VISIBLE])
    keep, hide = [w for w in light if w in chosen], [w for w in light if w not in chosen]
    more = getattr(frame, "_saber_more_button", None)
    if more is None or not more.winfo_exists():
        more = tk.Button(frame, text=MORE_TEXT, bg=OUTLINE_BG, fg=NAVY, pady=_pixels(keep[-1], "pady") or 5); more._saber_more = True
        more.configure(command=lambda f=frame, b=more: _more_menu(f, b)); _polish_button(more); frame._saber_more_button = more
        if mode == "pack":
            info = keep[-1].pack_info()  # the same spacing as its neighbours, so the row stays level
            more.pack(side="left", padx=info.get("padx", 3), pady=info.get("pady", 0), after=keep[-1])
        else:
            order = frame._flow_order; index = next((i for i, e in enumerate(order) if e[0] is keep[-1]), len(order) - 1)
            order.insert(index + 1, (more, "left", order[index][2], order[index][3]))
            more.bind("<Configure>", lambda _e, f=frame: f._flow_schedule(), add="+")
    for button in hide:
        if mode == "pack": button.pack_forget()
        else: button._flow_hidden = True; button.place_forget()
    frame._saber_folded = folded + hide
    if mode == "flow": frame._flow_schedule()
    return True


def fold_toolbars(widget):
    """Every row under `widget` with many light buttons gets a More menu."""
    stack = [widget]
    while stack:
        item = stack.pop()
        if type(item) in (tk.Frame, tk.LabelFrame) and not getattr(item, "_saber_no_fold", False): fold_toolbar(item)
        try: stack.extend(c for c in item.winfo_children() if not isinstance(c, tk.Toplevel))
        except tk.TclError: pass


def polish(widget, fold=False):
    """Apply the design system to a screen or window and everything in it (safe to call again).
    fold=True (the program's screens) also folds long rows of buttons into a More menu (2.9.116)."""
    stack = [widget]; seen = []
    while stack:
        item = stack.pop(); seen.append(item)
        if isinstance(item, tk.Button): _polish_button(item)
        elif isinstance(item, tk.LabelFrame): _polish_card(item)
        elif isinstance(item, tk.Entry) and not isinstance(item, ttk.Entry): _polish_entry(item)
        elif isinstance(item, ttk.Notebook):  # 2.9.134: a Notebook with many tabs gets a scrolling tab bar (the normal strip cuts tabs off)
            try:
                import desktop_design
                desktop_design.tab_bar(item)
            except (tk.TclError, ValueError, RuntimeError, AttributeError, ImportError): logging.getLogger("saber.ignored").debug("Tab bar skipped", exc_info=True)
        try: stack.extend(item.winfo_children())
        except tk.TclError: pass
    if fold: fold_toolbars(widget)
    _fit_width([w for w in seen if isinstance(w, (tk.Frame, tk.Label, tk.LabelFrame))])


def page_title_bar(parent):
    """The bar above every screen: SECTION › Screen on the left (the currency filter goes on the right)."""
    bar = tk.Frame(parent, bg="white", highlightthickness=1, highlightbackground=BORDER, padx=12, pady=8)
    section = tk.Label(bar, text="", bg="white", fg=GOLD, font=(FONT, 8, "bold"))
    section.pack(side="left", padx=(2, 8))
    title = tk.Label(bar, text="", bg="white", fg=NAVY, font=(FONT, 14, "bold"))
    title.pack(side="left")
    bar._section, bar._title = section, title
    return bar
