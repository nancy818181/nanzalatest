"""Shared imports, colours and small helpers used by every Saber desktop screen."""
from __future__ import annotations

import os
import logging
import ctypes
import tkinter as tk
import sys
import threading
import traceback
import mimetypes
import time
import json
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from client import ApiClient
from i18n import tr
from report_export import export_excel, export_invoice_pdf, export_pdf, print_rows
from party_similarity import similar_parties
from multi_select import MultiSelect, chosen_values  # 2.9.50: pick any combination in filters

NAVY, GOLD, LIGHT = "#102A43", "#B78B45", "#F4F7FA"
TAXABLE_LABEL="Taxable (standard rate)"  # 2.9.72: the rate is the company's (Settings > General)
SALE_TREATMENTS={TAXABLE_LABEL:"standard","Zero-rated (export)":"zero_rated","Exempt (Art. 16-17)":"exempt","Out of scope":"out_of_scope"}
PURCHASE_USES={"Mixed (partial deduction)":"mixed","Taxable sales only (100%)":"taxable","Exempt sales only (0%)":"exempt"}

def resource_path(relative_path):
    import nanza_paths  # 2.9.117: the program folder (Assets/), not this module's folder
    base = nanza_paths.ROOT
    path = base / relative_path
    if not path.exists() and relative_path.startswith("assets/"):
        alternative = base / "Assets" / relative_path[len("assets/"):]
        if alternative.exists(): return alternative
    return path

def row_matches_search(values, query):
    """Return True when every search term appears somewhere in the row.

    Amounts match with or without thousands separators (1250 finds 1,250.00) and dates match
    with or without dashes (31122024 finds 31-12-2024)."""
    terms = str(query or "").casefold().split()
    if not terms:
        return True
    searchable = " ".join("" if value is None else str(value) for value in values).casefold()
    searchable = f"{searchable} {searchable.replace(',', '')} {searchable.replace('-', '').replace('/', '')}"
    return all(term in searchable or term.replace(",", "") in searchable for term in terms)

def auto_dash_date(text):
    """Turn typed digits into DD-MM-YYYY as the user types: 3112 -> 31-12, 31122024 -> 31-12-2024."""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())[:8]
    if len(digits) <= 2: return digits
    if len(digits) <= 4: return f"{digits[:2]}-{digits[2:]}"
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"

def sortable_date(value):
    return _sortable_date(str(value or "").strip())


import functools as _functools


@_functools.lru_cache(maxsize=65536)
def _sortable_date(text):  # 2.9.91: tables sort thousands of rows by date; each date text is read once
    for pattern in ("%d-%m-%Y","%Y-%m-%d"):
        try: return datetime.strptime(text,pattern)
        except ValueError: pass
    return datetime.min

def initial_window_size(screen_width, screen_height, dpi_scale=1.0):
    """Keep the initial window and its minimum size inside compact displays."""
    available_width=max(1,screen_width-32)
    available_height=max(1,screen_height-72)
    width=min(round(1180*dpi_scale),available_width)
    height=min(round(720*dpi_scale),available_height)
    return width,height,min(round(760*dpi_scale),width),min(round(480*dpi_scale),height)

def parse_user_date(value):
    text=str(value or "").strip()
    for pattern in ("%d-%m-%Y","%d%m%Y","%Y-%m-%d","%Y%m%d"):
        try: return datetime.strptime(text,pattern)
        except ValueError: pass
    raise ValueError("Date must contain 8 digits: DDMMYYYY")

def formatted_user_date(value):
    return parse_user_date(value).strftime("%d-%m-%Y")

def safe_display_date(value):
    """Show a saved date as DD-MM-YYYY; keep the original text if it is in another format."""
    if value is None or str(value).strip().lower() in ("", "none", "null", "nan"): return ""
    try: return formatted_user_date(value)
    except (ValueError, TypeError): return str(value)

