"""CURRENT BEHAVIOR, NOT VERIFIED CORRECT: VAT child type/report presentation."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import nanza_paths  # noqa: F401 - configure application module imports without Tk
from database import Database
import vat_ledgers


class VatChildAccountsCharacterizationTest(unittest.TestCase):
    def test_sales_vat_child_balance_across_three_account_type_states(self):
        with tempfile.TemporaryDirectory(prefix="nanza-vat-child-characterization-") as folder:
            db = Database(Path(folder) / "synthetic-vat-child.db")
            db.initialize("Synthetic-Only-Test-Password-2026")
            try:
                vat_ledgers.save_settings(db, {"enabled": True})
                invoice_id = db.import_invoice(
                    {
                        "invoice_number": "SYN-VAT-CHILD-1",
                        "invoice_date": "10-03-2026",
                        "party_name": "Synthetic customer only",
                        "kind": "sale",
                        "currency": "USD",
                        "subtotal": "100.00",
                        "vat": "11.00",
                        "total": "111.00",
                        "status": "posted",
                    },
                    1,
                )
                with db.connect() as connection:
                    invoice = connection.execute(
                        "SELECT vat_account FROM invoices WHERE id=?", (invoice_id,)
                    ).fetchone()
                    vat_account = invoice["vat_account"]
                    entry_line = connection.execute(
                        """SELECT a.type,j.credit FROM journal_lines j
                        JOIN journal_entries e ON e.id=j.entry_id
                        JOIN accounts a ON a.id=j.account_id
                        WHERE e.source_type='invoice' AND e.source_id=? AND a.code=?""",
                        (invoice_id, vat_account),
                    ).fetchone()
                self.assertTrue(vat_account.startswith("4427"))
                self.assertEqual(Decimal(entry_line["credit"]), Decimal("11.00"))

                states = []

                def capture(label):
                    rows = db.balance_sheet(to_date="2026-03-10", currency="USD")
                    row = next(item for item in rows if item["code"] == vat_account)
                    record = (label, row["type"], Decimal(str(row["balance"])))
                    states.append(record)
                    print(
                        f"CURRENT BEHAVIOR, NOT VERIFIED CORRECT: {label}; "
                        f"account_code={vat_account}; section={record[1]}; signed_balance={record[2]}"
                    )

                capture("current types")
                with db.connect() as connection:
                    connection.execute("UPDATE accounts SET type='liability' WHERE code='4427'")
                capture("after 4427-only liability change")
                with db.connect() as connection:
                    connection.execute(
                        "UPDATE accounts SET type='liability' WHERE substr(code,1,4)='4427'"
                    )
                capture("after 4427 and descendants liability change")

                self.assertEqual(
                    states,
                    [
                        # 2.9.133 (RPT-BS-001 / F-01): output-VAT accounts are seeded as liability, so the
                        # sub-account is a liability in every state. The pre-2.9.133 pinned values were
                        # asset / asset / liability; the signed balance (-11.0) is unchanged.
                        ("current types", "liability", Decimal("-11.0")),
                        ("after 4427-only liability change", "liability", Decimal("-11.0")),
                        ("after 4427 and descendants liability change", "liability", Decimal("-11.0")),
                    ],
                )
            finally:
                db.release()


if __name__ == "__main__":
    unittest.main()
