"""2.9.118: the program in Arabic, laid out from right to left.

Chosen with Language = ar on the sign-in screen. Nothing changes in English: every hook below passes straight through
while Arabic is off.

How it works, without touching the screens one by one:
- texts: a label / button / box title / tab / menu item / window title / message whose English text is in
  arabic_texts.AR is shown in Arabic. Lists (combobox values) and data stay as they are, so the logic is unchanged.
- right to left: pack(side="left") becomes the right side, grid columns are counted from the right, w <-> e in
  anchors and sticky, and the columns of tables run from the right.
  The program still asks and gets its own (left to right) values from pack_info / grid_info / grid_slaves and from
  notebook.tab(..., "text"), so every check it makes on its own layout or tab names keeps working.
"""
import re
import tkinter as tk
from tkinter import messagebox, ttk

from arabic_texts import AR, PATTERNS

ON = False
MIRROR = 199  # grid column c is placed in column MIRROR - c (empty columns take no room)
_ARABIC = re.compile("[؀-ۿ]")
_SIDES = {"left": "right", "right": "left"}
_ANCHORS = {"w": "e", "e": "w", "nw": "ne", "ne": "nw", "sw": "se", "se": "sw"}
TEXT_WIDGETS = {"label", "button", "checkbutton", "radiobutton", "labelframe", "menubutton", "message",
                "ttk::label", "ttk::button", "ttk::checkbutton", "ttk::radiobutton", "ttk::labelframe", "ttk::menubutton"}
_REVERSE = {}
_UPPER = {}


def _add_i18n():
    try:
        import i18n
        english, arabic = i18n.TRANSLATIONS["en"], i18n.TRANSLATIONS["ar"]
        for key, text in english.items():
            if key in arabic and text not in AR: AR[text] = arabic[key]
    except (ImportError, KeyError):
        pass


_add_i18n()


def has_arabic(text):
    return bool(_ARABIC.search(str(text or "")))


_EDGES = " \u25be\u25b8\u203a\u2022\u2192\u2190:.\u2026*"
MISSING = set()  # English texts met on screen without an Arabic one (to add them later)


def _lookup(core):
    hit = AR.get(core)
    if hit is None and core.isupper() and len(core) > 2: hit = _upper().get(core)  # SALES, NET PROFIT
    if hit is None and core[:1].islower(): hit = AR.get(core[:1].upper() + core[1:])
    return hit


def translate(text):
    """The Arabic text for an English one (the text itself when there is none)."""
    if not isinstance(text, str) or not text.strip(): return text
    if text in AR: return AR[text]
    if has_arabic(text):
        for mark in (" | ", " / "):  # "Saved | تم الحفظ", "Help / مساعدة": the Arabic half
            if mark in text:
                right = text.rsplit(mark, 1)[1]
                if has_arabic(right) and not has_arabic(text.rsplit(mark, 1)[0]): return right.strip()
        return text
    hit = _lookup(text)
    if hit: return hit
    core = text.strip(_EDGES)
    if core and core != text:  # "\u25be  SALES", "SALES  \u203a", "Amount:" - the same marks around the Arabic
        hit = _lookup(core)
        if hit:
            start = text.index(core); return text[:start] + hit + text[start + len(core):]
    for pattern, arabic in _patterns():
        match = pattern.fullmatch(text)
        if match:
            parts = [translate(part) if part else "" for part in match.groups()]
            return arabic.format(None, *parts)
    if any(ch.isalpha() for ch in text) and len(MISSING) < 5000: MISSING.add(text)
    return text


_COMPILED = []


def _patterns():
    if not _COMPILED: _COMPILED.extend((re.compile(pattern), arabic) for pattern, arabic in PATTERNS)
    return _COMPILED


def _upper():
    if not _UPPER:
        for key, value in AR.items(): _UPPER.setdefault(key.upper(), value)
    return _UPPER


def english(text):
    """The English text behind an Arabic one shown on screen (the text itself otherwise)."""
    if not _REVERSE:
        for key, value in AR.items(): _REVERSE.setdefault(value, key)
    return _REVERSE.get(text, text)


def active():
    return ON


# ---------------------------------------------------------------- small helpers
def _flip_anchor(value):
    return _ANCHORS.get(value, value) if isinstance(value, str) else value


def _flip_sticky(value):
    if not isinstance(value, str) or not value: return value
    return "".join({"e": "w", "w": "e"}.get(ch, ch) for ch in value)


def _flip_pad(value):
    if isinstance(value, (list, tuple)) and len(value) == 2: return (value[1], value[0])
    if value is None or isinstance(value, (int, float)): return value
    parts = str(value).split()
    return (parts[1], parts[0]) if len(parts) == 2 else value


def _merged(cnf, kw):
    options = {}
    for part in (cnf, kw):
        if isinstance(part, dict): options.update(part)
        elif isinstance(part, (list, tuple)):
            for item in part:
                if isinstance(item, dict): options.update(item)
    return options


