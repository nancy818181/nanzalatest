"""2.9.136: screen check on your own PC - opens every main screen on a small DEMO company (temporary folder, never your
real data), in English then Arabic, saves a picture of each in ui_check_out/ and lists what does not fit the screen.

    python tools/run_ui_check.py          (Windows; on Linux: xvfb-run python tools/run_ui_check.py)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ui_check_out"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_help as helper  # noqa: E402  sets a temporary SABER_DATA_DIR and makes the demo company
import tkinter  # noqa: E402


def off_screen(widget, width, height):
    """Buttons / fields that are shown but lie (partly) outside the screen."""
    found, stack = [], [widget]
    while stack:
        item = stack.pop()
        try:
            if item.winfo_ismapped() and item.winfo_class() in ("Button", "TButton", "Entry", "TEntry", "TCombobox") and item.winfo_width() > 1:
                x, y = item.winfo_rootx(), item.winfo_rooty()
                if x < -2 or x + item.winfo_width() > width + 2 or y + item.winfo_height() > height + 2:
                    try: text = str(item.cget("text"))[:30]
                    except tkinter.TclError: text = ""
                    found.append(f"{item.winfo_class()} '{text}' at {x},{y}")
            stack.extend(item.winfo_children())
        except tkinter.TclError:
            continue
    return found


def picture(app, name):
    from PIL import ImageGrab
    for _ in range(10): app.update(); time.sleep(0.03)
    x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY")).save(OUT / f"{name}.png")


def check(url, company, year, language):
    import desktop
    app = desktop.SaberApp(); app.update()
    app.server.set(url); app.password.set("admin12345"); app.language.set(language); app.login(); app.update()
    app.client.select_company_year(company["id"], year); app.current_company = company; app.current_fiscal_year = int(year)
    app.main_screen(); app.update()
    width, height = app.winfo_screenwidth(), app.winfo_screenheight()
    print(f"\n[{language}] screen {width}x{height}, window {app.winfo_width()}x{app.winfo_height()}")
    problems = 0
    for attribute, page in zip(app._page_attributes, app.main_tab_pages):
        app.select_main_tab(page); app.update()
        picture(app, f"{language}_{attribute}")
        issues = off_screen(getattr(app, attribute, page), width, height)
        problems += len(issues)
        print(f"  {attribute}: " + ("OK" if not issues else f"{len(issues)} control(s) outside the screen (scroll to reach them?)"))
        for issue in issues[:5]: print("     -", issue)
    app.destroy()
    return problems


def main():
    OUT.mkdir(exist_ok=True)
    url, company, year = helper.demo_company()
    total = sum(check(url, company, year, language) for language in ("en", "ar"))
    print(f"\nPictures: {OUT}\nControls outside the screen: {total} (a page that scrolls may list some - look at its picture)")


if __name__ == "__main__":
    main()
