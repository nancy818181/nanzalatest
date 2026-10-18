"""Machine-readable control checks for company books."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import audit_chain
import inventory


def build(database, as_of=None):
    as_of = as_of or date.today().isoformat()
    checks = []
    integrity = audit_chain.verify(database)
    checks.append({"id": "audit_chain", "status": "passed" if integrity["ok"] else "failed",
                   "message": integrity["message"], "details": integrity})

    unbalanced = database.unbalanced_entries()
    checks.append({"id": "journal_balance", "status": "passed" if not unbalanced else "failed",
                   "message": "All journal entries balance" if not unbalanced else "Unbalanced journal entries found",
                   "details": {"count": len(unbalanced), "entries": unbalanced[:100]}})

    stock = inventory.stock_ledger_check(database, as_of)
    difference = Decimal(str(stock["difference"] or 0))
    checks.append({"id": "stock_to_gl", "status": "passed" if abs(difference) < Decimal("0.01") else "warning",
                   "message": "Stock valuation agrees with the general ledger" if abs(difference) < Decimal("0.01")
                              else "Stock valuation differs from the general ledger",
                   "details": {"date": stock["date"], "currency": stock["currency"],
                               "valuation": stock["valuation"], "ledger": stock["ledger"],
                               "difference": difference, "posted": stock["posted"]}})

    lock = database.books_lock()
    checks.append({"id": "books_lock", "status": "info",
                   "message": (f"Books locked through {lock['display']}" if lock["locked_until"]
                               else "No books lock is set"),
                   "details": lock})

    statuses = {check["status"] for check in checks}
    overall = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
    return {"status": overall, "as_of": as_of, "checks": checks}
