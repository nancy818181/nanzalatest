"""2.9.60: grouped side menu and the 'Today' part of the Dashboard.

The side menu replaces the grid of 16 buttons above the pages: the same pages, in groups (Sales, Purchases,
Accounting ...), one click to open, groups can be folded. The old top buttons stay available
(Settings > General Settings > Screen layout), the choice is kept on this computer.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from datetime import datetime

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
MENU_BG, MENU_HOVER, MENU_TEXT, MENU_MUTED = "#0B1F33", "#1B3A57", "#FFFFFF", "#9FB3C8"
RED, AMBER, GREEN = "#8B1E1E", "#B7791F", "#2E7D5B"

# page attribute -> group. Pages not listed (added later) go to "More".
MENU_GROUPS = (
    ("Home", ("dashboard_tab",)),
    ("Sales", ("sales_tab", "invoices_tab", "parties_tab")),
    ("Purchases & Cash", ("purchases_tab", "transactions_tab", "import_tab")),
    ("Inventory", ("inventory_tab",)),
    ("Accounting", ("manual_tab", "journal_tab", "account_reports_tab", "pnl_tab", "reports_tab")),
    ("Payroll & VAT", ("payroll_tab", "vat_tab")),
    ("Settings", ("settings_tab",)),
)
MENU_WIDTH = 210
log = logging.getLogger("saber.layout")


def _settings_file():
    import app_runtime
    return app_runtime.data_dir() / "layout_settings.json"


def layout_settings():
    try: data = json.loads(_settings_file().read_text(encoding="utf-8"))
    except Exception: data = {}
    return {"side_menu": bool(data.get("side_menu", True)), "folded": [str(g) for g in data.get("folded", []) if g],
            "hidden_columns": {str(k): [str(c) for c in v] for k, v in (data.get("hidden_columns") or {}).items() if isinstance(v, list)}}


def save_layout_settings(**changes):
    data = layout_settings(); data.update(changes)
    try: _settings_file().write_text(json.dumps(data), encoding="utf-8")
    except OSError: log.warning("Layout settings could not be saved", exc_info=True)
    return data


def side_menu_on():
    return layout_settings()["side_menu"]


def grouped_pages(attributes):
    """[(group, [attribute, ...]), ...] in menu order, only for pages that exist (payroll / VAT depend on rights)."""
    present = list(attributes); used = set(); groups = []
    for group, members in MENU_GROUPS:
        chosen = [a for a in members if a in present]
        used.update(chosen)
        if chosen: groups.append((group, chosen))
    rest = [a for a in present if a not in used]
    if rest: groups.insert(len(groups) - 1 if groups and groups[-1][0] == "Settings" else len(groups), ("More", rest))
    return groups


def menu_width(widget, names):
    """The menu width that shows every item whole: the longest name in bold Segoe UI 10 + the indent, 210 to 320 pixels."""
    try:
        import tkinter.font as tkfont
        font = tkfont.Font(root=widget, family="Segoe UI", size=10, weight="bold")
        longest = max((font.measure(str(n)) for n in names), default=0)
        return max(MENU_WIDTH, min(320, longest + 26 * 2 + 18))
    except tk.TclError:
        return MENU_WIDTH


def build_side_menu(app, holder, attributes, pages, names):
    """Fills holder (a navy column) with the grouped menu. Returns the page buttons in the SAME order as pages,
    so app.highlight_main_tab keeps colouring the selected one."""
    by_attribute = dict(zip(attributes, zip(pages, names)))
    width = menu_width(holder, names)  # 2.9.100: wide enough for the longest item in the real font (it was cut on Windows at 125%)
    try: holder.configure(width=width)
    except tk.TclError: pass
    canvas = tk.Canvas(holder, bg=MENU_BG, highlightthickness=0, width=width)
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=MENU_BG); window = canvas.create_window((0, 0), window=inner, anchor="nw", width=width)
    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
    canvas._saber_scroll_page = True  # the mouse wheel scrolls it like the pages
    buttons = {}; folded = set(layout_settings()["folded"]); app.side_menu_groups = {}

    def toggle(group):
        body, header = app.side_menu_groups[group]
        if body.winfo_manager(): body.pack_forget(); folded.add(group); header.config(text=f"▸  {group.upper()}")
        else: body.pack(fill="x", after=header); folded.discard(group); header.config(text=f"▾  {group.upper()}")
        save_layout_settings(folded=sorted(folded))
    app.toggle_menu_group = toggle

    for group, members in grouped_pages(attributes):
        header = tk.Label(inner, text=f"{'▸' if group in folded else '▾'}  {group.upper()}", bg=MENU_BG, fg=GOLD, anchor="w",
                          font=("Segoe UI", 8, "bold"), padx=14, pady=3, cursor="hand2")
        header.pack(fill="x", pady=(6, 0)); header.bind("<Button-1>", lambda _e, g=group: toggle(g))
        body = tk.Frame(inner, bg=MENU_BG)
        if group not in folded: body.pack(fill="x")
        app.side_menu_groups[group] = (body, header)
        for attribute in members:
            page, name = by_attribute[attribute]
            button = tk.Button(body, text=name, command=lambda p=page: app.select_main_tab(p), bg=MENU_BG, fg=MENU_TEXT, anchor="w",
                               activebackground=GOLD, activeforeground=NAVY, border=0, relief="flat", font=("Segoe UI", 10),
                               padx=26, pady=4, cursor="hand2", highlightthickness=0)
            button.pack(fill="x")
            button.bind("<Enter>", lambda _e, b=button: b.config(bg=MENU_HOVER) if b.cget("bg") == MENU_BG else None)
            button.bind("<Leave>", lambda _e, b=button: b.config(bg=MENU_BG) if b.cget("bg") == MENU_HOVER else None)
            buttons[str(page)] = button
    return [buttons[str(page)] for page in pages]


def colour_menu_button(button, selected):
    """Selected page: gold bar; others: the menu colour (top-grid buttons keep their navy)."""
    if button.cget("bg") in (MENU_BG, MENU_HOVER) or getattr(button, "_side_selected", False):
        button._side_selected = selected
        button.config(bg=GOLD if selected else MENU_BG, fg=NAVY if selected else MENU_TEXT, font=("Segoe UI", 10, "bold" if selected else "normal"))
        return True
    return False


# ---------------------------------------------------------------- dashboard "Today"
QUICK_ACTIONS = (
    ("+ Sales Invoice", "sales_tab"), ("+ Purchase / Expense", "purchases_tab"), ("Import Excel / PDF", "import_tab"),
    ("Journal Voucher", "manual_tab"), ("Statement of Account", "account_reports_tab"), ("Financial Reports", "reports_tab"),
)


def attention_items(app, metrics=None):
    """What needs a look today: [(level, text, action_label, callback)]. level: red / amber / green."""
    items = []; client = app.client
    overdue = sum(int(r.get("overdue") or 0) for r in (metrics or []))
    if overdue:
        items.append(("red", f"{overdue} overdue invoice(s) not paid yet", "Open invoices", lambda: app.select_main_tab(app.invoices_tab)))
    try:
        alerts = client.document_alerts(30)
        if alerts.get("items"):
            level = "red" if alerts.get("expired") else "amber"
            items.append((level, f"{alerts.get('expired', 0)} legal document(s) expired, {alerts.get('expiring', 0)} expiring in 30 days", "Show", app.show_document_alerts))
    except Exception: log.debug("Document alerts not available", exc_info=True)
    try:
        unbalanced = client.unbalanced_entries()
        if unbalanced:
            items.append(("red", f"{len(unbalanced)} journal entr{'y is' if len(unbalanced) == 1 else 'ies are'} not balanced", "Check", app.check_unbalanced_entries))
    except Exception: log.debug("Balance check not available", exc_info=True)
    try:  # 2.9.82: accounts off budget
        alert = app.budget_alert_item() if hasattr(app, "budget_alert_item") else None
        if alert: items.append(alert)
    except Exception: log.debug("Budget alerts not available", exc_info=True)
    role = (getattr(app, "current_user", None) or {}).get("role")
    if role != "viewer":
        try:
            backups = client.backups()
            if not backups:
                items.append(("amber", "No backup of this company / year yet", "Back up now", app.create_backup))
            else:
                last = datetime.fromisoformat(str(backups[0]["modified"])[:19]); days = (datetime.now() - last).days
                text = f"Last backup {last.strftime('%d-%m-%Y %H:%M')}" + (f" ({days} days ago)" if days >= 1 else "")
                items.append(("amber" if days >= 3 else "green", text, "Back up now", app.create_backup))
        except Exception: log.debug("Backups not available", exc_info=True)
    if not any(level != "green" for level, *_rest in items):
        items.insert(0, ("green", "Nothing waiting: no overdue invoice, no document alert, every entry balanced", None, None))
    return items


def build_today_panel(app, parent):
    """Quick actions + 'Needs attention' list at the top of the Dashboard."""
    box = tk.Frame(parent, bg=LIGHT); box.pack(fill="x", padx=12, pady=(2, 6))
    actions = tk.Frame(box, bg=LIGHT); actions.pack(fill="x")
    tk.Label(actions, text="Quick actions", bg=LIGHT, fg=NAVY, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
    for text, attribute in QUICK_ACTIONS:
        if attribute not in getattr(app, "_page_attributes", ()): continue
        tk.Button(actions, text=text, command=lambda a=attribute: app.select_main_tab(getattr(app, a)), bg="white", fg=NAVY,
                  activebackground=GOLD, border=1, relief="solid", padx=12, pady=5, cursor="hand2", font=("Segoe UI", 9, "bold")).pack(side="left", padx=3, pady=2)
    try:
        from desktop_common import flow_toolbars
        flow_toolbars(actions)
    except Exception: log.debug("Quick actions left unwrapped", exc_info=True)
    card = tk.Frame(box, bg="white", highlightthickness=1, highlightbackground="#dfe6ee"); card.pack(fill="x", pady=(6, 0))
    tk.Label(card, text="Needs attention", bg="white", fg=NAVY, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 2))
    app.today_list = tk.Frame(card, bg="white"); app.today_list.pack(fill="x", padx=12, pady=(0, 8))
    return box


def fill_today_panel(app, metrics=None):
    holder = getattr(app, "today_list", None)
    if holder is None or not holder.winfo_exists(): return []
    for child in holder.winfo_children(): child.destroy()
    items = attention_items(app, metrics)
    colours = {"red": RED, "amber": AMBER, "green": GREEN}
    for level, text, label, callback in items:
        line = tk.Frame(holder, bg="white"); line.pack(fill="x", pady=2)
        tk.Label(line, text="●", bg="white", fg=colours[level], font=("Segoe UI", 11)).pack(side="left")
        tk.Label(line, text=text, bg="white", fg=NAVY, font=("Segoe UI", 10), anchor="w").pack(side="left", padx=6)
        if label and callback:
            tk.Button(line, text=label, command=callback, bg=NAVY, fg="white", border=0, padx=10, pady=2, cursor="hand2").pack(side="right")
    app.today_items = items
    return items
