"""Hand-reviewed golden constants, independently derived by compute_golden_ledger.py.

The calculator reads only the synthetic fixture and Python Decimal; it does not import
or call Nanza. Constants are committed here so tests never generate expected values
from application outputs.
"""

EXPECTED_ENTRY_COUNT = 30

# Each currency total is the sum of literal debit and credit legs in all fixture entries.
EXPECTED_NATIVE = {
    "USD": {"debit": "1506.74", "credit": "1506.74", "cash_closing": "1054.43",
            "income": "110.48", "expense": "53.32"},
    "LBP": {"debit": "9039500", "credit": "9039500", "cash_closing": "8860500",
            "income": "0", "expense": "89500"},
    "EUR": {"debit": "4.45", "credit": "4.45", "cash_closing": "1.11",
            "income": "3.33", "expense": "0.01"},
}

# USD conversion uses only the fixture rates: EUR/USD = 1.07 and USD/LBP = 89,500.
# These are arbitrary test rates, not actual or recommended exchange rates.
EXPECTED_ACCOUNT_BALANCES_USD = {
    "ap": "-29.9607", "ar": "242.2054", "cash": "1154.6177",
    "equity": "-1300", "expense": "54.3307", "income": "-114.0431",
    "vat_input": "4.95", "vat_output": "-12.1",
}
EXPECTED_CONVERTED_PNL_USD = {"income": "114.0431", "expense": "54.3307"}
EXPECTED_CONSOLIDATED_BS_USD = {
    "assets": "1401.7731", "liabilities": "42.0607", "equity": "1359.7124"
}

# GL period test: 01-01 through 31-01 movements yield 1,051.90 USD cash;
# February reverses 2.34 and has +0.30 -0.10 +0.04 -0.02 -0.03 = +0.19,
# so February movement is 2.53 and cash closes at 1,054.43.
EXPECTED_USD_CASH_JANUARY_CLOSE = "1051.90"
EXPECTED_USD_CASH_FEBRUARY_MOVEMENT = "2.53"
EXPECTED_USD_CASH_CLOSE = "1054.43"

# VAT control account arithmetic only: fixture sales VAT 11 + 2.20 - 1.10;
# purchases VAT 5.50 - 0.55. No Lebanese rate, eligibility, or deduction rule is certified.
NEEDS_ACCOUNTANT_SIGN_OFF = True
EXPECTED_VAT_INPUT_USD = "4.95"
EXPECTED_VAT_OUTPUT_CREDIT_USD = "12.10"