def natural_sort_value(value):
    text=str(value or "").strip()
    try: return (0,float(text.replace(",","")))
    except ValueError: return (1,text.casefold())

def _enable_windows_dpi_awareness():
    """Let Windows report real monitor dimensions before Tk chooses the initial window size."""
    if sys.platform!="win32": return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)): return
    except (AttributeError,OSError):
        pass
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError,OSError): pass


# ---------------------------------------------------------------- 2.9.59: tidier screens
import re as _re

_AMOUNT_WORDS = ("debit", "credit", "balance", "total", "amount", "subtotal", "deductible", "vat", "paid", "outstanding",
                 "inflow", "outflow", "net", "value", "price", "cost", "salary", "eq.", "qty", "quantity", "rate", "variance",
                 "current", "prior", "opening", "closing", "budget", "actual", "lbp", "usd", "eur")
_NOT_AMOUNT = ("account", "name", "date", "status", "method", "type", "description", "currency", "number", "no.", "party", "vat status",
               "deductible?", "category", "code", "kind")


def is_amount_column(key, label=""):
    """True for a column that holds amounts (shown on the right, like a spreadsheet)."""
    text = f"{key} {label}".strip().casefold()
    if any(word in text for word in ("vat_status", "vat deductible", "vat treatment", "currency", "date", "rate date")): return False
    words = str(key).casefold().replace("_", " ").split() + str(label).casefold().split()
    if any(w in _NOT_AMOUNT for w in words) and not any(w in ("debit", "credit", "balance", "total", "amount") for w in words): return False
    return any(word in text for word in _AMOUNT_WORDS)


_ISO_DAY = _re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def display_cells(values):
    """Dates are shown DD-MM-YYYY everywhere: a cell holding a YYYY-MM-DD date is turned around (data is unchanged)."""
    if isinstance(values, str) or not isinstance(values, (list, tuple)): return values
    shown = []
    for value in values:
        if value is None or value == "None": value = ""  # 2.9.101: an empty cell, not the word None
        if isinstance(value, str):
            match = _ISO_DAY.match(value.strip())
            if match: value = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        shown.append(value)
    return type(values)(shown) if isinstance(values, tuple) else shown


def _iso_to_shown(value):
    if isinstance(value, str):
        match = _ISO_DAY.match(value.strip())
        if match: return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return None


