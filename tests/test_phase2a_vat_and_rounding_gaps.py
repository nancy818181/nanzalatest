"""Strict characterization gaps for VAT and rounding; synthetic DB only.

Expected failures are intentionally strict and remain visible until the
corresponding accounting decisions are approved and implemented.
"""

import sqlite3
from decimal import Decimal

from tests.pytest_compat import pytest
from database import utcnow


_CLOSED_PERIODS = [
    ("month", "2026-01-31", "2026-01-15"),
    ("quarter", "2026-03-31", "2026-02-15"),
    ("year", "2025-12-31", "2025-06-15"),
]
_SOURCES = [
    ("sales_invoice", "invoice"),
    ("purchase", "invoice"),
    ("receipt", "payment"),
    ("payment", "payment"),
    ("journal_voucher", "journal_voucher"),
    ("excel_pdf_import", "invoice"),
]
_LOCK_OPERATIONS = ("edit", "cancel", "new_posting")


@pytest.mark.parametrize(("period", "locked_until", "entry_date"), _CLOSED_PERIODS)
@pytest.mark.parametrize(("source", "source_type"), _SOURCES)
@pytest.mark.parametrize("operation", _LOCK_OPERATIONS)
def test_closed_period_journal_entry_trigger_matrix(
    synthetic_db, period, locked_until, entry_date, source, source_type, operation
):
    """CURRENT BEHAVIOR: 54 labels exercise one journal-entry trigger, not six source integrations."""
    with synthetic_db.connect() as connection:
        entry_id = None
        if operation != "new_posting":
            entry_id = connection.execute(
                """INSERT INTO journal_entries(
                       entry_number,entry_date,description,source_type,currency,
                       created_by,created_at,posting_status
                   ) VALUES(?,?,?,?,?,?,?,'draft')""",
                (f"SYN-{period}-{source}-{operation}", entry_date, "Synthetic lock probe",
                 source_type, "USD", 1, utcnow()),
            ).lastrowid
        connection.execute(
            "INSERT INTO app_settings(key,value) VALUES('books_locked_until',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (locked_until,),
        )

        with pytest.raises(sqlite3.IntegrityError, match="(?i)period locked"):
            if operation == "new_posting":
                connection.execute(
                    """INSERT INTO journal_entries(
                           entry_number,entry_date,description,source_type,currency,
                           created_by,created_at,posting_status
                       ) VALUES(?,?,?,?,?,?,?,'posted')""",
                    (f"SYN-{period}-{source}-new", entry_date, "Synthetic new posting",
                     source_type, "USD", 1, utcnow()),
                )
            elif operation == "edit":
                connection.execute(
                    "UPDATE journal_entries SET description='edited' WHERE id=?", (entry_id,)
                )
            else:
                connection.execute("DELETE FROM journal_entries WHERE id=?", (entry_id,))


def _invoice(db, number, *, status="posted", kind="purchase"):
    return db.import_invoice(
        {
            "invoice_number": number,
            "invoice_date": "10-03-2026",
            "party_name": f"Synthetic {kind} party",
            "kind": kind,
            "currency": "LBP",
            "subtotal": "100.00",
            "vat": "11.00",
            "total": "111.00",
            "status": status,
        },
        1,
    )


@pytest.mark.xfail(
    strict=True,
    reason="A6-VAT-POSTED-SOURCE: VAT inclusion must require the source invoice's journal entry to be posted.",
)
def test_vat_return_excludes_invoice_when_linked_journal_entry_is_draft(synthetic_db):
    from vat_return import build_vat_return

    invoice_id = _invoice(synthetic_db, "SYN-VAT-JE-DRAFT")
    with synthetic_db.connect() as connection:
        connection.execute(
            "UPDATE journal_entries SET posting_status='draft' WHERE source_type='invoice' AND source_id=?",
            (invoice_id,),
        )
    result = build_vat_return(synthetic_db, 2026, 1)
    assert "SYN-VAT-JE-DRAFT" not in {row["number"] for row in result["documents"]}


@pytest.mark.xfail(
    strict=True,
    reason="A6-VAT-EXPENSE-POSTED-SOURCE: VAT inclusion must require an active posted source journal entry.",
)
def test_vat_return_excludes_expense_without_posted_journal_entry(synthetic_db):
    from vat_return import build_vat_return

    expense_id = synthetic_db.add_expense(
        {"expense_date": "10-03-2026", "description": "Synthetic draft expense",
         "currency": "LBP", "with_vat_subtotal": "100.00",
         "without_vat_subtotal": "0", "vat": "11.00"},
        1,
        defer_posting=True,
    )
    result = build_vat_return(synthetic_db, 2026, 1)
    assert f"EXP-{expense_id}" not in {row["number"] for row in result["documents"]}


