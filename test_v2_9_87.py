"""2.9.87: PDF uploads on every tab and bank reconciliation, checked as an accountant; program start and setup.
- bank statement in PDF (text or scan) with its running balance; same statement not doubled; an opening balance
  brought forward is not an outstanding deposit;
- purchase item lines with VAT Yes / No; sales PDF lines; expense account suggested; asset purchase booked;
- invoice number on its label line; supplier names (TECHZONE is not a 'zone'); customer of our own sales invoice;
- the background backup never upgrades the files; the data files wait for a busy writer; the program waits while
  the company files are prepared."""
import sqlite3
import tempfile
import threading
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import bank_rec
import pdf_import
from database import Database


def _statement_pdf(path, scanned=False):
    from reportlab.pdfgen import canvas
    page = canvas.Canvas(str(path)); page.setFont("Helvetica", 9)
    page.drawString(40, 800, "TEST BANK SAL - Statement of Account"); page.drawString(40, 785, "Currency: USD")
    xs = (40, 95, 150, 360, 430, 500)
    for x, h in zip(xs, ("Date", "Value Date", "Description", "Debit", "Credit", "Balance")): page.drawString(x, 760, h)
    rows = (("01/03/2025", "", "OPENING BALANCE", "", "", "10,000.00"), ("05/03/2025", "05/03/2025", "TRANSFER FROM CLIENT", "", "1,665.00", "11,665.00"),
            ("15/03/2025", "15/03/2025", "BANK CHARGES", "15.00", "", "11,650.00"), ("22/03/2025", "22/03/2025", "CHQ 100245 SUPPLIER", "2,220.00", "", "9,430.00"),
            ("28/03/2025", "28/03/2025", "INTEREST", "", "4.50", "9,434.50"), ("31/03/2025", "", "CLOSING BALANCE", "", "", "9,434.50"))
    for i, row in enumerate(rows):
        for x, value in zip(xs, row):
            (page.drawRightString(x + 55, 740 - i * 15, value) if x >= 360 and value else page.drawString(x, 740 - i * 15, value))
    page.save()


class BankStatementPdfTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.folder.cleanup)
        self.pdf = Path(self.folder.name) / "statement.pdf"; _statement_pdf(self.pdf)

    def test_rows_signs_and_balances(self):
        rows = bank_rec.read_statement_file(self.pdf)
        self.assertEqual([(r["date"], r["amount"]) for r in rows],
                         [("2025-03-05", Decimal("1665.00")), ("2025-03-15", Decimal("-15.00")), ("2025-03-22", Decimal("-2220.00")), ("2025-03-28", Decimal("4.50"))])
        self.assertEqual((rows.opening, rows.closing), (Decimal("10000.00"), Decimal("9434.50")))
        self.assertEqual(rows[2]["reference"], "100245")

    def test_reconciliation_to_zero_and_no_double_import(self):
        db = Database(Path(self.folder.name) / "b.db"); db.initialize("secret12345"); self.addCleanup(db.release)
        db.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"}, 1)
        voucher = lambda day, lines, kind="01": db.save_journal_voucher({"entry_date": day, "description": "T", "currency": "USD", "voucher_type": kind},
                                                                       [{"account_code": c, "line_currency": "USD", "side": s, "amount": a} for c, s, a in lines], 1)
        voucher("01-03-2025", [("512", "D", "10000"), ("101", "C", "10000")], "04")  # opening balance brought forward
        voucher("05-03-2025", [("512", "D", "1665"), ("4111", "C", "1665")]); voucher("20-03-2025", [("6263.1", "D", "2220"), ("512", "C", "2220")])
        rows = [{**r, "amount": str(r["amount"])} for r in bank_rec.read_statement_file(self.pdf)]
        self.assertEqual(bank_rec.add_statement_lines(db, "512", "USD", rows, 1), 4)
        self.assertEqual(bank_rec.add_statement_lines(db, "512", "USD", rows, 1), 0)  # the same statement again
        self.assertEqual(bank_rec.auto_match(db, "512", "USD", "2025-03-01", "2025-03-31"), 2)
        for line in bank_rec.statement_lines(db, "512", "2025-03-01", "2025-03-31"):
            if not line["journal_line_id"]: bank_rec.post_statement_line(db, line["id"], "6739" if Decimal(line["amount"]) < 0 else "773", 1)
        report = bank_rec.reconciliation(db, "512", "USD", "2025-03-01", "2025-03-31", "9434.50")
        self.assertEqual((report["book_balance"], report["difference"], report["matched"]), (9434.5, 0.0, 4))  # the opening is not an outstanding deposit