def _install_date_display():
    """Tables SHOW dates as DD-MM-YYYY, but the program still READS the original YYYY-MM-DD back from the table
    (item(..., "values"), set(...)), so editing, saving and exporting keep working with the real data."""
    if getattr(ttk.Treeview, "_saber_dates", False): return
    real_insert, real_item, real_set, real_delete = ttk.Treeview.insert, ttk.Treeview.item, ttk.Treeview.set, ttk.Treeview.delete

    def remember(tree, iid, values):
        store = tree.__dict__.setdefault("_saber_iso", {}); kept = {}; shown = list(values)
        for index, value in enumerate(values):
            text = _iso_to_shown(value)
            if text is not None: kept[index] = (text, value); shown[index] = text
        if kept: store[str(iid)] = kept
        else: store.pop(str(iid), None)
        return tuple(shown) if isinstance(values, tuple) else shown

    def original(tree, iid, values):
        kept = tree.__dict__.get("_saber_iso", {}).get(str(iid))
        if not kept or not isinstance(values, (list, tuple)): return values
        values = list(values)
        for index, (text, raw) in kept.items():
            if index < len(values) and str(values[index]) == text: values[index] = raw
        return tuple(values)

    def insert(self, parent, index, iid=None, **kw):
        values = kw.get("values")
        if not isinstance(values, (list, tuple)): return real_insert(self, parent, index, iid, **kw)
        kw["values"] = shown = display_cells(values)
        new_iid = real_insert(self, parent, index, iid, **kw)
        remember(self, new_iid, values); return new_iid

    def item(self, item_id, option=None, **kw):
        if isinstance(kw.get("values"), (list, tuple)): kw["values"] = remember(self, item_id, kw["values"])
        result = real_item(self, item_id, option, **kw)
        if kw: return result
        if option == "values": return original(self, item_id, result)
        if option is None and isinstance(result, dict) and "values" in result: result["values"] = original(self, item_id, result["values"])
        return result

    def set_(self, item_id, column=None, value=None):
        if column is None:
            result = real_set(self, item_id)
            kept = self.__dict__.get("_saber_iso", {}).get(str(item_id))
            if kept and isinstance(result, dict):
                names = list(self["columns"])
                for index, (text, raw) in kept.items():
                    if index < len(names) and str(result.get(names[index])) == text: result[names[index]] = raw
            return result
        names = list(self["columns"])
        try: index = names.index(column) if not isinstance(column, int) and not str(column).startswith("#") else (int(str(column).lstrip("#")) - (1 if str(column).startswith("#") else 0))
        except (ValueError, TypeError): index = None
        store = self.__dict__.setdefault("_saber_iso", {})
        if value is None:
            current = real_set(self, item_id, column)
            kept = store.get(str(item_id), {})
            if index in kept and str(current) == kept[index][0]: return kept[index][1]
            return current
        text = _iso_to_shown(value)
        if index is not None:
            kept = store.setdefault(str(item_id), {})
            if text is not None: kept[index] = (text, value)
            else: kept.pop(index, None)
        return real_set(self, item_id, column, text if text is not None else value)

    def delete(self, *items):
        store = self.__dict__.get("_saber_iso")
        if store:
            for iid in items: store.pop(str(iid), None)
        return real_delete(self, *items)

    ttk.Treeview.insert, ttk.Treeview.item, ttk.Treeview.set, ttk.Treeview.delete = insert, item, set_, delete
    ttk.Treeview._saber_dates = True


_install_date_display()


