"""Deterministic, read-only accounting baseline for a verified database copy.

This reports aggregate diagnostics only. It never prints names, descriptions,
document identifiers, database paths, or stored VAT snapshots. Amounts are read
through SQLite TEXT casts and aggregated with Decimal; cross-currency totals in
the ALL_CURRENCIES scope are raw stored amounts and are not FX-converted.

This script reads stored database data directly. It does NOT run the
application's report functions, so it cannot detect changes made only to report
queries (for example, a query changing to exclude draft entries).
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from diagnose_decimals import _decimal, _exact_sum, _has_subcent_digits


# VAT codes defined in nanza/tax/vat_ledgers.py and the chart seed. The current
# report emits only the 4427 record; keep any account-code output within this set.
VAT_ACCOUNT_CODES = frozenset({
    "4427", "44210", "44270", "44216", "44265", "44213", "44263",
    "4426.6", "4426.2", "442660000", "4425", "4429", "4428.3",
})
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")
VAT_RETURN_AMOUNT_COLUMNS = (
    "net_lbp", "credit_brought_forward_lbp", "payable_lbp",
    "credit_carried_forward_lbp", "refund_requested_lbp",
)


def connect_read_only(database_copy: Path) -> sqlite3.Connection:
    uri = database_copy.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> set[str] | None:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        return None
    return {str(row["name"]) for row in rows}


def amount(value: object) -> Decimal | None:
    return _decimal(value)


def decimal_text(value: Decimal) -> str:
    # Decimal.__str__ preserves the maximum stored fractional scale present in
    # the exact sum, without converting to float or applying display rounding.
    return str(value)


def sum_amounts(values: list[Decimal]) -> Decimal:
    return _exact_sum(values)


def _currency(value: object) -> str:
    return str(value or "").strip().upper()


def _status_bucket(value: object) -> str:
    value = str(value or "").strip().lower()
    return value if value in ("posted", "draft") else "other"


def _missing(value: object) -> str:
    return "not found" if value is None else str(value)


def _collect_currency_set(connection: sqlite3.Connection) -> tuple[list[str], bool]:
    currencies: set[str] = set()
    found_any_source = False
    for table, column in (("journal_entries", "currency"), ("journal_lines", "line_currency"), ("invoices", "currency")):
        columns = table_columns(connection, table)
        if columns is None:
            continue
        if column == "line_currency" and column not in columns:
            continue
        if column not in columns:
            continue
        found_any_source = True
        for row in connection.execute(f'SELECT DISTINCT "{column}" FROM "{table}"'):
            code = _currency(row[0])
            if code:
                currencies.add(code)
    return sorted(currencies), found_any_source


def _entry_counts(connection: sqlite3.Connection, currency: str | None) -> tuple[dict[str, int] | None, int | None]:
    columns = table_columns(connection, "journal_entries")
    if columns is None or not {"posting_status", "currency"}.issubset(columns):
        return None, None
    counts = {"posted": 0, "draft": 0, "other": 0}
    for row in connection.execute('SELECT currency,posting_status FROM journal_entries'):
        if currency is not None and _currency(row["currency"]) != currency:
            continue
        counts[_status_bucket(row["posting_status"])] += 1
    lines = _line_rows(connection, currency)
    return counts, None if lines is None else len(lines)


def _line_rows(connection: sqlite3.Connection, currency: str | None) -> list[sqlite3.Row] | None:
    entries = table_columns(connection, "journal_entries")
    lines = table_columns(connection, "journal_lines")
    if entries is None or lines is None:
        return None
    required_entries = {"id", "currency", "posting_status"}
    required_lines = {"entry_id", "account_id", "debit", "credit"}
    if not required_entries.issubset(entries) or not required_lines.issubset(lines):
        return None
    line_currency = "COALESCE(NULLIF(l.line_currency,''),e.currency)" if "line_currency" in lines else "e.currency"
    accounts = table_columns(connection, "accounts")
    account_join = "LEFT JOIN accounts a ON a.id=l.account_id" if accounts and {"id", "type"}.issubset(accounts) else ""
    account_type = "a.type" if account_join else "NULL"
    query = (
        "SELECT CAST(l.debit AS TEXT) AS debit,CAST(l.credit AS TEXT) AS credit,"
        "e.posting_status,e.currency AS entry_currency," + line_currency + " AS currency,"
        + account_type + " AS account_type "
        + "FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
        + account_join
    )
    rows = connection.execute(query).fetchall()
    if currency is None:
        return rows
    return [row for row in rows if _currency(row["currency"]) == currency]


def _ledger_aggregates(connection: sqlite3.Connection, currency: str | None, posted_only: bool) -> dict[str, object] | None:
    rows = _line_rows(connection, currency)
    if rows is None:
        return None
    selected = [row for row in rows if not posted_only or _status_bucket(row["posting_status"]) == "posted"]
    debits: list[Decimal] = []
    credits: list[Decimal] = []
    grouped: dict[str, list[Decimal]] = {account_type: [] for account_type in ACCOUNT_TYPES}
    grouped["other"] = []
    for row in selected:
        debit, credit = amount(row["debit"]), amount(row["credit"])
        if debit is None or credit is None:
            return {"invalid": "not found"}
        debits.append(debit)
        credits.append(credit)
        account_type = str(row["account_type"] or "other").lower()
        if account_type == "asset" or account_type == "expense":
            grouped.setdefault(account_type, []).append(debit - credit)
        else:
            grouped.setdefault(account_type, []).append(credit - debit)
    debit_total, credit_total = sum_amounts(debits), sum_amounts(credits)
    return {
        "debit": debit_total,
        "credit": credit_total,
        "difference": debit_total - credit_total,
        "by_type": {key: sum_amounts(values) for key, values in grouped.items()},
    }


def _account_4427(connection: sqlite3.Connection, currency: str | None) -> dict[str, object] | None:
    accounts = table_columns(connection, "accounts")
    if accounts is None or not {"id", "code", "type"}.issubset(accounts):
        return None
    account = connection.execute("SELECT id,type FROM accounts WHERE code='4427'").fetchone()
    if account is None:
        return {"type": "not found", "debit": Decimal("0"), "credit": Decimal("0"), "net": Decimal("0")}
    rows = _line_rows(connection, currency)
    if rows is None:
        return None
    # Resolve through account id; no account names or arbitrary codes are emitted.
    currency_filter = ""
    params: tuple[object, ...] = (account["id"],)
    if currency is not None:
        currency_filter = " AND " + ("COALESCE(NULLIF(l.line_currency,''),e.currency)" if "line_currency" in (table_columns(connection, "journal_lines") or set()) else "e.currency") + "=?"
        params = (account["id"], currency)
    query = (
        "SELECT CAST(l.debit AS TEXT) debit,CAST(l.credit AS TEXT) credit FROM journal_lines l "
        "JOIN journal_entries e ON e.id=l.entry_id WHERE l.account_id=? AND e.posting_status='posted'" + currency_filter
    )
    debits: list[Decimal] = []
    credits: list[Decimal] = []
    for row in connection.execute(query, params):
        debit, credit = amount(row["debit"]), amount(row["credit"])
        if debit is None or credit is None:
            return None
        debits.append(debit)
        credits.append(credit)
    debit_total, credit_total = sum_amounts(debits), sum_amounts(credits)
    return {"type": str(account["type"]), "debit": debit_total, "credit": credit_total, "net": credit_total - debit_total}


def _precision_count(connection: sqlite3.Connection, currency: str | None) -> int | None:
    rows = _line_rows(connection, currency)
    if rows is None:
        return None
    count = 0
    for row in rows:
        extra = [_has_subcent_digits(row[column]) for column in ("debit", "credit")]
        if any(value is None for value in extra):
            return None
        if any(extra):
            count += 1
    return count


def _invoice_counts(connection: sqlite3.Connection, currency: str | None) -> tuple[dict[tuple[str, str], int] | None, int | None]:
    columns = table_columns(connection, "invoices")
    entries = table_columns(connection, "journal_entries")
    if columns is None or not {"id", "currency", "status", "kind"}.issubset(columns):
        return None, None
    counts: dict[tuple[str, str], int] = defaultdict(int)
    unposted = 0
    has_linked_source = bool(entries and {"source_type", "source_id", "posting_status"}.issubset(entries))
    query = 'SELECT id,currency,status,kind FROM invoices'
    for row in connection.execute(query):
        if currency is not None and _currency(row["currency"]) != currency:
            continue
        counts[(str(row["status"] or "other"), str(row["kind"] or "other"))] += 1
        if has_linked_source:
            linked = connection.execute(
                "SELECT 1 FROM journal_entries WHERE source_type='invoice' AND source_id=? LIMIT 1", (row["id"],)
            ).fetchone()
            posted = connection.execute(
                "SELECT 1 FROM journal_entries WHERE source_type='invoice' AND source_id=? AND posting_status='posted' LIMIT 1", (row["id"],)
            ).fetchone()
            if linked and not posted:
                unposted += 1
    return counts, unposted if has_linked_source else None


def _vat_return_lines(connection: sqlite3.Connection) -> list[str]:
    columns = table_columns(connection, "vat_returns")
    if columns is None:
        return ["vat_returns: not found"]
    required = {"year", "quarter"}
    if not required.issubset(columns):
        return ["vat_returns: not found"]
    amounts = [column for column in VAT_RETURN_AMOUNT_COLUMNS if column in columns]
    missing_amounts = [column for column in VAT_RETURN_AMOUNT_COLUMNS if column not in columns]
    select_parts = ["year", "quarter"]
    if "deduction_ratio" in columns:
        select_parts.append('CAST("deduction_ratio" AS TEXT) AS deduction_ratio')
    select = ",".join(select_parts + [f'CAST("{column}" AS TEXT) AS "{column}"' for column in amounts])
    lines = []
    for row in connection.execute(f"SELECT {select} FROM vat_returns ORDER BY year,quarter,id" if "id" in columns else f"SELECT {select} FROM vat_returns ORDER BY year,quarter"):
        vals = []
        ratio = amount(row["deduction_ratio"]) if "deduction_ratio" in columns else None
        vals.append("deduction_ratio=" + (decimal_text(ratio) if ratio is not None else "not found"))
        for column in amounts:
            value = amount(row[column])
            vals.append(f"{column}={decimal_text(value)}" if value is not None else f"{column}=not found")
        vals.extend(f"{column}=not found" for column in missing_amounts)
        if "deduction_ratio" not in columns:
            vals.append("deduction_ratio=not found")
        lines.append(f"vat_return year={row['year']} quarter={row['quarter']} " + " ".join(vals))
    if not lines:
        lines.append("vat_returns: 0 saved returns")
    return lines


def _period_lock_lines(connection: sqlite3.Connection) -> list[str]:
    result = []
    settings = table_columns(connection, "app_settings")
    if settings is None or not {"key", "value"}.issubset(settings):
        result.append("books_locked_until.setting: not found")
    else:
        row = connection.execute("SELECT value FROM app_settings WHERE key='books_locked_until'").fetchone()
        result.append("books_locked_until.setting: " + ("1" if row and str(row[0] or "").strip() else "0"))
    years = table_columns(connection, "fiscal_years")
    if years is None or "status" not in years:
        result.append("fiscal_years.closed: not found")
    else:
        result.append("fiscal_years.closed: " + str(connection.execute("SELECT COUNT(*) FROM fiscal_years WHERE lower(status)='closed'").fetchone()[0]))
    for table in ("period_locks", "period_closings"):
        columns = table_columns(connection, table)
        result.append(f"{table}: " + (str(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if columns is not None else "not found"))
    return result


def _vat_4427_descendants(connection: sqlite3.Connection, currency: str | None) -> dict[str, object] | None:
    columns = table_columns(connection, "accounts")
    if columns is None or not {"id", "code", "type"}.issubset(columns):
        return None
    rows = connection.execute(
        "SELECT id,type FROM accounts WHERE substr(code,1,4)='4427' AND code<>'4427'"
    ).fetchall()
    type_counts = {account_type: 0 for account_type in (*ACCOUNT_TYPES, "other")}
    account_ids = []
    for row in rows:
        account_ids.append(int(row["id"]))
        account_type = str(row["type"] or "other").lower()
        type_counts[account_type if account_type in type_counts else "other"] += 1
    entries = table_columns(connection, "journal_entries")
    lines = table_columns(connection, "journal_lines")
    if entries is None or lines is None or not {"id", "currency", "posting_status"}.issubset(entries) or not {"entry_id", "account_id", "debit", "credit"}.issubset(lines):
        return {"count": len(rows), "types": type_counts, "debit": None, "credit": None, "net": None}
    debits: list[Decimal] = []
    credits: list[Decimal] = []
    if account_ids:
        marks = ",".join("?" for _ in account_ids)
        line_currency = "COALESCE(NULLIF(l.line_currency,''),e.currency)" if "line_currency" in lines else "e.currency"
        query = (
            "SELECT CAST(l.debit AS TEXT) debit,CAST(l.credit AS TEXT) credit FROM journal_lines l "
            "JOIN journal_entries e ON e.id=l.entry_id "
            f"WHERE e.posting_status='posted' AND l.account_id IN ({marks})"
        )
        params: tuple[object, ...] = tuple(account_ids)
        if currency is not None:
            query += " AND " + line_currency + "=?"
            params += (currency,)
        for row in connection.execute(query, params):
            debit, credit = amount(row["debit"]), amount(row["credit"])
            if debit is None or credit is None:
                return {"count": len(rows), "types": type_counts, "debit": None, "credit": None, "net": None}
            debits.append(debit)
            credits.append(credit)
    debit_total, credit_total = sum_amounts(debits), sum_amounts(credits)
    return {"count": len(rows), "types": type_counts, "debit": debit_total, "credit": credit_total, "net": credit_total - debit_total}


def build_snapshot(connection: sqlite3.Connection) -> str:
    currencies, currencies_available = _collect_currency_set(connection)
    scopes: list[tuple[str, str | None]] = [(f"CURRENCY {currency}", currency) for currency in currencies]
    scopes.append(("ALL_CURRENCIES (raw units; no FX conversion)", None))
    output = ["HEADER: stored-data snapshot only; application report functions NOT run; report-query-only changes are not detected"]
    for label, currency in scopes:
        output.append(f"[{label}]")
        entry_counts, line_count = _entry_counts(connection, currency)
        if entry_counts is None:
            output.append("journal_entries.posted: not found")
            output.append("journal_entries.draft: not found")
            output.append("journal_entries.other: not found")
            output.append("journal_lines.count: not found")
        else:
            output.append(f"journal_entries.posted: {entry_counts['posted']}")
            output.append(f"journal_entries.draft: {entry_counts['draft']}")
            output.append(f"journal_entries.other: {entry_counts['other']}")
            output.append(f"journal_lines.count: {_missing(line_count)}")
        for status, posted_only in (("posted_only", True), ("all_statuses", False)):
            totals = _ledger_aggregates(connection, currency, posted_only)
            if totals is None:
                output.extend((f"trial_balance.{status}.debits: not found", f"trial_balance.{status}.credits: not found", f"trial_balance.{status}.difference: not found"))
                output.extend(f"account_balance.{status}.{account_type}: not found" for account_type in ACCOUNT_TYPES)
            elif "invalid" in totals:
                output.extend((f"trial_balance.{status}.debits: not found", f"trial_balance.{status}.credits: not found", f"trial_balance.{status}.difference: not found"))
                output.extend(f"account_balance.{status}.{account_type}: not found" for account_type in ACCOUNT_TYPES)
            else:
                output.append(f"trial_balance.{status}.debits: {decimal_text(totals['debit'])}")
                output.append(f"trial_balance.{status}.credits: {decimal_text(totals['credit'])}")
                output.append(f"trial_balance.{status}.difference: {decimal_text(totals['difference'])}")
                for account_type in ACCOUNT_TYPES:
                    output.append(f"account_balance.{status}.{account_type}: {decimal_text(totals['by_type'].get(account_type, Decimal('0')))}")
        account = _account_4427(connection, currency)
        if account is None:
            output.append("account.4427: not found")
        else:
            output.append(f"account.4427.type: {account['type']}")
            output.append(f"account.4427.posted_debits: {decimal_text(account['debit'])}")
            output.append(f"account.4427.posted_credits: {decimal_text(account['credit'])}")
            output.append(f"account.4427.posted_net_credit_minus_debit: {decimal_text(account['net'])}")
        descendants = _vat_4427_descendants(connection, currency)
        if descendants is None:
            output.append("account.4427_descendants.count: not found")
            output.extend(f"account.4427_descendants.type.{account_type}: not found" for account_type in (*ACCOUNT_TYPES, "other"))
            output.extend(("account.4427_descendants.posted_debits: not found", "account.4427_descendants.posted_credits: not found", "account.4427_descendants.posted_net_credit_minus_debit: not found"))
        else:
            output.append(f"account.4427_descendants.count: {descendants['count']}")
            for account_type in (*ACCOUNT_TYPES, "other"):
                output.append(f"account.4427_descendants.type.{account_type}: {descendants['types'][account_type]}")
            for key, label in (("debit", "posted_debits"), ("credit", "posted_credits"), ("net", "posted_net_credit_minus_debit")):
                value = descendants[key]
                output.append(f"account.4427_descendants.{label}: {decimal_text(value) if value is not None else 'not found'}")
        invoice_counts, unposted = _invoice_counts(connection, currency)
        if invoice_counts is None:
            output.append("invoices.status_kind_counts: not found")
        else:
            for (status, kind), count in sorted(invoice_counts.items()):
                output.append(f"invoices.status_kind_count status={status} kind={kind}: {count}")
            output.append("invoices.linked_entry_not_posted: " + _missing(unposted))
        precision_count = _precision_count(connection, currency)
        output.append("journal_lines.precision_over_2dp.count: " + _missing(precision_count))
        if currency is None:
            output.extend(_vat_return_lines(connection))
            output.extend(_period_lock_lines(connection))
    if not currencies_available:
        output.insert(0, "currencies: not found")
    return "\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Counts and aggregate totals from a read-only company database copy.")
    parser.add_argument("database_copy", type=Path, help="path to a COPY of the company database")
    parser.add_argument("--confirm-copy", action="store_true", required=True, help="confirm this is a copy, not the live database")
    args = parser.parse_args()
    try:
        connection = connect_read_only(args.database_copy)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"database: unable to open read-only ({type(exc).__name__})")
        return 2
    try:
        print(build_snapshot(connection), end="")
    except sqlite3.DatabaseError as exc:
        print(f"database: unreadable ({type(exc).__name__})")
        return 2
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
