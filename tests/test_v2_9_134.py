"""2.9.134: duplicate invoice identity (D3). All data is synthetic."""
import tempfile
import unittest
from pathlib import Path

from database import Database


def invoice(number, kind="sale", party="Synthetic customer A", subtype=None, **extra):
    base = {"invoice_number": number, "invoice_date": "05-01-2026", "party_name": party, "kind": kind, "currency": "USD",
            "subtotal": "100.00", "vat": "11.00", "total": "111.00", "status": "posted"}
    if subtype: base["doc_subtype"] = subtype
    base.update(extra)
    return base


class DuplicateInvoiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "books.db")
        self.db.initialize("Synthetic-Only-Password-2026!"); self.addCleanup(self.db.release)

    def test_second_sales_invoice_with_same_number_is_refused_even_for_another_customer(self):
        self.db.import_invoice(invoice("S-1"), 1)
        with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
            self.db.import_invoice(invoice("S-1"), 1)
        with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
            self.db.import_invoice(invoice("S-1", party="Synthetic customer B"), 1)
        self.assertEqual(len(self.db.list_invoices()), 1)  # nothing half-posted

    def test_number_comparison_ignores_separators_case_and_leading_zeros(self):
        self.db.import_invoice(invoice("INV-0045"), 1)
        for variant in ("inv45", "INV 45", "INV/045"):
            with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
                self.db.import_invoice(invoice(variant), 1)
        self.db.import_invoice(invoice("INV-0046"), 1)  # a different number is fine
        self.db.import_invoice(invoice("INV-450"), 1)   # 45 is not a substring match

    def test_purchase_identity_is_supplier_plus_number(self):
        self.db.import_invoice(invoice("P-9", kind="purchase", party="Synthetic supplier A"), 1)
        self.db.import_invoice(invoice("P-9", kind="purchase", party="Synthetic supplier B"), 1)  # another supplier: allowed
        with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
            self.db.import_invoice(invoice("P-9", kind="purchase", party="Synthetic supplier A"), 1)

    def test_credit_note_has_its_own_numbering_and_cancelled_documents_free_the_number(self):
        first = self.db.import_invoice(invoice("X-1"), 1)
        note = invoice("X-1", subtype="credit_note")  # a credit note may share the digits (its subtype is stored by the manual path)
        self.db.create_manual_invoice(note, [{"description": "Return", "quantity": 1, "unit_price": "10.00", "vat_rate": 11}], 1)
        self.db.cancel_invoice(first, "synthetic test", 1)
        self.db.import_invoice(invoice("X-1"), 1)  # the cancelled one no longer holds the number

    def test_admin_flag_allows_a_deliberate_duplicate_and_report_lists_it(self):
        self.db.import_invoice(invoice("D-1"), 1)
        self.db.import_invoice(invoice("D-1", allow_duplicate=True), 1)
        groups = self.db.duplicate_invoice_report()
        self.assertEqual([len(g) for g in groups], [2])

    def test_editing_to_an_existing_number_is_refused_but_editing_a_legacy_duplicate_is_not(self):
        first = self.db.import_invoice(invoice("E-1"), 1)
        second = self.db.import_invoice(invoice("E-2"), 1)
        edit = invoice("E-1", status="posted", debit="", credit="")
        with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
            self.db.update_invoice(second, edit, 1)
        legacy = self.db.import_invoice(invoice("L-1"), 1)
        twin = self.db.import_invoice(invoice("L-1", allow_duplicate=True), 1)
        self.db.update_invoice(twin, invoice("L-1", description="same number, amount untouched"), 1)  # identity unchanged: allowed
        self.assertNotEqual(legacy, twin)

    def test_replacing_an_invoice_with_its_own_number_is_not_a_duplicate(self):
        lines = [{"description": "Service", "quantity": 1, "unit_price": "100.00", "vat_rate": 11}]
        first = self.db.create_manual_invoice(invoice("R-1"), lines, 1)
        second = self.db.replace_manual_invoice(first, invoice("R-1"), [{**lines[0], "unit_price": "120.00"}], 1)
        self.assertNotEqual(first, second)
        self.assertEqual([r["invoice_number"] for r in self.db.list_invoices() if r["status"] != "deleted"], ["R-1"])
        with self.assertRaisesRegex(ValueError, "(?i)duplicate"):
            self.db.create_manual_invoice(invoice("R-1"), lines, 1)


