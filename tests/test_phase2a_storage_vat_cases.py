"""Synthetic-only Phase 2a probes for document locks and VAT save behavior."""

import json
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from tests.pytest_compat import pytest

# The unittest-only CI imports this pytest module without executing its tests.
# Keep parametrization declarations importable when pytest is absent.
if not hasattr(pytest, "param"):
    pytest.param = lambda *values, **_kwargs: values[0] if len(values) == 1 else values


_CUTOFFS = {
    "closed_month": ("2026-01-31", "2026-01-15"),
    "closed_quarter": ("2026-03-31", "2026-02-15"),
    "closed_year": ("2026-12-31", "2026-06-15"),
    "saved_vat_quarter": (None, "2026-02-15"),
}


def _close_period(db, period):
    cutoff, _date = _CUTOFFS[period]
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO app_settings(key,value) VALUES('books_locked_until',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (cutoff,),
        )
        if period == "closed_year":
            connection.execute("INSERT INTO fiscal_years(year,status,opened_at) VALUES(2026,'closed','synthetic')")


def _new_invoice(db, kind, date):
    return db.import_invoice({
        "invoice_number": f"SYN-SVC-{kind}-{date}", "invoice_date": date,
        "party_name": "Synthetic only", "kind": kind, "currency": "USD",
        "subtotal": "10.00", "vat": "0", "total": "10.00", "status": "posted",
    }, 1)


def _new_payment(db, kind, date):
    party = db.save_party({"name": f"Synthetic {kind}", "kind": "customer" if kind == "customer_receipt" else "supplier"}, 1)
    return db.add_payment({"kind": kind, "party_id": party["id"], "payment_date": date,
                           "currency": "USD", "amount": "10.00"}, 1)


def _new_expense(db, date):
    return db.add_expense({"expense_date": date, "description": "Synthetic only", "currency": "USD",
                           "subtotal": "10.00", "vat": "0", "total": "10.00"}, 1)


def _make_doc(db, table, date):
    if table == "invoices":
        return db.import_invoice({
            "invoice_number": f"SYN-RAW-{table}-{date}", "invoice_date": date,
            "party_name": "Synthetic only", "kind": "purchase", "currency": "USD",
            "subtotal": "10.00", "vat": "0", "total": "10.00", "status": "posted",
        }, 1)
    if table == "expenses":
        return db.add_expense({
            "expense_date": date, "description": "Synthetic only", "currency": "USD",
            "subtotal": "10.00", "vat": "0", "total": "10.00",
        }, 1)
    party = db.save_party({"name": "Synthetic only", "kind": "supplier", "currency": "USD"}, 1)
    return db.add_payment({
        "kind": "supplier_payment", "party_id": party["id"], "payment_date": date,
        "currency": "USD", "amount": "10.00",
    }, 1)


def _set_lock(db, lock_date, period):
    with db.connect() as connection:
        if lock_date:
            connection.execute(
                "INSERT INTO app_settings(key,value) VALUES('books_locked_until',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (lock_date,),
            )
        if period == "closed_year":
            connection.execute(
                "INSERT INTO fiscal_years(year,status,opened_at) VALUES(2026,'closed','synthetic')"
            )
    if period == "saved_vat_quarter":
        from vat_return import save_return
        save_return(db, 2026, 1, 1)


@pytest.mark.parametrize("table", [
    pytest.param("invoices", marks=pytest.mark.xfail(strict=True, reason="DOC-LOCK-INVOICE-001: invoice rows are directly mutable by raw SQL in locked periods.")),
    pytest.param("payments", marks=pytest.mark.xfail(strict=True, reason="DOC-LOCK-PAYMENT-001: payment rows are directly mutable by raw SQL in locked periods.")),
    pytest.param("expenses", marks=pytest.mark.xfail(strict=True, reason="DOC-LOCK-EXPENSE-001: expense rows are directly mutable by raw SQL in locked periods.")),
])
@pytest.mark.parametrize("period", list(_CUTOFFS))
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_document_table_raw_sql_lock_gaps_are_visible(synthetic_db, table, period, operation):
    """Raw SQL should be blocked; currently the direct document-table write succeeds."""
    lock_date, document_date = _CUTOFFS[period]
    doc_id = _make_doc(synthetic_db, table, document_date)
    _set_lock(synthetic_db, lock_date, period)
    date_column = {"invoices": "invoice_date", "payments": "payment_date", "expenses": "expense_date"}[table]
    with pytest.raises(sqlite3.IntegrityError):
        with synthetic_db.connect() as connection:
            if operation == "update":
                connection.execute(f"UPDATE {table} SET {date_column}=? WHERE id=?", (document_date, doc_id))
            else:
                connection.execute(f"DELETE FROM {table} WHERE id=?", (doc_id,))