class ParserTest(unittest.TestCase):
    def setUp(self):
        pdf_import.set_own_company("Buyer Trading Co"); self.addCleanup(pdf_import.set_own_company)

    def test_labels_names_and_expense_account(self):
        text = ("Buyer Trading Co                      TAX INVOICE\nW38, Free Zone - Tel 1\nInvoice No: EC-2025-101\nDate: 15/03/2025\n"
                "Bill To: Hotel Client SAL\nCatering pack 10 120.00 1,200.00\nSubtotal 1,200.00\nVAT 11% 132.00\nTotal USD 1,332.00")
        parsed = pdf_import._parse_invoice_text("sale.pdf", text)
        self.assertEqual((parsed["invoice_number"], parsed["party_name"]), ("EC-2025-101", "Hotel Client SAL"))  # not "W38"; our own sale: the customer
        self.assertEqual(pdf_import._supplier_name("TECHZONE SARL      Invoice No: TZ-1\nDora Highway - Tel 01"), "TECHZONE SARL")
        self.assertEqual(pdf_import.suggest_expense_account("Office rent - March 2025"), "6263.1")
        self.assertEqual(pdf_import.suggest_expense_account("Spare parts"), "")


class PurchaseLinesVatTest(unittest.TestCase):
    def test_lines_without_vat_make_the_exempt_amount(self):
        from desktop_purchases import PurchasesMixin
        class Var:
            def __init__(self, value=""): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value
        rows = [{"name": "Spices", "quantity": 10, "unit_cost": 5, "total": 50.0, "vat_flag": "Yes"},
                {"name": "Rice", "quantity": 20, "unit_cost": 2, "total": 40.0, "vat_flag": "No"}]
        screen = types.SimpleNamespace(purchase_form={"items_sheet": types.SimpleNamespace(ordered=lambda: rows), "vars": {"taxable": Var(), "exempt": Var()}},
                                       purchase_amounts_changed=lambda key: None)
        PurchasesMixin.purchase_items_changed(screen)
        self.assertEqual((screen.purchase_form["vars"]["taxable"].get(), screen.purchase_form["vars"]["exempt"].get()), ("50.00", "40.00"))


class StartAndBackupTest(unittest.TestCase):
    def test_backup_never_upgrades_and_connections_wait(self):
        import backup_service
        from company_manager import CompanyManager
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        master = Database(Path(folder.name) / "m.db"); master.initialize("secret12345"); master.release()
        with mock.patch("backup_service.CompanyManager", wraps=CompanyManager) as manager:
            backup_service.backup_all(Path(folder.name) / "m.db")
        self.assertEqual(manager.call_args.kwargs.get("prepare"), False)
        self.assertFalse(CompanyManager(Path(folder.name) / "m.db", prepare=False).prepare)
        with master.connect() as db: self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_disk_io_error_on_wal_does_not_stop_the_start(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(folder.cleanup)
        db = Database(Path(folder.name) / "w.db")
        class Connection:
            calls = 0
            def execute(self, sql):
                if "journal_mode" in sql:
                    Connection.calls += 1; raise sqlite3.OperationalError("disk I/O error")
        with mock.patch("time.sleep"):
            self.assertFalse(db._set_wal(Connection()))  # the log of the user: PRAGMA journal_mode=WAL -> disk I/O error
        self.assertEqual(Connection.calls, 10)
        with self.assertRaises(sqlite3.OperationalError):
            db._set_wal(types.SimpleNamespace(execute=mock.Mock(side_effect=sqlite3.OperationalError("malformed"))))  # other errors still show

    def test_program_waits_while_files_are_prepared(self):
        import run_desktop
        ready = threading.Event(); worker = threading.Thread(target=lambda: (ready.wait(0.3), ready.set())); worker.start()
        timer = threading.Timer(6.0, ready.set); timer.start()  # the service answers after the 5-second first wait
        with mock.patch("run_desktop.tk.Tk", side_effect=RuntimeError("no display")):
            run_desktop._wait_for_service(ready, types.SimpleNamespace(is_alive=lambda: True))
        timer.cancel(); worker.join()
        self.assertTrue(ready.is_set())

    def test_installer_stops_the_backup_before_replacing_it(self):
        text = (Path(__file__).parent / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("function PrepareToInstall", text); self.assertIn("/F /IM SaberAccountingBackup.exe", text)


if __name__ == "__main__":
    unittest.main()