def _install_column_fit():
    """2.9.101: every table shows its column titles and values in full, and fills its width.
    A column is never narrower than its title (and the values of the first rows, up to 320 pixels); when the table is wider
    than its columns, the extra space is shared between them. Hidden columns (width 0) stay hidden."""
    if getattr(ttk.Treeview, "_saber_fit", False): return
    real_heading, real_column, real_insert = ttk.Treeview.heading, ttk.Treeview.column, ttk.Treeview.insert

    def schedule(tree):
        if tree.__dict__.get("_fit_pending"): return
        tree.__dict__["_fit_pending"] = True
        try: tree.after_idle(lambda: fit(tree))
        except tk.TclError: pass

    def fonts(tree):
        cached = tree.__dict__.get("_fit_fonts")
        if cached: return cached
        style = ttk.Style(tree); name = str(tree.cget("style") or "Treeview")
        head = style.lookup(name + ".Heading", "font") or style.lookup("Treeview.Heading", "font") or "TkHeadingFont"
        body = style.lookup(name, "font") or style.lookup("Treeview", "font") or "TkDefaultFont"
        try: cached = (tkfont.Font(tree, font=head), tkfont.Font(tree, font=body))
        except tk.TclError: cached = (tkfont.nametofont("TkHeadingFont"), tkfont.nametofont("TkDefaultFont"))
        tree.__dict__["_fit_fonts"] = cached
        return cached

    def fit(tree):
        tree.__dict__["_fit_pending"] = False
        try:
            if not tree.winfo_exists(): return
            columns = list(tree["columns"]); shown = list(tree["displaycolumns"])
            if not columns: return
            if not shown or shown[0] == "#all": shown = columns
            head_font, body_font = fonts(tree)
            base = tree.__dict__.setdefault("_fit_base", {})
            rows = tree.get_children("")[:30]
            widths = {}
            for column in shown:
                wanted = base.get(column)
                if wanted is None: wanted = base[column] = int(real_column(tree, column, "width"))
                if wanted <= 0: continue  # hidden on purpose
                need = head_font.measure(str(real_heading(tree, column, "text") or "")) + 22
                index = columns.index(column)
                for row in rows:
                    values = tree.item(row, "values")
                    if index < len(values): need = max(need, min(320, body_font.measure(str(values[index])) + 16))
                widths[column] = max(wanted, need)
            if not widths: return
            total = sum(widths.values()) + (int(real_column(tree, "#0", "width")) if "tree" in str(tree.cget("show")) else 0)
            space = tree.winfo_width() - 4
            if space > total + 8:
                extra = space - total; share = sum(widths.values())
                for column in widths: widths[column] += int(extra * widths[column] / share)
            # 2.9.103: Tk squeezes stretchable columns back into the window (titles cut again): when the columns are wider
            # than the table and it can scroll sideways, they keep their width and the horizontal scrollbar shows the rest
            keep = total > space + 8 and bool(str(tree.cget("xscrollcommand") or ""))
            for column, width in widths.items():
                real_column(tree, column, width=width, stretch=not keep)
        except (tk.TclError, ValueError, ZeroDivisionError):
            return

    def on_resize(event):
        tree = event.widget
        if tree.__dict__.get("_fit_last") != event.width:
            tree.__dict__["_fit_last"] = event.width; schedule(tree)

    def watch(tree):
        if not tree.__dict__.get("_fit_bound"):
            tree.__dict__["_fit_bound"] = True
            try: tree.bind("<Configure>", on_resize, add="+")
            except tk.TclError: pass
        schedule(tree)

    def heading(self, column, option=None, **kw):
        result = real_heading(self, column, option, **kw)
        if "text" in kw: watch(self)
        return result

    def column(self, column, option=None, **kw):
        if "width" in kw:
            try: self.__dict__.setdefault("_fit_base", {})[column] = int(kw["width"])
            except (TypeError, ValueError): pass
        result = real_column(self, column, option, **kw)
        if kw: watch(self)
        return result

    def insert(self, parent, index, iid=None, **kw):
        new_iid = real_insert(self, parent, index, iid, **kw)
        if self.__dict__.get("_fit_bound") and len(self.get_children("")) <= 30: schedule(self)
        return new_iid

    ttk.Treeview.heading, ttk.Treeview.column, ttk.Treeview.insert = heading, column, insert
    ttk.Treeview._saber_fit = True


_install_column_fit()


