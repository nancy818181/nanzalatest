"""2.9.116: small line icons for the menu and the main buttons, drawn by the program (no image files, no icon font).

Each icon is drawn large on a transparent square and scaled down, so the lines stay smooth at 16-20 px on any screen.
icon(name, colour, size) returns a PIL image; tk_icon(...) a Tk PhotoImage kept in a cache (Tk forgets images
nobody holds)."""
from __future__ import annotations

import math

_CACHE = {}
S = 64          # drawing size
W = 5           # line width at the drawing size


def _draw(name, d, c):
    line = lambda *pts: d.line(pts, fill=c, width=W, joint="curve")
    box = lambda x0, y0, x1, y1, r=6: d.rounded_rectangle((x0, y0, x1, y1), radius=r, outline=c, width=W)
    dot = lambda x, y, r=3: d.ellipse((x - r, y - r, x + r, y + r), fill=c)
    if name == "home":
        line((8, 30), (32, 10), (56, 30)); line((15, 25), (15, 54), (49, 54), (49, 25)); box(27, 38, 37, 54, 2)
    elif name == "invoice":
        box(14, 6, 50, 58, 4); [line((22, y), (42, y)) for y in (20, 30, 40)]; line((30, 48), (42, 48))
    elif name == "upload":
        box(10, 8, 54, 56, 6); [line((18, y), (46, y)) for y in (20, 32, 44)]
    elif name == "people":
        d.ellipse((14, 10, 34, 30), outline=c, width=W); d.arc((6, 34, 42, 70), 180, 360, fill=c, width=W)
        d.ellipse((36, 14, 52, 30), outline=c, width=W); d.arc((34, 36, 62, 66), 200, 340, fill=c, width=W)
    elif name == "cart":
        line((6, 12), (16, 12), (22, 42), (50, 42), (56, 20), (19, 20)); dot(25, 52, 4); dot(47, 52, 4)
    elif name == "cash":
        box(6, 16, 58, 48, 4); d.ellipse((24, 24, 40, 40), outline=c, width=W); dot(14, 32); dot(50, 32)
    elif name == "import":
        line((32, 6), (32, 38)); line((20, 26), (32, 38), (44, 26)); line((8, 40), (8, 56), (56, 56), (56, 40))
    elif name == "box":
        line((32, 6), (56, 18), (56, 46), (32, 58), (8, 46), (8, 18), (32, 6)); line((8, 18), (32, 30), (56, 18)); line((32, 30), (32, 58))
    elif name == "voucher":
        box(10, 8, 54, 56, 6); line((32, 8), (32, 56)); line((16, 22), (26, 22)); line((38, 22), (48, 22)); line((16, 34), (26, 34)); line((38, 34), (48, 34))
    elif name == "journal":
        box(12, 6, 52, 58, 4); line((20, 6), (20, 58)); [line((28, y), (44, y)) for y in (20, 30, 40)]
    elif name == "statement":
        box(8, 8, 56, 56, 6); line((8, 22), (56, 22)); line((24, 22), (24, 56)); [line((30, y), (50, y)) for y in (32, 42)]
    elif name == "profit":
        line((8, 54), (56, 54)); line((10, 46), (24, 32), (34, 40), (54, 16)); line((44, 16), (54, 16), (54, 26))
    elif name == "reports":
        line((8, 56), (56, 56)); [box(x, y, x + 10, 56, 2) for x, y in ((12, 34), (27, 20), (42, 8))]
    elif name == "payroll":
        d.ellipse((20, 6, 44, 30), outline=c, width=W); d.arc((8, 34, 56, 82), 180, 360, fill=c, width=W)
    elif name == "vat":
        d.ellipse((10, 10, 24, 24), outline=c, width=W); d.ellipse((40, 40, 54, 54), outline=c, width=W); line((50, 10), (14, 54))
    elif name == "settings":
        cx = cy = 32
        for k in range(8):
            a = k * math.pi / 4; line((cx + 18 * math.cos(a), cy + 18 * math.sin(a)), (cx + 27 * math.cos(a), cy + 27 * math.sin(a)))
        d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=c, width=W); d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), outline=c, width=W)
    elif name == "more":
        [dot(x, 32, 5) for x in (14, 32, 50)]
    elif name == "help":
        d.ellipse((6, 6, 58, 58), outline=c, width=W); d.arc((22, 14, 42, 34), 200, 90, fill=c, width=W); line((32, 34), (32, 40)); dot(32, 48, 4)
    elif name == "plus":
        line((32, 10), (32, 54)); line((10, 32), (54, 32))
    elif name == "check":
        line((10, 34), (26, 50), (54, 16))
    elif name == "printer":
        box(18, 6, 46, 22, 2); box(6, 22, 58, 46, 6); box(18, 38, 46, 58, 2)
    elif name == "trash":
        line((10, 14), (54, 14)); line((24, 14), (26, 6), (38, 6), (40, 14)); line((16, 14), (20, 58), (44, 58), (48, 14)); line((28, 24), (28, 48)); line((36, 24), (36, 48))
    elif name == "export":
        line((32, 40), (32, 8)); line((20, 20), (32, 8), (44, 20)); line((8, 40), (8, 56), (56, 56), (56, 40))
    elif name == "pdf":
        line((14, 6), (40, 6), (52, 18), (52, 58), (14, 58), (14, 6)); line((40, 6), (40, 18), (52, 18)); line((22, 34), (44, 34)); line((22, 44), (38, 44))
    else:
        box(12, 12, 52, 52)


def icon(name, colour="#FFFFFF", size=18, gap=0):
    """The icon as a PIL image; gap = empty pixels on its right (the space before the text of a button)."""
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    _draw(name, ImageDraw.Draw(image), colour)
    small = image.resize((size, size), Image.LANCZOS)
    if not gap: return small
    padded = Image.new("RGBA", (size + gap, size), (0, 0, 0, 0)); padded.paste(small, (0, 0)); return padded


def tk_icon(master, name, colour="#FFFFFF", size=18, gap=0):
    key = (id(master.tk), name, colour, size, gap)
    cached = _CACHE.get(key)
    if cached is None or str(cached) not in master.tk.call("image", "names"):  # a window closed and opened again
        if cached is not None: _CACHE.pop(key, None)
        from PIL import ImageTk
        _CACHE[key] = ImageTk.PhotoImage(icon(name, colour, size, gap), master=master)
    return _CACHE[key]


# page attribute -> icon (pages added later get a plain square)
PAGE_ICONS = {
    "dashboard_tab": "home", "sales_tab": "invoice", "invoices_tab": "upload", "parties_tab": "people",
    "purchases_tab": "cart", "transactions_tab": "cash", "import_tab": "import", "inventory_tab": "box",
    "manual_tab": "voucher", "journal_tab": "journal", "account_reports_tab": "statement", "pnl_tab": "profit",
    "reports_tab": "reports", "payroll_tab": "payroll", "vat_tab": "vat", "settings_tab": "settings",
}


# 2.9.116: the first word of a button -> its icon (only these everyday actions get one)
BUTTON_ICONS = {"new": "plus", "add": "plus", "save": "check", "print": "printer", "delete": "trash",
                "excel": "export", "export": "export", "pdf": "pdf", "import": "import"}
