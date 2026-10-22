"""Read-only, counts-only scan for stored monetary precision in a database copy."""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path


CENT = Decimal("0.01")


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, str] | None:
    try:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.DatabaseError:
        return None
    if not rows:
        return None
    return {str(row["name"]): str(row["type"] or "").upper() for row in rows}


def _decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() else None


def _has_subcent_digits(value: object) -> bool | None:
    amount = _decimal(value)
    if amount is None:
        return None
    return amount.as_tuple().exponent < -2


def _round_half_up(amount: Decimal) -> Decimal:
    parts = amount.as_tuple()
    precision = max(28, len(parts.digits) + max(0, -parts.exponent) + 3, amount.adjusted() + 4)
    with localcontext() as context:
        context.prec = precision
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _exact_sum(amounts: list[Decimal]) -> Decimal:
    if not amounts:
        return Decimal("0")
    integer_digits = max(1, max(amount.adjusted() + 1 for amount in amounts))
    precision = max(28, integer_digits + 2 + len(str(len(amounts))) + 2)
    with localcontext() as context:
        context.prec = precision
        return sum(amounts, Decimal("0"))


def _classify_currency(currency: object) -> str | None:
    code = str(currency or "").strip().upper()
    if code == "LBP":
        return "LBP"
    if code:
        return "non_LBP"
    return None