def _widget_options(name, options):
    """Texts and anchors of a widget being made or changed."""
    if name in TEXT_WIDGETS:
        if isinstance(options.get("text"), str): options["text"] = translate(options["text"])
        if "anchor" in options: options["anchor"] = _flip_anchor(options["anchor"])
        if options.get("justify") in _SIDES: options["justify"] = _SIDES[options["justify"]]
        if options.get("compound") in _SIDES and name.endswith("button"): options["compound"] = _SIDES[options["compound"]]
    return options


def _reversed_columns(tree, wanted):
    """The columns of a table from the right: the last column first."""
    try:
        if wanted in (None, "#all", ("#all",), ["#all"]): wanted = tree.tk.splitlist(_real["cget"](tree, "columns"))
        elif isinstance(wanted, str): wanted = tree.tk.splitlist(wanted)
        return list(reversed(list(wanted)))
    except tk.TclError:
        return wanted


# ---------------------------------------------------------------- the hooks
_real = {}


def _base_init(self, master, widgetName, cnf={}, kw={}, extra=()):  # noqa: B006 - the same signature as tkinter
    if not ON: return _real["init"](self, master, widgetName, cnf, kw, extra)
    options = _widget_options(widgetName, _merged(cnf, kw))
    columns = None
    if widgetName == "ttk::treeview" and "columns" in options:
        columns = options.pop("displaycolumns", "#all")
    _real["init"](self, master, widgetName, options, {}, extra)
    if columns is not None:
        try: _real["configure"](self, "configure", {"displaycolumns": _reversed_columns(self, columns)}, {})
        except tk.TclError: pass
    if widgetName == "ttk::treeview":  # a wide table opens on its first columns, which are now on the right
        self.bind("<Map>", lambda _e, tree=self: tree.after_idle(lambda: show_right_end(tree)), add="+")


def show_right_end(widget):
    """Scroll a wide table / page to its right end (where its first columns are in Arabic)."""
    try:
        if widget.winfo_exists() and widget.xview() != (0.0, 1.0): widget.xview_moveto(1.0)
    except tk.TclError:
        pass


def _configure(self, cmd, cnf, kw):
    if not ON or cmd != "configure": return _real["configure"](self, cmd, cnf, kw)
    if isinstance(cnf, str) or (cnf is None and not kw): return _real["configure"](self, cmd, cnf, kw)
    options = _widget_options(getattr(self, "widgetName", ""), _merged(cnf, kw))
    if getattr(self, "widgetName", "") == "ttk::treeview" and ("displaycolumns" in options or "columns" in options):
        wanted = options.pop("displaycolumns", "#all")
        result = _real["configure"](self, cmd, options, {}) if options else None
        _real["configure"](self, cmd, {"displaycolumns": _reversed_columns(self, wanted)}, {})
        return result
    return _real["configure"](self, cmd, options, {})


def _pack(self, cnf={}, **kw):  # noqa: B006
    if not ON: return _real["pack"](self, cnf, **kw)
    options = _merged(cnf, kw)
    if "side" in options: options["side"] = _SIDES.get(options["side"], options["side"])
    if "anchor" in options: options["anchor"] = _flip_anchor(options["anchor"])
    if "padx" in options: options["padx"] = _flip_pad(options["padx"])
    self.__dict__["_rtl_pack"] = True
    return _real["pack"](self, options)


def _pack_info(self):
    info = _real["pack_info"](self)
    if self.__dict__.get("_rtl_pack"):
        info["side"] = _SIDES.get(info.get("side"), info.get("side"))
        if "anchor" in info: info["anchor"] = _flip_anchor(info["anchor"])
        if "padx" in info: info["padx"] = _flip_pad(info["padx"])
    return info


def _grid(self, cnf={}, **kw):  # noqa: B006
    if not ON: return _real["grid"](self, cnf, **kw)
    options = _merged(cnf, kw)
    for short, full in (("col", "column"), ("cs", "columnspan")):
        if short in options: options[full] = options.pop(short)
    known = self.__dict__.get("_rtl_grid")
    if "column" in options or "columnspan" in options or known is None:
        column = int(options.get("column", known[0] if known else 0))
        span = int(options.get("columnspan", known[1] if known else 1))
        self.__dict__["_rtl_grid"] = (column, span)
        options["column"] = MIRROR - column - span + 1
    if "sticky" in options: options["sticky"] = _flip_sticky(options["sticky"])
    if "padx" in options: options["padx"] = _flip_pad(options["padx"])
    if "in_" not in options and "in" not in options:
        try:
            master = self.master
            if master is not None and not master.__dict__.get("_rtl_anchor"):
                master.__dict__["_rtl_anchor"] = True
                if str(master.tk.call("grid", "anchor", master._w)) == "nw": master.grid_anchor("ne")
        except (tk.TclError, AttributeError): pass
    return _real["grid"](self, options)


def _grid_info(self):
    info = _real["grid_info"](self)
    known = self.__dict__.get("_rtl_grid")
    if known and info:
        info["column"] = known[0]
        if "sticky" in info: info["sticky"] = _flip_sticky(info["sticky"])
        if "padx" in info: info["padx"] = _flip_pad(info["padx"])
    return info