def test_vat_review_invoice_is_excluded_by_default_and_labeled_when_included(synthetic_db):
    from vat_return import build_vat_return

    _invoice(synthetic_db, "SYN-VAT-REVIEW", status="review")
    default = build_vat_return(synthetic_db, 2026, 1)
    explicit = build_vat_return(synthetic_db, 2026, 1, include_review=True)
    assert "SYN-VAT-REVIEW" not in {row["number"] for row in default["documents"]}
    assert "SYN-VAT-REVIEW" in {row["number"] for row in explicit["documents"]}
    assert explicit["review_excluded"] == 0


def test_vat_return_excludes_rejected_draft_invoice_status(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT; rejection returns the invoice to draft."""
    from vat_return import build_vat_return

    invoice_id = _invoice(synthetic_db, "SYN-VAT-REJECTED", status="review")
    with synthetic_db.connect() as connection:
        connection.execute(
            "UPDATE invoices SET status='draft',rejection_reason='synthetic test rejection' WHERE id=?",
            (invoice_id,),
        )
        connection.execute(
            "UPDATE journal_entries SET posting_status='draft' WHERE source_type='invoice' AND source_id=?",
            (invoice_id,),
        )
    result = build_vat_return(synthetic_db, 2026, 1)
    assert "SYN-VAT-REJECTED" not in {row["number"] for row in result["documents"]}


def test_vat_return_currently_excludes_cancelled_invoice_snapshot(synthetic_db):
    """CURRENT BEHAVIOR, NOT VERIFIED CORRECT; no VAT filing eligibility rule is asserted."""
    from vat_return import build_vat_return

    invoice_id = _invoice(synthetic_db, "SYN-VAT-CANCELLED", status="posted")
    synthetic_db.cancel_invoice(invoice_id, "Synthetic test cancellation", 1)
    result = build_vat_return(synthetic_db, 2026, 1)
    assert "SYN-VAT-CANCELLED" not in {row["number"] for row in result["documents"]}


@pytest.mark.xfail(
    strict=True,
    reason="RPT-DRAFTS-001 (Decision 1): default excludes drafts; an explicit include_drafts switch is not exposed by reports.",
)
def test_trial_balance_include_drafts_flag_is_explicit_and_includes_drafts(synthetic_db):
    from tests.test_accounting_safety_net import _draft_voucher

    _draft_voucher(synthetic_db)
    rows = synthetic_db.trial_balance(include_drafts=True)
    assert any(row["code"] == "531" for row in rows)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2.675", "2.68"), ("2.665", "2.67"), ("1.004", "1.00"),
     ("1500000.005", "1500000.01"), ("1500000.004", "1500000.00")],
)
def test_invoice_calculation_uses_round_half_up_for_fractional_amount_cases(raw, expected):
    import invoice_calc

    result = invoice_calc.calculate(
        [{"description": "Synthetic", "quantity": "1", "unit_price": raw, "vat_rate": "0"}]
    )
    assert Decimal(str(result["lines"][0]["gross_amount"])) == Decimal(expected)


def test_three_way_split_of_one_hundred_reconciles_without_float():
    import invoice_calc

    result = invoice_calc.calculate(
        [{"description": f"Part {index}", "quantity": "1", "unit_price": amount, "vat_rate": "0"}
         for index, amount in enumerate(("33.33", "33.33", "33.34"), 1)]
    )
    assert sum((Decimal(str(line["net"])) for line in result["lines"]), Decimal("0")) == Decimal("100.00")


def test_posting_rejects_imbalance_above_approved_tolerance(synthetic_db):
    with synthetic_db.connect() as connection:
        cash = connection.execute("SELECT code FROM accounts WHERE code='531'").fetchone()["code"]
        equity = connection.execute("SELECT code FROM accounts WHERE type='equity' LIMIT 1").fetchone()["code"]
    with pytest.raises(ValueError, match="(?i)unbalanced"):
        synthetic_db.save_journal_voucher(
            {"entry_number": "SYN-TOO-LARGE-DIFF", "entry_date": "10-03-2026",
             "description": "Synthetic imbalance", "currency": "USD"},
            [{"account_code": cash, "debit": "10.00"},
             {"account_code": equity, "credit": "9.00"}],
            1,
        )


@pytest.mark.parametrize("amount", ["1.004", "1500000.004"])
@pytest.mark.xfail(
    strict=True,
    reason="POST-DECIMAL-001 (Decision 2): nonzero sub-cent imbalance acceptance depends on the owner's approved posting tolerance.",
)
def test_posting_rejects_nonzero_subcent_imbalance(amount, synthetic_db):
    with synthetic_db.connect() as connection:
        cash = connection.execute("SELECT code FROM accounts WHERE code='531'").fetchone()["code"]
        equity = connection.execute("SELECT code FROM accounts WHERE type='equity' LIMIT 1").fetchone()["code"]
    with pytest.raises(ValueError, match="(?i)unbalanced"):
        synthetic_db.save_journal_voucher(
            {"entry_number": f"SYN-SUBCENT-{amount}", "entry_date": "10-03-2026",
             "description": "Synthetic sub-cent difference", "currency": "LBP"},
            [{"account_code": cash, "debit": amount},
             {"account_code": equity, "credit": str(Decimal(amount).quantize(Decimal("1")))}],
            1,
        )


@pytest.mark.xfail(
    strict=True,
    reason="POST-ROUNDING-LINE-001 (Decision 2): a separately identified rounding-difference line is not specified/implemented.",
)
def test_posting_rounding_difference_line_is_visible(synthetic_db):
    from tests.test_accounting_safety_net import _account_codes

    cash, equity, _income, _expense = _account_codes(synthetic_db)
    synthetic_db.save_journal_voucher(
        {"entry_number": "SYN-ROUNDING-LINE", "entry_date": "10-03-2026",
         "description": "Synthetic rounding", "currency": "USD"},
        [{"account_code": cash, "debit": "1.004"},
         {"account_code": equity, "credit": "1.000"}],
        1,
    )
    with synthetic_db.connect() as connection:
        entry_id = connection.execute(
            "SELECT id FROM journal_entries WHERE entry_number='SYN-ROUNDING-LINE'"
        ).fetchone()["id"]
        lines = connection.execute(
            "SELECT a.code,j.debit,j.credit FROM journal_lines j "
            "JOIN accounts a ON a.id=j.account_id WHERE j.entry_id=?",
            (entry_id,),
        ).fetchall()
    assert any("round" in row["code"].lower() for row in lines)


@pytest.mark.xfail(
    strict=True,
    reason="POST-DUPLICATE-001 (Decision 3): duplicate identity policy is not approved; importer currently permits repeated invoice numbers.",
)
def test_duplicate_invoice_identity_is_rejected(synthetic_db):
    _invoice(synthetic_db, "SYN-DUPLICATE-IDENTITY")
    with pytest.raises(ValueError, match="(?i)duplicate"):
        _invoice(synthetic_db, "SYN-DUPLICATE-IDENTITY")


@pytest.mark.xfail(
    strict=True,
    reason="POST-IMMUTABILITY-001 (Decision 4): posted invoice-source entries must reject raw SQL updates and deletes.",
)
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_posted_invoice_source_entry_rejects_raw_sql_mutation(synthetic_db, operation):
    invoice_id = _invoice(synthetic_db, "SYN-POSTED-IMMUTABLE")
    with synthetic_db.connect() as connection:
        entry_id = connection.execute(
            "SELECT id FROM journal_entries WHERE source_type='invoice' AND source_id=?",
            (invoice_id,),
        ).fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError, match="(?i)immutable"):
            if operation == "update":
                connection.execute(
                    "UPDATE journal_entries SET description='tampered' WHERE id=?", (entry_id,)
                )
            else:
                connection.execute("DELETE FROM journal_entries WHERE id=?", (entry_id,))


@pytest.mark.xfail(
    strict=True,
    reason="POST-IMMUTABILITY-001 (Decision 4): a non-admin must not edit a posted sales invoice in place; corrections require reversal.",
)
def test_non_admin_posted_sales_invoice_edit_requires_reversal():
    import server

    class _MasterWithoutApprovalPermission:
        @staticmethod
        def user_can(_user, _permission):
            return False

    handler = object.__new__(server.ApiHandler)
    handler.master_db = _MasterWithoutApprovalPermission()
    handler._approval_required = lambda: False
    user = {"id": 2, "role": "accountant"}
    posted_sales_invoice = {"status": "posted", "kind": "sales"}
    with pytest.raises(PermissionError, match="(?i)posted|reversal"):
        handler._approval_gate(user, posted_sales_invoice, invoice_id=42)
