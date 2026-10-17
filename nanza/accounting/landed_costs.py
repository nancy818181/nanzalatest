"""Normalize purchase costs while preserving the source currency of each amount."""
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP

COMPONENTS = (("freight", "Freight"), ("insurance", "Insurance"),
              ("customs_group_1", "Customs per item"), ("customs_duties", "Customs fees"),
              ("customs_group_2", "Customs - group 2"), ("broker_fees", "Customs broker fees"),
              ("other_costs", "Other landed costs"), ("import_vat", "Import VAT"))


def amount(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        number = Decimal(str(value if value not in (None, "") else "0").replace(",", ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _normalize(item, default_currency):
    """Legacy flat inputs retain their currency; dual inputs require an explicit FX rate.

    Return (normalized invoice input, auditable source amounts). Recoverable import
    VAT remains separate from inventory cost. Round each converted component once.
    """
    result = dict(item)
    currency = str(item.get("currency") or default_currency).upper()
    result["currency"] = currency
    inputs = item.get("currency_amounts")
    if inputs is not None and not isinstance(inputs, dict):
        raise ValueError("Currency amounts must contain cost components")
    if inputs is not None and set(inputs) - {key for key, _ in COMPONENTS}:
        raise ValueError("Unknown cost component")
    sources = []
    rate = None
    if inputs is not None and currency not in ("USD", "LBP"):
        raise ValueError("Dual-currency purchase costs must be posted in USD or LBP")
    for key, label in COMPONENTS:
        legacy = amount(item.get(key), label)
        if inputs is None:
            result[key] = str(legacy)
            if legacy:
                sources.append((key, currency, str(legacy), "1", str(legacy)))
            continue
        if legacy:
            raise ValueError(f"{label}: use either currency columns or the legacy amount")
        values = inputs.get(key, {})
        if not isinstance(values, dict) or set(values) - {"USD", "LBP"}:
            raise ValueError(f"{label}: only USD and LBP amounts are supported")
        converted = Decimal("0")
        for source, value in values.items():
            original = amount(value, f"{label} ({source})")
            if not original:
                continue
            factor = Decimal("1")
            if source != currency:
                if rate is None:
                    rate = amount(item.get("usd_lbp_rate"), "LBP per USD")
                    if not rate:
                        raise ValueError("Enter a positive LBP per USD exchange rate")
                factor = rate if source == "USD" else Decimal("1") / rate
            value = original * factor
            sources.append((key, source, str(original), str(factor), str(value)))
            converted += value
        quantum = Decimal("1") if currency == "LBP" else Decimal(".01")
        result[key] = str(converted.quantize(quantum, rounding=ROUND_HALF_UP))
    return result, sources


def normalize(item, default_currency):
    try:
        return _normalize(item, default_currency)
    except DecimalException as exc:
        raise ValueError("Amounts or exchange rate exceed supported precision") from exc
