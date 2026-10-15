"""2.9.120: the program with a year of a big company - is it still fast?

Builds a made-up company (nothing real) for 2026 and times the screens and reports an accountant uses every day:

    python tools/scale_test.py build  <folder>      the company: 1,500 customers, 150 suppliers, 20,000 invoices with 3-5 lines,
                                                     8,000 receipts / payments settled against invoices, 2,000 journal vouchers,
                                                     in USD, LBP and EUR over the 12 months
    python tools/scale_test.py measure <folder>     the time of each report (seconds), written to <folder>/timings.json

Not part of the program: a check before each version (the data stays in <folder>).
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import nanza_paths  # noqa: E402,F401

CUSTOMERS, SUPPLIERS, SALES, PURCHASES, PAYMENTS, VOUCHERS = 1500, 150, 16000, 4000, 8000, 2000
YEAR = 2026
WORDS = ["Consulting", "Paper A4", "Toner", "Cement", "Steel bars", "Olive oil", "Software licence", "Maintenance", "Transport", "Training",
         "Printing", "Cleaning", "Security", "Rent", "Electric cable", "Paint", "Tiles", "Coffee", "Water", "Fuel"]


def _day(rng):
    return date(YEAR, 1, 1) + timedelta(days=rng.randrange(365))


def _money(currency, rng):
    if currency == "LBP": return rng.randrange(100, 5000) * 10000
    return round(rng.uniform(20, 2500), 2)


def open_company(folder):
    from database import Database
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    db = Database(folder / "big_company.db", pooled=True)  # as the data service keeps it
    db.initialize_if_needed("Scale-Test-2026!")
    user = db.user_for_token(db.login("admin", "Scale-Test-2026!")["token"])["id"]
    return db, user


def build(folder):
    rng = random.Random(119)
    db, user = open_company(folder)
    started = time.perf_counter(); log = lambda text: print(f"{time.perf_counter() - started:7.1f}s  {text}", flush=True)
    with db.connect() as connection:  # EUR rates of every day (made-up but realistic), entered by a user (not the offline default)
        rows = []; day = date(YEAR, 1, 1)
        while day.year == YEAR:
            text = day.strftime("%d-%m-%Y"); eur = 1.05 + 0.08 * ((day.timetuple().tm_yday % 90) / 90)
            rows += [(text, "EUR", "USD", f"{eur:.4f}", user, "x"), (text, "EUR", "LBP", f"{eur * 89500:.2f}", user, "x"), (text, "USD", "LBP", "89500", user, "x")]
            day += timedelta(days=1)
        connection.executemany("""INSERT INTO exchange_rates(rate_date,from_currency,to_currency,rate,created_by,created_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(rate_date,from_currency,to_currency) DO NOTHING""", rows)
    customers = [db.save_party({"kind": "customer", "name": f"Customer {n:04d} SARL", "currency": rng.choice(["USD"] * 7 + ["LBP"] * 2 + ["EUR"]),
                                "due_days": rng.choice([0, 30, 60, 90])}, user) for n in range(1, CUSTOMERS + 1)]
    log(f"{len(customers)} customers")
    suppliers = [db.save_party({"kind": "supplier", "name": f"Supplier {n:03d} SAL", "currency": rng.choice(["USD"] * 8 + ["LBP"] * 2)}, user)
                 for n in range(1, SUPPLIERS + 1)]
    log(f"{len(suppliers)} suppliers")
    sales = []
    for n in range(1, SALES + 1):
        party = rng.choice(customers); currency = party["currency"]
        lines = [{"description": rng.choice(WORDS), "quantity": rng.randint(1, 20), "unit_price": _money(currency, rng) / 10} for _ in range(rng.randint(3, 5))]
        invoice = db.create_manual_invoice({"invoice_number": f"SAL-{YEAR}-{n:06d}", "invoice_date": _day(rng).strftime("%d-%m-%Y"),
                                            "party_name": party["name"], "kind": "sale", "currency": currency}, lines, user)
        sales.append((invoice["id"] if isinstance(invoice, dict) else int(invoice), party, currency))
        if n % 2000 == 0: log(f"{n} sales invoices")
    for n in range(1, PURCHASES + 1):
        party = rng.choice(suppliers); currency = party["currency"]
        lines = [{"description": rng.choice(WORDS), "quantity": rng.randint(1, 20), "unit_price": _money(currency, rng) / 10} for _ in range(rng.randint(3, 5))]
        db.create_manual_invoice({"invoice_number": f"F-{n:05d}", "invoice_date": _day(rng).strftime("%d-%m-%Y"), "party_name": party["name"],
                                  "kind": "purchase", "currency": currency}, lines, user)
        if n % 2000 == 0: log(f"{n} purchase invoices")
    with db.connect() as connection:
        totals = {r[0]: (r[1], r[2]) for r in connection.execute("SELECT id, CAST(total AS REAL), invoice_date FROM invoices WHERE kind='sale'")}
    for n, (invoice_id, party, currency) in enumerate(rng.sample(sales, PAYMENTS), 1):
        total, invoice_day = totals[invoice_id]
        day = min(date(YEAR, 12, 31), date(int(invoice_day[6:]), int(invoice_day[3:5]), int(invoice_day[:2])) + timedelta(days=rng.randrange(0, 60)))
        amount = round(total * rng.choice([1, 1, 1, 0.5]), 2)
        payment = db.add_payment({"kind": "customer_receipt", "payment_date": day.strftime("%d-%m-%Y"), "party_id": party["id"], "currency": currency,
                                  "amount": str(amount), "cash_account": "531", "party_account": party["account_number"]}, user)
        payment_id = payment["id"] if isinstance(payment, dict) else int(payment)
        db.save_allocations(payment_id, [{"invoice_id": invoice_id, "amount": amount}], user)
        if n % 2000 == 0: log(f"{n} receipts")
    vouchers(db, user, rng, log)
    log("done")


def vouchers(db, user, rng, log=print):
    for n in range(1, VOUCHERS + 1):
        amount = round(rng.uniform(10, 3000), 2); debit, credit = rng.choice([("6263.1", "531"), ("6263.2", "5121"), ("5121", "531"), ("6263.3", "531")])
        db.save_journal_voucher({"entry_date": _day(rng).strftime("%d-%m-%Y"), "currency": "USD", "description": f"Voucher {n}"},
                                [{"account_code": debit, "debit": str(amount)}, {"account_code": credit, "credit": str(amount)}], user)
        if n % 1000 == 0: log(f"{n} journal vouchers")


def _time(label, function, results):
    started = time.perf_counter()
    try: value = function(); status = "ok"
    except Exception as exc:  # noqa: BLE001 - a timing tool: every failure is written down and the next report runs
        value = None; status = f"failed: {exc}"
    seconds = round(time.perf_counter() - started, 2)
    results.append({"report": label, "seconds": seconds, "status": status}); print(f"{seconds:7.2f}s  {label}  {status}", flush=True)
    return value


def measure(folder):
    import books_check, ledger_reports, vat_return
    from business_reports import ageing
    db, user = open_company(folder); results = []
    with db.connect() as connection:
        party = connection.execute("SELECT id FROM parties WHERE kind='customer' ORDER BY id LIMIT 1").fetchone()[0]
    import business_reports
    _time("Dashboard figures", db.professional_dashboard, results)
    _time("Dashboard charts", lambda: business_reports.dashboard_charts(db, {"year": YEAR, "basis": "USD"}), results)
    _time("Invoices list (Uploaded Data)", db.list_invoices, results)
    _time("Receipts / payments list", db.list_payments, results)
    _time("Trial balance (year)", lambda: db.trial_balance(f"01-01-{YEAR}", f"31-12-{YEAR}"), results)
    _time("General journal (all)", lambda: db.journal(f"01-01-{YEAR}", f"31-12-{YEAR}"), results)
    _time("Statement of account (one customer)", lambda: db.statement_of_account(party, f"01-01-{YEAR}", f"31-12-{YEAR}", None, True, None, None), results)
    _time("Receivables ageing", lambda: ageing(db, {"date_to": f"31-12-{YEAR}", "side": "receivables", "basis": "USD"}), results)
    _time("Top clients", lambda: business_reports.build(db, "top_clients", {"date_from": f"01-01-{YEAR}", "date_to": f"31-12-{YEAR}", "basis": "USD"}), results)
    _time("Accounts report (general ledger, detailed)", lambda: ledger_reports.build_account_report(db, {"date_from": f"01-01-{YEAR}", "date_to": f"31-12-{YEAR}",
                                                                                                    "first_column": "USD", "second_column": "LBP", "detailed": True}), results)
    _time("Accounts report (trial balance view)", lambda: ledger_reports.build_account_report(db, {"date_from": f"01-01-{YEAR}", "date_to": f"31-12-{YEAR}",
                                                                                                "first_column": "USD", "second_column": "LBP"}), results)
    for quarter in (1, 2, 3, 4):
        _time(f"VAT return Q{quarter}", lambda q=quarter: vat_return.build_vat_return(db, YEAR, q), results)
    _time("Books Health Check", lambda: books_check.run(db, YEAR), results)
    _time("Books Health Check (dashboard, quick)", lambda: books_check.run(db, YEAR, quick=True), results)
    _time("Save one new sales invoice", lambda: db.create_manual_invoice({"invoice_date": f"15-12-{YEAR}", "party_name": "Customer 0001 SARL", "kind": "sale",
                                                                        "currency": "USD"}, [{"description": "Test", "quantity": 1, "unit_price": 10}], user), results)
    (Path(folder) / "timings.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return results


if __name__ == "__main__":
    action, target = sys.argv[1], sys.argv[2]
    if action == "build": build(target)
    elif action == "vouchers": vouchers(*open_company(target), random.Random(120))
    else: measure(target)
