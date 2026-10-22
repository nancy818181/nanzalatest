#!/usr/bin/env python3
"""Read-only 4427 chart-type diagnostic for a COPY of a Nanza company database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database_copy", type=Path, help="path to a COPY of a company SQLite database")
    args = parser.parse_args()
    database = args.database_copy.expanduser().resolve(strict=True)
    if not database.is_file():
        parser.error("database_copy must be a file")

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "nanza" / "accounting"))
    from lebanese_accounts import LEBANESE_ACCOUNTS

    seed_types = {str(row[0]): str(row[4]) for row in LEBANESE_ACCOUNTS}
    uri = database.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute("SELECT type FROM accounts WHERE code=?", ("4427",)).fetchone()
        # Only account codes/types are read; no names, parties, or balances are selected.
        stored = dict(connection.execute("SELECT code,type FROM accounts"))
        mismatch_count = sum(1 for code, expected in seed_types.items()
                             if code in stored and stored[code] != expected)
        print(f"4427 stored type: {row[0] if row else 'NOT FOUND'}")
        print(f"Accounts whose type differs from Lebanese seed: {mismatch_count}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