class PasswordAndSessionTest(unittest.TestCase):
    """D7: versioned scrypt (N=2^17 by default), re-hash at the next sign-in, session tokens kept as hashes, 10-character minimum."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "books.db")
        self.db.initialize("Synthetic-Only-Password-2026!"); self.addCleanup(self.db.release)

    def test_hash_format_is_versioned_and_old_hashes_still_verify(self):
        import hashlib, os
        import database_common as common
        saved = os.environ.pop("NANZA_SCRYPT_LOG_N", None)
        try:
            new = common.hash_password("Synthetic-Pass-123")
            self.assertTrue(new.startswith("scrypt$17$8$1$"))
            self.assertTrue(common.verify_password("Synthetic-Pass-123", new)); self.assertFalse(common.verify_password("wrong", new))
            salt = bytes(range(16))
            legacy = f"{salt.hex()}:{hashlib.scrypt(b'Synthetic-Pass-123', salt=salt, n=2**14, r=8, p=1).hex()}"  # the pre-2.9.134 format
            self.assertTrue(common.verify_password("Synthetic-Pass-123", legacy)); self.assertFalse(common.verify_password("x", legacy))
            self.assertTrue(common.password_needs_rehash(legacy)); self.assertFalse(common.password_needs_rehash(new))
            self.assertFalse(common.verify_password("anything", "!"))  # a company-year copy of a user has no password
        finally:
            if saved is not None: os.environ["NANZA_SCRYPT_LOG_N"] = saved

    def test_legacy_hash_is_rewritten_at_sign_in_and_token_is_stored_hashed(self):
        import hashlib
        salt = bytes(range(16)); password = "Synthetic-Pass-123"
        legacy = f"{salt.hex()}:{hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"
        with self.db.connect() as c: c.execute("UPDATE users SET password_hash=? WHERE username='admin'", (legacy,))
        session = self.db.login("admin", password)
        self.assertTrue(session and session.get("token"))
        with self.db.connect() as c:
            stored = c.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()["password_hash"]
            tokens = [r["token"] for r in c.execute("SELECT token FROM sessions")]
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn(session["token"], tokens); self.assertTrue(all(t.startswith("h1:") for t in tokens))
        self.assertEqual(self.db.user_for_token(session["token"])["username"], "admin")
        self.assertIsNone(self.db.user_for_token("not-a-token"))
        self.assertIsNone(self.db.login("admin", "wrong-password"))

    def test_session_of_an_older_file_is_converted_once(self):
        with self.db.connect() as c:
            admin = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
            c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES('legacy-clear-token',?,?)", (admin, __import__("database_common").utcnow()))
            c.execute("UPDATE app_settings SET value='stale' WHERE key='startup_schema_version'")
        self.db.initialize_if_needed("Synthetic-Only-Password-2026!")
        self.assertEqual(self.db.user_for_token("legacy-clear-token")["username"], "admin")  # the signed-in program keeps working
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) n FROM sessions WHERE token='legacy-clear-token'").fetchone()["n"], 0)

    def test_new_passwords_need_ten_characters_but_existing_users_are_not_blocked(self):
        with self.assertRaisesRegex(ValueError, "10"):
            self.db.save_user({"username": "short.user", "role": "viewer", "password": "123456789"}, 1)
        self.db.save_user({"username": "long.user", "role": "viewer", "password": "1234567890"}, 1)
        self.assertTrue(self.db.login("long.user", "1234567890"))


class NotTaxableBenefitsTest(unittest.TestCase):
    """Payroll > Additional payments: every benefit line can be entered as taxable or as not taxable."""

    def test_each_benefit_line_has_both_treatments_and_the_exempt_one_stays_out_of_tax_and_nssf(self):
        import payroll_lines as PL
        import lebanese_payroll
        by_line = {}
        for code, (line, taxable, _recurring, _ar, _en) in PL.ALLOWANCES.items():
            if line >= 110: by_line.setdefault(line, set()).add(taxable)
        for line, kinds in by_line.items():
            self.assertEqual(kinds, {True, False}, f"R6 line {line} needs a taxable and a not-taxable entry")
        with tempfile.TemporaryDirectory() as folder:
            db = Database(str(Path(folder) / "c_2026.db")); db.initialize("StrongPass123")
            try:
                db.save_payroll_periods(lebanese_payroll.official_periods(), 1)
                emp = db.save_employee({"full_name": "Synthetic Emp", "employee_number": "9001", "currency": "LBP", "base_salary": "60000000",
                                        "hire_date": "01-01-2026", "mof_number": "11", "nssf_number": "22"}, 1)
                base = {"employee_id": emp["id"], "period_date": "31-01-2026"}
                plain = db.calculate_payroll(base)
                for taxable, exempt in (("housing", "housing_exempt"), ("car", "car_exempt"), ("health_insurance", "health_insurance_exempt")):
                    t = db.calculate_payroll({**base, "allowances": {taxable: "10000000"}})
                    e = db.calculate_payroll({**base, "allowances": {exempt: "10000000"}})
                    self.assertGreater(t["income_tax"], plain["income_tax"], taxable)
                    self.assertEqual(e["income_tax"], plain["income_tax"], exempt)            # not taxable: no extra tax
                    self.assertEqual(e["employee_nssf"], plain["employee_nssf"], exempt)      # and no NSSF base
                    self.assertEqual(e["allowances_taxable"], 0); self.assertEqual(e["allowances_total"], 10000000)
            finally:
                db.release()


if __name__ == "__main__":
    unittest.main()
