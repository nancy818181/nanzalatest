"""Synthetic posted-ledger input. Amounts and FX rates are test data, not legal policy."""

from decimal import Decimal


# Arbitrary fixture rates effective 01-01-2026; never use these as real exchange rates.
FIXTURE_RATES = {
    ("EUR", "USD"): Decimal("1.07"),
    ("USD", "LBP"): Decimal("89500"),
    ("EUR", "LBP"): Decimal("95765"),
}
RATE_DATE = "01-01-2026"
PERIOD_START = "2026-01-01"
PERIOD_END = "2026-02-28"

# Each tuple is (entry number, date, currency, scenario, lines, reversal_of).
# Each line is (symbolic account, debit, credit); all values are literal decimals.
ENTRIES = [
    ("GL-001", "01-01-2026", "USD", "opening cash", [("cash", "1000.00", "0"), ("equity", "0", "1000.00")], None),
    ("GL-002", "01-01-2026", "USD", "opening receivable", [("ar", "200.00", "0"), ("equity", "0", "200.00")], None),
    ("GL-003", "05-01-2026", "USD", "sale with output VAT", [("ar", "111.00", "0"), ("income", "0", "100.00"), ("vat_output", "0", "11.00")], None),
    ("GL-004", "08-01-2026", "USD", "partial customer receipt", [("cash", "40.00", "0"), ("ar", "0", "40.00")], None),
    ("GL-005", "10-01-2026", "USD", "purchase with input VAT", [("expense", "50.00", "0"), ("vat_input", "5.50", "0"), ("ap", "0", "55.50")], None),
    ("GL-006", "12-01-2026", "USD", "partial vendor payment", [("ap", "20.00", "0"), ("cash", "0", "20.00")], None),
    ("GL-007", "14-01-2026", "USD", "sales credit note", [("income", "10.00", "0"), ("vat_output", "1.10", "0"), ("ar", "0", "11.10")], None),
    ("GL-008", "16-01-2026", "USD", "cash sale with output VAT", [("cash", "22.20", "0"), ("income", "0", "20.00"), ("vat_output", "0", "2.20")], None),
    ("GL-009", "18-01-2026", "USD", "purchase credit note", [("ap", "5.55", "0"), ("expense", "0", "5.00"), ("vat_input", "0", "0.55")], None),
    ("GL-010", "20-01-2026", "USD", "fractional expense rounding", [("expense", "0.33", "0"), ("cash", "0", "0.33")], None),
    ("GL-011", "22-01-2026", "USD", "fractional cash sale", [("cash", "0.10", "0"), ("income", "0", "0.10")], None),
    ("GL-012", "25-01-2026", "USD", "expense later reversed", [("expense", "2.34", "0"), ("cash", "0", "2.34")], None),
    ("GL-013", "12-02-2026", "USD", "reversal of GL-012", [("cash", "2.34", "0"), ("expense", "0", "2.34")], "GL-012"),
    ("GL-014", "27-01-2026", "USD", "second partial customer receipt", [("cash", "20.00", "0"), ("ar", "0", "20.00")], None),
    ("GL-015", "28-01-2026", "USD", "accrued expense", [("expense", "7.77", "0"), ("ap", "0", "7.77")], None),
    ("GL-016", "29-01-2026", "USD", "settlement of accrued expense", [("ap", "7.77", "0"), ("cash", "0", "7.77")], None),
    ("GL-017", "30-01-2026", "USD", "fractional cash purchase", [("expense", "0.07", "0"), ("cash", "0", "0.07")], None),
    ("GL-018", "31-01-2026", "USD", "cash sale without VAT", [("cash", "0.11", "0"), ("income", "0", "0.11")], None),
    ("GL-019", "31-01-2026", "USD", "credit note without VAT", [("income", "0.02", "0"), ("ar", "0", "0.02")], None),
    ("GL-020", "01-01-2026", "LBP", "opening cash in LBP", [("cash", "8950000", "0"), ("equity", "0", "8950000")], None),
    ("GL-021", "31-01-2026", "LBP", "LBP purchase", [("expense", "89500", "0"), ("cash", "0", "89500")], None),
    ("GL-022", "02-02-2026", "USD", "February cash sale", [("cash", "0.30", "0"), ("income", "0", "0.30")], None),
    ("GL-023", "03-02-2026", "USD", "February fractional expense", [("expense", "0.10", "0"), ("cash", "0", "0.10")], None),
    ("GL-024", "05-02-2026", "EUR", "EUR sale at fixture rate", [("ar", "3.33", "0"), ("income", "0", "3.33")], None),
    ("GL-025", "10-02-2026", "EUR", "partial EUR receipt", [("cash", "1.11", "0"), ("ar", "0", "1.11")], None),
    ("GL-026", "15-02-2026", "EUR", "fractional EUR purchase", [("expense", "0.01", "0"), ("ap", "0", "0.01")], None),
    ("GL-027", "20-02-2026", "USD", "small February sale", [("cash", "0.04", "0"), ("income", "0", "0.04")], None),
    ("GL-028", "21-02-2026", "USD", "small February purchase", [("expense", "0.02", "0"), ("cash", "0", "0.02")], None),
    ("GL-029", "25-02-2026", "USD", "small February credit note", [("income", "0.05", "0"), ("ar", "0", "0.05")], None),
    ("GL-030", "28-02-2026", "USD", "rounding remainder transaction", [("expense", "0.03", "0"), ("cash", "0", "0.03")], None),
]

# Attempts are explicitly not included in posted expected totals.
REJECTED_ATTEMPTS = {
    "duplicate_entry_number": "GL-003",
    "closed_period_date": "31-12-2025",
}

# NEEDS ACCOUNTANT SIGN-OFF: VAT amount/rate, eligibility, and treatment are fixture arithmetic only.
# The explicit VAT lines below are not a statement about Lebanese law or filing treatment.
