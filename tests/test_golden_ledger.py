"""Golden-ledger certification checks; all inputs are synthetic and expectations external."""

from decimal import Decimal

from tests.pytest_compat import pytest

from compute_golden_ledger import compute as independent_decimal_calculation
from golden_ledger_expected import (
    EXPECTED_ACCOUNT_BALANCES_USD,
    EXPECTED_CONSOLIDATED_BS_USD,
    EXPECTED_CONVERTED_PNL_USD,
    EXPECTED_ENTRY_COUNT,
    EXPECTED_NATIVE,
    EXPECTED_USD_CASH_CLOSE,
    EXPECTED_USD_CASH_FEBRUARY_MOVEMENT,
    EXPECTED_USD_CASH_JANUARY_CLOSE,
    EXPECTED_VAT_INPUT_USD,
    EXPECTED_VAT_OUTPUT_CREDIT_USD,
)
from golden_ledger_fixture import ENTRIES, FIXTURE_RATES, PERIOD_END, PERIOD_START, RATE_DATE, REJECTED_ATTEMPTS


def _account_codes(db):
    with db.connect() as connection:
        rows = {row["code"]: row["type"] for row in connection.execute("SELECT code,type FROM accounts")}
    codes = {
        "cash": "531", "ar": "4111", "ap": "4011", "equity": "1013",
        "income": "701100001", "expense": "601100000",
        "vat_input": "44210", "vat_output": "4427",
    }
    assert all(code in rows for code in codes.values())
    return codes


@pytest.fixture
def posted_golden_ledger(synthetic_db):
    """Load 30 posted synthetic vouchers and explicit fixture-only rates into the temp DB."""
    db = synthetic_db
    db.save_exchange_rate({"date_from": RATE_DATE, "date_to": RATE_DATE,
                           "from_currency": "EUR", "to_currency": "USD",
                           "rate": str(FIXTURE_RATES[("EUR", "USD")])}, 1)
    db.save_exchange_rate({"date_from": RATE_DATE, "date_to": RATE_DATE,
                           "from_currency": "USD", "to_currency": "LBP",
                           "rate": str(FIXTURE_RATES[("USD", "LBP")])}, 1)
    codes = _account_codes(db)
    ids = {}
    for number, date, currency, scenario, lines, reversal_of in ENTRIES:
        voucher = db.save_journal_voucher(
            {"entry_number": number, "entry_date": date,
             "description": f"Synthetic golden fixture: {scenario}", "currency": currency},
            [{"account_code": codes[account], "debit": debit, "credit": credit,
              "description": scenario} for account, debit, credit in lines],
            1,
            reversal_of=ids.get(reversal_of),
        )["voucher"]
        ids[number] = voucher["id"]
    return {"db": db, "codes": codes, "ids": ids}


def _dec(value):
    return Decimal(str(value or 0))


def test_fixture_has_thirty_exactly_balanced_entries():
    assert len(ENTRIES) == EXPECTED_ENTRY_COUNT == 30
    for number, _date, _currency, _scenario, lines, _reversal in ENTRIES:
        debit = sum((Decimal(line[1]) for line in lines), Decimal("0"))
        credit = sum((Decimal(line[2]) for line in lines), Decimal("0"))
        assert debit == credit, number


def test_checked_in_golden_constants_match_independent_decimal_script():
    """The script imports only fixture literals and Decimal; it never calls Nanza."""
    derived = independent_decimal_calculation()
    assert derived["entry_count"] == EXPECTED_ENTRY_COUNT
    assert derived["native"] == EXPECTED_NATIVE
    assert derived["account_balances_usd"] == EXPECTED_ACCOUNT_BALANCES_USD
    assert derived["converted_pnl_usd"] == EXPECTED_CONVERTED_PNL_USD
    assert derived["bs_assets_usd"] == EXPECTED_CONSOLIDATED_BS_USD["assets"]
    assert derived["bs_liabilities_usd"] == EXPECTED_CONSOLIDATED_BS_USD["liabilities"]
    assert derived["bs_equity_usd"] == EXPECTED_CONSOLIDATED_BS_USD["equity"]
    assert Decimal(derived["usd_cash_january_closing"]) == Decimal(EXPECTED_USD_CASH_JANUARY_CLOSE)
    assert Decimal(derived["usd_cash_february_movement"]) == Decimal(EXPECTED_USD_CASH_FEBRUARY_MOVEMENT)
    assert Decimal(derived["native"]["USD"]["cash_closing"]) == Decimal(EXPECTED_USD_CASH_CLOSE)


