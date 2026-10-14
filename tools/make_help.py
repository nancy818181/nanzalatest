"""2.9.116: build the picture help (Assets/help/help.html + Assets/help/img/*.png).

Opens Nanza on the screen with a small demo company, takes a picture of every screen, draws the numbered steps of
tools/help_topics.py on it and writes the help page (English and Arabic). Run it again after the screens change, so
the pictures always match the program:

    python tools/make_help.py            (Windows, or Linux with a display / xvfb-run)
"""
from __future__ import annotations

import html
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Assets" / "help"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)
os.environ["SABER_DATA_DIR"] = str(Path(tempfile.mkdtemp()) / "NanzaAccounting")

import tkinter  # noqa: E402
from tkinter import messagebox  # noqa: E402

for _name in ("showerror", "showwarning", "showinfo"): setattr(messagebox, _name, lambda *a, **k: None)
messagebox.askyesno = lambda *a, **k: True

from help_topics import TOPICS, WIZARD  # noqa: E402

GOLD, NAVY = (208, 165, 87), (16, 42, 67)
WIDTH = 1200  # pictures are scaled to this width


def demo_company():
    from client import ApiClient
    from server import run_server
    database = Path(os.environ["SABER_DATA_DIR"]) / "nanza_accounting.db"; database.parent.mkdir(parents=True)
    probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
    threading.Thread(target=run_server, kwargs={"host": "127.0.0.1", "port": port, "database": str(database), "admin_password": "admin12345"}, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: ApiClient(url).login("admin", "admin12345"); break
        except Exception: time.sleep(0.1)  # noqa: BLE001 - the data service is starting
    api = ApiClient(url); api.login("admin", "admin12345")
    if not api.companies(): api.create_company({"name": "Cedar Demo SARL", "year": 2026})
    company = api.companies()[0]; year = company["years"][0]["year"]; api.select_company_year(company["id"], year)
    for i, (who, amount) in enumerate([("Cedar Trading SARL", 1200), ("Byblos Foods", 850), ("Mount Lebanon Clinic", 2300), ("Tripoli Steel", 460)], 1):
        api.create_manual_invoice({"invoice_date": f"{10 + i:02d}-0{i}-{year}", "party_name": who, "kind": "sale", "currency": "USD"},
                                  [{"description": f"Consulting services {i}", "quantity": 1, "unit_price": amount}])
    api.create_manual_invoice({"invoice_date": f"05-02-{year}", "party_name": "Office Supplies Co", "kind": "purchase", "currency": "USD"},
                              [{"description": "Printer paper", "quantity": 10, "unit_price": 12}])
    return url, company, year


def find(widget, text):
    """The first visible button / label / tick box under `widget` whose text is `text` (or starts with it, for 'x *')."""
    starts = text.endswith("*"); text = text.rstrip("* ").strip() if starts else text
    stack = [widget]
    while stack:
        item = stack.pop(0)
        try:
            if isinstance(item, (tkinter.Button, tkinter.Label, tkinter.Radiobutton, tkinter.Checkbutton)) and item.winfo_ismapped():
                value = str(item.cget("text")).strip()
                if value == text or (starts and value.startswith(text)): return item
            stack.extend(item.winfo_children())
        except tkinter.TclError:
            continue
    return None


def picture(window, marks, name):
    """Screenshot of `window` with numbered boxes around the marked widgets, saved as img/<name>.png."""
    from PIL import ImageDraw, ImageFont, ImageGrab
    for _ in range(10): window.update(); time.sleep(0.05)
    x, y, w, h = window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height()
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY")).convert("RGB")
    draw = ImageDraw.Draw(image)
    try: font = ImageFont.truetype(str(ROOT / "Assets" / "fonts" / "Amiri-Bold.ttf"), 18)
    except OSError: font = ImageFont.load_default()
    for number, widget in marks:
        if widget is None: continue
        left, top = widget.winfo_rootx() - x - 4, widget.winfo_rooty() - y - 4
        right, bottom = left + widget.winfo_width() + 8, top + widget.winfo_height() + 8
        draw.rounded_rectangle((left, top, right, bottom), radius=6, outline=GOLD, width=3)
        cx, cy = max(14, left), max(14, top)
        draw.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill=NAVY, outline=GOLD, width=2)
        draw.text((cx, cy), str(number), fill=(255, 255, 255), font=font, anchor="mm")
    if image.width > WIDTH: image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    image.quantize(colors=200).save(OUT / "img" / f"{name}.png", optimize=True)
    return f"img/{name}.png"


