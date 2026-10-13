"""2.9.94: the shared server on the office network, as it is really used: the server runs in its own program on all
network cards (0.0.0.0) with an office certificate (HTTPS), and three "PCs" (three separate programs) work on the same
company at the same time, with the approval step on. Then the server is stopped and started again."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from client import ApiClient

HERE = Path(__file__).resolve().parent

PC = r"""
import sys, json
sys.path.insert(0, sys.argv[1])
from client import ApiClient
url, user, password, company, action = sys.argv[2:7]
api = ApiClient(url); api.login(user, password); api.select_company_year(company, 2025)
done = []
if action == "work":
    party = api.save_party({"kind": "customer", "name": "Client of " + user, "currency": "USD", "account_category": "client"})
    for i in range(15):
        created = api.create_manual_invoice({"invoice_date": "%02d-04-2025" % (i % 28 + 1), "party_name": party["name"], "kind": "sales",
                                             "currency": "USD", "status": "posted"},
                                            [{"description": "Service", "quantity": 1, "unit_price": 200 + i, "vat_rate": 11}])
        done.append(created["invoice_id"])
        if i % 5 == 0:
            api.add_payment({"kind": "customer_receipt", "party_id": party["id"], "payment_date": "%02d-04-2025" % (i % 28 + 1),
                             "currency": "USD", "amount": "100", "cash_account": "531", "payment_method": "Cash"})
else:
    drafts = [i["id"] for i in api.invoices() if i.get("status") == "review"]
    done = api.approve_invoices(drafts)["approved"]
print(json.dumps(done))
"""


def _lan_address():
    """This computer's address on the network (falls back to 127.0.0.1 when there is no network card)."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); probe.connect(("10.255.255.255", 1))
        address = probe.getsockname()[0]; probe.close()
        return address if not address.startswith("127.") else "127.0.0.1"
    except OSError:
        return "127.0.0.1"


class OfficeNetworkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("cryptography is needed to make the office certificate")
        import office_tls
        cls.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(cls.folder.name)
        cls.address = _lan_address()
        cls.cert, cls.key = office_tls.make_certificate(root / "server", ["localhost", "127.0.0.1", cls.address])
        probe = socket.socket(); probe.bind(("0.0.0.0", 0)); cls.port = probe.getsockname()[1]; probe.close()
        cls.database = root / "server" / "saber.db"
        cls.env = {**os.environ, "SABER_DATA_DIR": str(root / "server")}
        cls.url = f"https://{cls.address}:{cls.port}"
        cls.old_cert = os.environ.get("SABER_SERVER_CERT"); os.environ["SABER_SERVER_CERT"] = str(cls.cert)
        cls.pc_env = {**os.environ, "SABER_DATA_DIR": str(root / "pc"), "SABER_SERVER_CERT": str(cls.cert)}
        cls.start_server()
        admin = ApiClient(cls.url); admin.login("admin", "Admin-2025!")
        cls.company = admin.create_company({"name": "Office Co", "year": 2025, "main_currency_1": "USD", "main_currency_2": "LBP"})
        admin.select_company_year(cls.company["id"], 2025)
        admin.save_exchange_rate({"date_from": "01-01-2025", "date_to": "31-12-2025", "from_currency": "USD", "to_currency": "LBP", "rate": "89500"})
        admin.save_user({"username": "rita", "password": "Rita-2025!", "role": "accountant", "language": "en", "permissions": {"payroll": True, "vat": True}})
        for name in ("omar", "lina"):
            admin.save_user({"username": name, "password": f"{name.title()}-2025!", "role": "accountant", "language": "en", "permissions": {"approve": True}})
        admin.save_accounting_setup({"approval_required": True})
        cls.admin = admin

    @classmethod
    def start_server(cls):
        cls.server = subprocess.Popen([sys.executable, str(HERE / "run_server.py"), "--host", "0.0.0.0", "--port", str(cls.port), "--database", str(cls.database),
                                       "--admin-password", "Admin-2025!", "--tls-cert", str(cls.cert), "--tls-key", str(cls.key)],
                                      cwd=str(HERE), env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        urls = [cls.url] + ([f"https://127.0.0.1:{cls.port}"] if cls.address != "127.0.0.1" else [])
        for attempt in range(600):
            for url in urls if attempt > 40 else urls[:1]:  # some cloud machines block their own network address: then 127.0.0.1
                try: ApiClient(url).login("admin", "Admin-2025!"); cls.url = url; return
                except Exception: pass
            if cls.server.poll() is not None: raise RuntimeError("server stopped: " + cls.server.stderr.read()[-1500:])
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(30)
        except subprocess.TimeoutExpired: cls.server.kill(); cls.server.wait(30)
        cls.server.stderr.close()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        if cls.old_cert is None: os.environ.pop("SABER_SERVER_CERT", None)
        else: os.environ["SABER_SERVER_CERT"] = cls.old_cert
        import gc; gc.collect(); cls.folder.cleanup()

    def run_pcs(self, jobs):
        programs = [subprocess.Popen([sys.executable, "-c", PC, str(HERE), self.url, user, password, str(self.company["id"]), action],
                                     cwd=str(HERE), env=self.pc_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for user, password, action in jobs]
        results = []
        for program in programs:
            out, err = program.communicate(timeout=600)
            self.assertEqual(program.returncode, 0, err[-1500:])
            import json; results.append(json.loads(out.strip().splitlines()[-1]))
        return results

    def test_1_the_network_is_protected(self):
        import http.client, ssl
        plain = http.client.HTTPConnection(self.address, self.port, timeout=10)
        with self.assertRaises((OSError, http.client.HTTPException)):  # plain HTTP is not answered on the HTTPS port
            plain.request("GET", "/api/health"); plain.getresponse().read()
        plain.close()
        stranger = http.client.HTTPSConnection(self.address, self.port, timeout=10, context=ssl.create_default_context())
        with self.assertRaises(ssl.SSLError):  # a PC without the office certificate does not trust the server
            stranger.request("GET", "/api/health"); stranger.getresponse().read()
        stranger.close()
        with self.assertRaises(Exception): ApiClient(self.url).login("admin", "wrong-password")

    def test_2_three_pcs_at_the_same_time_with_approval(self):
        rita, omar, lina = self.run_pcs([("rita", "Rita-2025!", "work"), ("omar", "Omar-2025!", "work"), ("lina", "Lina-2025!", "work")])
        self.assertEqual((len(rita), len(omar), len(lina)), (15, 15, 15))
        invoices = [i for i in self.admin.invoices() if i["kind"] == "sale"]
        self.assertEqual(len(invoices), 45)
        self.assertEqual(len({i["invoice_number"] for i in invoices}), 45)  # no number given twice
        self.assertEqual(sorted(i["id"] for i in invoices if i["status"] == "review"), sorted(rita))  # rita's wait for approval
        (approved,) = self.run_pcs([("omar", "Omar-2025!", "approve")])
        self.assertEqual(sorted(approved), sorted(i["invoice_number"] for i in invoices if i["id"] in rita))  # the approval lists invoice numbers
        self.assertTrue(all(i["status"] == "posted" for i in self.admin.invoices() if i["kind"] == "sale"))
        trail = self.admin.audit_log(entity="invoice", action="approve")["items"]
        self.assertEqual(len(trail), 15); self.assertTrue(all(t["username"] == "omar" for t in trail))
        rows = self.admin.trial_balance(to_date="31-12-2025")
        self.assertLess(abs(sum(Decimal(str(r.get("debit") or 0)) - Decimal(str(r.get("credit") or 0)) for r in rows)), Decimal("0.01"))
        sales = sum(Decimal(str(r.get("credit") or 0)) - Decimal(str(r.get("debit") or 0)) for r in rows if str(r.get("code", "")).startswith("7"))
        self.assertEqual(sales.quantize(Decimal("0.01")), Decimal(3 * sum(200 + i for i in range(15))).quantize(Decimal("0.01")))  # 3 x 3,105 USD

    def test_3_server_stopped_and_started_again(self):
        before = len(self.admin.invoices())
        self.stop_server()
        with self.assertRaises(Exception): ApiClient(self.url).login("admin", "Admin-2025!")  # clear error while the server is off
        type(self).start_server()
        def signed_in(user, password):  # each PC signs in again after the restart (a fresh connection; retried while the server warms up)
            for attempt in range(40):
                try:
                    api = ApiClient(type(self).url); api.login(user, password); api.select_company_year(self.company["id"], 2025); return api
                except Exception:
                    if attempt == 39: raise
                    time.sleep(0.25)
        again = signed_in("lina", "Lina-2025!")
        self.assertEqual(len(again.invoices()), before)  # nothing lost
        type(self).admin = signed_in("admin", "Admin-2025!")


class SplitAndLookTest(unittest.TestCase):
    def test_split_files_keep_every_name(self):
        import inventory, inventory_reports
        for name in inventory._REPORT_NAMES: self.assertIs(getattr(inventory, name), getattr(inventory_reports, name))
        from inventory import build_report  # old imports keep working
        self.assertIs(build_report, inventory_reports.build_report)
        try:
            import desktop_invoices, desktop_sales_invoice
        except ImportError as exc: self.skipTest(f"tkinter not available: {exc}")
        self.assertTrue(issubclass(desktop_invoices.InvoicesMixin, desktop_sales_invoice.SalesInvoiceMixin))
        self.assertTrue(hasattr(desktop_invoices.InvoicesMixin, "save_sales_invoice"))

    def test_striped_rows(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            import desktop_theme
            root = tk.Tk()
        except Exception as exc: self.skipTest(f"no screen: {exc}")
        try:
            desktop_theme.apply_theme(root)
            tree = ttk.Treeview(root, columns=("a",))
            for i in range(5): tree.insert("", "end", iid=str(i), values=(i,), tags=("deleted",) if i == 3 else ())
            desktop_theme.restripe(tree)
            self.assertEqual([("stripe" in tree.item(str(i), "tags")) for i in range(5)], [False, True, False, True, False])
            self.assertIn("deleted", tree.item("3", "tags"))  # the row's own colour is kept
        finally: root.destroy()


if __name__ == "__main__":
    unittest.main()
