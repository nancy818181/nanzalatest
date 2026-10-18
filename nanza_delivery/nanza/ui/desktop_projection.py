"""Financial Reports > Projection & Budget (3D) - 2.9.50.

Projected income statement, cash flow, key indicators, scenarios, budget by account and month, all from the books,
with a growth % per line and per year typed in the assumptions sheet, and 3D charts on screen, in PDF and in Excel.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import chart3d
import projection_model as pm
from desktop_brains import EditableSheet

from desktop_common import GOLD, LIGHT, NAVY

MUTED = "#5f6b76"
log = logging.getLogger("saber")


def _number(text):
    text = str(text or "").strip().replace(",", "").rstrip("%")
    if text == "": return None
    return float(text)


class ProjectionMixin:
    # ------------------------------------------------------------ screen
    def build_projection_page(self, nested):
        page = tk.Frame(nested, bg=LIGHT); nested.add(page, text="Projection & Budget (3D)")
        year = int(getattr(self, "current_fiscal_year", datetime.now().year))
        default_base = year if year < datetime.now().year or datetime.now().month > 1 else year - 1
        self.pj = {"base_year": tk.StringVar(value=str(default_base)), "years": tk.StringVar(value="3"), "currency": tk.StringVar(value="USD"),
                   "spread": tk.StringVar(value="10"), "tax": tk.StringVar(value="17"), "dso": tk.StringVar(), "dpo": tk.StringVar(),
                   "life": tk.StringVar(value="5"), "scenario": tk.StringVar(value="Base"), "all_growth": tk.StringVar(value="10"),
                   "budget_year": tk.StringVar(value=str(default_base + 1))}
        codes = list(getattr(self, "currency_codes", ["USD", "LBP"]))
        if codes and self.pj["currency"].get() not in codes: self.pj["currency"].set(codes[0])
        bar = tk.Frame(page, bg=LIGHT); bar.pack(fill="x", padx=10, pady=(8, 2))
        for label, key, width in (("Base year", "base_year", 6), ("Years ahead (1-5)", "years", 3)):
            tk.Label(bar, text=label, bg=LIGHT, fg=NAVY).pack(side="left"); tk.Entry(bar, textvariable=self.pj[key], width=width).pack(side="left", padx=(4, 10))
        tk.Label(bar, text="Currency", bg=LIGHT, fg=NAVY).pack(side="left")
        ttk.Combobox(bar, textvariable=self.pj["currency"], values=codes, state="readonly", width=6).pack(side="left", padx=(4, 10))
        tk.Label(bar, text="Scenario", bg=LIGHT, fg=NAVY).pack(side="left")
        box = ttk.Combobox(bar, textvariable=self.pj["scenario"], values=list(pm.SCENARIOS), state="readonly", width=11); box.pack(side="left", padx=(4, 10))
        box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_projection(reload=False))
        tk.Button(bar, text="Build from the books", command=self.refresh_projection, bg=GOLD, fg=NAVY, border=0, padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left", padx=3)
        self.action_button(bar, "3D Charts", self.show_projection_charts).pack(side="left", padx=3)
        for label, fmt in (("Excel", "xlsx"), ("PDF", "pdf")):
            self.action_button(bar, label, lambda f=fmt: self.export_projection(f)).pack(side="left", padx=2)
        bar2 = tk.Frame(page, bg=LIGHT); bar2.pack(fill="x", padx=10, pady=2)
        for label, key, width in (("Scenario spread (± points)", "spread", 5), ("Income tax %", "tax", 5), ("Customer days (DSO)", "dso", 5),
                                  ("Supplier days (DPO)", "dpo", 5), ("Asset life (years)", "life", 4)):
            tk.Label(bar2, text=label, bg=LIGHT).pack(side="left"); tk.Entry(bar2, textvariable=self.pj[key], width=width).pack(side="left", padx=(4, 10))
        tk.Label(bar2, text="(DSO / DPO empty = taken from the books)", bg=LIGHT, fg=MUTED).pack(side="left")
        bar3 = tk.Frame(page, bg=LIGHT); bar3.pack(fill="x", padx=10, pady=2)
        tk.Label(bar3, text="Same revenue % for every year", bg=LIGHT).pack(side="left"); tk.Entry(bar3, textvariable=self.pj["all_growth"], width=6).pack(side="left", padx=4)
        self.action_button(bar3, "Apply to all years", self.apply_projection_growth_to_all).pack(side="left", padx=(2, 4))
        self.action_button(bar3, "% from past years", self.suggest_projection_growth).pack(side="left", padx=(2, 12))
        self.action_button(bar3, "Save assumptions", self.save_projection_assumptions).pack(side="left", padx=3)
        tk.Label(bar3, text="Save as budget for year", bg=LIGHT).pack(side="left", padx=(16, 2)); tk.Entry(bar3, textvariable=self.pj["budget_year"], width=6).pack(side="left", padx=2)
        tk.Button(bar3, text="Save as Budget", command=self.save_projection_as_budget, bg=NAVY, fg="white", border=0, padx=12, pady=6).pack(side="left", padx=4)
        tk.Label(page, text="Assumptions per year - double-click a cell. Growth in % against the year before; Cost of sales empty = follows revenue (same gross margin). "
                 "Investments and Financing in the chosen currency (financing: + loans / capital received, - repayments).", bg=LIGHT, fg=MUTED,
                 wraplength=1200, justify="left").pack(fill="x", padx=12)
        columns = [("year", "Year", 70, "center")] + [(key, label, 110, "e") for key, label in pm.GROWTH_FIELDS] + [("capex", "Investments", 110, "e"), ("financing", "Financing", 110, "e")]
        self.pj_sheet = EditableSheet(self, page, columns, [key for key, *_ in columns[1:]], self.projection_cell_changed, height=5)
        self.pj_info = tk.Label(page, text="Press Build from the books.", bg=LIGHT, fg=NAVY, anchor="w", font=("Segoe UI", 9, "bold")); self.pj_info.pack(fill="x", padx=12)
        self.pj_viewer = self.report_viewer(page, [230, 200, 120, 120, 120, 120, 120, 120])
        self.load_projection_assumptions(); self.fill_projection_sheet()

    # ------------------------------------------------------------ assumptions
    def _projection_file(self):
        import app_runtime
        return app_runtime.data_dir() / "projection_assumptions.json"

    def _projection_key(self):
        company = getattr(self, "current_company", None) or {}
        return str(company.get("id") or company.get("name") or "default")

    def load_projection_assumptions(self):
        try: stored = json.loads(self._projection_file().read_text(encoding="utf-8")).get(self._projection_key())
        except Exception: stored = None
        self.pj_assumptions = stored or pm.default_assumptions(int(self.pj["base_year"].get() or datetime.now().year), int(self.pj["years"].get() or 3))
        for key, field in (("base_year", "base_year"), ("years", "years"), ("spread", "scenario_spread"), ("tax", "tax_rate"), ("dso", "dso"), ("dpo", "dpo"), ("life", "asset_life")):
            value = self.pj_assumptions.get(field)
            if value not in (None, ""): self.pj[key].set(f"{value:g}" if isinstance(value, float) else str(value))
        if self.pj_assumptions.get("currency"): self.pj["currency"].set(self.pj_assumptions["currency"])

    def collect_projection_assumptions(self):
        base_year = int(self.pj["base_year"].get()); years = int(self.pj["years"].get())
        if not 1 <= years <= pm.MAX_YEARS: raise ValueError(f"Years ahead must be between 1 and {pm.MAX_YEARS}")
        per_year = {}
        for row in self.pj_sheet.ordered():
            per_year[str(row["year"])] = {key: row.get(key) for key, *_ in self.pj_sheet.columns[1:]}
        stored = (getattr(self, "pj_assumptions", None) or {}).get("per_year") or {}
        for offset in range(1, years + 1):
            key = str(base_year + offset); per_year.setdefault(key, stored.get(key) or pm.default_year())
        return {"base_year": base_year, "years": years, "currency": self.pj["currency"].get(), "scenario_spread": _number(self.pj["spread"].get()) or 0.0,
                "tax_rate": _number(self.pj["tax"].get()) or 0.0, "dso": _number(self.pj["dso"].get()), "dpo": _number(self.pj["dpo"].get()),
                "asset_life": _number(self.pj["life"].get()) or 5.0, "per_year": per_year}

    def fill_projection_sheet(self):
        try: base_year = int(self.pj["base_year"].get()); years = max(1, min(pm.MAX_YEARS, int(self.pj["years"].get())))
        except ValueError: return
        stored = (getattr(self, "pj_assumptions", None) or {}).get("per_year") or {}
        current = {str(r["year"]): r for r in self.pj_sheet.ordered()}
        self.pj_sheet.clear()
        for offset in range(1, years + 1):
            key = str(base_year + offset); values = current.get(key) or {**pm.default_year(), **(stored.get(key) or {})}
            row = {"year": key, **{k: values.get(k) for k, *_ in self.pj_sheet.columns[1:]}}
            self.pj_sheet.insert(self._format_projection_row(row))

    def _format_projection_row(self, row):
        row["_display"] = {key: ("follows revenue" if key == "cost_of_sales" and row.get(key) in (None, "") else
                                 f"{float(row.get(key) or 0):,.2f}" if key in ("capex", "financing") else f"{float(row.get(key) or 0):g}%")
                           for key, *_ in self.pj_sheet.columns[1:]}
        return row

    def projection_cell_changed(self, iid, key, text):
        row = self.pj_sheet.rows[iid]
        try: value = _number(text)
        except ValueError: messagebox.showwarning("Projection", "Enter a number (for example 8 for +8%, -5 for -5%)"); return False
        if key in ("capex",) and value is not None and value < 0: messagebox.showwarning("Projection", "Investments are a positive amount"); return False
        row[key] = value if (value is not None or key == "cost_of_sales") else 0.0
        self._format_projection_row(row)

    def apply_projection_growth_to_all(self):
        try: value = float(self.pj["all_growth"].get())
        except ValueError: return messagebox.showwarning("Projection", "Enter the revenue growth %, for example 10")
        self.fill_projection_sheet()
        for iid, row in self.pj_sheet.rows.items():
            row["revenue"] = value; self._format_projection_row(row); self.pj_sheet.refresh(iid)

    def save_projection_assumptions(self, quiet=False):
        try: assumptions = self.collect_projection_assumptions()
        except ValueError as exc: return messagebox.showwarning("Projection", str(exc))
        path = self._projection_file()
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except Exception: data = {}
        data[self._projection_key()] = assumptions
        try: path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc: return messagebox.showerror("Projection", f"The assumptions could not be saved: {exc}")
        self.pj_assumptions = assumptions
        if not quiet: messagebox.showinfo("Projection", "Assumptions saved for this company.")

    # ------------------------------------------------------------ data from the books
    def _year_profit_loss(self, year, start, end, currency):
        """P&L of any fiscal year: its own file when the company keeps one per year (2.9.52), else this one."""
        try: return self.client.fiscal_year_profit_loss(year, start, end, currency, convert=True)
        except Exception:
            try: return self.client.profit_loss(start, end, currency, convert=True)
            except Exception: return []

    def load_projection_base(self, base_year, currency):
        months, label = pm.base_period(base_year)
        monthly = {month: self.client.profit_loss(f"{base_year}-{month:02d}-01", pm.month_end(base_year, month), currency, convert=True) for month in range(1, months + 1)}
        used = months
        if months < 12:  # 2.9.52: a year in progress is completed with the same months of last year (last 12 months)
            previous = {month: self._year_profit_loss(base_year - 1, f"{base_year - 1}-{month:02d}-01", pm.month_end(base_year - 1, month), currency)
                        for month in range(months + 1, 13)}
            if any(rows for rows in previous.values()):
                monthly.update(previous); used = 12
                label = f"Last 12 months ({pm.MONTHS[months]} {base_year - 1} - {pm.MONTHS[months - 1]} {base_year})"
        accounts = pm.collect_base(monthly, used)
        balances = pm.balances_from(self.client.balance_sheet(pm.month_end(base_year, months), currency, convert=True))
        history = []
        for year in (base_year - 2, base_year - 1):
            if used == 12 and months < 12 and year == base_year - 1: continue  # already inside the last 12 months
            rows = self._year_profit_loss(year, f"{year}-01-01", f"{year}-12-31", currency)
            if rows: history.append((f"Actual {year}", pm.statement_from_rows(rows)))
        self.pj_history = history
        return accounts, balances, label

    def suggest_projection_growth(self):
        """Revenue % of every projected year = the average growth of the actual years."""
        if getattr(self, "pj_base", None) is None: self.refresh_projection()
        if getattr(self, "pj_base", None) is None: return
        base = pm._statement(pm._lines_total(self.pj_base[0]))
        growth = pm.historical_growth(getattr(self, "pj_history", []), base)
        if growth is None: return messagebox.showinfo("Projection", "There is no earlier year with revenue in Nanza to measure the growth. Type the % yourself.")
        self.pj["all_growth"].set(f"{growth:g}"); self.apply_projection_growth_to_all(); self.refresh_projection(reload=False)
        messagebox.showinfo("Projection", f"Revenue growth set to {growth:g}% per year (average of the actual years). Adjust any year in the sheet.")

    def refresh_projection(self, reload=True):
        try:
            self.fill_projection_sheet()
            assumptions = self.collect_projection_assumptions(); currency = assumptions["currency"]
            if reload or getattr(self, "pj_base", None) is None or self.pj_base[3] != (assumptions["base_year"], currency):
                accounts, balances, label = self.load_projection_base(assumptions["base_year"], currency)
                self.pj_base = (accounts, balances, label, (assumptions["base_year"], currency))
            accounts, balances, label, _key = self.pj_base
            budget_year = int(self.pj["budget_year"].get() or 0) or None
            projections, sections = pm.report_sections(accounts, assumptions, balances, label, currency, self.pj["scenario"].get(), budget_year,
                                                       getattr(self, "pj_history", []))
        except ValueError as exc: return messagebox.showwarning("Projection", str(exc))
        except Exception as exc:
            log.exception("Projection failed"); return messagebox.showerror("Projection", str(exc))
        self.pj_assumptions = assumptions; self.pj_projections = projections; self.pj_sections = sections
        self.show_sections(self.pj_viewer, sections)
        p = projections[self.pj["scenario"].get()]; last = p["years"][-1]
        self.pj_info.config(text=f"{label} -> {p['years'][0]}-{last}   |   {self.pj['scenario'].get()}: revenue {p['rows'][last]['revenue']:,.0f}, "
                                 f"net profit {p['rows'][last]['net_profit']:,.0f}, closing cash {p['cash'][last]['closing']:,.0f} {currency} in {last}")
        self.save_projection_assumptions(quiet=True)

    def _projection_ready(self):
        if not getattr(self, "pj_sections", None): self.refresh_projection()
        return getattr(self, "pj_sections", None)

    def export_projection(self, format_name):
        sections = self._projection_ready()
        if not sections: return
        a = self.pj_assumptions; scenario = self.pj["scenario"].get()
        company = {}
        try: company = self.client.settings()
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
        meta = [f"Company: {company.get('company_name') or '-'}", f"Base: {self.pj_base[2]}   Scenario: {scenario}   Currency: {a['currency']}",
                "Figures projected from the posted books with the growth % per year shown in the assumptions. A projection is an estimate, not a forecast guarantee."]
        title = f"Financial projection and budget {a['base_year'] + 1}-{a['base_year'] + a['years']}"
        self.save_sections(title, meta, sections, f"Projection_{a['base_year'] + 1}_{a['base_year'] + a['years']}_{scenario}", format_name)

    def save_projection_as_budget(self):
        if not self._projection_ready(): return
        try: year = int(self.pj["budget_year"].get())
        except ValueError: return messagebox.showwarning("Projection", "Enter the budget year")
        p = self.pj_projections[self.pj["scenario"].get()]
        if year not in p["years"]: return messagebox.showwarning("Projection", f"Choose one of the projected years: {', '.join(map(str, p['years']))}")
        lines = pm.budget_lines(self.pj_base[0], p, year); currency = self.pj_assumptions["currency"]
        if not lines: return messagebox.showwarning("Projection", "No positive budget line to save")
        if not messagebox.askyesno("Save as Budget", f"Replace the company budget {year} ({currency}) with {len(lines)} account line(s) from the "
                                   f"{self.pj['scenario'].get()} projection, spread by month?\nDepartment and project budgets are not changed."):
            return
        try: self.client.save_budget({"year": year, "currency": currency, "lines": lines})
        except Exception as exc: return messagebox.showerror("Save as Budget", str(exc))
        messagebox.showinfo("Save as Budget", f"Budget {year} saved. Open the Budget tab and press Load, or Budget vs Actual during the year.")

    # ------------------------------------------------------------ 3D charts window
    def show_projection_charts(self):
        sections = self._projection_ready()
        if not sections: return
        return show_3d_charts(self, [(s["chart"]["title"], s["chart"]) for s in sections if s.get("chart")])


def show_3d_charts(app, charts, title="3D Charts"):
    """A window with a list of 3D charts, angle and depth sliders (projection, inventory analysis).
    No Tk variables here: closures holding them could be freed on another thread and stop the program."""
    window = tk.Toplevel(app); window.title(title); window.configure(bg=LIGHT); window.geometry("1000x600")
    top = tk.Frame(window, bg=LIGHT); top.pack(fill="x", padx=10, pady=6)
    names = []
    for name, _spec in charts:
        while name in names: name += " "
        names.append(name)
    specs = dict(zip(names, [spec for _n, spec in charts]))
    tk.Label(top, text="Chart", bg=LIGHT).pack(side="left")
    chooser = ttk.Combobox(top, values=names, state="readonly", width=40); chooser.pack(side="left", padx=6); chooser.set(names[0])
    canvas = tk.Canvas(window, bg="white", highlightthickness=0)
    sliders = {}
    def draw(*_args):
        if not canvas.winfo_exists() or not sliders: return
        spec = dict(specs.get(chooser.get(), specs[names[0]])); spec.update(angle=int(sliders["angle"].get()), depth=float(sliders["depth"].get()))
        width = max(600, canvas.winfo_width()); height = max(360, canvas.winfo_height())
        chart3d.draw_on_canvas(canvas, chart3d.chart_from_spec(spec, width, height))
    for label, key, low, high, step, start in (("Angle", "angle", 10, 70, 1, 35), ("Depth", "depth", 0.2, 1.2, 0.05, 0.55)):
        tk.Label(top, text=label, bg=LIGHT).pack(side="left", padx=(10, 2))
        scale = tk.Scale(top, from_=low, to=high, resolution=step, orient="horizontal", length=140, bg=LIGHT, highlightthickness=0, command=lambda _v: draw())
        scale.set(start); scale.pack(side="left"); sliders[key] = scale
    canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    chooser.bind("<<ComboboxSelected>>", draw); canvas.bind("<Configure>", draw)
    window.bind("<Escape>", lambda _e: window.destroy())
    window.after(80, draw)
    return window