def flow_toolbar(frame, gap=4):
    """A row of buttons that wraps onto a second line when the window is narrow, instead of being cut off on the
    right. Works on a frame already filled with pack(side=left / right): the same widgets, same order.
    Can be called again after the frame's contents were rebuilt (the new packed widgets join the flow)."""
    slaves = frame.pack_slaves()
    if not slaves: return frame
    def padding(info, key):
        value = info.get(key, 0)
        parts = [int(float(p)) for p in str(value).split()] if not isinstance(value, (list, tuple)) else [int(p) for p in value]
        return (parts[0], parts[-1]) if parts else (0, 0)
    entries = []
    for widget in slaves:
        info = widget.pack_info(); entries.append((widget, info.get("side", "top"), padding(info, "padx"), padding(info, "pady")))
        widget.pack_forget()
    order = [e for e in entries if e[1] != "right"] + list(reversed([e for e in entries if e[1] == "right"]))
    first_time = not getattr(frame, "_saber_flow", False)
    frame._flow_order = [e for e in getattr(frame, "_flow_order", []) if e[0].winfo_exists()] + order
    frame._saber_flow = True; frame._flow_pending = False
    try:
        import arabic_ui
        if arabic_ui.active(): frame._flow_rtl = True
    except ImportError: pass
    mirrored = getattr(frame, "_flow_rtl", False)

    def inner_offsets():
        """2.9.97: a titled box (LabelFrame) or a padded frame. Tk already places the rows inside the border and below the
        title, so the rows only move by the padding - but the box HEIGHT must count the title, border and padding (it did
        not, and the box was cut in half: Cash Budget / Budget 'from a year + %'). Returns (left, top, extra_height)."""
        def pixels(option):
            try: return int(round(frame.winfo_fpixels(str(frame.cget(option)) or "0")))
            except (tk.TclError, ValueError): return 0
        border = pixels("borderwidth") + pixels("highlightthickness")
        padx, pady = pixels("padx"), pixels("pady")
        title = 0
        if isinstance(frame, tk.LabelFrame) and str(frame.cget("text") or ""):
            try:
                import tkinter.font as tkfont
                title = tkfont.Font(root=frame, font=frame.cget("font")).metrics("linespace")
            except tk.TclError: title = 16
        return padx, pady, 2 * border + title + 2 * pady, 2 * padx

    def layout():
        frame._flow_pending = False
        if not frame.winfo_exists(): return
        left0, top0, extra_height, extra_width = inner_offsets()
        width = frame.winfo_width() - extra_width
        if width <= 1: width = max(frame.winfo_reqwidth(), 600)
        x = y = 0; row = 0
        for widget, _side, (left, right), (top, bottom) in frame._flow_order:
            if not widget.winfo_exists() or getattr(widget, "_flow_hidden", False): continue
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x > 0 and x + left + w + right > width: x = 0; y += row + gap; row = 0
            if mirrored: widget.place(x=left0 + width - x - left - w, y=top0 + y + top)  # 2.9.118: Arabic, from the right
            else: widget.place(x=left0 + x + left, y=top0 + y + top)
            x += left + w + right; row = max(row, top + h + bottom)
        height = max(1, y + row + extra_height)
        if int(frame.cget("height") or 0) != height: frame.configure(height=height)

    def schedule(_event=None):
        if not getattr(frame, "_flow_pending", False) and frame.winfo_exists():
            frame._flow_pending = True
            frame.after_idle(layout)

    frame._flow_schedule = schedule
    if first_time:
        try: frame.pack_propagate(False)
        except tk.TclError: pass
        try:
            if frame.winfo_manager() == "pack": frame.pack_configure(fill="x")
        except tk.TclError: pass
        frame.bind("<Configure>", schedule, add="+")
    widest = max((w.winfo_reqwidth() + l + r for w, _s, (l, r), _p in frame._flow_order if w.winfo_exists()), default=100)
    frame.configure(width=widest)
    for widget, *_rest in order: widget.bind("<Configure>", lambda _e, f=frame: f._flow_schedule(), add="+")
    schedule()
    return frame


def flow_toolbars(*frames):
    for frame in frames:
        try: flow_toolbar(frame)
        except Exception: logging.getLogger("saber.ignored").debug("Toolbar left as it was", exc_info=True)


# ---------------------------------------------------------------- 2.9.66: select several rows, see their totals
def enable_drag_select(tree):
    """Ctrl+click and Shift+click already select several rows; this adds: press the mouse on a row and drag over the
    rows below (or above) to select them all."""
    state = {"anchor": None}
    def press(event):
        state["anchor"] = None
        if event.state & 0x0005: return  # Shift / Ctrl: the Treeview's own multi-selection
        if tree.identify_region(event.x, event.y) in ("cell", "tree"): state["anchor"] = tree.identify_row(event.y) or None
    def drag(event):
        anchor = state["anchor"]
        if not anchor or not tree.exists(anchor): return
        row = tree.identify_row(event.y)
        if not row:  # dragged above / below the visible rows: scroll and take the edge row
            rows = tree.get_children("")
            if not rows: return
            if event.y < 0: tree.yview_scroll(-1, "units")
            elif event.y > tree.winfo_height(): tree.yview_scroll(1, "units")
            return
        rows = list(tree.get_children("")); a, b = rows.index(anchor), rows.index(row)
        tree.selection_set(rows[min(a, b):max(a, b) + 1]); tree.focus(row)
    tree.bind("<ButtonPress-1>", press, add="+"); tree.bind("<B1-Motion>", drag, add="+")
    return tree


