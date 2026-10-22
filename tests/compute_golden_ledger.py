"""Independent golden-value calculator; imports only Python stdlib and fixture literals."""

from collections import defaultdict
from decimal import Decimal
import json

from golden_ledger_fixture import ENTRIES, FIXTURE_RATES


ZERO = Decimal("0")
ACCOUNT_TYPES = {"cash": "asset", "ar": "asset", "vat_input": "asset",
                 "ap": "liability", "vat_output": "liability", "equity": "equity",
                 "income": "income", "expense": "expense"}


def _format(value):
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def compute():
    by_currency = defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO]))
    by_date_cash = defaultdict(lambda: ZERO)
    pnl = defaultdict(lambda: [ZERO, ZERO])
    for _number, date, currency, _scenario, lines, _reversal in ENTRIES:
        for account, debit_text, credit_text in lines:
            debit, credit = Decimal(debit_text), Decimal(credit_text)
            by_currency[currency][account][0] += debit
            by_currency[currency][account][1] += credit
            if account == "cash":
                by_date_cash[(currency, date)] += debit - credit
            kind = ACCOUNT_TYPES[account]
            if kind == "income":
                pnl[(currency, "income")][0] += credit - debit
            elif kind == "expense":
                pnl[(currency, "expense")][1] += debit - credit

    converted_balances = defaultdict(lambda: ZERO)
    converted_pnl = {"income": ZERO, "expense": ZERO}
    for currency, accounts in by_currency.items():
        rate = Decimal("1") if currency == "USD" else (
            FIXTURE_RATES[("EUR", "USD")] if currency == "EUR"
            else Decimal("1") / FIXTURE_RATES[("USD", "LBP")]
        )
        for account, (debit, credit) in accounts.items():
            converted_balances[account] += (debit - credit) * rate
        converted_pnl["income"] += pnl[(currency, "income")][0] * rate
        converted_pnl["expense"] += pnl[(currency, "expense")][1] * rate

    native = {}
    for currency, accounts in by_currency.items():
        debit = sum((amounts[0] for amounts in accounts.values()), ZERO)
        credit = sum((amounts[1] for amounts in accounts.values()), ZERO)
        native[currency] = {
            "debit": _format(debit), "credit": _format(credit),
            "cash_closing": _format(accounts["cash"][0] - accounts["cash"][1]),
            "income": _format(pnl[(currency, "income")][0]),
            "expense": _format(pnl[(currency, "expense")][1]),
        }

    usd_cash_jan = sum((delta for (currency, date), delta in by_date_cash.items()
                        if currency == "USD" and date[3:] == "01-2026"), ZERO)
    usd_cash_feb = sum((delta for (currency, date), delta in by_date_cash.items()
                        if currency == "USD" and date[3:] == "02-2026"), ZERO)
    bs_assets = sum(
        (converted_balances[account] for account, kind in ACCOUNT_TYPES.items() if kind == "asset"),
        ZERO,
    )
    bs_liabilities = -sum(
        (converted_balances[account] for account, kind in ACCOUNT_TYPES.items() if kind == "liability"),
        ZERO,
    )
    bs_equity = -converted_balances["equity"] + converted_pnl["income"] - converted_pnl["expense"]
    usd_accounts = by_currency["USD"]
    usd_assets = sum(
        (debit - credit for account, (debit, credit) in usd_accounts.items()
         if ACCOUNT_TYPES[account] == "asset"),
        ZERO,
    )
    usd_liabilities = -sum(
        (debit - credit for account, (debit, credit) in usd_accounts.items()
         if ACCOUNT_TYPES[account] == "liability"),
        ZERO,
    )
    usd_equity = (
        -(usd_accounts["equity"][0] - usd_accounts["equity"][1])
        + pnl[("USD", "income")][0] - pnl[("USD", "expense")][1]
    )
    result = {
        "entry_count": len(ENTRIES),
        "native": native,
        "account_balances_usd": {key: _format(value) for key, value in sorted(converted_balances.items())},
        "converted_pnl_usd": {key: _format(value) for key, value in converted_pnl.items()},
        "usd_cash_january_closing": _format(usd_cash_jan),
        "usd_cash_february_movement": _format(usd_cash_feb),
        "consolidated_cash_usd": _format(converted_balances["cash"]),
        "vat_input_usd": _format(converted_balances["vat_input"]),
        "vat_output_usd_credit_balance": _format(-converted_balances["vat_output"]),
        "bs_assets_usd": _format(bs_assets),
        "bs_liabilities_usd": _format(bs_liabilities),
        "bs_equity_usd": _format(bs_equity),
        "bs_usd_native": {
            "assets": _format(usd_assets),
            "liabilities": _format(usd_liabilities),
            "equity": _format(usd_equity),
        },
    }
    return result


if __name__ == "__main__":
    print(json.dumps(compute(), indent=2, sort_keys=True))
