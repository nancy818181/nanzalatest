"""Read-only board model and clean vector board. No external AI or sample balances."""

from __future__ import annotations
import calendar
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from database_common import iso_date

ZERO = Decimal(0)
GOLD, BLACK, GREEN, RED = "#c8a54c", "#102A43", "#26775c", "#a73f42"
GROUPS = {
    "cogs": "Cost of sales",
    "sga": "SG&A",
    "interest": "Interest expense",
    "depreciation": "Depreciation / amortisation",
    "tax": "Income tax expense",
    "senior_debt": "Senior funded debt",
    "subordinated_debt": "Subordinated funded debt",
    "current_assets": "Current assets",
    "current_liabilities": "Current liabilities",
    "capex": "Cash-flow: capital expenditure",
    "operating_cash": "Cash-flow: operating counterparts",
    "financing_cash": "Cash-flow: financing counterparts",
}
LIMITS = {
    "debt_ebitda_max",
    "current_ratio_min",
    "debt_equity_max",
    "roic_min",
    "interest_coverage_min",
    "ebitda_margin_target",
    "sga_max",
}


def settings(database):
    with database.connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='board_dashboard_settings' AND type='table'"
        ).fetchone()
        row = (
            connection.execute("SELECT config FROM board_dashboard_settings WHERE id=1").fetchone()
            if exists
            else None
        )
    return json.loads(row["config"]) if row else {"reviewed": False, **{k: [] for k in GROUPS}, "targets": {}}


def validate_config(database, config):
    if not isinstance(config, dict) or set(config) - set(GROUPS) - {"reviewed", "targets"}:
        raise ValueError("Unsupported board settings")
    if not isinstance(config.get("reviewed", False), bool):
        raise ValueError("Reviewed must be a boolean")
    accounts = {r["code"]: r for r in database.list_accounts() if r["is_active"] and r["is_posting"]}
    result = {"reviewed": config.get("reviewed", False)}
    for group in GROUPS:
        values = config.get(group, [])
        if (
            not isinstance(values, list)
            or len(values) > 1000
            or any(not isinstance(v, str) or v not in accounts for v in values)
        ):
            raise ValueError(f"{group}: select active posting accounts from this company")
        if len(set(values)) != len(values):
            raise ValueError(f"{group}: duplicate account")
        wanted = (
            ("expense",)
            if group in ("cogs", "sga", "interest", "depreciation", "tax")
            else (
                ("liability",)
                if group in ("senior_debt", "subordinated_debt", "current_liabilities")
                else ("asset",) if group in ("current_assets", "capex") else None
            )
        )
        if wanted and any(accounts[v]["type"] not in wanted for v in values):
            raise ValueError(f"{group}: incorrect account type")
        result[group] = values
    for groups in [
        ("cogs", "sga", "interest", "depreciation", "tax"),
        ("senior_debt", "subordinated_debt"),
        ("capex", "operating_cash", "financing_cash"),
    ]:
        chosen = []
        for group in groups:
            chosen.extend(result[group])
        if len(chosen) != len(set(chosen)):
            raise ValueError("Overlapping board account groups")
    target = config.get("targets", {})
    if not isinstance(target, dict) or set(target) - LIMITS:
        raise ValueError("Unsupported board target")
    result["targets"] = {}
    for key, value in target.items():
        if value in (None, ""):
            continue
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > 100000:
            raise ValueError("Targets must be positive finite numbers")
        result["targets"][key] = str(number)
    return result


def save_settings(database, config, user_id):
    config = validate_config(database, config)
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS board_dashboard_settings (
            id INTEGER PRIMARY KEY CHECK(id=1),schema_version INTEGER NOT NULL DEFAULT 1,
            config TEXT NOT NULL,updated_by INTEGER NOT NULL,updated_at TEXT NOT NULL)""")
        connection.execute(
            """INSERT INTO board_dashboard_settings(id,config,updated_by,updated_at) VALUES(1,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET config=excluded.config,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (json.dumps(config, ensure_ascii=False), int(user_id)),
        )
        connection.execute(
            """INSERT INTO audit_log(user_id,action,entity,entity_id,details,created_at)
            VALUES(?,'update','board_dashboard_settings',1,?,CURRENT_TIMESTAMP)""",
            (int(user_id), json.dumps(config)),
        )
    return config


def _value(row, currency):
    value = row["signed"].get(currency)
    if value is None:
        raise ValueError("A ledger line has no reviewed currency conversion")
    return Decimal(str(value))


def _cash(row):
    # Same cash/bank convention as the existing executive dashboard.
    return "".join(c for c in row["code"] if c.isdigit()).startswith(("51", "53"))


def _performance(lines, currency):
    income = sum((-_value(r, currency) for r in lines if r["account_type"] == "income"), ZERO)
    expenses = sum((_value(r, currency) for r in lines if r["account_type"] == "expense"), ZERO)
    return income, income - expenses


def _ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def _yoy(current, previous):
    return (
        (current - previous) / abs(previous) * 100
        if current is not None and previous not in (None, 0)
        else None
    )


