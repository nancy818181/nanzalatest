"""Headless characterization and invariant tests for posting and reports.

Expected report figures below are snapshots of current behavior. They are not
independently certified accounting results; that work belongs to Phase 2.
"""

import sqlite3
from decimal import Decimal

from tests.pytest_compat import pytest

from database import utcnow


SYNTHETIC_DATE = "10-01-2026"


def _account_codes(db):
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT type,code FROM accounts WHERE code='531' OR type IN ('equity','income','expense') ORDER BY code"
        ).fetchall()
    by_type = {row["type"]: row["code"] for row in rows if row["type"] != "asset"}
    cash = next(row["code"] for row in rows if row["code"] == "531")
    assert {"equity", "income", "expense"} <= by_type.keys()
    return cash, by_type["equity"], by_type["income"], by_type["expense"]


def _voucher(db, number, debit_code, credit_code, amount, *, credit_amount=None,
             day=SYNTHETIC_DATE, defer_posting=False):
    credit_amount = amount if credit_amount is None else credit_amount
    return db.save_journal_voucher(
        {"entry_number": number, "entry_date": day,
         "description": f"Synthetic {number}", "currency": "USD"},
        [{"account_code": debit_code, "debit": str(amount)},
         {"account_code": credit_code, "credit": str(credit_amount)}],
        1,
        defer_posting=defer_posting,
    )["voucher"]


def _posted_synthetic_invoice(db, invoice_number="SYN-INV-1"):
    return db.create_manual_invoice(
        {"invoice_number": invoice_number, "invoice_date": SYNTHETIC_DATE,
         "party_name": "Synthetic Test Customer", "kind": "sales",
         "currency": "USD", "status": "posted"},
        [{"description": "Synthetic service", "quantity": "1",
          "unit_price": "10.00", "vat_rate": "0"}],
        1,
    )


