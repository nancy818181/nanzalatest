#!/usr/bin/env python3
"""Nanza trial simulation (2.9.133): a known scenario posted through the public Database API, then every figure is
recomputed independently with Python Decimal (no Nanza code produces an expected value) and compared.

It is a headless acceptance check for a trial installation: no Tk, no network, a temporary company file only.
All amounts and the exchange rate are SYNTHETIC test data (USD/LBP 89,500 is a fixture, not a recommended rate).

    python tools/trial_simulation.py            # prints PASS / FAIL / GAP per check, exit code 1 if a CORE check fails
    python tools/trial_simulation.py --json     # the same as JSON

Check kinds
  core     arithmetic and report identities that must always hold (trial balance, VAT, year close, backup ...)
  control  accounting controls. A control that is not enforced yet is reported as GAP (known, owner decision pending),
           never silently skipped. See docs/TRIAL_PLAN.md, section "Decisions still open".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATE = D("89500")  # SYNTHETIC USD -> LBP test rate


def _load():
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("SABER_FIRST_COMPANY", "Trial Co SARL|2026")
    import nanza_paths  # noqa: F401
    from database import Database
    return Database


def run(workdir=None):
    """Run the scenario in `workdir` (a temp folder when None). Returns a list of {name, ok, kind, detail}."""
    Database = _load()
    import books_check
    import vat_return
    own_tmp = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="nanza_trial_"))
    results = []

    def chk(name, ok, detail="", kind="core"):
        results.append({"name": name, "ok": bool(ok), "kind": kind, "detail": str(detail)[:300]})

    def attempt(fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
            return None
        except Exception as exc:  # the control's own refusal is the evidence
            return f"{type(exc).__name__}: {exc}"

    db = Database(workdir / "trial.db")
    db.initialize("Trial-Only-Password-2026!")
    try:
        db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "31-12-2026", "from_currency": "USD",
                               "to_currency": "LBP", "rate": str(RATE)}, 1)
        customer = db.save_party({"kind": "customer", "name": "Trial Customer", "currency": "USD"}, 1)
        supplier = db.save_party({"kind": "supplier", "name": "Trial Supplier", "currency": "USD"}, 1)

        def voucher(number, date, currency, lines, description="trial"):
            return db.save_journal_voucher(
                {"entry_number": number, "entry_date": date, "description": description, "currency": currency},
                [{"account_code": c, "debit": d, "credit": k} for c, d, k in lines], 1)

        def invoice(number, date, party, kind, currency, price, vat_rate, _db=None, **extra):
            return (_db or db).create_manual_invoice(
                {"invoice_number": number, "invoice_date": date, "party_name": party, "kind": kind,
                 "currency": currency, "status": "posted", **extra},
                [{"description": "line", "quantity": 1, "unit_price": price, "vat_rate": vat_rate}], 1)

        # ---------------------------------------------------------------- the scenario (USD unless stated)
        voucher("T-001", "01-01-2026", "USD", [("531", "10000.00", "0"), ("1013", "0", "10000.00")], "capital")
        sale = invoice("S-1", "05-01-2026", "Trial Customer", "sales", "USD", "1000.00", 11)
        invoice("P-1", "06-01-2026", "Trial Supplier", "purchase", "USD", "400.00", 11)
        receipt = db.add_payment({"kind": "customer_receipt", "payment_date": "10-01-2026", "party_id": customer["id"],
                                  "currency": "USD", "amount": "500.00", "cash_account": "531",
                                  "party_account": customer["account_number"]}, 1)
        db.save_allocations(receipt, [{"invoice_id": sale, "amount": "500.00"}], 1)
        db.add_payment({"kind": "supplier_payment", "payment_date": "12-01-2026", "party_id": supplier["id"],
                        "currency": "USD", "amount": "200.00", "cash_account": "531",
                        "party_account": supplier["account_number"]}, 1)
        voucher("T-002", "15-01-2026", "LBP", [("601100000", "8950000", "0"), ("531", "0", "8950000")], "LBP expense")
        invoice("CN-1", "20-01-2026", "Trial Customer", "sales", "USD", "100.00", 11, doc_subtype="credit_note",
                supplier_side="C - Credit", vat_side="D - Debit", expense_side="D - Debit")
        invoice("S-LBP-1", "25-02-2026", "Trial Customer", "sales", "LBP", "10000000", 11)

        # ---------------------------------------------------------------- independent expectations
        trial = db.trial_balance(to_date="31-12-2026")

        def balance(code, currency):
            return sum((D(str(r["debit"])) - D(str(r["credit"])) for r in trial
                        if r["code"] == code and r["currency"] == currency), D(0))

        totals = {}
        for r in trial:
            t = totals.setdefault(r["currency"], [D(0), D(0)])
            t[0] += D(str(r["debit"]))
            t[1] += D(str(r["credit"]))
        exp_usd_side = D("10000") + D("1110") + D("444") + D("500") + D("200") + D("111")  # capital, sale, purchase, receipt, payment, credit note
        for currency, (debit, credit) in sorted(totals.items()):
            chk(f"Trial balance: debit = credit in {currency}", debit == credit, f"debit={debit} credit={credit}")
        chk("Trial balance USD total equals the independent sum of the scenario",
            totals["USD"][0] == exp_usd_side, f"app={totals['USD'][0]} independent={exp_usd_side}")
        chk("Trial balance LBP total equals the independent sum", totals["LBP"][0] == D("20050000"), totals["LBP"][0])
        chk("Cash 531 USD = 10,000 + 500 - 200", balance("531", "USD") == D("10300"), balance("531", "USD"))
        chk("Output VAT 4427 USD = -(110 - 11 credit note) = -99", balance("4427", "USD") == D("-99"), balance("4427", "USD"))
        chk("Output VAT 4427 LBP = -1,100,000", balance("4427", "LBP") == D("-1100000"), balance("4427", "LBP"))
        chk("Input VAT 44210 USD = 44", balance("44210", "USD") == D("44"), balance("44210", "USD"))
        chk("Customer account USD = 1,110 - 500 - 111 = 499", balance(customer["account_number"], "USD") == D("499"),
            balance(customer["account_number"], "USD"))
        chk("Supplier account USD = -(444 - 200) = -244", balance(supplier["account_number"], "USD") == D("-244"),
            balance(supplier["account_number"], "USD"))

        # balance sheet by account type: output VAT must sit under liabilities
        with db.connect() as c:
            vat_type = c.execute("SELECT type FROM accounts WHERE code='4427'").fetchone()["type"]
        chk("Chart: 4427 (output VAT) is typed liability", vat_type == "liability", vat_type)
        sheet = db.balance_sheet(to_date="31-12-2026", currency="USD")
        assets = sum((D(str(r["balance"])) for r in sheet if r["type"] == "asset"), D(0))
        liabilities = -sum((D(str(r["balance"])) for r in sheet if r["type"] == "liability"), D(0))
        equity = -sum((D(str(r["balance"])) for r in sheet if r["type"] == "equity"), D(0))
        chk("Balance sheet USD: assets = liabilities + equity (equity includes the year result)",
            assets == liabilities + equity, f"A={assets} L={liabilities} E={equity}")
        chk("Balance sheet USD: liabilities = AP 244 + output VAT 99 = 343", liabilities == D("343"), liabilities)
        pnl = db.profit_and_loss(currency="USD")
        result = sum((D(str(r["amount"])) for r in pnl if r["type"] == "income"), D(0)) - \
            sum((D(str(r["amount"])) for r in pnl if r["type"] == "expense"), D(0))
        chk("P&L USD result = sales 1,000 - credit note 100 - purchase 400 = 500",
            result == D("500"), f"result={result}")
        chk("P&L amounts carry no float residue (at most 2 decimals)",
            all(D(str(r["amount"])).as_tuple().exponent >= -2 for r in pnl), [r["amount"] for r in pnl][:6])

        # VAT return Q1 against an independent computation (rounded UP to LBP 10,000 as in AI_RULES section 5)
        vat = vat_return.build_vat_return(db, 2026, 1)
        output_lbp = (D("1000") - D("100")) * D("0.11") * RATE + D("10000000") * D("0.11")
        input_lbp = D("44") * RATE
        net = output_lbp - input_lbp
        payable = (net / D(10000)).to_integral_value(rounding="ROUND_CEILING") * D(10000)
        chk("VAT Q1: net (LBP) equals the independent calculation", D(str(vat["totals_lbp"]["net"])) == net,
            f"app={vat['totals_lbp']['net']} independent={net}")
        chk("VAT Q1: payable rounded up to LBP 10,000", D(str(vat["payable_lbp"])) == payable,
            f"app={vat['payable_lbp']} independent={payable}")

        health = books_check.run(db)
        chk("Books health check: no errors", health["errors"] == 0, health["summary"])
        copy_path = db.backup("trial")
        chk("Backup is created and verified", bool(copy_path) and Path(copy_path).exists(), copy_path)
        copy = Database(Path(copy_path))
        key = lambda rows: sorted((r["code"], r["currency"], str(D(str(r["debit"]))), str(D(str(r["credit"])))) for r in rows)
        chk("Backup trial balance is identical to the live file", key(copy.trial_balance(to_date="31-12-2026")) == key(trial))
        copy.release()

        # ---------------------------------------------------------------- controls (live file)
        e = attempt(voucher, "T-BAD", "20-01-2026", "USD", [("531", "10.00", "0"), ("1013", "0", "9.99")])
        chk("Control: unbalanced voucher is refused", bool(e) and "unbalanced" in e.lower(), e, "control")
        e = attempt(voucher, "T-001", "20-01-2026", "USD", [("531", "1.00", "0"), ("1013", "0", "1.00")])
        chk("Control: duplicate voucher number is refused", bool(e) and "already exists" in e, e, "control")
        with db.connect() as c:
            jid = c.execute("SELECT id FROM journal_entries WHERE entry_number='T-001'").fetchone()["id"]
        try:
            with db.connect() as c:
                c.execute("UPDATE journal_lines SET debit='1' WHERE entry_id=?", (jid,))
            e = None
        except Exception as exc:
            e = str(exc)
        chk("Control: a posted journal voucher is immutable at database level", bool(e) and "IMMUTABLE" in e, e, "control")
        db.set_books_lock("2026-01-31", 1)
        e = attempt(voucher, "T-LOCK", "20-01-2026", "USD", [("531", "1.00", "0"), ("1013", "0", "1.00")])
        db.set_books_lock("", 1)
        chk("Control: books lock refuses an entry on/before the lock date", bool(e) and "LOCKED" in e.upper(), e, "control")
        reversal = attempt(db.reverse_journal_voucher, jid, "02-02-2026", 1)
        chk("Control: a posted voucher is corrected by a reversal entry", reversal is None, reversal, "control")
        audit = __import__("audit_chain").verify(db)
        chk("Control: the audit trail hash chain verifies", bool(audit.get("ok")), audit.get("message"), "control")

        # ---------------------------------------------------------------- controls that need a destructive probe: on a COPY
        probe_path = db.backup("probe")
        probe = Database(Path(probe_path))
        with probe.connect() as c:
            entry = c.execute("SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?", (sale,)).fetchone()["id"]
            lines = c.execute("SELECT id,debit,credit FROM journal_lines WHERE entry_id=? ORDER BY id", (entry,)).fetchall()
        # a BALANCED tamper (one debit and one credit line raised by the same amount): the balance guard cannot see it
        debit_line = next(l for l in lines if D(l["debit"]) > 0)
        credit_line = next(l for l in lines if D(l["credit"]) > 0)
        try:
            with probe.connect() as c:
                c.execute("UPDATE journal_lines SET debit=? WHERE id=?", (str(D(debit_line["debit"]) + 1), debit_line["id"]))
                c.execute("UPDATE journal_lines SET credit=? WHERE id=?", (str(D(credit_line["credit"]) + 1), credit_line["id"]))
            tampered = True
        except Exception:
            tampered = False
        chk("Control: a posted INVOICE entry resists a balanced raw-SQL change (owner decision D4 open)", not tampered,
            "balanced raw SQL change succeeded" if tampered else "refused", "gap" if tampered else "control")
        e = attempt(invoice, "S-1", "07-01-2026", "Trial Customer", "sales", "USD", "1", 0, _db=probe)
        chk("Control: a second sales invoice with an existing number is refused (2.9.134 D3)", bool(e),
            "second S-1 accepted" if not e else e, "control")
        e = attempt(probe.delete_invoice, sale, 1)
        with probe.connect() as c:
            left = c.execute("SELECT COUNT(*) n FROM invoices WHERE id=?", (sale,)).fetchone()["n"]
            audited = c.execute("SELECT details FROM audit_log WHERE action='delete' AND entity='invoice' ORDER BY id DESC LIMIT 1").fetchone()
        chk("Control: a POSTED invoice cannot be hard-deleted (cancel / credit note only) (owner decision open)", left == 1,
            "hard delete accepted" if left == 0 else e, "gap" if left == 0 else "control")
        if left == 0:
            chk("Control: the hard delete is at least fully recorded in the audit trail (2.9.133)",
                bool(audited) and "journal_lines_removed" in audited["details"], "audit_log details", "control")
        probe.release()
        for stray in (probe_path,):
            Path(stray).unlink(missing_ok=True)

        # ---------------------------------------------------------------- year-end close (live file, last)
        closing = db.close_fiscal_year(2026, 1)
        after = db.trial_balance(to_date="31-12-2026")
        for currency in ("USD", "LBP"):
            d = sum((D(str(r["debit"])) for r in after if r["currency"] == currency), D(0))
            k = sum((D(str(r["credit"])) for r in after if r["currency"] == currency), D(0))
            chk(f"Year close: trial balance still balances in {currency}", d == k, f"{d} vs {k}")
        leftovers = [(r["code"], r["currency"]) for r in after
                     if r["code"][:1] in "67" and D(str(r["debit"])) - D(str(r["credit"])) != 0]
        chk("Year close: classes 6 and 7 net to zero", not leftovers, leftovers[:3])
        chk("Year close: net results equal the independent P&L (USD 500, LBP 1,050,000)",
            D(str(closing["net_results"].get("USD"))) == D("500") and D(str(closing["net_results"].get("LBP"))) == D("1050000"),
            closing["net_results"])
        e = attempt(voucher, "T-AFTER", "20-12-2026", "USD", [("531", "1.00", "0"), ("1013", "0", "1.00")])
        chk("Control: a closed fiscal year refuses new entries", bool(e), e, "control")
    finally:
        db.release()
        if own_tmp:
            shutil.rmtree(workdir, ignore_errors=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print the results as JSON")
    args = parser.parse_args(argv)
    results = run()
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        width = max(len(r["name"]) for r in results)
        for r in results:
            label = "PASS" if r["ok"] else ("GAP " if r["kind"] == "gap" else "FAIL")
            print(f"{label} {r['name'].ljust(width)} | {r['detail']}")
        core_bad = [r for r in results if not r["ok"] and r["kind"] in ("core", "control")]
        gaps = [r for r in results if r["kind"] == "gap"]
        print(f"\n{len(results)} checks: {sum(r['ok'] for r in results)} pass, {len(core_bad)} FAIL, {len(gaps)} known GAP (owner decision pending)")
    return 1 if any(not r["ok"] and r["kind"] in ("core", "control") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