def _mirror_index(index):
    if isinstance(index, bool): return index
    if isinstance(index, int): return MIRROR - index
    if isinstance(index, str) and index.isdigit(): return MIRROR - int(index)
    if isinstance(index, (list, tuple)): return type(index)(_mirror_index(i) for i in index)
    return index


def _columnconfigure(self, index, cnf={}, **kw):  # noqa: B006
    if ON: index = _mirror_index(index)
    return _real["columnconfigure"](self, index, cnf, **kw)


def _grid_slaves(self, row=None, column=None):
    if ON and column is not None: column = _mirror_index(column)
    return _real["grid_slaves"](self, row, column)


def _tab_key(notebook, tab_id):
    try: return str(notebook.tabs()[notebook.index(tab_id)])
    except (tk.TclError, IndexError, TypeError): return str(tab_id)


def _notebook_add(self, child, **kw):
    if ON and isinstance(kw.get("text"), str):
        self.__dict__.setdefault("_en_tabs", {})[str(child)] = kw["text"]; kw["text"] = translate(kw["text"])
    return _real["nb_add"](self, child, **kw)


def _notebook_insert(self, pos, child, **kw):
    if ON and isinstance(kw.get("text"), str):
        self.__dict__.setdefault("_en_tabs", {})[str(child)] = kw["text"]; kw["text"] = translate(kw["text"])
    return _real["nb_insert"](self, pos, child, **kw)


def _notebook_tab(self, tab_id, option=None, **kw):
    names = self.__dict__.get("_en_tabs")
    if names is not None:
        if option == "text" and not kw:
            key = _tab_key(self, tab_id)
            if key in names: return names[key]
        if isinstance(kw.get("text"), str) and ON:
            names[_tab_key(self, tab_id)] = kw["text"]; kw["text"] = translate(kw["text"])
    return _real["nb_tab"](self, tab_id, option, **kw)


def _heading(self, column, option=None, **kw):
    if ON and isinstance(kw.get("text"), str): kw["text"] = translate(kw["text"])
    return _real["heading"](self, column, option, **kw)


def _menu_add(self, itemType, cnf={}, **kw):  # noqa: B006
    if ON:
        options = _merged(cnf, kw)
        if isinstance(options.get("label"), str): options["label"] = translate(options["label"])
        return _real["menu_add"](self, itemType, options)
    return _real["menu_add"](self, itemType, cnf, **kw)


def _menu_insert(self, index, itemType, cnf={}, **kw):  # noqa: B006
    if ON:
        options = _merged(cnf, kw)
        if isinstance(options.get("label"), str): options["label"] = translate(options["label"])
        return _real["menu_insert"](self, index, itemType, options)
    return _real["menu_insert"](self, index, itemType, cnf, **kw)


def _title(self, string=None):
    if ON and isinstance(string, str): string = translate(string)
    return _real["title"](self, string)


def _show(title=None, message=None, _icon=None, _type=None, **options):
    if ON:
        title = translate(title) if isinstance(title, str) else title
        message = translate(message) if isinstance(message, str) else message
    return _real["show"](title, message, _icon, _type, **options)


def install():
    """Put the hooks in place (once). They do nothing until switch() turns Arabic on."""
    if _real: return
    _real.update(init=tk.BaseWidget.__init__, configure=tk.Misc._configure, cget=tk.Misc.cget,
                 pack=tk.Pack.pack_configure, pack_info=tk.Pack.pack_info,
                 grid=tk.Grid.grid_configure, grid_info=tk.Grid.grid_info,
                 columnconfigure=tk.Misc.grid_columnconfigure, grid_slaves=tk.Misc.grid_slaves,
                 nb_add=ttk.Notebook.add, nb_insert=ttk.Notebook.insert, nb_tab=ttk.Notebook.tab,
                 heading=ttk.Treeview.heading, menu_add=tk.Menu.add, menu_insert=tk.Menu.insert,
                 title=tk.Wm.wm_title, show=messagebox._show)
    tk.BaseWidget.__init__ = _base_init
    tk.Misc._configure = _configure
    tk.Pack.pack_configure = tk.Pack.pack = _pack
    tk.Pack.pack_info = tk.Pack.info = _pack_info
    tk.Grid.grid_configure = tk.Grid.grid = _grid
    tk.Grid.grid_info = _grid_info
    tk.Misc.grid_columnconfigure = tk.Misc.columnconfigure = _columnconfigure
    tk.Misc.grid_slaves = _grid_slaves
    ttk.Notebook.add, ttk.Notebook.insert, ttk.Notebook.tab = _notebook_add, _notebook_insert, _notebook_tab
    ttk.Treeview.heading = _heading
    tk.Menu.add, tk.Menu.insert = _menu_add, _menu_insert
    tk.Wm.wm_title = tk.Wm.title = _title
    messagebox._show = _show


def switch(root, language):
    """Arabic on (language 'ar') or off. Screens made from now on follow it."""
    global ON
    install()
    ON = str(language or "").lower().startswith("ar")
    try: ttk.Style(root).configure("TNotebook", tabposition="ne" if ON else "nw")
    except tk.TclError: pass
    return ON