def _amount(value):
    text = str(value if value is not None else "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"): text = "-" + text[1:-1]
    try: return float(text)
    except ValueError: return None


def selection_totals(tree, columns, label, hint=None):
    """With 2 or more rows selected, the label shows how many and the total of every amount column (Debit, Credit,
    Total, VAT...): an automatic sum like the status bar of Excel."""
    amount_columns = [(index, key, title) for index, (key, title, *_rest) in enumerate(columns) if is_amount_column(key, title)]
    def update(_event=None):
        skip = getattr(tree, "_totals_skip", ())  # e.g. a running balance, whose sum means nothing
        try: selected = tree.selection()
        except tk.TclError: return
        if len(selected) < 2 or not amount_columns:
            label.config(text="")
            if hint is not None and not hint.winfo_manager(): hint.pack(side="right")
            return
        if hint is not None and hint.winfo_manager(): hint.pack_forget()  # room for the totals
        sums = {}
        for iid in selected:
            values = tree.item(iid, "values")
            for index, key, title in amount_columns:
                if key in skip: continue
                number = _amount(values[index]) if index < len(values) else None
                if number is not None: sums[title] = sums.get(title, 0.0) + number
        label.config(text=f"{len(selected)} selected   " + "   ".join(f"{title}: {total:,.2f}" for title, total in sums.items()))
    tree.bind("<<TreeviewSelect>>", update, add="+")
    return update


def company_settings(app):
    """2.9.71: the settings of the open company, read once per company / year (main currencies, VAT rate ...)."""
    client = getattr(app, "client", None)
    key = (getattr(client, "company_id", None), getattr(client, "fiscal_year", None))
    cache = getattr(app, "_main_currency_cache", None)
    if not cache or cache[0] != key or not isinstance(cache[1], dict):
        try: values = client.settings() if client is not None else {}
        except Exception: values = {}
        cache = (key, values if isinstance(values, dict) else {})
        try: app._main_currency_cache = cache
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    return cache[1]


def main_currency(app, which=1):
    """2.9.71: the company's two main currencies (chosen when the company was created, changed in Settings > General):
    1 = the first (base) currency, 2 = the second one. New vouchers, invoices, payments, imports and reports start with them."""
    values = company_settings(app)
    return str(values.get("base_currency" if int(which) == 1 else "second_currency") or ("USD" if int(which) == 1 else "LBP")).upper()


def vat_rate(app):
    """2.9.72: the company's standard VAT rate in % as a number (11 in Lebanon, 5 in the Emirates ...)."""
    try: return float(str(company_settings(app).get("vat_rate") or "11").replace("%", "").strip())
    except (TypeError, ValueError): return 11.0


def vat_rate_text(app):
    """'11%', '5%', '7.5%'"""
    return f"{vat_rate(app):g}%"


def account_names(app):
    """2.9.79: {account number: name} of the open company, read once (Chart of Accounts changes clear it)."""
    names = getattr(app, "_all_accounts", None)
    if not isinstance(names, dict) or not names:
        try: names = {str(a["code"]): a.get("name_en") or "" for a in app.client.accounts()}
        except Exception: names = {}
        if names:
            try: app._all_accounts = names
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    return names or {}


def account_label(app, value):
    """2.9.79: an account is always shown as 'number - name' (lists, sheets, forms). Text already labelled is kept."""
    text = str(value or "").strip()
    if not text or " - " in text: return text
    name = account_names(app).get(text)
    return f"{text} - {name}" if name else text


