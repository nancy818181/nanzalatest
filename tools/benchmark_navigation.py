"""Measure desktop navigation against temporary synthetic company books.

Run with a Tk display, passing the checkout to measure as --source. Use the
same physical display size and Tk scale for both checkouts and separate
output folders. The setup helper starts the normal desktop data service.
"""
import argparse
import cProfile
import json
import math
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter, sleep


def purchase_layout(app, page, output):
    from PIL import ImageGrab

    app.select_main_tab(page)
    for index in range(12):
        app.purchase_item_line({"name": f"Synthetic purchase item {index + 1}", "quantity": 2,
                                "unit": "unit", "unit_cost": 10, "discount_percent": 0})
    app.purchase_items_changed()
    app.update()
    tree = app.purchase_form["items_sheet"].tree
    footer = app.purchase_form["total"]
    canvas = tree
    while not getattr(canvas, "_saber_scroll_page", False):
        canvas = canvas.master
    clip = min(tree.winfo_rooty() + tree.winfo_height(),
               canvas.winfo_rooty() + canvas.winfo_height())
    rows = sum(1 for item in tree.get_children() if (box := tree.bbox(item))
               and tree.winfo_rooty() + box[1] + box[3] <= clip)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(output / "purchase.png")
    fields = app.purchase_form["header_widgets"]
    right = canvas.winfo_rootx() + canvas.winfo_width()
    clipped = [key for key, field in fields.items()
               if not field.winfo_ismapped() or field.winfo_rootx() + field.winfo_width() > right]
    result = {"display": [app.winfo_screenwidth(), app.winfo_screenheight()],
              "window": [w, h], "tk_scale": float(app.tk.call("tk", "scaling")),
              "visible_rows": rows, "footer_visible": bool(footer.winfo_ismapped()),
              "clipped_header_fields": clipped}
    (output / "purchase-layout.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result



def quotation_layout(app, page, output):
    from PIL import ImageGrab

    app.select_main_tab(page)
    app.update()
    window = app.open_commercial_documents(quotations_only=True)
    if window is None:
        raise RuntimeError("Quotation workspace did not open")
    app.update()
    left, top = window.winfo_rootx(), window.winfo_rooty()
    right = left + window.winfo_width()
    bottom = top + window.winfo_height()
    ImageGrab.grab(bbox=(left, top, right, bottom)).save(output / "quotation.png")
    window.destroy()


def run(args):
    sys.path.insert(0, str(args.source))
    sys.path.insert(0, str(args.source / "tools"))
    import make_help
    import desktop
    from client import ApiClient

    url, company, year = make_help.demo_company()
    api = ApiClient(url)
    api.login("admin", "admin12345")
    api.select_company_year(company["id"], year)
    for index in range(args.records):
        kind = "sale" if index % 2 == 0 else "purchase"
        api.create_manual_invoice(
            {"invoice_date": f"15-01-{year}", "party_name": f"Benchmark {kind}",
             "kind": kind, "currency": "USD", "invoice_number": f"BENCH-{index:06}"},
            [{"description": f"Synthetic item {index}", "quantity": 2, "unit_price": "5.25"}],
        )
    for index in range(max(5, args.records // 5)):
        api.save_inventory_item({"sku": f"BENCH-{index:05}", "name": f"Paper product {index}", "unit": "unit"})
    customer = api.save_party({"kind": "customer", "name": "Quotation benchmark", "currency": "USD"})
    for index in range(max(3, args.records // 20)):
        api.request("POST", "/api/commercial", {
            "header": {"kind": "quotation", "doc_date": f"{year}-01-15",
                       "party_id": customer["id"], "currency": "USD"},
            "rows": [{"sku": "BENCH-00000", "description": f"Paper {index}", "quantity": "1",
                      "unit_price": "12", "vat_rate": "11"}],
        })
    start = perf_counter()
    app = desktop.SaberApp()
    app.tk.call("tk", "scaling", args.scale)
    app.geometry(f"{args.width}x{args.height}+0+0")
    app.server.set(url)
    app.password.set("admin12345")
    app.language.set(args.language)
    app.login()
    app.client.select_company_year(company["id"], year)
    app.current_company = company
    app.current_fiscal_year = int(year)
    app.main_screen()
    app.update()
    startup = 1000 * (perf_counter() - start)

    routes = {"Dashboard": "dashboard_tab", "Purchases": "purchases_tab",
              "Sales Invoice": "sales_tab", "Financial Reports": "reports_tab"}
    pages = dict(zip(app._page_attributes, app.main_tab_pages))
    if args.layout_only:
        print(json.dumps(purchase_layout(app, pages["purchases_tab"], args.output)))
        if args.quotation_layout:
            quotation_layout(app, pages["sales_tab"], args.output)
        app.destroy()
        return
    previous_tick = perf_counter()
    longest_gap = 0

    def heartbeat():
        nonlocal previous_tick, longest_gap
        now = perf_counter()
        longest_gap = max(longest_gap, now - previous_tick)
        previous_tick = now
        app.after(5, heartbeat)

    heartbeat()

    def measure(action, *, financial=False):
        nonlocal previous_tick, longest_gap
        longest_gap = 0
        previous_tick = start = perf_counter()
        action()
        app.update()
        if financial:
            deadline = start + 30
            while app.__dict__.get("_financial_loading"):
                if perf_counter() > deadline:
                    raise RuntimeError("Financial Reports did not load within 30 seconds")
                sleep(.001)
                app.update()
        elapsed = perf_counter() - start
        return elapsed * 1000, longest_gap * 1000

    def select(name):
        app.select_main_tab(pages[routes[name]])

    def quotation():
        window = app.open_commercial_documents(quotations_only=True)
        return window

    def lookup():
        return app.choose_sales_inventory_item(app, lambda _item: None, "paper")

    def summarize(samples):
        values = sorted(timing for timing, _gap in samples)
        return {"samples": len(values), "median_ms": round(statistics.median(values), 2),
                "p95_ms": round(values[math.ceil(.95 * len(values)) - 1], 2),
                "worst_ms": round(values[-1], 2),
                "longest_gap_ms": round(max(gap for _timing, gap in samples), 2)}

    first = {name: summarize([measure(lambda name=name: select(name), financial=name == "Financial Reports")]) for name in routes}
    repeats = {name: [] for name in routes}
    for _ in range(args.samples):
        for name in routes:
            repeats[name].append(measure(lambda name=name: select(name)))
    select("Sales Invoice")
    for name, action in (("Quotation", quotation), ("Item lookup", lookup)):
        samples = []
        for _ in range(args.samples + 1):
            previous = set(app.winfo_children())
            samples.append(measure(action))
            for widget in set(app.winfo_children()) - previous:
                widget.destroy()
            app.update()
        first[name] = summarize(samples[:1])
        repeats[name] = samples[1:]

    profiler = cProfile.Profile()
    profiler.enable()
    for name in ("Sales Invoice", "Purchases") * 30:
        measure(lambda name=name: select(name))
    profiler.disable()
    profiler.dump_stats(args.output / "repeat-profile.pstats")

    layout = purchase_layout(app, pages["purchases_tab"], args.output)
    report_rows = {"trial": api.trial_balance(), "vat": api.vat_report(), "balance": api.balance_sheet()}
    (args.output / "reports.json").write_text(json.dumps(report_rows, sort_keys=True, default=str) + "\n", encoding="utf-8")
    result = {"os": platform.platform(), "python": platform.python_version(),
              "records": args.records + 5, **layout,
              "startup_ms": round(startup, 2), "first_open": first,
              "repeat": {name: summarize(samples) for name, samples in repeats.items()},
              "mixed_navigation_actions": args.samples * len(routes) + 60}
    (args.output / "navigation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    app.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=int, default=0)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--scale", type=float, default=96 / 72)
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--quotation-layout", action="store_true", help="Also capture Quotations in layout-only mode")
    parser.add_argument("--language", choices=["en", "ar"], default="en")
    arguments = parser.parse_args()
    arguments.source = arguments.source.resolve()
    arguments.output = arguments.output.resolve()
    arguments.output.mkdir(parents=True, exist_ok=True)
    run(arguments)