def test_current_behavior_snapshot_three_posted_vouchers(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: three synthetic posted entries."""
    cash, equity, income, expense = _account_codes(synthetic_db)
    _voucher(synthetic_db, "SYN-OPEN-1", cash, equity, Decimal("100.00"))
    _voucher(synthetic_db, "SYN-SALE-1", cash, income, Decimal("23.50"))
    _voucher(synthetic_db, "SYN-EXP-1", expense, cash, Decimal("5.25"))

    trial_balance = synthetic_db.trial_balance()
    trial_balance = [row for row in trial_balance if row["currency"] == "USD"]
    debit = sum((Decimal(str(row["debit"])) for row in trial_balance), Decimal("0"))
    credit = sum((Decimal(str(row["credit"])) for row in trial_balance), Decimal("0"))
    assert debit == Decimal("128.75")
    assert credit == Decimal("128.75")

    pnl = synthetic_db.profit_and_loss(currency="USD")
    income_total = sum((Decimal(str(row["amount"])) for row in pnl if row["type"] == "income"), Decimal("0"))
    expense_total = sum((Decimal(str(row["amount"])) for row in pnl if row["type"] == "expense"), Decimal("0"))
    assert (income_total, expense_total) == (Decimal("23.5"), Decimal("5.25"))

    balance_sheet = synthetic_db.balance_sheet(currency="USD")
    cash_balance = sum((Decimal(str(row["balance"])) for row in balance_sheet if row["code"] == cash), Decimal("0"))
    assert cash_balance == Decimal("118.25")

    cash_flow = synthetic_db.cash_flow(currency="USD")
    cash_net = sum((Decimal(str(row["net"])) for row in cash_flow), Decimal("0"))
    assert cash_net == Decimal("118.25")


def test_posting_guard_uses_decimal_for_entry_totals(synthetic_db):
    """Current posting rejects differences at/above its threshold; exact equality is separate."""
    cash, _equity, _income, expense = _account_codes(synthetic_db)
    _voucher(synthetic_db, "SYN-BALANCED-1", cash, expense, Decimal("0.10"))
    with synthetic_db.connect() as connection:
        row = connection.execute(
            "SELECT SUM(CAST(debit AS TEXT)) debit,SUM(CAST(credit AS TEXT)) credit "
            "FROM journal_lines WHERE entry_id=(SELECT id FROM journal_entries WHERE entry_number=?)",
            ("SYN-BALANCED-1",),
        ).fetchone()
    assert Decimal(str(row["debit"])) == Decimal(str(row["credit"])) == Decimal("0.1")


def test_posted_manual_voucher_is_immutable_at_storage_layer(synthetic_db):
    cash, equity, _income, _expense = _account_codes(synthetic_db)
    entry = _voucher(synthetic_db, "SYN-IMMUTABLE-JV-1", cash, equity, Decimal("10.00"))
    with synthetic_db.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="(?i)immutable"):
            connection.execute(
                "UPDATE journal_entries SET description='tampered' WHERE id=?", (entry["id"],)
            )
        with pytest.raises(sqlite3.IntegrityError, match="(?i)immutable"):
            connection.execute("DELETE FROM journal_entries WHERE id=?", (entry["id"],))


@pytest.mark.xfail(
    strict=True,
    reason="POST-DECIMAL-001: journal posting accepts a nonzero 0.004 Decimal imbalance under its tolerance.",
)
def test_posted_entry_must_balance_exactly_as_decimal(synthetic_db):
    cash, _equity, _income, expense = _account_codes(synthetic_db)
    _voucher(synthetic_db, "SYN-ROUNDING-1", cash, expense, Decimal("1.004"),
             credit_amount=Decimal("1.000"))
    with synthetic_db.connect() as connection:
        row = connection.execute(
            "SELECT debit,credit FROM journal_lines WHERE entry_id=(SELECT id FROM journal_entries WHERE entry_number=?)",
            ("SYN-ROUNDING-1",),
        ).fetchall()
    debit = sum((Decimal(value["debit"]) for value in row), Decimal("0"))
    credit = sum((Decimal(value["credit"]) for value in row), Decimal("0"))
    assert debit == credit


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.xfail(
    strict=True,
    reason="POST-IMMUTABILITY-001: SQLite triggers only freeze posted manual journal vouchers, not invoice-source entries.",
)
def test_posted_invoice_journal_entry_is_immutable_at_storage_layer(synthetic_db, operation):
    invoice_id = _posted_synthetic_invoice(synthetic_db)
    with synthetic_db.connect() as connection:
        entry_id = connection.execute(
            "SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?", (invoice_id,)
        ).fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError, match="(?i)immutable"):
            if operation == "update":
                connection.execute("UPDATE journal_entries SET description='tampered' WHERE id=?", (entry_id,))
            else:
                connection.execute("DELETE FROM journal_entries WHERE id=?", (entry_id,))


@pytest.mark.xfail(
    strict=True,
    reason="POST-DUPLICATE-001: repeated supplier/customer invoice identity is retained by import_invoice without a hard idempotency guard.",
)
def test_same_posted_invoice_identity_cannot_be_posted_twice(synthetic_db):
    _posted_synthetic_invoice(synthetic_db, "SYN-DUPLICATE-1")
    with pytest.raises(ValueError, match="(?i)duplicate"):
        _posted_synthetic_invoice(synthetic_db, "SYN-DUPLICATE-1")


def test_duplicate_journal_voucher_number_is_rejected(synthetic_db):
    cash, equity, _income, _expense = _account_codes(synthetic_db)
    _voucher(synthetic_db, "SYN-DUP-JV-1", cash, equity, Decimal("1.00"))
    with pytest.raises(ValueError, match="(?i)already exists"):
        _voucher(synthetic_db, "SYN-DUP-JV-1", cash, equity, Decimal("1.00"))


def test_closed_period_rejects_journal_voucher(synthetic_db):
    with synthetic_db.connect() as connection:
        connection.execute(
            "INSERT INTO fiscal_years(year,status,opened_at) VALUES(2025,'closed',?)", (utcnow(),)
        )
    cash, equity, _income, _expense = _account_codes(synthetic_db)
    with pytest.raises(ValueError, match="(?i)closed"):
        _voucher(synthetic_db, "SYN-CLOSED-1", cash, equity, Decimal("1.00"), day="10-01-2025")


def _draft_voucher(synthetic_db):
    cash, _equity, income, _expense = _account_codes(synthetic_db)
    return _voucher(
        synthetic_db, "SYN-DRAFT-1", cash, income, Decimal("12.34"), defer_posting=True
    )


def test_trial_balance_default_excludes_draft_voucher(synthetic_db):
    cash = _draft_voucher(synthetic_db)
    del cash
    assert all(row["code"] != "531" for row in synthetic_db.trial_balance())


@pytest.mark.parametrize("report", ["pnl", "balance_sheet", "cash_flow", "general_ledger", "financial_statements"])
@pytest.mark.xfail(
    strict=True,
    reason="RPT-UNPOSTED-001: current report query paths include draft journal vouchers.",
)
def test_financial_reports_exclude_draft_voucher(synthetic_db, report):
    _draft_voucher(synthetic_db)
    if report == "pnl":
        included = any(Decimal(str(row["amount"])) != 0 for row in synthetic_db.profit_and_loss())
    elif report == "balance_sheet":
        included = any(Decimal(str(row["balance"])) != 0 for row in synthetic_db.balance_sheet() if row["code"] == "531")
    elif report == "cash_flow":
        included = any(Decimal(str(row["net"])) != 0 for row in synthetic_db.cash_flow())
    elif report == "general_ledger":
        included = any(row["entry_number"] == "SYN-DRAFT-1" for row in synthetic_db.general_ledger()["items"])
    else:
        import financial_statements
        result = financial_statements.load_period(synthetic_db, "2026-01-01", "2026-12-31", "USD")
        included = result["count"] != 0
    assert not included