def test_golden_trial_balance_debits_equal_credits_per_currency(posted_golden_ledger):
    rows = posted_golden_ledger["db"].trial_balance(to_date=PERIOD_END)
    for currency, expected in EXPECTED_NATIVE.items():
        debit = sum((_dec(row["debit"]) for row in rows if row["currency"] == currency), Decimal("0"))
        credit = sum((_dec(row["credit"]) for row in rows if row["currency"] == currency), Decimal("0"))
        assert debit == credit == Decimal(expected["debit"])


def test_golden_trial_balance_ties_to_general_ledger_for_february_cash(posted_golden_ledger):
    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    ledger = db.general_ledger(account_code=codes["cash"], from_date="2026-02-01",
                               to_date=PERIOD_END, currency="USD")
    opening = next(_dec(row["amount"]) for row in ledger["opening"]
                   if row["account_code"] == codes["cash"] and row["currency"] == "USD")
    movement = sum((_dec(row["debit"]) - _dec(row["credit"]) for row in ledger["items"]), Decimal("0"))
    closing = opening + movement
    trial = next(row for row in db.trial_balance(from_date="2026-02-01", to_date=PERIOD_END)
                 if row["code"] == codes["cash"] and row["currency"] == "USD")
    assert opening == Decimal(EXPECTED_USD_CASH_JANUARY_CLOSE)
    assert movement == Decimal(EXPECTED_USD_CASH_FEBRUARY_MOVEMENT)
    assert closing == Decimal(EXPECTED_USD_CASH_CLOSE)
    assert _dec(trial["closing_balance"]) == closing


@pytest.mark.xfail(strict=True, reason=(
    "MONEY-FLOAT-001: P&L subtracts SQLite float totals and returns 110.47999999999999 "
    "instead of the exact Decimal ledger value 110.48."
))
def test_golden_profit_and_loss_reproduces_usd_ledger(posted_golden_ledger):
    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    rows = db.profit_and_loss(from_date=PERIOD_START, to_date=PERIOD_END, currency="USD")
    actual = {row["code"]: _dec(row["amount"]) for row in rows}
    assert actual[codes["income"]] == Decimal(EXPECTED_NATIVE["USD"]["income"])
    assert actual[codes["expense"]] == Decimal(EXPECTED_NATIVE["USD"]["expense"])


@pytest.mark.xfail(strict=True, reason=(
    "RPT-BS-001: account 4427 is typed as an asset, so its output-VAT credit is included "
    "as a negative asset instead of a liability in the Balance Sheet."
))
def test_golden_balance_sheet_balances_in_usd(posted_golden_ledger):
    db = posted_golden_ledger["db"]
    rows = db.balance_sheet(to_date=PERIOD_END, currency="USD")
    assets = sum((_dec(row["balance"]) for row in rows if row["type"] == "asset"), Decimal("0"))
    liabilities = -sum((_dec(row["balance"]) for row in rows if row["type"] == "liability"), Decimal("0"))
    equity = -sum((_dec(row["balance"]) for row in rows if row["type"] == "equity"), Decimal("0"))
    assert assets == Decimal("1299.21")
    assert liabilities == Decimal("42.05")
    assert equity == Decimal("1257.16")
    assert assets == liabilities + equity


def test_golden_cash_flow_net_movement_ties_to_native_cash(posted_golden_ledger):
    rows = posted_golden_ledger["db"].cash_flow(from_date=PERIOD_START, to_date=PERIOD_END)
    for currency, expected in EXPECTED_NATIVE.items():
        net = sum((_dec(row["net"]) for row in rows if row["currency"] == currency), Decimal("0"))
        # Fixture opening cash is zero before the first posted opening-balance voucher.
        assert net == Decimal(expected["cash_closing"])


