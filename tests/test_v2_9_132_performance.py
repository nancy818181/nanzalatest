"""2.9.132 performance changes keep every figure: the trial balance and the general ledger are compared, field by field and
as exact Decimals, with the row-by-row calculation they replaced (synthetic data, two currencies, an opening period,
DD-MM-YYYY dates, a draft voucher that must stay out)."""
import tests_setup  # noqa: F401
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from database import Database


def reference_trial_balance(db, from_date, to_date):
    """The 2.9.131 loop: strptime and _converted_amount for every row."""
    from_date = datetime.strptime(from_date, "%d-%m-%Y").strftime("%Y-%m-%d"); to_date = datetime.strptime(to_date, "%d-%m-%Y").strftime("%Y-%m-%d")
    normalized = "CASE WHEN e.entry_date GLOB '??-??-????' THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2) ELSE e.entry_date END"
    with db.connect() as connection:
        raw = [dict(r) for r in connection.execute(f"""SELECT a.code,a.name_en,e.currency,e.entry_date,DSUM_EXACT(j.debit) debit,DSUM_EXACT(j.credit) credit
            FROM journal_lines j JOIN accounts a ON a.id=j.account_id JOIN journal_entries e ON e.id=j.entry_id
            LEFT JOIN invoices i ON e.source_type='invoice' AND i.id=e.source_id
            WHERE {normalized}<=? AND (e.posting_status='posted' AND (e.source_type!='invoice' OR i.status IN ('posted','cancelled')))
            GROUP BY a.code,a.name_en,e.currency,e.entry_date ORDER BY e.currency,a.code""", (to_date,))]
    totals = {}
    for row in raw:
        key = (row["code"], row["currency"])
        item = totals.setdefault(key, {f: Decimal("0") for f in ("opening", "debit", "credit", "usd_opening", "usd_debit", "usd_credit", "lbp_opening", "lbp_debit", "lbp_credit")})
        date = str(row["entry_date"])
        try: date = datetime.strptime(date, "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError: pass
        debit = Decimal(str(row["debit"] or 0)); credit = Decimal(str(row["credit"] or 0))
        conv = lambda v, t: db._converted_amount(v, row["currency"], t, date)
        if date < from_date:
            item["opening"] += debit - credit; item["usd_opening"] += conv(debit, "USD") - conv(credit, "USD"); item["lbp_opening"] += conv(debit, "LBP") - conv(credit, "LBP")
            continue
        for f, v in (("debit", debit), ("credit", credit), ("usd_debit", conv(debit, "USD")), ("usd_credit", conv(credit, "USD")),
                     ("lbp_debit", conv(debit, "LBP")), ("lbp_credit", conv(credit, "LBP"))): item[f] += v
    return totals


class PerformanceKeepsFiguresTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.db = Database(Path(self.folder.name) / "perf.db"); self.db.initialize("secret12345"); self.addCleanup(self.db.release)
        u = self.db.user_for_token(self.db.login("admin", "secret12345")["token"])["id"]
        self.db.save_exchange_rate({"date_from": "01-01-2026", "date_to": "30-06-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, u)
        self.db.save_exchange_rate({"date_from": "01-07-2026", "date_to": "31-12-2026", "from_currency": "USD", "to_currency": "LBP", "rate": "89750"}, u)
        for i, (day, cur, amount) in enumerate((("05-01-2026", "USD", "100.10"), ("05-01-2026", "LBP", "8950000"), ("17-03-2026", "USD", "0.07"),
                                                 ("01-07-2026", "LBP", "1234567.89"), ("15-08-2026", "USD", "999.99"), ("31-12-2026", "USD", "12.34"))):
            self.db.import_invoice({"invoice_number": f"S-{i}", "kind": "sale", "invoice_date": day, "party_name": f"C{i % 2}", "currency": cur,
                                    "subtotal": amount, "vat": str((Decimal(amount) * Decimal("0.11")).quantize(Decimal("0.01"))),
                                    "total": str(Decimal(amount) + (Decimal(amount) * Decimal("0.11")).quantize(Decimal("0.01"))), "status": "posted"}, u)
        self.db.save_journal_voucher({"entry_date": "10-09-2026", "description": "x", "currency": "LBP"},
                                     [{"account_code": "6262", "debit": "500000"}, {"account_code": "531", "credit": "500000"}], u)
        self.db.save_journal_voucher({"entry_date": "11-09-2026", "description": "draft", "currency": "USD"},
                                     [{"account_code": "6262", "debit": "77"}, {"account_code": "531", "credit": "77"}], u, defer_posting=True)

    def test_trial_balance_matches_the_row_by_row_calculation(self):
        expected = reference_trial_balance(self.db, "01-04-2026", "31-12-2026")
        rows = self.db.trial_balance("01-04-2026", "31-12-2026")
        self.assertEqual(len(rows), len(expected))
        for row in rows:
            want = expected[(row["code"], row["currency"])]
            for field, value in want.items():
                self.assertEqual(Decimal(str(row[field])), Decimal(str(value)), (row["code"], row["currency"], field))
        self.assertTrue(any(row["usd_opening"] for row in rows))         # the opening period is exercised

    def test_general_ledger_balances_match_the_journal(self):
        ledger = self.db.general_ledger(None, "01-04-2026", "31-12-2026")
        journal = [r for r in self.db.journal(None, "31-12-2026", posted_only=True)]
        running = {}
        for row in journal:
            key = (row["currency"], row["account_code"])
            running[key] = running.get(key, Decimal("0")) + Decimal(str(row["debit"] or 0)) - Decimal(str(row["credit"] or 0))
            row["expected"] = float(running[key])
        expected = [r for r in journal if datetime.strptime(r["entry_date"], "%d-%m-%Y").strftime("%Y-%m-%d") >= "2026-04-01"]
        self.assertEqual([(r["entry_number"], r["account_code"], r["balance"]) for r in ledger["items"]],
                         [(r["entry_number"], r["account_code"], r["expected"]) for r in expected])
        self.assertNotIn("draft", {r["description"] for r in ledger["items"]})
        self.assertTrue(all("line_id" not in r for r in ledger["items"]))

    def test_a_missing_rate_still_stops_the_report(self):
        with self.db.connect() as connection:
            connection.execute("UPDATE journal_entries SET currency='EUR' WHERE source_type='invoice' AND source_id=(SELECT MIN(id) FROM invoices)")
        with self.assertRaises(ValueError): self.db.trial_balance("01-04-2026", "31-12-2026")


if __name__ == "__main__":
    unittest.main()