def build_board(database, start, end, currency="USD", prior_db=None, language="en"):
    start, end = iso_date(start), iso_date(end)
    if start > end or start[:4] != end[:4]:
        raise ValueError("Choose a period within one fiscal year")
    if currency not in database.currency_codes():
        raise ValueError("Choose a company currency")
    config = validate_config(database, settings(database))
    reviewed = config["reviewed"]
    # Read one snapshot; all chart values come from the same selected books.
    with database.connect() as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN")
        all_lines = database._converted_lines(currency, None, end)
    lines = [r for r in all_lines if start <= r["iso_date"] <= end]
    income, profit = _performance(lines, currency)
    cash = sum((_value(r, currency) for r in all_lines if _cash(r)), ZERO)
    prior_income = prior_profit = prior_cash = None
    prior_warning = None

    def previous(day):
        d = date.fromisoformat(day)
        try:
            return d.replace(year=d.year - 1).isoformat()
        except ValueError:
            return d.replace(year=d.year - 1, day=28).isoformat()

    prior_start, prior_end = previous(start), previous(end)
    candidate = prior_db
    if candidate is None and any(prior_start <= r["iso_date"] <= prior_end for r in all_lines):
        candidate = database
    if candidate is not None:
        try:
            prior_all = candidate._converted_lines(currency, None, prior_end)
            prior_period = [r for r in prior_all if prior_start <= r["iso_date"] <= prior_end]
            if prior_period:
                prior_income, prior_profit = _performance(prior_period, currency)
                prior_cash = sum((_value(r, currency) for r in prior_all if _cash(r)), ZERO)
        except (ValueError, ArithmeticError, LookupError) as exc:
            prior_warning = str(exc)

    def amount(group, source=lines):
        return (
            sum((_value(r, currency) for r in source if r["code"] in config[group]), ZERO)
            if reviewed
            else None
        )

    cogs, sga, interest, da, tax = [amount(k) for k in ("cogs", "sga", "interest", "depreciation", "tax")]
    ebit = profit + interest + tax if reviewed else None
    ebitda = ebit + da if reviewed else None
    senior = -amount("senior_debt", all_lines) if reviewed else None
    subordinated = -amount("subordinated_debt", all_lines) if reviewed else None
    debt = senior + subordinated if reviewed else None
    equity = -sum((_value(r, currency) for r in all_lines if r["account_type"] == "equity"), ZERO)
    # Current-year earnings may not yet have been closed into equity.
    accumulated_profit = _performance(all_lines, currency)[1]
    total_equity = equity + accumulated_profit
    assets = amount("current_assets", all_lines)
    liabilities = -amount("current_liabilities", all_lines) if reviewed else None
    full_year = start.endswith("01-01") and end.endswith("12-31") and date.fromisoformat(end) <= date.today()
    debt_ratio = _ratio(debt, ebitda) if full_year else None
    interest_coverage = _ratio(ebit, interest)
    current_ratio = _ratio(assets, liabilities)
    debt_equity = _ratio(debt, total_equity)
    # ROIC needs average invested capital at period start and end; no annualisation of partial periods.
    opening_lines = [
        r
        for r in all_lines
        if r["iso_date"] < start or r.get("source_type") == "opening" and r["iso_date"] == start
    ]
    opening_cash = sum((_value(r, currency) for r in opening_lines if _cash(r)), ZERO)
    opening_debt = -sum(
        (
            _value(r, currency)
            for r in opening_lines
            if r["code"] in set(config["senior_debt"] + config["subordinated_debt"])
        ),
        ZERO,
    )
    opening_equity = (
        -sum((_value(r, currency) for r in opening_lines if r["account_type"] == "equity"), ZERO)
        + _performance(opening_lines, currency)[1]
    )
    invested = (
        (opening_debt + opening_equity - opening_cash + debt + total_equity - cash) / 2 if reviewed else None
    )
    roic = (
        _ratio(ebit - tax, invested) * 100
        if full_year and reviewed and _ratio(ebit - tax, invested) is not None
        else None
    )
    cash_groups = defaultdict(lambda: ZERO)
    grouped_entries = defaultdict(list)
    for row in lines:
        grouped_entries[row["entry_id"]].append(row)
        if _cash(row):
            cash_groups[row.get("source_type") or "other"] += _value(row, currency)
    beginning = sum((_value(r, currency) for r in all_lines if _cash(r) and r["iso_date"] < start), ZERO)
    waterfall = [
        {"label": "Beginning cash", "value": beginning},
        *(
            {"label": key.replace("_", " ").title(), "value": value}
            for key, value in sorted(cash_groups.items())
            if value
        ),
        {"label": "Ending cash", "value": cash},
    ]
    cashflow_by_month = defaultdict(
        lambda: {"operating": ZERO, "capex": ZERO, "financing": ZERO, "unclassified": ZERO}
    )
    for entry in grouped_entries.values():
        net = sum((_value(r, currency) for r in entry if _cash(r)), ZERO)
        if not net or entry[0].get("source_type") == "opening":
            continue
        others = {r["code"] for r in entry if not _cash(r) and _value(r, currency) != 0}
        categories = []
        for label, group in [
            ("operating", "operating_cash"),
            ("capex", "capex"),
            ("financing", "financing_cash"),
        ]:
            if others and others <= set(config[group]):
                categories.append(label)
        classification = categories[0] if reviewed and len(categories) == 1 else "unclassified"
        cashflow_by_month[entry[0]["iso_date"][:7]][classification] += net
    fcf_available = reviewed and not any(v["unclassified"] for v in cashflow_by_month.values())
    # Any unmatched entry prevents FCF even if unmatched positives/negatives happen to cancel.
    unmatched = 0
    for entry in grouped_entries.values():
        net = sum((_value(r, currency) for r in entry if _cash(r)), ZERO)
        if not net or entry[0].get("source_type") == "opening":
            continue
        others = {r["code"] for r in entry if not _cash(r) and _value(r, currency) != 0}
        if (
            not reviewed
            or sum(
                bool(others) and others <= set(config[g])
                for g in ("operating_cash", "capex", "financing_cash")
            )
            != 1
        ):
            unmatched += 1
    fcf_available = fcf_available and unmatched == 0
    if fcf_available:
        classification_totals = {
            key: sum((row[key] for row in cashflow_by_month.values()), ZERO)
            for key in ("operating", "capex", "financing")
        }
        opening_adjustments = sum(
            (_value(r, currency) for r in lines if _cash(r) and r.get("source_type") == "opening"), ZERO
        )
        waterfall = [{"label": "Beginning cash", "value": beginning}]
        if opening_adjustments:
            waterfall.append({"label": "Opening balances", "value": opening_adjustments})
        waterfall.extend(
            {"label": label, "value": classification_totals[key]}
            for key, label in [
                ("operating", "Operating cash"),
                ("capex", "Capital expenditure"),
                ("financing", "Financing cash"),
            ]
            if classification_totals[key]
        )
        waterfall.append({"label": "Ending cash", "value": cash})
    last_month = int(end[5:7])
    first_month = max(int(start[5:7]), last_month - 5)
    months = []
    for month in range(first_month, last_month + 1):
        key = f"{start[:4]}-{month:02d}"
        rows = [r for r in lines if r["iso_date"][:7] == key]
        revenue, net_income = _performance(rows, currency)
        cost = amount("cogs", rows)
        cf = cashflow_by_month[key]
        months.append(
            {
                "month": calendar.month_abbr[month],
                "key": key,
                "revenue": revenue,
                "gross_margin": (
                    _ratio(revenue - cost, revenue) * 100
                    if reviewed and _ratio(revenue - cost, revenue) is not None
                    else None
                ),
                "fcf": cf["operating"] + cf["capex"] if fcf_available else None,
            }
        )
    limits = {key: Decimal(value) for key, value in config["targets"].items()}
    debt_status = "Unknown"
    if debt_ratio is not None and limits.get("debt_ebitda_max") is not None:
        debt_status = "Compliant" if debt_ratio <= limits["debt_ebitda_max"] else "Breach"
    metrics = {
        "revenue": income,
        "cash": cash,
        "net_income": profit,
        "year_end": cash if end.endswith("12-31") and date.fromisoformat(end) <= date.today() else None,
        "revenue_yoy": _yoy(income, prior_income),
        "profit_yoy": _yoy(profit, prior_profit),
        "cash_yoy": _yoy(cash, prior_cash),
        "year_end_yoy": (
            _yoy(cash, prior_cash)
            if end.endswith("12-31") and date.fromisoformat(end) <= date.today()
            else None
        ),
        "ebitda": ebitda,
        "ebit": ebit,
        "ebitda_margin": _ratio(ebitda, income) * 100 if _ratio(ebitda, income) is not None else None,
        "sga_percent": _ratio(sga, income) * 100 if _ratio(sga, income) is not None else None,
        "senior_debt": senior,
        "subordinated_debt": subordinated,
        "equity": total_equity,
        "capital": debt + total_equity if reviewed else None,
        "debt_ebitda": debt_ratio,
        "interest_coverage": interest_coverage,
        "current_ratio": current_ratio,
        "debt_equity": debt_equity,
        "roic": roic,
        "debt_status": debt_status,
        "dscr": None,
        "fcf": sum((m["fcf"] for m in months), ZERO) if fcf_available else None,
    }
    # Six-chart-month FCF is deliberately not labelled full-year YTD.
    summary = [
        f"Revenue {income:,.0f} {currency}; net income {profit:,.0f} {currency}.",
        f"Book cash {cash:,.0f} {currency} as of {end}.",
    ]
    if metrics["revenue_yoy"] is not None:
        summary.append(f"Revenue change {metrics['revenue_yoy']:+.1f}% versus the same prior-year period.")
    if debt_status != "Unknown":
        summary.append(f"Funded debt / full-year EBITDA: {debt_status.lower()}.")
    if not reviewed:
        summary.append("Account mapping needs accountant review before advanced ratios are available.")
    if language == "ar":
        summary = [
            f"الإيرادات {income:,.0f} {currency}؛ صافي الربح {profit:,.0f} {currency}.",
            f"رصيد النقد الدفتري {cash:,.0f} {currency} بتاريخ {end}.",
        ]
        if not reviewed:
            summary.append("المؤشرات المتقدمة تحتاج مراجعة ربط الحسابات.")
    return {
        "start": start,
        "end": end,
        "currency": currency,
        "year": int(start[:4]),
        "language": language,
        "metrics": metrics,
        "months": months,
        "waterfall": waterfall,
        "summary": summary,
        "targets": limits,
        "reviewed": reviewed,
        "unclassified_cash_entries": unmatched,
        "prior_warning": prior_warning,
        "bridge": [
            {"label": "Net income", "value": profit},
            {"label": "Interest", "value": interest},
            {"label": "Income tax", "value": tax},
            {"label": "D&A", "value": da},
            {"label": "EBITDA", "value": ebitda},
        ],
        "notes": {
            "year_end": "Actual cash at 31 December only; no approved year-end forecast feed is configured.",
            "covenant": "Debt / EBITDA compliance is available only for a full fiscal year with reviewed mappings and a user-entered limit. DSCR requires a debt-service schedule.",
            "fcf": "Operating cash plus net capex cash; unavailable if any non-opening cash entry is unclassified or mixed. Only displayed months are summed.",
            "ratios": "Current assets / current liabilities; funded debt / equity including unclosed earnings; ROIC=(EBIT-tax)/average invested capital, full-year only.",
            "waterfall": "Direct posted cash movement by source, including opening movements; not inferred AR/AP or cash conversion days.",
        },
    }


