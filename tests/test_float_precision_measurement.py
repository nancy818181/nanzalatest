"""Measure float error after fractional postings reach a report. 2.9.133: the P&L now subtracts exact Decimals (MONEY-FLOAT-001)."""

from decimal import Decimal


def test_measurement_pnl_float_subtraction_for_fractional_amounts(synthetic_db):
    """2.9.133: 40 one-cent entries leave NO float residue in the P&L (was 0.19999999999999998)."""
    with synthetic_db.connect() as connection:
        cash_code = connection.execute("SELECT code FROM accounts WHERE code='531'").fetchone()["code"]
        income_code = connection.execute(
            "SELECT code FROM accounts WHERE type='income' ORDER BY code LIMIT 1"
        ).fetchone()["code"]

    def save(number, *, debit_income):
        income = {"account_code": income_code, "debit": "0.01" if debit_income else "0",
                  "credit": "0" if debit_income else "0.01"}
        cash = {"account_code": cash_code, "debit": "0" if debit_income else "0.01",
                "credit": "0.01" if debit_income else "0"}
        synthetic_db.save_journal_voucher(
            {"entry_number": number, "entry_date": "10-01-2026",
             "description": "Synthetic float measurement", "currency": "USD"},
            [income, cash], 1,
        )

    for index in range(30):
        save(f"SYN-FLOAT-CR-{index:03d}", debit_income=False)
    for index in range(10):
        save(f"SYN-FLOAT-DR-{index:03d}", debit_income=True)

    row = next(
        item for item in synthetic_db.profit_and_loss(currency="USD")
        if item["code"] == income_code
    )
    expected = Decimal("0.20")  # 30 credits x 0.01 less 10 debits x 0.01
    actual = Decimal(str(row["amount"]))
    difference = actual - expected
    print(f"float measurement: expected={expected}; actual={actual}; difference={difference}")

    assert actual == expected
    assert difference == Decimal("0")