def accounting_setup(app, refresh=False):
    """2.9.81: the Accounting Settings of the open company for this user (hidden modules / reports, default accounts)."""
    client = getattr(app, "client", None)
    key = (getattr(client, "company_id", None), getattr(client, "fiscal_year", None))
    cache = getattr(app, "_accounting_setup_cache", None)
    if refresh or not cache or cache[0] != key:
        try: values = client.accounting_setup() if client is not None else {}
        except Exception: values = {}
        cache = (key, values if isinstance(values, dict) else {})
        try: app._accounting_setup_cache = cache
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    return cache[1]


def default_account_code(app, key):
    """2.9.81: a default posting account of Accounting Settings (the program default when it cannot be read)."""
    import accounting_setup as rules
    for row in accounting_setup(app).get("defaults") or []:
        if row.get("key") == key and row.get("account"): return str(row["account"])
    return rules.DEFAULT_ACCOUNTS[key][1]


def hidden_view(app):
    """2.9.81: what is hidden for this user in this company: the company's choice plus his own."""
    values = accounting_setup(app)
    return set(values.get("hidden") or []) | set(values.get("user_hidden") or [])


def account_code(value):
    """The account number of 'number - name' (or of a bare number)."""
    return str(value or "").split(" - ", 1)[0].strip()


def vat_currency(app, which=1):
    """2.9.72: the currencies of the VAT return: 1 = LBP in Lebanon (AED, EUR ... elsewhere), 2 = the one shown next to it (USD)."""
    values = company_settings(app)
    return str(values.get("vat_currency" if int(which) == 1 else "vat_second_currency") or ("LBP" if int(which) == 1 else "USD")).upper()


def search_arrows(entry, tree, choose, variable=None):
    """2.9.78: in a search box over a list, Up / Down (and Page Up / Down) move the highlighted row while you keep typing,
    Enter takes the highlighted row (the first one when none is), and the first match is highlighted after every key."""
    def first():
        try:
            rows = tree.get_children()
            if rows and not tree.selection(): tree.selection_set(rows[0]); tree.focus(rows[0]); tree.see(rows[0])
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    def move(step):
        rows = list(tree.get_children())
        if not rows: return "break"
        current = tree.selection()
        index = rows.index(current[0]) if current and current[0] in rows else -1
        index = max(0, min(len(rows) - 1, index + step))
        tree.selection_set(rows[index]); tree.focus(rows[index]); tree.see(rows[index])
        return "break"
    def enter(_event=None):
        rows = tree.get_children()
        if not rows: return "break"
        if not tree.selection(): tree.selection_set(rows[0]); tree.focus(rows[0])
        choose(); return "break"
    entry.bind("<Down>", lambda _e: move(1)); entry.bind("<Up>", lambda _e: move(-1))
    entry.bind("<Next>", lambda _e: move(10)); entry.bind("<Prior>", lambda _e: move(-10)); entry.bind("<Return>", enter)
    if variable is not None: variable.trace_add("write", lambda *_a: entry.after_idle(first))
    entry.after_idle(first)