def _number(value):
    return Decimal(str(value)) if value is not None else None


def compact(value, currency="", percent=False, ratio=False):
    value = _number(value)
    if value is None:
        return "—"
    if percent:
        return f"{value:.1f}%"
    if ratio:
        return f"{value:.1f}x"
    sign = "−" if value < 0 else ""
    amount = abs(value)
    symbol = {"USD": "$", "EUR": "€", "LBP": "LBP "}.get(currency, currency + " " if currency else "")
    scale, suffix = (
        (Decimal(1000000000000), "T")
        if amount >= 1000000000000
        else (
            (Decimal(1000000000), "B")
            if amount >= 1000000000
            else (
                (Decimal(1000000), "M")
                if amount >= 1000000
                else (Decimal(1000), "K") if amount >= 1000 else (Decimal(1), "")
            )
        )
    )
    return f"{sign}{symbol}{amount/scale:.2f}".rstrip("0").rstrip(".") + suffix


def _display(text, language="en"):
    if language == "ar" and any("\u0600" <= c <= "\u06ff" for c in str(text)):
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(str(text)))
    return str(text)


def render_board(data):
    """One vector figure is shared by Tk and full-board PDF; no links, ads or footer."""
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyBboxPatch, Rectangle
    from matplotlib.ticker import FuncFormatter
    from matplotlib import font_manager
    import textwrap
    import nanza_paths

    ar = data.get("language") == "ar"
    family = "DejaVu Sans"
    font = nanza_paths.ROOT / "Assets" / "fonts" / "Amiri-Regular.ttf"
    if ar and font.exists():
        font_manager.fontManager.addfont(str(font))
        family = "Amiri"
    figure = Figure(figsize=(12.8, 8.5), dpi=100, facecolor="white")
    background = figure.add_axes([0, 0, 1, 1])
    background.set_axis_off()
    background.set_xlim(0, 1)
    background.set_ylim(0, 1)
    background.add_patch(Rectangle((0, 0.915), 1, 0.085, color=BLACK))

    def txt(ax, x, y, text, size=10, color=BLACK, weight="normal", ha="left", va="center", **kw):
        return ax.text(
            x,
            y,
            _display(text, "ar" if ar else "en"),
            fontsize=size,
            color=color,
            fontweight=weight,
            ha=ha,
            va=va,
            fontfamily=family,
            **kw,
        )

    txt(background, 0.035, 0.958, "NANZA", 29, GOLD, "bold")
    txt(
        background,
        0.275,
        0.966,
        "The Complete Board Dashboard" if not ar else "لوحة الإدارة المالية الشاملة",
        16,
        "white",
        "bold",
    )
    txt(
        background,
        0.275,
        0.938,
        data.get("company_name")
        or (
            "Income statement · Balance sheet · Cash flow"
            if not ar
            else "قائمة الدخل • الميزانية • التدفقات النقدية"
        ),
        9,
        "#e1e1e1",
    )
    txt(background, 0.965, 0.961, f"FY{data['year']} • Board Review", 11, GOLD, "bold", ha="right")
    txt(background, 0.965, 0.936, f"{data['end']} • {data['currency']}", 9, "white", ha="right")
    metrics = data["metrics"]
    currency = data["currency"]
    icons = ["Revenue", "Cash", "Net", "Year"]
    kpis = [
        ("Revenue", "الإيرادات", "revenue", "revenue_yoy"),
        ("Cash", "النقد", "cash", "cash_yoy"),
        ("Net Income", "صافي الربح", "net_income", "profit_yoy"),
        ("Year-End", "نهاية السنة", "year_end", "year_end_yoy"),
    ]
    for i, (en, arabic, key, delta) in enumerate(kpis):
        x = 0.035 + i * 0.238
        background.add_patch(
            FancyBboxPatch(
                (x, 0.748),
                0.224,
                0.15,
                boxstyle="round,pad=.003,rounding_size=.004",
                facecolor="white",
                edgecolor="#e7edf3",
                linewidth=0.7,
            )
        )
        if i == 0:
            for bar, height in enumerate((0.025, 0.041, 0.032)):
                background.add_patch(
                    Rectangle(
                        (x + 0.014 + bar * 0.012, 0.807),
                        0.008,
                        height,
                        fill=False,
                        edgecolor=GOLD,
                        linewidth=1.5,
                    )
                )
        elif i == 1:
            for step in range(3):
                background.add_patch(
                    Rectangle(
                        (x + 0.014 + step * 0.003, 0.809 + step * 0.011),
                        0.032,
                        0.015,
                        fill=False,
                        edgecolor=GOLD,
                        linewidth=1.5,
                    )
                )
        elif i == 2:
            background.plot(
                [x + 0.014, x + 0.027, x + 0.037, x + 0.049],
                [0.812, 0.834, 0.827, 0.853],
                color=GOLD,
                linewidth=2,
            )
            background.annotate(
                "",
                xy=(x + 0.049, 0.853),
                xytext=(x + 0.037, 0.827),
                arrowprops={"arrowstyle": "->", "color": GOLD, "lw": 2},
            )
        else:
            background.add_patch(
                Rectangle((x + 0.014, 0.811), 0.035, 0.039, fill=False, edgecolor=GOLD, linewidth=1.5)
            )
            background.plot([x + 0.014, x + 0.049], [0.839, 0.839], color=GOLD, linewidth=1.5)
        txt(background, x + 0.061, 0.875, arabic if ar else en, 12, GOLD, "bold")
        value = metrics.get(key)
        txt(
            background,
            x + 0.061,
            0.83,
            compact(value, currency),
            27,
            RED if value is not None and _number(value) < 0 else BLACK,
            "bold",
        )
        change = metrics.get(delta)
        if change is not None:
            change = _number(change)
            txt(background, x + 0.061, 0.776, f"{change:+.1f}% YoY", 9, GREEN if change >= 0 else RED, "bold")
        else:
            label = (
                "Actual cash · no forecast"
                if key == "year_end" and value is not None
                else "No approved forecast" if key == "year_end" else "YoY unavailable"
            )
            txt(background, x + 0.061, 0.776, label, 8, "#777777")

    def panel(x, y, w, h, title, arabic):
        background.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=.002,rounding_size=.005",
                facecolor="white",
                edgecolor="#cfcfcf",
                linewidth=1,
            )
        )
        background.add_patch(Rectangle((x, y + h - 0.042), w, 0.042, color=BLACK))
        background.add_patch(Rectangle((x, y + h - 0.004), w, 0.004, color=GOLD))
        txt(background, x + 0.009, y + h - 0.023, arabic if ar else title, 12, GOLD, "bold")
        ax = figure.add_axes([x + 0.012, y + 0.012, w - 0.024, h - 0.062])
        ax.set_axis_off()
        return ax

    # Three compact columns keep related figures together without oversized card gaps.
    left = 0.03
    middle = 0.35
    right = 0.67
    width = 0.30
    summary = panel(left, 0.38, width, 0.34, "Exec Summary", "ملخص الإدارة")
    summary_text = "\n".join(textwrap.fill(line, 43 if not ar else 46) for line in data["summary"][:3])
    txt(summary, 0.01, 0.97, summary_text, 9, va="top", linespacing=1.5)
    for y, key, label, target in [
        (0.28, "ebitda_margin", "EBITDA Margin", "ebitda_margin_target"),
        (0.085, "sga_percent", "SG&A as % Revenue", "sga_max"),
    ]:
        txt(summary, 0.01, y + 0.075, label, 9, weight="bold")
        txt(summary, 0.99, y + 0.075, compact(metrics.get(key), percent=True), 11, weight="bold", ha="right")
        summary.add_patch(Rectangle((0.01, y), 0.98, 0.022, color="#eeeeee"))
        v = _number(metrics.get(key))
        if v is not None:
            summary.add_patch(
                Rectangle((0.01, y), min(0.98, max(0, float(v) / 100) * 0.98), 0.022, color=GOLD)
            )
        limit = data.get("targets", {}).get(target)
        txt(
            summary,
            0.01,
            y - 0.04,
            "Target " + (compact(limit, percent=True) if limit is not None else "not configured"),
            7,
            "#777777",
        )
    panel(left, 0.055, width, 0.305, "Revenue and Margins", "الإيرادات والهوامش")
    revenue_ax = figure.add_axes([left + 0.034, 0.1, width - 0.064, 0.19])
    months = data["months"]
    xs = list(range(len(months)))
    revenues = [float(_number(r["revenue"])) for r in months]
    revenue_ax.bar(xs, revenues, color=GOLD, width=0.58, alpha=0.85)
    revenue_ax.set_xticks(xs, [r["month"] for r in months], fontsize=8)
    revenue_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: compact(value)))
    revenue_ax.tick_params(axis="y", labelsize=7)
    revenue_ax.spines[["top", "right"]].set_visible(False)
    revenue_ax.grid(axis="y", alpha=0.16)
    margins = [r["gross_margin"] for r in months]
    if margins and any(v is not None for v in margins):
        second = revenue_ax.twinx()
        second.plot(
            xs,
            [float(_number(v)) if v is not None else float("nan") for v in margins],
            color=BLACK,
            marker="o",
            linewidth=1.4,
        )
        second.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
        second.tick_params(labelsize=7)
        second.spines["top"].set_visible(False)
    cov = panel(middle, 0.535, width, 0.185, "Funded Debt Covenant", "تعهدات الديون المموّلة")
    status = metrics["debt_status"]
    tone = GREEN if status == "Compliant" else RED if status == "Breach" else "#777777"
    txt(cov, 0.01, 0.83, status, 12, tone, "bold")
    txt(cov, 0.98, 0.83, compact(metrics["debt_ebitda"], ratio=True), 16, weight="bold", ha="right")
    txt(cov, 0.01, 0.57, "Debt / full-year EBITDA", 8)
    limit = data.get("targets", {}).get("debt_ebitda_max")
    txt(
        cov,
        0.01,
        0.34,
        "Limit: " + (compact(limit, ratio=True) if limit is not None else "not configured"),
        8,
        "#777777",
    )
    txt(cov, 0.01, 0.1, "DSCR: —  ·  debt-service schedule needed", 8, "#777777")
    panel(middle, 0.29, width, 0.225, "Cash-to-Cash Waterfall", "جسر حركة النقد")
    bridge_ax = figure.add_axes([middle + 0.095, 0.325, width - 0.125, 0.14])
    rows = data["waterfall"]
    if len(rows) > 7:
        rows = [
            rows[0],
            *rows[1:5],
            {"label": "Other movements", "value": sum((_number(r["value"]) for r in rows[5:-1]), ZERO)},
            rows[-1],
        ]
    values = [float(_number(r["value"])) for r in rows]
    bridge_ax.barh(
        range(len(rows)),
        values,
        color=[GOLD if i in (0, len(rows) - 1) else GREEN if v >= 0 else RED for i, v in enumerate(values)],
        height=0.62,
    )
    bridge_ax.set_yticks(range(len(rows)), [r["label"] for r in rows], fontsize=7)
    bridge_ax.invert_yaxis()
    bridge_ax.spines[["top", "right", "bottom"]].set_visible(False)
    bridge_ax.tick_params(axis="x", bottom=False, labelbottom=False)
    for i, v in enumerate(values):
        bridge_ax.annotate(compact(v), (v, i), fontsize=7, ha="left" if v >= 0 else "right", va="center")
    bridge = panel(middle, 0.055, width, 0.215, "Built as a Bridge", "جسر تفسير الربح")
    items = data["bridge"]
    for i, item in enumerate(items):
        y = 0.9 - i * 0.19
        txt(bridge, 0.02, y, item["label"], 9, weight="bold" if i in (0, 4) else "normal")
        txt(
            bridge,
            0.98,
            y,
            compact(item["value"], currency),
            10,
            GOLD if i == 4 else BLACK,
            "bold" if i == 4 else "normal",
            ha="right",
        )
    capital = panel(right, 0.55, width, 0.17, "Capital Structure", "هيكل رأس المال")
    components = [metrics["senior_debt"], metrics["equity"], metrics["subordinated_debt"]]
    if (
        all(v is not None and _number(v) >= 0 for v in components)
        and sum((_number(v) for v in components), ZERO) > 0
    ):
        donut = figure.add_axes([right + 0.008, 0.566, 0.09, 0.098])
        donut.pie(
            [float(_number(v)) for v in components],
            colors=[GOLD, BLACK, "#aaaaaa"],
            wedgeprops={"width": 0.28, "edgecolor": "white"},
        )
        donut.set_aspect("equal")
    else:
        txt(capital, 0.12, 0.47, "—", 28, "#888888", ha="center")
    txt(capital, 0.37, 0.84, "Senior debt  " + compact(components[0]), 7)
    txt(capital, 0.37, 0.62, "Equity  " + compact(components[1]), 7)
    txt(capital, 0.37, 0.4, "Subordinated  " + compact(components[2]), 7)
    txt(capital, 0.99, 0.16, compact(metrics["capital"], currency), 17, weight="bold", ha="right")
    ratios = panel(right, 0.365, width, 0.165, "Ratios Against Target", "المؤشرات مقابل المستهدف")
    for y, key, label, target, percentage, lower_better in [
        (0.85, "current_ratio", "Current ratio", "current_ratio_min", False, False),
        (0.52, "debt_equity", "Debt / equity", "debt_equity_max", False, True),
        (0.19, "roic", "ROIC", "roic_min", True, False),
    ]:
        v = _number(metrics.get(key))
        limit = _number(data.get("targets", {}).get(target))
        tone = (
            "#777777"
            if v is None or limit is None
            else GREEN if (v <= limit if lower_better else v >= limit) else RED
        )
        txt(ratios, 0.01, y, label, 9)
        txt(
            ratios,
            0.66,
            y,
            compact(v, percent=percentage, ratio=not percentage),
            10,
            weight="bold",
            ha="right",
        )
        txt(ratios, 0.99, y, compact(limit, percent=percentage, ratio=not percentage), 8, tone, ha="right")
    fcf = panel(right, 0.205, width, 0.14, "Free Cash Flow", "التدفق النقدي الحر")
    fcf_values = [r["fcf"] for r in months]
    if fcf_values and all(v is not None for v in fcf_values):
        ax = figure.add_axes([right + 0.025, 0.227, width - 0.05, 0.066])
        ax.bar(xs, [float(_number(v)) for v in fcf_values], color=GOLD, width=0.62)
        ax.set_xticks(xs, [r["month"] for r in months], fontsize=7)
        ax.yaxis.set_visible(False)
        ax.spines[["top", "right", "left"]].set_visible(False)
    else:
        txt(fcf, 0.5, 0.5, "—", 24, "#888888", ha="center")
    coverage = panel(right, 0.055, width, 0.13, "Year-End Cash & Coverage", "نقد نهاية السنة والتغطية")
    txt(coverage, 0.01, 0.88, "Year-end cash", 8)
    txt(coverage, 0.99, 0.88, "Interest coverage", 8, ha="right")
    txt(coverage, 0.01, 0.38, compact(metrics["year_end"], currency), 19, weight="bold")
    txt(
        coverage, 0.99, 0.38, compact(metrics["interest_coverage"], ratio=True), 19, weight="bold", ha="right"
    )
    return figure


