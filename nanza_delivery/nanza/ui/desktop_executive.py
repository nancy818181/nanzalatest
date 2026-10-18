"""Native executive dashboard with real posted-book figures and explicit missing data."""

from decimal import Decimal, InvalidOperation
import math
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.parse import urlencode
from desktop_common import main_currency, flow_toolbar
from desktop_stage3_common import run_with_progress

NAVY = "#0a1931"
GREEN = "#16836A"
GOLD = "#d4a017"
BG = "#F1F5F7"
MUTED = "#617482"


def open_executive(app):
    window = tk.Toplevel(app)
    window.title("Executive Financial Dashboard")
    window.configure(bg=BG)
    window.geometry(
        f"{min(1220,app.winfo_screenwidth()-50)}x{min(820,app.winfo_screenheight()-80)}"
    )
    window.transient(app)
    window._executive_state = state = {"report": None, "generation": 0, "filters": None}
    ar = app.language.get() == "ar"
    header = tk.Frame(window, bg=NAVY)
    header.pack(fill="x")
    title = "لوحة الإدارة المالية" if ar else "EXECUTIVE FINANCIAL DASHBOARD"
    tk.Label(
        header, text=title, bg=NAVY, fg="white", font=("Segoe UI", 17, "bold")
    ).pack(anchor="e" if ar else "w", padx=18, pady=12)
    bar = tk.Frame(window, bg=BG)
    bar.pack(fill="x", padx=14, pady=9)
    start = tk.StringVar(value=f"01-01-{app.current_fiscal_year}")
    end = tk.StringVar(value=app.fiscal_today())
    currency = tk.StringVar(value=main_currency(app))
    state["date_fields"] = (start, end, currency)
    for label, var, width in (
        ("من" if ar else "From", start, 12),
        ("إلى" if ar else "To", end, 12),
        ("العملة" if ar else "Currency", currency, 8),
    ):
        tk.Label(bar, text=label, bg=BG).pack(side="left", padx=3)
        if var is currency:
            ttk.Combobox(
                bar,
                textvariable=var,
                values=[r["code"] for r in app.client.currencies()],
                state="readonly",
                width=width,
            ).pack(side="left")
        else:
            tk.Entry(bar, textvariable=var, width=width).pack(side="left")
    canvas = tk.Canvas(window, bg=BG, highlightthickness=0)
    scroll = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(fill="both", expand=True)
    body = tk.Frame(canvas, bg=BG)
    body_id = canvas.create_window((0, 0), window=body, anchor="nw")
    body.bind(
        "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_id, width=e.width))
    status = tk.StringVar(value="")
    tk.Label(window, textvariable=status, bg=BG, fg=MUTED, wraplength=1000).pack(
        fill="x", padx=12, pady=5
    )

    def filters():
        return (start.get(), end.get(), currency.get())

    def money(value):
        return (
            "غير متاح"
            if value is None and ar
            else "Unavailable" if value is None else f"{Decimal(str(value)):,.2f}"
        )

    def graph(parent, heading, report, keys, labels, column):
        frame = tk.LabelFrame(
            parent, text=heading, bg="white", fg=NAVY, font=("Segoe UI", 11, "bold")
        )
        frame.grid(row=0, column=column, sticky="nsew", padx=4, pady=6)
        chart = tk.Canvas(frame, height=210, bg="white", highlightthickness=0)
        chart.pack(fill="x")

        def draw(_event=None):
            chart.delete("all")
            width = max(300, chart.winfo_width())
            rows = report["months"]
            values = [
                float(row[key]) for row in rows for key in keys if row[key] is not None
            ]
            if not values or not all(math.isfinite(v) for v in values):
                chart.create_text(
                    width / 2, 100, text="غير متاح" if ar else "Unavailable", fill=MUTED
                )
                return
            high = max(max(values), 0)
            low = min(min(values), 0)
            span = high - low or 1
            y = lambda v: 175 - (v - low) / span * 135
            zero = y(0)
            chart.create_line(55, zero, width - 15, zero, fill="#D5DFE5")
            chart.create_text(
                5, 30, text=money(high), anchor="w", fill=MUTED, font=("Segoe UI", 8)
            )
            chart.create_text(
                5, 175, text=money(low), anchor="w", fill=MUTED, font=("Segoe UI", 8)
            )
            step = (width - 80) / max(1, len(rows))
            bar_width = min(20, step / (len(keys) + 1))
            for i, row in enumerate(rows):
                group_x = 65 + i * step
                for n, key in enumerate(keys):
                    if row[key] is None:
                        continue
                    x = group_x + n * bar_width
                    top = y(float(row[key]))
                    chart.create_rectangle(
                        x,
                        min(top, zero),
                        x + bar_width - 2,
                        max(top, zero),
                        fill=(GREEN, GOLD)[n % 2],
                        outline="",
                    )
                chart.create_text(
                    group_x + bar_width,
                    190,
                    text=row["month"][5:],
                    fill=MUTED,
                    font=("Segoe UI", 8),
                )
            chart.create_text(
                width / 2,
                12,
                text="   |   ".join(labels),
                fill=NAVY,
                font=("Segoe UI", 9),
            )

        chart.bind("<Configure>", draw)
        chart.after_idle(draw)

    def show(report):
        for child in body.winfo_children():
            child.destroy()
        report["metrics"] = {
            k: Decimal(str(v)) if v is not None else None
            for k, v in report["metrics"].items()
        }
        for row in report["months"]:
            for key in ("income", "expenses", "profit", "budget_profit"):
                if row[key] is not None:
                    row[key] = Decimal(str(row[key]))
        state["report"] = report
        company = getattr(app, "current_company", {}).get("name") or ""
        tk.Label(
            body,
            text=f"{company}   |   {state['filters'][0]} — {state['filters'][1]}   |   {state['filters'][2]}",
            bg=BG,
            fg=NAVY,
            font=("Segoe UI", 11, "bold"),
        ).pack(fill="x", padx=14, pady=6)
        cards = tk.Frame(body, bg=BG)
        cards.pack(fill="x", padx=10)
        metrics = report["metrics"]
        specs = [
            ("income", "الإيرادات" if ar else "INCOME"),
            ("profit", "صافي الربح / الخسارة" if ar else "NET PROFIT / LOSS"),
            ("profit_margin", "هامش صافي الربح %" if ar else "NET PROFIT MARGIN %"),
            (
                "cash",
                "رصيد النقد والمصارف الدفتري" if ar else "CASH / BANK BOOK BALANCE",
            ),
            (
                "overdue_receivables",
                "الذمم المدينة المتأخرة" if ar else "OVERDUE RECEIVABLES",
            ),
            (
                "overdue_payables",
                "الذمم الدائنة المتأخرة" if ar else "OVERDUE PAYABLES",
            ),
        ]
        for index, (key, label) in enumerate(specs):
            card = tk.Frame(
                cards, bg="white", highlightbackground="#DCE5E8", highlightthickness=1
            )
            card.grid(
                row=index // 3,
                column=(2 - index % 3) if ar else index % 3,
                sticky="nsew",
                padx=5,
                pady=5,
            )
            tk.Label(
                card,
                text=label,
                bg="white",
                fg=MUTED,
                font=("Segoe UI", 9),
                wraplength=250,
            ).pack(anchor="e" if ar else "w", padx=12, pady=(10, 3))
            tk.Label(
                card,
                text=money(metrics[key]),
                bg="white",
                fg=(
                    GREEN
                    if metrics[key] is not None and metrics[key] >= 0
                    else "#A34141"
                ),
                font=("Segoe UI", 19, "bold"),
            ).pack(anchor="e" if ar else "w", padx=12, pady=(0, 10))
        for col in range(3):
            cards.columnconfigure(col, weight=1, uniform="cards")
        charts = tk.Frame(body, bg=BG)
        charts.pack(fill="x", padx=14)
        for column in range(2):
            charts.columnconfigure(column, weight=1, uniform="charts")
        graph(
            charts,
            "الإيرادات والمصاريف" if ar else "Income and expenses",
            report,
            ("income", "expenses"),
            ("Income", "Expenses"),
            1 if ar else 0,
        )
        graph(
            charts,
            "الربح الفعلي والموازنة" if ar else "Actual and budget profit",
            report,
            ("profit", "budget_profit"),
            ("Actual profit", "Budget profit"),
            0 if ar else 1,
        )
        panel = tk.LabelFrame(
            body,
            text="المقارنة والمتابعة" if ar else "Comparison and management actions",
            bg="white",
            fg=NAVY,
        )
        panel.pack(fill="x", padx=14, pady=8)
        for label, key in (
            (
                "نفس الفترة السابقة" if ar else "Same-period prior profit",
                "prior_profit",
            ),
            (
                "فرق الربح عن السنة السابقة" if ar else "Profit variance vs prior year",
                "profit_variance",
            ),
            ("الربح بالموازنة" if ar else "Budget profit", "budget_profit"),
        ):
            tk.Label(
                panel, text=f"{label}: {money(metrics[key])}", bg="white", fg=NAVY
            ).pack(anchor="e" if ar else "w", padx=12, pady=3)
        for note in report["actions"] + report["notes"]:
            tk.Label(
                panel,
                text=note,
                bg="white",
                fg=MUTED,
                wraplength=900,
                justify="right" if ar else "left",
            ).pack(anchor="e" if ar else "w", padx=12, pady=3)
        status.set(
            "قيود مرحّلة فقط؛ الرصيد الدفتري لا يؤكد المتاح لدى المصرف"
            if ar
            else "Posted books only. Book cash is not bank-confirmed available cash."
        )

    def refresh():
        state["generation"] += 1
        generation = state["generation"]
        snapshot = filters()
        client = app.client
        company_key = (client.company_id, client.fiscal_year)

        def done(report):
            if (
                not window.winfo_exists()
                or generation != state["generation"]
                or company_key != (app.client.company_id, app.client.fiscal_year)
            ):
                return
            state["filters"] = snapshot
            show(report)

        query = urlencode(
            {
                "date_from": snapshot[0],
                "date_to": snapshot[1],
                "currency": snapshot[2],
                "language": app.language.get(),
            }
        )
        run_with_progress(
            app,
            "Executive dashboard",
            lambda _progress, _cancel: client.request(
                "GET", "/api/dashboard/executive?" + query
            ),
            done,
        )

    def export(kind):
        if state["report"] is None or state["filters"] != filters():
            return messagebox.showwarning(
                title, "Refresh the selected period before exporting", parent=window
            )
        report = state["report"]
        for section in report["sections"]:
            for row in section["rows"]:
                for index, value in enumerate(row):
                    if index and isinstance(value, str) and value:
                        try:
                            row[index] = Decimal(value)
                        except InvalidOperation:
                            pass
        app.output_sections(
            report["title"],
            report["meta"],
            report["sections"],
            "Executive-dashboard",
            kind,
        )

    for label, action in (
        ("تحديث" if ar else "Refresh", refresh),
        ("PDF", lambda: export("pdf")),
        ("Excel", lambda: export("xlsx")),
    ):
        tk.Button(bar, text=label, command=action, bg=NAVY, fg="white", padx=12).pack(
            side="left", padx=4
        )
    flow_toolbar(bar)
    refresh()
    return window