def add_search_bar(tree, keep_tags=("section", "header", "group", "total")):
    """2.9.78: the same Search box as Uploaded Data, for a table built on its own (asset register, depreciation, DOE,
    warehouses, recipes, bank reconciliation, reports): every column is searched as you type, Clear shows everything
    again, and rows tagged as titles / totals of a report stay visible. Call it once the table is placed."""
    if getattr(tree, "_search_bar", None) is not None: return tree._search_bar
    holder = tree if tree.winfo_manager() == "pack" else tree.master
    if holder.winfo_manager() != "pack": return None
    bar = tk.Frame(holder.master, bg=LIGHT); bar.pack(fill="x", padx=4, pady=(4, 0), before=holder)
    variable = tk.StringVar()
    tk.Label(bar, text="Search:", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
    entry = tk.Entry(bar, textvariable=variable, width=30); entry._is_search_entry = True; entry.pack(side="left", padx=6)
    tk.Button(bar, text="Clear", command=lambda: variable.set(""), bg=NAVY, fg="white", border=0, padx=10, pady=2).pack(side="left")
    real_insert, real_delete = tree.insert, tree.delete
    tree._search_rows = []; counter = {"n": 0}
    def kept(kwargs):
        tags = kwargs.get("tags") or ()
        tags = (tags,) if isinstance(tags, str) else tags
        return any(tag in keep_tags for tag in tags) or row_matches_search(kwargs.get("values", ()), variable.get())
    def tracked_insert(parent_id, index, *args, **kwargs):
        counter["n"] += 1; kwargs.setdefault("iid", f"find-{id(tree)}-{counter['n']}")
        tree._search_rows.append((parent_id, index, args, kwargs))
        if parent_id == "" and not kept(kwargs): return kwargs["iid"]
        return real_insert(parent_id, index, *args, **kwargs)
    def tracked_delete(*item_ids):
        requested = {str(i) for i in item_ids}
        if requested >= {str(i) for i in tree.get_children("")}: tree._search_rows.clear()
        else: tree._search_rows = [r for r in tree._search_rows if str(r[3].get("iid")) not in requested]
        present = [i for i in item_ids if tree.exists(i)]
        if present: real_delete(*present)
    def apply(*_a):
        visible = tree.get_children("")
        if visible: real_delete(*visible)
        for parent_id, index, args, kwargs in tree._search_rows:
            if parent_id == "" and kept(kwargs): real_insert(parent_id, "end", *args, **kwargs)
    pending = {"id": None}
    def schedule(*_a):
        if pending["id"] is not None:
            try: tree.after_cancel(pending["id"])
            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        pending["id"] = tree.after(180, apply)
    variable.trace_add("write", schedule)
    tree.insert = tracked_insert; tree.delete = tracked_delete; tree.search_var = variable; tree._search_bar = bar
    return bar


def bulk_action(title, labels, action, parent=None):
    """2.9.69: run `action(key)` for every selected record; one question before, one summary after.
    labels = [(key, text shown)]. Returns the keys that were done."""
    if not labels: return []
    done, failed = [], []
    for key, text in labels:
        try: action(key); done.append(key)
        except Exception as exc: failed.append(f"{text}: {exc}")
    message = f"{len(done)} done" + (f", {len(failed)} not done:\n\n" + "\n".join(failed[:15]) + (f"\n... and {len(failed) - 15} more" if len(failed) > 15 else "") if failed else ".")
    (messagebox.showwarning if failed else messagebox.showinfo)(title, message, **({"parent": parent} if parent else {}))
    return done


def column_toggles(tree, keys, store_key):
    """2.9.69: tick boxes next to the Search box that show / hide some columns of a table (kept on this computer)."""
    import desktop_layout
    bar = getattr(tree, "_search_bar", None)
    if bar is None: return {}
    titles = getattr(tree, "_column_titles", {})
    hidden = set(desktop_layout.layout_settings().get("hidden_columns", {}).get(store_key, []))
    variables = {}
    def apply():
        shown = [key for key in tree["columns"] if key not in keys or variables[key].get()]
        tree.configure(displaycolumns=shown)
        saved = dict(desktop_layout.layout_settings().get("hidden_columns", {}))
        saved[store_key] = [key for key in keys if not variables[key].get()]
        desktop_layout.save_layout_settings(hidden_columns=saved)
    box = tk.Frame(bar, bg=LIGHT); totals = getattr(tree, "_selection_totals", None)
    box.pack(side="left", padx=(14, 0), **({"before": totals} if totals is not None else {}))
    tk.Label(box, text="Show:", bg=LIGHT, font=("Segoe UI", 9, "bold")).pack(side="left")
    for key in keys:
        variables[key] = tk.BooleanVar(master=tree, value=key not in hidden)
        tk.Checkbutton(box, text=titles.get(key, key), variable=variables[key], command=apply, bg=LIGHT).pack(side="left")
    if hidden: tree.configure(displaycolumns=[key for key in tree["columns"] if key not in hidden])
    tree._column_toggles = variables
    return variables