def export_board_pdf(data, path):
    """Re-render a snapshot with Agg; vector PDF contains the full clean board, no footer."""
    from pathlib import Path
    import tempfile
    import os

    target = Path(path)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, suffix=".pdf", prefix=".nanza-board-", delete=False
    ) as tmp:
        temporary = Path(tmp.name)
    figure = None
    try:
        figure = render_board(data)
        figure.savefig(temporary, format="pdf", facecolor="white")
        os.replace(temporary, target)
    finally:
        if figure is not None:
            figure.clear()
        temporary.unlink(missing_ok=True)
    return str(target)


def open_board(app):
    """CustomTkinter shell over the existing Tk app; original dashboard stays intact."""
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from desktop_workbench import async_call, context_key, tooltip
    from desktop_common import parse_user_date

    class BoardWindow(ctk.CTkToplevel):
        def __init__(self):
            super().__init__(app, fg_color="white")
            self.app = app
            self.scope = context_key(app)
            self.data = None
            self.figure = None
            self.canvas = None
            self.title("NANZA | The Complete Board Dashboard")
            # Start maximized, using the window manager's usable work area. The figure
            # below already tracks the holder size, so it follows later resizes too.
            self.after_idle(self._maximize_window)
            self.bar = ctk.CTkFrame(self, fg_color=BLACK, corner_radius=0, height=35)
            self.bar.pack(fill="x")
            initial_day = parse_user_date(app.fiscal_today()).date()
            if initial_day.year < date.today().year:
                initial_day = initial_day.replace(month=12, day=31)
            self.day = tk.StringVar(value=initial_day.isoformat())
            currency = app.dashboard_base_currency.get()
            self.currency = tk.StringVar(value="USD" if currency == "All Currencies" else currency)
            ctk.CTkEntry(self.bar, textvariable=self.day, width=115, height=27).pack(
                side="left", padx=6, pady=4
            )
            self.currency_box = ctk.CTkComboBox(
                self.bar, variable=self.currency, values=["USD", "LBP", "EUR"], width=90, height=27
            )
            self.currency_box.pack(side="left", padx=4)
            self.refresh_button = ctk.CTkButton(
                self.bar, text="↻", width=36, height=27, fg_color=GOLD, text_color=BLACK, command=self.load
            )
            self.refresh_button.pack(side="left", padx=4)
            self.configure_button = ctk.CTkButton(
                self.bar,
                text="⚙",
                width=36,
                height=27,
                fg_color=GOLD,
                text_color=BLACK,
                command=self.configure_accounts,
            )
            self.configure_button.pack(side="right", padx=4)
            self.pdf_button = ctk.CTkButton(
                self.bar,
                text="PDF",
                width=65,
                height=27,
                fg_color=GOLD,
                text_color=BLACK,
                command=self.export,
            )
            self.pdf_button.pack(side="right", padx=4)
            self.update_idletasks()
            screen_width=max(1,self.winfo_screenwidth())
            screen_height=max(1,self.winfo_screenheight())
            self.minsize(
                min(max(620,self.bar.winfo_reqwidth()),screen_width),
                min(max(400,self.bar.winfo_reqheight()+300),screen_height),
            )
            tooltip(self.refresh_button, "تحديث بيانات الشركة والسنة المختارتين؛ لا يتم ترحيل أي قيد")
            tooltip(
                self.configure_button,
                "ربط المؤشرات بالحسابات الفعلية وإدخال حدود التعهدات بعد مراجعة المحاسب",
            )
            tooltip(self.pdf_button, "تصدير كامل اللوحة إلى PDF، بلا روابط أو تذييل أو إعلانات")
            self.holder = tk.Frame(self, bg="white")
            self.holder.pack(fill="both", expand=True)
            self.state_label = tk.Label(
                self.holder, text="Loading board / تحميل اللوحة…", bg="white", fg=BLACK
            )
            self.state_label.pack(expand=True)
            self.bind("<Control-b>", lambda _e: self.lift())
            self.bind("<Control-e>", lambda _e: self.export())
            self._scope_timer = self.after(300, self.check_scope)
            self.load()

        def _maximize_window(self):
            try:
                self.state("zoomed")
            except tk.TclError:
                try:
                    self.attributes("-zoomed", True)
                except (tk.TclError, TypeError):
                    self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
            self.lift()

        def check_scope(self):
            if context_key(app) != self.scope:
                self.destroy()
                return
            self._scope_timer = self.after(300, self.check_scope)

        def destroy(self):
            timer = getattr(self, "_scope_timer", None)
            if timer:
                self.after_cancel(timer)
            super().destroy()

        def load(self):
            try:
                end = parse_user_date(self.day.get()).date().isoformat()
            except ValueError as exc:
                return messagebox.showerror("Board", str(exc), parent=self)
            start = end[:4] + "-01-01"
            currency = self.currency.get()
            language = app.language.get()
            self.pdf_button.configure(state="disabled")
            self.data = None
            async_call(
                self,
                app,
                lambda c: c.workbench(
                    "board", date_from=start, date_to=end, currency=currency, language=language
                ),
                self.loaded,
            )

        def loaded(self, data):
            self.data = data
            if self.canvas is not None:
                self.canvas.get_tk_widget().destroy()
            if self.figure is not None:
                self.figure.clear()
            self.state_label.pack_forget()
            self.figure = render_board(data)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.holder)
            widget = self.canvas.get_tk_widget()
            widget.pack(fill="both", expand=True)
            widget.bind("<Configure>", self.resize_figure, add="+")
            self.canvas.draw_idle()
            self.pdf_button.configure(state="normal")
            tooltip(
                self.canvas.get_tk_widget(),
                "الأرقام من القيود المرحّلة. الشرطة — تعني بيانات أو إعدادات غير متاحة. افتح ⚙ لربط الحسابات. نهاية السنة الفعلية ليست توقعاً.",
            )

        def resize_figure(self, event):
            if self.figure is None or event.width < 200 or event.height < 200:
                return
            dpi = self.figure.get_dpi()
            size = (event.width / dpi, event.height / dpi)
            if any(abs(old - new) > 0.03 for old, new in zip(self.figure.get_size_inches(), size)):
                self.figure.set_size_inches(*size, forward=True)
                self.canvas.draw_idle()

        def export(self):
            if self.data is None:
                return
            path = filedialog.asksaveasfilename(
                parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
            )
            if not path:
                return
            snapshot = self.data
            self.pdf_button.configure(state="disabled")
            # A separate worker owner keeps PDF work independent of refresh requests.
            owner = tk.Frame(self)

            def done(_result):
                self.pdf_button.configure(state="normal")
                owner.destroy()

            async_call(owner, app, lambda _c: export_board_pdf(snapshot, path), done)

        def configure_accounts(self):
            if getattr(app, "current_user", None) and app.current_user.get("role") != "admin":
                return messagebox.showinfo(
                    "Board", "Account mapping requires administrator permission.", parent=self
                )
            owner = tk.Frame(self)

            def show(result):
                owner.destroy()
                dialog = ctk.CTkToplevel(self, fg_color="white")
                dialog.title("Board account mapping / ربط الحسابات")
                dialog.geometry("850x710")
                config = result["config"]
                accounts = result["accounts"]
                labels = {
                    f"{r['code']} · {r['name_en']}": r["code"]
                    for r in accounts
                    if r["is_active"] and r["is_posting"]
                }
                variables = {}
                scroller = ctk.CTkScrollableFrame(dialog, fg_color="white")
                scroller.pack(fill="both", expand=True, padx=12, pady=12)
                for group, title in GROUPS.items():
                    row = ctk.CTkFrame(scroller, fg_color="#f4f4f4")
                    row.pack(fill="x", pady=3)
                    ctk.CTkLabel(row, text=title, width=240, anchor="w", text_color=BLACK).pack(
                        side="left", padx=6
                    )
                    var = tk.StringVar(value=", ".join(config.get(group, [])))
                    variables[group] = var
                    ctk.CTkEntry(row, textvariable=var, width=330).pack(side="left", padx=5)

                    def choose(g=group, v=var):
                        popup = ctk.CTkToplevel(dialog)
                        popup.title(GROUPS[g])
                        popup.geometry("600x450")
                        search = tk.StringVar()
                        ctk.CTkEntry(
                            popup, textvariable=search, placeholder_text="Search accounts / ابحث"
                        ).pack(fill="x", padx=10, pady=8)
                        box = tk.Listbox(popup, selectmode="multiple", exportselection=False)
                        box.pack(fill="both", expand=True, padx=10)
                        selected = {x.strip() for x in v.get().split(",") if x.strip()}
                        visible = []

                        def redraw(*_):
                            visible[:] = [
                                label for label in labels if search.get().casefold() in label.casefold()
                            ]
                            box.delete(0, "end")
                            for i, label in enumerate(visible):
                                box.insert("end", label)
                                if labels[label] in selected:
                                    box.selection_set(i)

                        def remember(_event=None):
                            selected.difference_update(labels[label] for label in visible)
                            selected.update(labels[visible[i]] for i in box.curselection())

                        box.bind("<<ListboxSelect>>", remember)
                        search.trace_add("write", redraw)
                        redraw()
                        ctk.CTkButton(
                            popup,
                            text="Use selection",
                            command=lambda: (v.set(", ".join(sorted(selected))), popup.destroy()),
                        ).pack(pady=8)

                    ctk.CTkButton(row, text="…", width=30, command=choose).pack(side="left")
                target_vars = {}
                for target in sorted(LIMITS):
                    row = ctk.CTkFrame(scroller, fg_color="white")
                    row.pack(fill="x", pady=3)
                    ctk.CTkLabel(
                        row, text=target.replace("_", " ").title(), width=280, anchor="w", text_color=BLACK
                    ).pack(side="left")
                    var = tk.StringVar(value=str(config.get("targets", {}).get(target, "")))
                    target_vars[target] = var
                    ctk.CTkEntry(row, textvariable=var, width=120).pack(side="left")
                reviewed = tk.BooleanVar(value=config.get("reviewed", False))
                ctk.CTkCheckBox(
                    dialog,
                    text="I reviewed all mappings; empty groups mean confirmed zero / راجعت الربط",
                    variable=reviewed,
                    text_color=BLACK,
                ).pack(pady=8)

                def save():
                    payload = {
                        key: [x.strip() for x in value.get().split(",") if x.strip()]
                        for key, value in variables.items()
                    }
                    payload.update(
                        reviewed=reviewed.get(),
                        targets={k: v.get() for k, v in target_vars.items() if v.get().strip()},
                    )

                    def saved(_r):
                        dialog.destroy()
                        self.load()

                    async_call(
                        dialog,
                        app,
                        lambda c: c.request("POST", "/api/workbench/board-settings", {"config": payload}),
                        saved,
                    )

                ctk.CTkButton(dialog, text="Save reviewed settings / حفظ", command=save).pack(pady=8)

            async_call(
                owner,
                app,
                lambda c: {"config": c.workbench("board-settings"), "accounts": c.accounts()},
                show,
            )

    return BoardWindow()
