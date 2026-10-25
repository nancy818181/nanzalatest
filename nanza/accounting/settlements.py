"""Shared settlement policy: approved postings, party direction and settlement value."""

from decimal import Decimal


def posted_payment_sql(alias="x"):
    if alias not in ("x", "pay"):
        raise ValueError("Unsupported payment alias")
    return (
        f"{alias}.voided_at IS NULL AND "  # 2.9.136: a voided / reversed payment settles nothing
        f"EXISTS (SELECT 1 FROM journal_entries pe WHERE pe.source_type='payment' "
        f"AND pe.source_id={alias}.id AND COALESCE(pe.approval_status,'')<>'review' "
        "AND EXISTS (SELECT 1 FROM journal_lines pl WHERE pl.entry_id=pe.id))"
    )


def settlement_amount(payment):
    value = Decimal(str(payment["amount"] or 0)) + Decimal(str(payment["exchange_difference"] or 0))
    if not value.is_finite():
        raise ValueError("Invalid party settlement amount")
    return value


def invoice_kind(payment):
    kind = payment.get("party_kind")
    if kind == "customer":
        return "sale"
    if kind == "supplier":
        return "purchase"
    account = str(payment.get("party_account") or payment.get("account_number") or "")
    if account.startswith("41"):
        return "sale"
    if account.startswith("40"):
        return "purchase"
    return "sale" if payment["kind"] == "customer_receipt" else "purchase"


def settlement_sign(payment, kind):
    return 1 if payment["kind"] == ("customer_receipt" if kind == "sale" else "supplier_payment") else -1