@pytest.mark.parametrize("kind", ["sale", "purchase"])
@pytest.mark.parametrize("period", list(_CUTOFFS)[:3])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_invoice_service_closed_period_matrix(synthetic_db, kind, period, operation):
    _cutoff, date = _CUTOFFS[period]
    invoice_id = _new_invoice(synthetic_db, kind, date)
    _close_period(synthetic_db, period)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match="(?i)(period locked|fiscal year .* closed)"):
        if operation == "edit":
            synthetic_db.update_invoice(invoice_id, synthetic_db.get_invoice(invoice_id), 1)
        else:
            synthetic_db.cancel_invoice(invoice_id, "Synthetic closed-period probe", 1)


@pytest.mark.parametrize("kind", ["customer_receipt", "supplier_payment"])
@pytest.mark.parametrize("period", list(_CUTOFFS)[:3])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_payment_service_closed_period_matrix(synthetic_db, kind, period, operation):
    _cutoff, date = _CUTOFFS[period]
    payment_id = _new_payment(synthetic_db, kind, date)
    _close_period(synthetic_db, period)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match="(?i)(period locked|fiscal year .* closed)"):
        if operation == "edit":
            synthetic_db.update_payment(payment_id, {"payment_date": date, "currency": "USD", "amount": "10.00"}, 1)
        else:
            synthetic_db.delete_payment(payment_id, 1)


@pytest.mark.parametrize("period", list(_CUTOFFS)[:3])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_expense_service_closed_period_matrix(synthetic_db, period, operation):
    _cutoff, date = _CUTOFFS[period]
    expense_id = _new_expense(synthetic_db, date)
    _close_period(synthetic_db, period)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match="(?i)(period locked|fiscal year .* closed)"):
        if operation == "edit":
            synthetic_db.update_expense(expense_id, {"expense_date": date, "description": "Synthetic edit",
                "currency": "USD", "subtotal": "10.00", "vat": "0", "total": "10.00"}, 1)
        else:
            synthetic_db.delete_expense(expense_id, 1)


@pytest.mark.parametrize("period", list(_CUTOFFS)[:3])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_journal_voucher_service_closed_period_matrix(synthetic_db, period, operation):
    _cutoff, date = _CUTOFFS[period]
    voucher = synthetic_db.save_journal_voucher(
        {"entry_number": f"SYN-SVC-JV-{period}", "entry_date": date, "description": "Synthetic JV", "currency": "USD"},
        [{"account_code": "531", "debit": "10.00"}, {"account_code": "1013", "credit": "10.00"}],
        1, defer_posting=True,
    )["voucher"]
    _close_period(synthetic_db, period)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match="(?i)(period locked|fiscal year .* closed)"):
        if operation == "edit":
            synthetic_db.save_journal_voucher(
                {"entry_number": voucher["entry_number"], "entry_date": date,
                 "description": "Synthetic JV edited", "currency": "USD"},
                [{"account_code": "531", "debit": "10.00"}, {"account_code": "1013", "credit": "10.00"}],
                1, entry_id=voucher["id"], defer_posting=True,
            )
        else:
            synthetic_db.delete_journal_voucher(voucher["id"], 1)


@pytest.mark.parametrize("period", list(_CUTOFFS)[:3])
def test_invoice_import_service_closed_period_matrix(synthetic_db, period):
    _cutoff, date = _CUTOFFS[period]
    _close_period(synthetic_db, period)
    with pytest.raises((ValueError, sqlite3.IntegrityError), match="(?i)(period locked|fiscal year .* closed)"):
        _new_invoice(synthetic_db, "purchase", date)