def build():
    url, company, year = demo_company()
    import desktop
    app = desktop.SaberApp(); app.geometry("1440x900+0+0"); app.update()
    app.server.set(url); app.password.set("admin12345"); app.login(); app.update()
    app.client.select_company_year(company["id"], year); app.current_company = company; app.current_fiscal_year = int(year)
    app.main_screen(); app.update()
    pages = dict(zip(app._page_attributes, app.main_tab_pages)); done = []
    for attribute, title_en, title_ar, intro_en, intro_ar, steps in TOPICS:
        if attribute not in pages: continue
        app.select_main_tab(pages[attribute]); app.update()
        page = getattr(app, attribute)
        marks = [(n, find(page, text) if text else None) for n, (text, _en, _ar) in enumerate(steps, 1)]
        missing = [text for (n, w), (text, _e, _a) in zip(marks, steps) if text and w is None]
        if missing: print(f"  {attribute}: not found on the screen: {missing}")
        done.append((attribute, title_en, title_ar, intro_en, intro_ar, steps, picture(app, marks, attribute)))
        print("picture", attribute)
    key, title_en, title_ar, intro_en, intro_ar, steps = WIZARD
    window = app.create_company_dialog(); window.geometry("640x520+200+120"); app.update()
    find(window, "Next").invoke(); app.update()
    marks = [(n, find(window, text) if text else None) for n, (text, _en, _ar) in enumerate(steps, 1)]
    done.insert(1, (key, title_en, title_ar, intro_en, intro_ar, steps, picture(window, marks, key))); window.destroy()
    app.destroy()
    (OUT / "help.html").write_text(page_html(done), encoding="utf-8")
    print("written", OUT / "help.html")


def page_html(topics):
    e = html.escape
    nav = "".join(f'<a href="#{t[0]}"><span class="en">{e(t[1])}</span><span class="ar">{e(t[2])}</span></a>' for t in topics)
    cards = []
    for key, title_en, title_ar, intro_en, intro_ar, steps, image in topics:
        items = "".join(f'<li><b>{n}</b><span class="en">{e(en)}</span><span class="ar">{e(ar)}</span></li>' for n, (_t, en, ar) in enumerate(steps, 1))
        cards.append(f'''<section class="topic" id="{key}"><h2><span class="en">{e(title_en)}</span><span class="ar">{e(title_ar)}</span></h2>
<p class="intro"><span class="en">{e(intro_en)}</span><span class="ar">{e(intro_ar)}</span></p>
<a href="{image}" target="_blank"><img src="{image}" alt="{e(title_en)}" loading="lazy"></a><ol>{items}</ol></section>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nanza Accounting - Help</title><style>
:root{{--navy:#102A43;--gold:#D0A557;--page:#F4F7FA;--line:#DDE4EC;--muted:#5F6B76}}
*{{box-sizing:border-box}} body{{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--page);color:var(--navy)}}
header{{background:var(--navy);color:#fff;padding:14px 24px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:2}}
header img{{height:38px}} header h1{{font-size:20px;margin:0;flex:1}} header button{{background:transparent;color:#fff;border:1px solid #5d7590;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:14px}}
header button.on{{background:var(--gold);color:var(--navy);border-color:var(--gold)}} header a{{color:var(--gold);font-size:13px}}
.wrap{{display:grid;grid-template-columns:250px 1fr;gap:24px;max-width:1400px;margin:0 auto;padding:20px}}
nav{{position:sticky;top:84px;align-self:start;background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px}}
nav a{{display:block;padding:7px 10px;border-radius:6px;color:var(--navy);text-decoration:none;font-size:14px}} nav a:hover{{background:#E8EEF5}}
.topic{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin-bottom:22px;scroll-margin-top:90px}}
.topic:target{{box-shadow:0 0 0 3px var(--gold)}} h2{{margin:0 0 4px;font-size:21px}} .intro{{color:var(--muted);margin:0 0 14px}}
.topic img{{width:100%;border:1px solid var(--line);border-radius:8px}}
ol{{list-style:none;padding:0;margin:16px 0 0}} li{{display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-top:1px solid #EEF2F6;font-size:15px}}
li b{{flex:none;width:28px;height:28px;border-radius:50%;background:var(--navy);color:#fff;border:2px solid var(--gold);display:grid;place-items:center;font-size:14px}}
.ar{{display:none}} body.arabic .en{{display:none}} body.arabic .ar{{display:inline}} body.arabic{{direction:rtl}}
body.arabic nav a .ar{{display:block}} nav a .en{{display:block}} body.arabic nav a .en{{display:none}}
@media (max-width:820px){{.wrap{{grid-template-columns:1fr}} nav{{position:static}}}}
</style></head><body>
<header><img src="../nanza_icon.png" alt="Nanza" onerror="this.style.display='none'"><h1><span class="en">Help with pictures</span><span class="ar">المساعدة بالصور</span></h1>
<button id="en" class="on" onclick="lang(false)">English</button><button id="ar" onclick="lang(true)">عربي</button>
<a href="../user_guide.html"><span class="en">Full user guide</span><span class="ar">الدليل الكامل</span></a></header>
<div class="wrap"><nav>{nav}</nav><main>{"".join(cards)}</main></div>
<script>
function lang(ar){{document.body.classList.toggle("arabic",ar);document.getElementById("ar").classList.toggle("on",ar);document.getElementById("en").classList.toggle("on",!ar);
try{{localStorage.setItem("nanza-help-lang",ar?"ar":"en")}}catch(e){{}}}}
try{{if(localStorage.getItem("nanza-help-lang")==="ar")lang(true)}}catch(e){{}}
if(location.search.indexOf("lang=ar")>=0)lang(true);
</script></body></html>'''


if __name__ == "__main__":
    build()