def test_golden_vat_control_accounts_reconcile_to_fixture_arithmetic(posted_golden_ledger):
    """NEEDS ACCOUNTANT SIGN-OFF: asserts ledger arithmetic, not VAT law or filing eligibility."""
    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    rows = db.trial_balance(to_date=PERIOD_END)
    input_row = next(row for row in rows if row["code"] == codes["vat_input"] and row["currency"] == "USD")
    output_row = next(row for row in rows if row["code"] == codes["vat_output"] and row["currency"] == "USD")
    input_net_debit = _dec(input_row["debit"]) - _dec(input_row["credit"])
    output_net_credit = _dec(output_row["credit"]) - _dec(output_row["debit"])
    assert input_net_debit == Decimal(EXPECTED_VAT_INPUT_USD)
    assert output_net_credit == Decimal(EXPECTED_VAT_OUTPUT_CREDIT_USD)


def test_golden_financial_statements_use_stored_fixture_fx_rates(posted_golden_ledger):
    import financial_statements

    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    assert db._converted_amount(Decimal("1"), "EUR", "USD", "05-02-2026") == FIXTURE_RATES[("EUR", "USD")]
    assert db._converted_amount(Decimal("1"), "USD", "LBP", "05-02-2026") == FIXTURE_RATES[("USD", "LBP")]
    result = financial_statements.load_period(db, PERIOD_START, PERIOD_END, "USD")
    for account in ("cash", "ar", "ap", "equity", "vat_input", "vat_output"):
        assert result["closing"][codes[account]] == Decimal(EXPECTED_ACCOUNT_BALANCES_USD[account])
    # The loader presents signed Dr-Cr P&L: revenue is negative; expenses are positive.
    assert result["pnl"][codes["income"]] == -Decimal(EXPECTED_CONVERTED_PNL_USD["income"])
    assert result["pnl"][codes["expense"]] == Decimal(EXPECTED_CONVERTED_PNL_USD["expense"])


def test_golden_reversal_links_to_original_and_nets_to_zero(posted_golden_ledger):
    db, ids = posted_golden_ledger["db"], posted_golden_ledger["ids"]
    with db.connect() as connection:
        row = connection.execute("SELECT reversal_of FROM journal_entries WHERE id=?", (ids["GL-013"],)).fetchone()
        lines = connection.execute(
            "SELECT a.code,j.debit,j.credit FROM journal_lines j JOIN accounts a ON a.id=j.account_id "
            "WHERE j.entry_id IN (?,?)", (ids["GL-012"], ids["GL-013"]),
        ).fetchall()
    assert row["reversal_of"] == ids["GL-012"]
    net = {}
    for line in lines:
        net[line["code"]] = net.get(line["code"], Decimal("0")) + Decimal(line["debit"]) - Decimal(line["credit"])
    assert all(value == 0 for value in net.values())


def test_golden_duplicate_entry_number_attempt_is_rejected(posted_golden_ledger):
    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    number = REJECTED_ATTEMPTS["duplicate_entry_number"]
    with pytest.raises(ValueError, match="(?i)already exists"):
        db.save_journal_voucher(
            {"entry_number": number, "entry_date": "01-03-2026", "description": "Synthetic duplicate", "currency": "USD"},
            [{"account_code": codes["cash"], "debit": "1.00", "credit": "0"},
             {"account_code": codes["equity"], "debit": "0", "credit": "1.00"}], 1,
        )


def test_golden_closed_period_attempt_is_rejected(posted_golden_ledger):
    db, codes = posted_golden_ledger["db"], posted_golden_ledger["codes"]
    with db.connect() as connection:
        connection.execute("INSERT INTO fiscal_years(year,status,opened_at) VALUES(2025,'closed','synthetic')")
    with pytest.raises(ValueError, match="(?i)closed"):
        db.save_journal_voucher(
            {"entry_number": "GL-CLOSED-ATTEMPT", "entry_date": REJECTED_ATTEMPTS["closed_period_date"],
             "description": "Synthetic closed-period attempt", "currency": "USD"},
            [{"account_code": codes["cash"], "debit": "1.00", "credit": "0"},
             {"account_code": codes["equity"], "debit": "0", "credit": "1.00"}], 1,
        )