@pytest.mark.xfail(strict=True, reason=(
    "RPT-BS-001: 4427 is output VAT (liability, owner-confirmed) but the seed stores asset; invoice module creates liability"
))
def test_balance_sheet_vat_control_accounts_remain_separate_in_refund_position(synthetic_db):
    cash, input_vat, output_vat = "531", "44210", "4427"
    for number, debit, credit in (
        ("SYN-INPUT-VAT", input_vat, cash),
        ("SYN-OUTPUT-VAT", cash, output_vat),
    ):
        amount = "100.00" if number == "SYN-INPUT-VAT" else "20.00"
        synthetic_db.save_journal_voucher(
            {"entry_number": number, "entry_date": "15-02-2026", "description": "Synthetic VAT control", "currency": "USD"},
            [{"account_code": debit, "debit": amount}, {"account_code": credit, "credit": amount}], 1,
        )
    rows = synthetic_db.balance_sheet(to_date="2026-03-31", currency="USD")
    vat_rows = {row["code"]: row for row in rows if row["code"] in (input_vat, output_vat)}
    assert set(vat_rows) == {input_vat, output_vat}
    assert Decimal(str(vat_rows[input_vat]["balance"])) > abs(Decimal(str(vat_rows[output_vat]["balance"])))
    assert vat_rows[input_vat]["type"] == "asset"
    assert vat_rows[output_vat]["type"] == "liability"