def _count_rows(connection: sqlite3.Connection, table: str) -> int | None:
    if _columns(connection, table) is None:
        return None
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def collect_counts(connection: sqlite3.Connection) -> tuple[dict[str, object], dict[str, str]]:
    counts: dict[str, object] = {}
    schema_types: dict[str, str] = {}

    line_columns = _columns(connection, "journal_lines")
    entry_columns = _columns(connection, "journal_entries")
    line_required = {"entry_id", "debit", "credit"}
    currency_available = bool(
        line_columns
        and ("line_currency" in line_columns or (entry_columns and "currency" in entry_columns))
    )
    if line_columns is None:
        counts["journal_lines.precision_over_2dp.LBP"] = "not found"
        counts["journal_lines.precision_over_2dp.non_LBP"] = "not found"
        counts["journal_lines.total"] = "not found"
        counts["posted_entries.unbalanced_after_line_rounding"] = "not found"
    else:
        for column in ("debit", "credit"):
            if column in line_columns:
                schema_types[f"journal_lines.{column}"] = line_columns[column]
        if not line_required.issubset(line_columns) or not currency_available:
            counts["journal_lines.precision_over_2dp.LBP"] = "not found"
            counts["journal_lines.precision_over_2dp.non_LBP"] = "not found"
        else:
            if "line_currency" in line_columns:
                currency_sql = "COALESCE(NULLIF(l.line_currency,''), e.currency)" if entry_columns and "currency" in entry_columns else "l.line_currency"
            else:
                currency_sql = "e.currency"
            join = "JOIN journal_entries e ON e.id=l.entry_id" if currency_sql.startswith("e.") or "e.currency" in currency_sql else ""
            rows = connection.execute(
                f"SELECT l.debit,l.credit,{currency_sql} AS currency FROM journal_lines l {join}"
            ).fetchall()
            precision = defaultdict(int)
            invalid = 0
            for row in rows:
                side_has_extra = False
                for column in ("debit", "credit"):
                    extra = _has_subcent_digits(row[column])
                    if extra is None:
                        invalid += 1
                    elif extra:
                        side_has_extra = True
                group = _classify_currency(row["currency"])
                if side_has_extra and group:
                    precision[group] += 1
            counts["journal_lines.precision_over_2dp.LBP"] = precision["LBP"]
            counts["journal_lines.precision_over_2dp.non_LBP"] = precision["non_LBP"]
            if invalid:
                counts["journal_lines.invalid_amount_values"] = invalid
        total_lines = _count_rows(connection, "journal_lines")
        counts["journal_lines.total"] = total_lines if total_lines is not None else "not found"

        if not line_required.issubset(line_columns) or not entry_columns or not {"id", "posting_status"}.issubset(entry_columns):
            counts["posted_entries.unbalanced_after_line_rounding"] = "not found"
            counts["posted_entries.unbalanced_before_rounding"] = "not found"
            counts["posted_entries.balanced_before_unbalanced_after_rounding"] = "not found"
        else:
            rows = connection.execute(
                "SELECT e.id AS entry_id,l.debit,l.credit FROM journal_entries e "
                "JOIN journal_lines l ON l.entry_id=e.id WHERE e.posting_status='posted'"
            ).fetchall()
            totals: dict[int, tuple[list[Decimal], list[Decimal], list[Decimal], list[Decimal]]] = {}
            invalid_entries: set[int] = set()
            for row in rows:
                entry_id = int(row["entry_id"])
                totals.setdefault(entry_id, ([], [], [], []))
                debit, credit = _decimal(row["debit"]), _decimal(row["credit"])
                if debit is None or credit is None:
                    invalid_entries.add(entry_id)
                    continue
                totals[entry_id][0].append(_round_half_up(debit))
                totals[entry_id][1].append(_round_half_up(credit))
                totals[entry_id][2].append(debit)
                totals[entry_id][3].append(credit)
            valid = {
                entry_id: values for entry_id, values in totals.items()
                if entry_id not in invalid_entries and values[0] and values[1]
            }
            unbalanced_before = sum(
                _exact_sum(debits) != _exact_sum(credits)
                for _rounded_debits, _rounded_credits, debits, credits in valid.values()
            )
            unbalanced_after = sum(
                _exact_sum(rounded_debits) != _exact_sum(rounded_credits)
                for rounded_debits, rounded_credits, _debits, _credits in valid.values()
            )
            balanced_before_unbalanced_after = sum(
                _exact_sum(debits) == _exact_sum(credits)
                and _exact_sum(rounded_debits) != _exact_sum(rounded_credits)
                for rounded_debits, rounded_credits, debits, credits in valid.values()
            )
            counts["posted_entries.unbalanced_after_line_rounding"] = unbalanced_after
            counts["posted_entries.unbalanced_before_rounding"] = unbalanced_before
            counts["posted_entries.balanced_before_unbalanced_after_rounding"] = balanced_before_unbalanced_after
            if invalid_entries:
                counts["posted_entries.invalid_amount_values"] = len(invalid_entries)

    entry_total = _count_rows(connection, "journal_entries")
    counts["journal_entries.total"] = entry_total if entry_total is not None else "not found"

    invoice_columns = _columns(connection, "invoices")
    if invoice_columns is None:
        counts["invoices.total.precision_over_2dp.LBP"] = "not found"
        counts["invoices.total.precision_over_2dp.non_LBP"] = "not found"
        counts["invoices.vat.precision_over_2dp.LBP"] = "not found"
        counts["invoices.vat.precision_over_2dp.non_LBP"] = "not found"
    else:
        for column in ("total", "vat"):
            if column in invoice_columns:
                schema_types[f"invoices.{column}"] = invoice_columns[column]
        for amount_column, label in (("total", "total"), ("vat", "vat")):
            if amount_column not in invoice_columns or "currency" not in invoice_columns:
                for group in ("LBP", "non_LBP"):
                    counts[f"invoices.{label}.precision_over_2dp.{group}"] = "not found"
                continue
            precision = defaultdict(int)
            invalid = 0
            for row in connection.execute(
                f'SELECT currency,"{amount_column}" AS amount FROM invoices'
            ):
                extra = _has_subcent_digits(row["amount"])
                group = _classify_currency(row["currency"])
                if extra is None:
                    invalid += 1
                elif extra and group:
                    precision[group] += 1
            for group in ("LBP", "non_LBP"):
                counts[f"invoices.{label}.precision_over_2dp.{group}"] = precision[group]
            if invalid:
                counts[f"invoices.{label}.invalid_amount_values"] = invalid

    return counts, schema_types


def diagnose(database_path: Path) -> int:
    try:
        connection = _connect_read_only(database_path)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"database: unable to open read-only ({type(exc).__name__})")
        return 2
    try:
        counts, schema_types = collect_counts(connection)
    except sqlite3.DatabaseError as exc:
        print(f"database: unreadable ({type(exc).__name__})")
        return 2
    finally:
        connection.close()

    print("database: opened read-only; path redacted")
    for key, value in counts.items():
        print(f"{key}: {value}")
    for key, value in schema_types.items():
        print(f"schema_type.{key}: {value or 'not declared'}")
    non_text = [key for key, value in schema_types.items() if value != "TEXT"]
    print("schema.non_text_amount_columns: " + (", ".join(sorted(non_text)) if non_text else "none"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Counts-only monetary precision scan. Use a verified COPY of a company database."
    )
    parser.add_argument("database_copy", type=Path, help="path to a COPY of the company SQLite database")
    parser.add_argument(
        "--confirm-copy", action="store_true", required=True,
        help="confirm the supplied database path is a COPY, not the live company database",
    )
    args = parser.parse_args()
    return diagnose(args.database_copy)


if __name__ == "__main__":
    raise SystemExit(main())