def test_4427_read_only_diagnostic_on_synthetic_database(synthetic_db):
    synthetic_db.release()
    script = Path(__file__).resolve().parents[1] / "tools" / "diagnose_4427.py"
    result = subprocess.run(
        [sys.executable, str(script), str(synthetic_db.path)],
        check=True, capture_output=True, text=True,
    )
    assert "4427 stored type: asset" in result.stdout
    assert "Accounts whose type differs from Lebanese seed:" in result.stdout
    count = int(result.stdout.rsplit(":", 1)[1].strip())
    assert count == 0
    assert "Synthetic only" not in result.stdout
    read_only = sqlite3.connect(Path(synthetic_db.path).as_uri() + "?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="(?i)readonly"):
            read_only.execute("UPDATE accounts SET type='liability' WHERE code='4427'")
    finally:
        read_only.close()


def test_vat_same_quarter_three_saves_update_one_row(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: repeat saves are supported upserts."""
    from vat_return import save_return

    ids = []
    for _ in range(3):
        save_return(synthetic_db, 2026, 1, 1, user_name="Synthetic reviewer")
        with synthetic_db.connect() as connection:
            ids.append(connection.execute(
                "SELECT id FROM vat_returns WHERE year=2026 AND quarter=1"
            ).fetchone()["id"])
    assert len(set(ids)) == 1
    with synthetic_db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM vat_returns WHERE year=2026 AND quarter=1"
        ).fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["sale", "purchase"])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_saved_vat_quarter_blocks_invoice_service_mutations(synthetic_db, kind, operation):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: first save creates the document quarter lock."""
    from vat_return import save_return

    invoice_id = synthetic_db.import_invoice({
        "invoice_number": f"SYN-FIRST-SAVE-{kind}-{operation}", "invoice_date": "15-02-2026",
        "party_name": "Synthetic only", "kind": kind, "currency": "USD",
        "subtotal": "10.00", "vat": "0", "total": "10.00", "status": "posted",
    }, 1)
    save_return(synthetic_db, 2026, 1, 1)
    with pytest.raises(ValueError, match="VAT return is saved"):
        if operation == "edit":
            synthetic_db.update_invoice(invoice_id, {}, 1)
        else:
            synthetic_db.cancel_invoice(invoice_id, "Synthetic test", 1)


@pytest.mark.parametrize("kind", ["customer_receipt", "supplier_payment"])
@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_saved_vat_quarter_payment_service_mutation_behavior(synthetic_db, kind, operation):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: payment service checks fiscal year, not VAT quarter."""
    from vat_return import save_return

    party = synthetic_db.save_party({"name": f"Synthetic {kind}", "kind": "customer" if kind == "customer_receipt" else "supplier"}, 1)
    payment_id = synthetic_db.add_payment({
        "kind": kind, "party_id": party["id"], "payment_date": "15-02-2026",
        "currency": "USD", "amount": "10.00",
    }, 1)
    save_return(synthetic_db, 2026, 1, 1)
    if operation == "edit":
        new_id = synthetic_db.update_payment(payment_id, {
            "party_id": party["id"], "payment_date": "16-02-2026", "currency": "USD", "amount": "10.00",
        }, 1)
        assert new_id
    else:
        assert synthetic_db.delete_payment(payment_id, 1)["deleted"] == payment_id


@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_saved_vat_quarter_blocks_expense_service_mutations(synthetic_db, operation):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: expense service checks the saved quarter."""
    from vat_return import save_return

    expense_id = synthetic_db.add_expense({
        "expense_date": "15-02-2026", "description": "Synthetic only", "currency": "USD",
        "subtotal": "10.00", "vat": "0", "total": "10.00",
    }, 1)
    save_return(synthetic_db, 2026, 1, 1)
    with pytest.raises(ValueError, match="VAT return is saved"):
        if operation == "edit":
            synthetic_db.update_expense(expense_id, {}, 1)
        else:
            synthetic_db.delete_expense(expense_id, 1)


def test_q4_annual_ratio_uses_saved_prior_quarter_ratio_after_reopen_and_resave(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: Q4 consumes the latest saved prior-quarter ratio."""
    from vat_return import build_vat_return, reopen_return, save_return

    synthetic_db.save_settings({"vat_ratio_method": "annual"}, 1)
    synthetic_db.import_invoice({
        "invoice_number": "SYN-Q1-MIXED-PURCHASE", "invoice_date": "15-02-2026",
        "party_name": "Synthetic supplier", "kind": "purchase", "currency": "USD",
        "subtotal": "100.00", "vat": "11.00", "total": "111.00", "status": "posted",
        "vat_use": "mixed",
    }, 1)
    save_return(synthetic_db, 2026, 1, 1)
    with synthetic_db.connect() as connection:
        connection.execute("UPDATE vat_returns SET deduction_ratio='0.25' WHERE year=2026 AND quarter=1")
    before_reopen = build_vat_return(synthetic_db, 2026, 4)
    q1_before = next(item for item in before_reopen["annual_adjustment_detail"] if item["quarter"] == 1)
    assert Decimal(str(q1_before["ratio_applied"])) == Decimal("0.25")

    reopen_return(synthetic_db, 2026, 1, 1)
    after_reopen = build_vat_return(synthetic_db, 2026, 4)
    q1_reopened = next(item for item in after_reopen["annual_adjustment_detail"] if item["quarter"] == 1)
    assert Decimal(str(q1_reopened["ratio_applied"])) != Decimal("0.25")

    save_return(synthetic_db, 2026, 1, 1)
    after_resave = build_vat_return(synthetic_db, 2026, 4)
    q1_resaved = next(item for item in after_resave["annual_adjustment_detail"] if item["quarter"] == 1)
    assert Decimal(str(q1_resaved["ratio_applied"])) == Decimal(str(synthetic_db.vat_provisional_ratio(2026) or q1_resaved["ratio_applied"]))


def test_saved_vat_reopen_audit_records_user_time_but_no_reason(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT: audit row lacks a reason field/value."""
    from vat_return import reopen_return, save_return

    save_return(synthetic_db, 2026, 1, 1, user_name="Synthetic reviewer")
    reopen_return(synthetic_db, 2026, 1, 1)
    with synthetic_db.connect() as connection:
        row = connection.execute(
            "SELECT user_id,action,entity,details,created_at FROM audit_log "
            "WHERE action='reopen' AND entity='vat_return' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    details = json.loads(row["details"])
    assert row["user_id"] == 1 and row["created_at"] and details == {"year": 2026, "quarter": 1}
    assert "reason" not in details
