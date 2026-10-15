from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
if str(_Path(__file__).resolve().parents[2]) not in _sys.path: _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
import nanza_paths  # noqa: E402,F401  2.9.117: run directly (python nanza/core/server.py) the other folders are found too
import argparse
import os
import secrets
import socket
import ssl
import base64
import json
import traceback
import sqlite3
import threading
import tempfile
import hmac
import logging
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from database import Database, iso_date


def _account_codes(value, key=""):
    """2.9.79: the screens show every account as 'number - name'; what is saved is the number alone.
    Any field named ...account / ...account_code / account_from / account_to keeps only the number."""
    if isinstance(value, dict): return {k: _account_codes(v, str(k)) for k, v in value.items()}
    if isinstance(value, list): return [_account_codes(v, key) for v in value]
    if isinstance(value, str) and " - " in value and key.endswith(("account", "account_code", "account_from", "account_to")):
        code = value.split(" - ", 1)[0].strip()
        if code and code.replace(".", "").isdigit(): return code
    return value
from company_manager import CompanyManager
from payroll_reports import build_payroll_report, json_ready as payroll_json
import ledger_reports
import inventory
import fixed_assets
import vat_return
import accounting_setup
import payroll_extras
import management_pack

MAX_REQUEST_BODY_BYTES = 22 * 1024 * 1024
log = logging.getLogger("saber.server")
KEY_HEADER = "X-Saber-Key"


def _json_value(value):
    """2.9.61: a value json cannot write (Decimal, date, bytes saved by an older import ...) no longer fails the whole
    request with 'The data service could not complete the request'."""
    from decimal import Decimal as _Decimal
    from datetime import date as _date, datetime as _datetime
    if isinstance(value, _Decimal): return str(value)
    if isinstance(value, (_datetime, _date)): return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)): return None
    if isinstance(value, (set, frozenset, tuple)): return list(value)
    return str(value)

# 2.9.103: every request that only the administrator may make, in one place (checked before the request is handled).
# A new administrator-only request is added here; a test fails when a request checks "admin" itself without being listed.
ADMIN_ONLY = {
    "GET": {"/api/users", "/api/audit-log", "/api/audit-report", "/api/audit-verify", "/api/renumber"},
    "POST": {"/api/companies", "/api/companies/import", "/api/companies/year", "/api/accounting-setup", "/api/tax-adviser", "/api/vat-ledgers", "/api/vat-ledgers/create",
             "/api/vat-return/reopen", "/api/users", "/api/books-lock", "/api/backups/restore", "/api/settings", "/api/currencies",
             "/api/payroll/delete-period", "/api/payroll/apply-lebanese-rules", "/api/payroll/periods", "/api/payroll/settings",
             "/api/fiscal-years/close", "/api/fiscal-years/delete", "/api/fiscal-years/reopen", "/api/fiscal-years/refresh-opening",
             "/api/renumber", "/api/accounts/import", "/api/numbering", "/api/onboarding/import"},
    "PUT": {"/api/companies/*"},
    "DELETE": {"/api/opening-vouchers/*"},
}


def admin_only(method, path):
    for rule in ADMIN_ONLY.get(method, ()):
        if path == rule or (rule.endswith("/*") and path.startswith(rule[:-1])): return True
    return False



# 2.9.105: the ~150 "except Exception as exc: return 400 + message" blocks no longer hide program errors. A refusal the
# user caused (a wrong value, a missing permission, a duplicate, a locked period) is an expected error and is only answered;
# anything else (a bug: TypeError, AttributeError, a database error...) is also written to the log with its traceback, so
# it can be found and fixed instead of looking like an ordinary refusal.
EXPECTED_ERRORS = (ValueError, PermissionError, KeyError, LookupError, FileNotFoundError)


def _log_unexpected(path, status):
    exc = sys.exc_info()[1]
    if exc is None or isinstance(exc, EXPECTED_ERRORS): return
    import sqlite3
    if isinstance(exc, sqlite3.IntegrityError): return  # a duplicate / constraint refusal
    log.error("Unexpected error answered with %s on %s", status, path, exc_info=exc)

class ApiHandler(BaseHTTPRequestHandler):
    db: Database = None
    master_db: Database = None
    company_manager: CompanyManager = None
    # Set for the private data service inside the desktop program: every request must carry it.
    local_key: str | None = None

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def _key_refused(self):
        if not self.local_key: return False
        given = self.headers.get(KEY_HEADER, "")
        if given and hmac.compare_digest(given.encode("utf-8"), self.local_key.encode("utf-8")): return False
        self.close_connection = True
        self._json(403, {"error": "This data service only answers Nanza Accounting on this computer"})
        return True

    # HTTP/1.1 lets the desktop program keep one connection open and reuse it for every
    # request, instead of opening a new TCP connection (and a new server thread) each time.
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        # Send each small answer at once (no Nagle / delayed-ACK wait on a kept-open connection).
        try: self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError): pass

    def _json(self, status, body):
        if status >= 400: _log_unexpected(self.path, status)  # 2.9.105
        data = json.dumps(body, ensure_ascii=False, default=_json_value).encode("utf-8")
        self._responded = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        raw = getattr(self, "_raw_body", None)
        if raw is None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length > 0 else b""; self._raw_body = raw
        return _account_codes(json.loads(raw or b"{}"))

    def _user(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        # Backups are made when the user asks (and automatically before a restore or an import that replaces data),
        # not every time the program is opened.
        return self.master_db.user_for_token(token)

    def _query(self, parsed, name, default=None):
        return parse_qs(parsed.query).get(name, [default])[0]

    def _module_denied(self, user, path):
        """Module permissions: payroll (salaries) and VAT can be granted per user."""
        module = "payroll" if path.startswith(("/api/employees", "/api/payroll")) else "vat" if path.startswith(("/api/vat", "/api/vat-")) else None
        if module and not self.master_db.user_can(user, module):
            self._json(403, {"error": f"You do not have permission to use {module.upper() if module=='vat' else module.title()}. Ask the administrator."})
            return True
        return False

    def _previous_year_db(self, year):
        try:
            company_id = self.headers.get("X-Company-ID")
            return self.company_manager.database(company_id, int(year) - 1) if company_id else None
        except Exception:
            return None

    def _year_db(self, year):
        """2.9.52: the books of another fiscal year of the selected company (each year has its own file);
        the current file when that year is kept in it (or not set up separately)."""
        try:
            company_id = self.headers.get("X-Company-ID")
            other = self.company_manager.database(company_id, int(year)) if company_id else None
        except Exception:
            other = None
        return other or self.db

    def _select_database(self):
        if not self.headers.get("X-Company-ID") and not self.company_manager.list_companies(True):
            self.db = self.master_db; return True  # 2.9.74: new installation, no company created yet
        try:
            self.db=self.company_manager.database(self.headers.get("X-Company-ID"),self.headers.get("X-Fiscal-Year"))
            # 2.9.52: users are kept in the main file; the company-year file needs the same user row so that what a
            # non-administrator saves can record who made it (it used to fail with "FOREIGN KEY constraint failed").
            try:
                user = self._user()
                if user and self.db is not self.master_db: self.db.ensure_user_row(user)
            except Exception: log.warning("User row not copied to the company file", exc_info=True)
            return True
        except (KeyError, ValueError) as exc:
            self._json(400,{"error":str(exc).strip("'\"")})
            return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            return self._json(200, {"status": "ok", "application": "Saber Accounting"})
        if path == "/api/licence":  # 2.9.103: Installation ID and licence state (shown on the sign-in screen)
            import licence
            with self.master_db.connect() as connection: return self._json(200,licence.status(connection))
        user = self._user()
        if not user:
            return self._json(401, {"error": "Unauthorized"})
        if admin_only("GET", path) and user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})  # 2.9.103
        if path == "/api/companies": return self._json(200,{"items":self.company_manager.list_companies(user["role"]=="admin")})
        if not self._select_database(): return
        if self._module_denied(user, path): return
        if path in ("/api/backups/download","/api/backups/folder","/api/backups") and user["role"]=="viewer":
            return self._json(403,{"error":"Backup access is not available for viewer accounts"})
        if path == "/api/me":
            info={k:user[k] for k in ("id","username","role","language","expires_at")}; info["permissions"]={m:self.master_db.user_can(user,m) for m in ("payroll","vat","delete")}
            import licence
            with self.master_db.connect() as connection: info["licence"]=licence.status(connection)
            return self._json(200,info)
        if path in ("/api/payroll/eos-provision","/api/payroll/leave","/api/payroll/leave-balances","/api/payroll/payslips"):  # 2.9.82
            try:
                if path.endswith("eos-provision"):
                    result=payroll_extras.eos_provision(self.db,self._query(parsed,"date")); result["sections"]=payroll_extras.eos_sections(result)
                    return self._json(200,ledger_reports.json_ready(result))
                if path.endswith("leave"): return self._json(200,{"items":payroll_extras.list_leave(self.db,self._query(parsed,"year"))})
                if path.endswith("leave-balances"):
                    result=payroll_extras.leave_balances(self.db,self._query(parsed,"date")); result["sections"]=payroll_extras.leave_sections(result)
                    return self._json(200,ledger_reports.json_ready(result))
                return self._json(200,{"sections":ledger_reports.json_ready(payroll_extras.payslip_sections(self.db,self._query(parsed,"month_end")))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/management-pack":  # 2.9.82
            try:
                month_end=self._query(parsed,"month_end"); year=int(iso_date(month_end)[:4])
                return self._json(200,ledger_reports.json_ready(management_pack.build(self.db,month_end,self._query(parsed,"currency","USD"),self._previous_year_db(year))))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/budget-alerts":  # 2.9.82
            try: return self._json(200,{"items":management_pack.budget_variances(self.db,self._query(parsed,"year"),self._query(parsed,"month"),
                                        self._query(parsed,"currency","USD"),self._query(parsed,"threshold","10"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounting-setup":  # 2.9.81: what the company / this user hides, the default posting accounts
            try: return self._json(200,accounting_setup.setup(self.db,self.master_db,user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/vat-ledgers":  # 2.9.97: VAT account per customer / supplier
            import vat_ledgers
            return self._json(200,vat_ledgers.settings(self.db))
        if path == "/api/vat-ledgers/test":
            import vat_ledgers
            return self._json(200,vat_ledgers.test_vat_accounts(self.db))
        if path == "/api/books-check":  # 2.9.119: Books Health Check (read only)
            import books_check
            try:
                year=self._query(parsed,"year") or getattr(self.db,"fiscal_year",None)
                check=books_check.run(self.db,int(year) if year else None,self._query(parsed,"quick")=="1"); check["sections"]=books_check.sections(check)
                return self._json(200,check)
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/year-end-check":  # 2.9.81: the checks before closing a year
            try:
                year=int(self._query(parsed,"year")); check=accounting_setup.year_end_check(self.db,year,self._previous_year_db(year))
                check["sections"]=accounting_setup.year_end_sections(check)
                return self._json(200,check)
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/invoices/account-check":  # 2.9.77: sales booked on wrong accounts by earlier versions
            try: return self._json(200,{"items":self.db.sales_account_problems()})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/asset-categories": return self._json(200,{"items":fixed_assets.list_categories(self.db)})
        if path == "/api/asset-depreciation":
            try: return self._json(200,ledger_reports.json_ready(fixed_assets.monthly_table(self.db,self._query(parsed,"month"),self._query(parsed,"account") or None)))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fixed-assets":
            return self._json(200,{"items":fixed_assets.list_assets(self.db)})
        if path.startswith("/api/fixed-assets/") and path.endswith("/attachments"):
            try: return self._json(200,{"items":fixed_assets.list_attachments(self.db,int(path.split("/")[-2]))})
            except KeyError: return self._json(404,{"error":"Asset not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/fixed-asset-attachments/"):
            try:
                attachment=fixed_assets.get_attachment(self.db,int(path.rsplit("/",1)[-1]))
                attachment["content"]=base64.b64encode(attachment["content"]).decode("ascii")
                return self._json(200,attachment)
            except KeyError: return self._json(404,{"error":"Asset attachment not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fixed-assets/rollforward":
            try: return self._json(200,fixed_assets.rollforward(self.db,self._query(parsed,"year","")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/fixed-assets/") and path.endswith("/schedule"):
            try: return self._json(200,{"items":fixed_assets.schedule(self.db,int(path.split("/")[-2]))})
            except KeyError: return self._json(404,{"error":"Asset not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/reports":
            try:
                result=build_payroll_report(self.db,self._query(parsed,"report","R10"),self._query(parsed,"period_type","quarterly"),
                    self._query(parsed,"year"),self._query(parsed,"index","1"),self._query(parsed,"group","both"),
                    self._query(parsed,"include_drafts","false").lower()=="true")
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,payroll_json(result))
        if path == "/api/payroll/nssf-filed":
            try: return self._json(200,{"items":self.db.nssf_filed_wages(self._query(parsed,"year",""))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/reports/accounts":
            try:
                options=json.loads(self._query(parsed,"options","{}") or "{}")
                books=self.db
                if str(options.get("view_year") or "").strip():  # 2.9.109: read another fiscal year of the company (read only)
                    view_year=int(options["view_year"]); books=self._year_db(view_year)
                    if books is self.db and str(view_year)!=str(self.headers.get("X-Fiscal-Year") or ""):
                        return self._json(400,{"error":f"There are no books for {view_year} in this company"})
                with books.connect() as connection:
                    department_id,project_id=books._dimension_ids(connection,{"department":options.get("department"),"project":options.get("project")})
                    # 2.9.62: several departments / projects ticked (codes); the budget needs exactly one
                    for key,table in (("departments","department"),("projects","project")):
                        codes=[c for c in (options.get(key) or []) if str(c).strip()]
                        if codes: options[f"{table}_ids"]=[books._dimension_ids(connection,{table:code})[0 if table=="department" else 1] for code in codes]
                if len(options.get("department_ids") or [])==1: department_id=options["department_ids"][0]
                if len(options.get("project_ids") or [])==1: project_id=options["project_ids"][0]
                options["department_id"]=department_id; options["project_id"]=project_id
                return self._json(200,ledger_reports.json_ready(ledger_reports.build_account_report(books,options)))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/documents/next-number":
            try: return self._json(200,{"number":self.db.next_document_number(self._query(parsed,"kind"),self._query(parsed,"date"),self._query(parsed,"branch"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/expenses/") and path.endswith("/attachments"):
            try: return self._json(200,{"items":self.db.list_expense_attachments(int(path.split("/")[-2]))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/expense-attachments/"):
            try:
                attachment=self.db.get_expense_attachment(int(path.rsplit("/",1)[-1])); attachment["content"]=base64.b64encode(attachment["content"]).decode("ascii")
            except KeyError: return self._json(404,{"error":"Attachment not found"})
            return self._json(200,attachment)
        if path.startswith("/api/invoices/") and path.endswith("/landed-costs"):
            try: return self._json(200,{"items":self.db.landed_costs(int(path.split("/")[-2]))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fiscal-years/closing-preview":
            try:
                import year_end
                data=year_end.closing_preview(self.db,int(self._query(parsed,"year")))
                return self._json(200,{c:{"lines":[[code,float(a),float(l),float(u),name] for code,a,l,u,name in v["lines"]],"net_result":float(v["net_result"])} for c,v in data.items()})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/production/"):  # 2.9.65
            import production
            try:
                if path == "/api/production/recipes": return self._json(200,{"items":production.list_boms(self.db)})
                if path == "/api/production/recipe": return self._json(200,production.get_bom(self.db,self._query(parsed,"item","")))
                if path == "/api/production/plan": return self._json(200,production.plan(self.db,self._query(parsed,"item",""),self._query(parsed,"quantity",
                        "0"),self._query(parsed,"warehouse"),self._query(parsed,"date")))
                if path == "/api/production/orders": return self._json(200,{"items":production.list_orders(self.db)})
                if path.startswith("/api/production/orders/"): return self._json(200,production.get_order(self.db,int(path.rsplit("/",1)[-1])))
                if path == "/api/production/report": return self._json(200,ledger_reports.json_ready(production.report(self.db,self._query(parsed,"from"),self._query(parsed,"to"))))
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/inventory/"):
            try:
                if path == "/api/inventory/items": return self._json(200,{"items":inventory.list_items(self.db,self._query(parsed,"date"))})
                if path == "/api/inventory/warehouses": return self._json(200,{"items":inventory.list_warehouses(self.db)})
                if path == "/api/inventory/settings": return self._json(200,inventory.settings(self.db))
                if path == "/api/inventory/documents": return self._json(200,{"items":inventory.list_documents(self.db)})
                if path.startswith("/api/inventory/documents/"): return self._json(200,inventory.get_document(self.db,int(path.rsplit("/",1)[-1])))
                if path == "/api/inventory/next-number": return self._json(200,{"number":inventory.next_number(self.db,self._query(parsed,"type"),self._query(parsed,"date"))})
                if path == "/api/inventory/categories": return self._json(200,inventory.list_categories(self.db))
                if path == "/api/inventory/brands": return self._json(200,{"items":inventory.brands(self.db)})
                if path == "/api/inventory/similar": return self._json(200,{"items":inventory.similar_items(self.db,self._query(parsed,"name",""))})
                if path == "/api/inventory/count-sheet": return self._json(200,{"items":inventory.count_sheet(self.db,self._query(parsed,"warehouse_id"),self._query(parsed,"date"))})
                if path == "/api/inventory/counts": return self._json(200,{"items":inventory.list_counts(self.db)})
                if path.startswith("/api/inventory/counts/"): return self._json(200,inventory.get_count(self.db,int(path.rsplit("/",1)[-1])))
                if path == "/api/inventory/report":
                    result=inventory.build_report(self.db,self._query(parsed,"report"),json.loads(self._query(parsed,"options","{}") or "{}"))
                    return self._json(200,ledger_reports.json_ready(result))
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/parties/") and path.endswith("/open-documents"):
            try: return self._json(200,{"items":self.db.open_documents(int(path.split("/")[-2]))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/payments/") and path.endswith("/allocations"):
            try: return self._json(200,{"items":self.db.payment_allocations(int(path.split("/")[-2]))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/reports/dashboard-charts":
            try:
                import business_reports
                return self._json(200,business_reports.dashboard_charts(self.db,{"year":self._query(parsed,"year"),"basis":self._query(parsed,"basis","USD")}))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/bank/lines":
            try:
                import bank_rec
                account=self._query(parsed,"account",""); currency=self._query(parsed,"currency","USD"); start=iso_date(self._query(parsed,"from")); end=iso_date(self._query(parsed,"to"))
                return self._json(200,ledger_reports.json_ready({"statement":bank_rec.statement_lines(self.db,account,start,end),"books":bank_rec.book_lines(self.db,account,currency,start,end),
                    "report":bank_rec.reconciliation(self.db,account,currency,start,end,self._query(parsed,"balance"))}))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/reports/financial-config":
            try:
                import financial_statements
                year = int(self._query(parsed,"year",self.headers.get("X-Fiscal-Year")))
                target = self.company_manager.database(self.headers.get("X-Company-ID"),year)
                others = list(self.company_manager.year_databases(self.headers.get("X-Company-ID")).values())  # 2.9.83
                return self._json(200,financial_statements.config(target,others,self.master_db))  # 2.9.97: + the auditor profile
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/reports/business":
            try:
                import business_reports
                report = self._query(parsed,"report","")
                options = json.loads(self._query(parsed,"options","{}") or "{}")
                if report == "financial_statements":
                    import financial_statements
                    if options.get("fs_mode")=="period":  # 2.9.69: a period of one year, with the same period one year before
                        end_year=int(iso_date(options.get("date_to"))[:4]); databases={end_year:self.company_manager.database(self.headers.get("X-Company-ID"),end_year)}
                        if options.get("fs_compare"):
                            try: databases[end_year-1]=self.company_manager.database(self.headers.get("X-Company-ID"),end_year-1)
                            except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
                    else:
                        years = financial_statements.years_from(options.get("years"))
                        databases = {year:self.company_manager.database(self.headers.get("X-Company-ID"),year) for year in years}
                    others = list(self.company_manager.year_databases(self.headers.get("X-Company-ID")).values())  # 2.9.83
                    result = financial_statements.build(databases,options,others,self.master_db)
                else:
                    result=business_reports.build(self.db,report,options)
                return self._json(200,ledger_reports.json_ready(result))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/departments": return self._json(200,{"items":self.db.list_departments()})
        if path == "/api/projects": return self._json(200,{"items":self.db.list_projects()})
        if path == "/api/budgets":
            try: return self._json(200,{"items":self.db.list_budgets(self._query(parsed,"year"),self._query(parsed,"currency","USD"),self._query(parsed,"department"),self._query(parsed,"project"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/rates/suggest":
            try:
                rates=self.db.suggested_rates(self._query(parsed,"currency","USD"),self._query(parsed,"date"))
                return self._json(200,{k:(float(v) if not isinstance(v,str) else v) for k,v in rates.items()})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/settings/list": return self._json(200,{"items":self.db.list_payroll_settings()})
        if path == "/api/vat-return":
            try:
                year=self._query(parsed,"year"); result=vat_return.build_vat_return(self.db,year,self._query(parsed,"quarter"),self._query(parsed,"currency"),
                    self._query(parsed,"include_review","false").lower()=="true",self._previous_year_db(year),self._query(parsed,"credit_brought_forward"),self._query(parsed,"refund_requested"))
                result["provisional_ratio"]=self.db.vat_provisional_ratio(year)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,vat_return.json_ready(result))
        if path == "/api/vat-returns": return self._json(200,{"items":vat_return.list_saved_returns(self.db)})
        if path == "/api/vat-return/check":  # 2.9.79: the return against the books + the settlement voucher it would post
            try:
                year=self._query(parsed,"year"); result=vat_return.build_vat_return(self.db,year,self._query(parsed,"quarter"),None,False,self._previous_year_db(year),
                    self._query(parsed,"credit_brought_forward"),self._query(parsed,"refund_requested"))
                check=vat_return.ledger_check(self.db,result)
                try: check["settlement"]=vat_return.settlement_lines(self.db,result,self._query(parsed,"payable_account"),self._query(parsed,"credit_account"),
                        self._query(parsed,"non_deductible_account"))
                except ValueError as exc: check["settlement_error"]=str(exc)
                check.update(saved=bool(result["saved"]) and not result["changed_since_saved"],payable=result["payable_lbp"],
                        credit_carried_forward=result["credit_carried_forward_lbp"],vat_currency=result["vat_currency"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,vat_return.json_ready(check))
        if path == "/api/alerts/documents":
            try: return self._json(200,self.db.legal_document_alerts(int(self._query(parsed,"days","30"))))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fiscal-year/journal":
            query=parse_qs(parsed.query)
            try:
                company_id=self.headers.get("X-Company-ID"); year=int(query.get("year",[""])[0])
                if not company_id: raise ValueError("Select a company first")
                year_db=self.company_manager.database(company_id,year)
                return self._json(200,{"items":year_db.journal(query.get("from_date",[None])[0],query.get("to_date",[None])[0],query.get("currency",[None])[0]),"year":year,"read_only":True})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fiscal-year/cash-flow":  # 2.9.79: cash flow of any fiscal year (its own file when kept per year)
            try:
                year=int(self._query(parsed,"year")); year_db=self._year_db(year)
                convert=self._query(parsed,"convert","")=="1" and self._query(parsed,"currency")
                return self._json(200,{"items":(year_db.cash_flow_converted if convert else year_db.cash_flow)(self._query(parsed,"from_date"),
                        self._query(parsed,"to_date"),self._query(parsed,"currency")),"year":year})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/fiscal-year/profit-loss", "/api/fiscal-year/balance-sheet"):
            try:
                year = int(self._query(parsed, "year")); year_db = self._year_db(year); currency = self._query(parsed, "currency")
                convert = self._query(parsed, "convert", "") == "1" and currency  # 2.9.80: every currency converted (planning tools)
                if path.endswith("profit-loss"):
                    items = (year_db.profit_and_loss_converted if convert else year_db.profit_and_loss)(self._query(parsed, "from_date"), self._query(parsed, "to_date"), currency)
                else:
                    items = (year_db.balance_sheet_converted if convert else year_db.balance_sheet)(self._query(parsed, "to_date"), currency)
                return self._json(200, {"items": items, "year": year, "separate_file": year_db is not self.db})
            except Exception as exc: return self._json(400, {"error": str(exc)})
        if path == "/api/invoices/next-number":
            try: return self._json(200,{"invoice_number":self.db.next_invoice_number(self._query(parsed,"kind","sale"),self._query(parsed,"date"),self._query(parsed,"branch"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/parties/next-number":
            try: return self._json(200,{"account_number":self.db.next_party_account_number(self._query(parsed,"prefix",""))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/invoices/") and path.endswith("/items"):
            try: return self._json(200,{"items":self.db.invoice_detail(int(path.split("/")[-2])).get("items",[])})
            except KeyError: return self._json(404,{"error":"Invoice not found"})
        if path == "/api/invoices":
            return self._json(200, {"items": self.db.list_invoices()})
        if path.startswith("/api/invoices/") and path.endswith("/detail"):
            try: result=self.db.invoice_detail(int(path.split("/")[-2]))
            except KeyError: return self._json(404,{"error":"Invoice not found"})
            return self._json(200,result)
        if path.startswith("/api/invoices/") and path.endswith("/history"):
            try: invoice_id=int(path.split("/")[-2]); items=self.db.invoice_history(invoice_id)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"items":items})
        if path.startswith("/api/invoices/") and path.endswith("/attachments"):
            try: invoice_id=int(path.split("/")[-2]); items=self.db.list_attachments(invoice_id)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"items":items})
        if path.startswith("/api/attachments/"):
            try:
                attachment=self.db.get_attachment(int(path.rsplit("/",1)[-1]))
                attachment["content"]=base64.b64encode(attachment["content"]).decode("ascii")
            except KeyError: return self._json(404,{"error":"Attachment not found"})
            return self._json(200,attachment)
        if path == "/api/document-cases": return self._json(200,{"items":self.db.list_document_cases()})
        if path.startswith("/api/document-cases/") and path.endswith("/attachments"):
            try: items=self.db.list_case_attachments(int(path.split("/")[-2]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"items":items})
        if path.startswith("/api/case-attachments/"):
            try:
                attachment=self.db.get_case_attachment(int(path.rsplit("/",1)[-1])); attachment["content"]=base64.b64encode(attachment["content"]).decode("ascii")
            except KeyError: return self._json(404,{"error":"Case attachment not found"})
            return self._json(200,attachment)
        if path.startswith("/api/parties/") and path.endswith("/documents"):
            try: items=self.db.list_party_documents(int(path.split("/")[-2]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"items":items})
        if path.startswith("/api/party-documents/"):
            try:
                document=self.db.get_party_document(int(path.rsplit("/",1)[-1])); document["content"]=base64.b64encode(document["content"]).decode("ascii")
            except KeyError: return self._json(404,{"error":"Party document not found"})
            return self._json(200,document)
        if path == "/api/accounts":
            return self._json(200, {"items": self.db.list_accounts()})
        if path == "/api/accounts/usage":  # 2.9.66
            codes=[c for c in self._query(parsed,"codes","").split(",") if c.strip()]
            return self._json(200,{"items":list(self.db.account_usage(codes or None).values())})
        if path == "/api/accounts/lines":  # 2.9.67
            try: return self._json(200,{"items":self.db.account_lines(self._query(parsed,"code",""),self._query(parsed,"from"),self._query(parsed,"to"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounts/unused":
            return self._json(200,{"items":self.db.unused_accounts(self._query(parsed,"scope","all"))})
        if path == "/api/accounts/next-number":
            query=parse_qs(parsed.query)
            try: return self._json(200,{"account_number":self.db.next_account_number(query.get("prefix",[""])[0])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/parties":
            return self._json(200, {"items": self.db.list_parties()})
        if path == "/api/branches": return self._json(200,{"items":self.db.list_branches()})
        if path == "/api/payments": return self._json(200,{"items":self.db.list_payments()})
        if path == "/api/expenses": return self._json(200,{"items":self.db.list_expenses()})
        if path == "/api/tax-flags":  # 2.9.113: the entries ticked "not deductible for income tax"
            try: return self._json(200,{"ids":self.db.tax_flag_ids(self._query(parsed,"source_type") or "")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/income-exemptions":  # 2.9.113
            return self._json(200,{"items":self.db.income_exemptions()})
        if path == "/api/income-exemptions/schedule":  # 2.9.113
            return self._json(200,{"items":self.db.exempt_income(self._query(parsed,"year") or None)})
        if path == "/api/expenses/non-deductible":  # 2.9.110
            return self._json(200,{"items":self.db.non_deductible_expenses(self._query(parsed,"year") or None)})
        if path == "/api/employees": return self._json(200,{"items":self.db.list_employees()})
        if path == "/api/payroll":
            query=parse_qs(parsed.query)
            return self._json(200,{"items":self.db.list_payroll(query.get("from_date",[None])[0],query.get("to_date",[None])[0])})
        if path == "/api/payroll/settings":
            query=parse_qs(parsed.query)
            return self._json(200,self.db.payroll_settings_for(query.get("date",[None])[0]))
        if path == "/api/employees/next-number":
            query=parse_qs(parsed.query)
            try: return self._json(200,{"employee_number":self.db.next_employee_number(query.get("prefix",["1000"])[0])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/statement":
            query = parse_qs(parsed.query)
            try:
                party_id = int(query.get("party_id", [""])[0])
                result = self.db.statement_of_account(
                    party_id,
                    query.get("from_date", [None])[0],
                    query.get("to_date", [None])[0],
                    query.get("currency", [None])[0],
                    query.get("include_opening", ["true"])[0].lower() == "true",
                    query.get("display_currency", [None])[0],
                    query.get("branch_id",[None])[0],
                )
            except KeyError:
                return self._json(404, {"error": "Party not found"})
            except Exception as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200, result)
        if path == "/api/dashboard":
            return self._json(200, {"items": self.db.dashboard()})
        if path == "/api/dashboard/professional": return self._json(200,self.db.professional_dashboard())
        if path == "/api/dashboard/conversion":
            source=self._query(parsed,"source","USD").upper(); target=self._query(parsed,"target","USD").upper()
            day=self._query(parsed,"date","")
            if source not in self.db.currency_codes() or target not in self.db.currency_codes(): return self._json(400,{"error":"Invalid currency"})
            try: rate=self.db._converted_amount(__import__("decimal").Decimal("1"),source,target,day)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"rate":str(rate),"source":source,"target":target,"date":day})
        if path == "/api/users":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            return self._json(200,{"items":self.master_db.list_users()})
        if path == "/api/cash-check":  # 2.9.84: warn before the cash / bank goes negative
            try: result=self.db.cash_check(*(self._query(parsed,name,"") for name in ("account","currency","date","amount")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/audit-log":  # 2.9.84: audit trail screen (administrator)
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try:
                result=self.db.audit_trail(*(self._query(parsed,name,"") for name in ("date_from","date_to","username","entity","action","text")),
                                           int(self._query(parsed,"limit","5000") or 5000))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/approvals":  # 2.9.100: what waits for approval, and the kinds chosen for this company
            import approvals
            return self._json(200,{"items":approvals.pending(self.db),"types":approvals.types_on(self.db),"labels":approvals.TYPES})
        if path == "/api/tax-review":  # 2.9.98: the payroll and VAT rules applied, for the tax adviser
            import tax_review
            try: return self._json(200,tax_review.build(self.db,self._query(parsed,"date","")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/tax-settings-report","/api/tax-adviser"):  # 2.9.100: settings on paper; the adviser who checked them
            import tax_review
            try:
                if path=="/api/tax-adviser": return self._json(200,tax_review.adviser(self.db))
                return self._json(200,tax_review.settings_report(self.db,self._query(parsed,"date","")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/numbering":  # 2.9.116: the naming series (prefix / branch per kind of document)
            import numbering
            with self.db.connect() as connection: return self._json(200,{"items":numbering.settings(connection),"labels":numbering.LABELS,"with_branch":list(numbering.WITH_BRANCH)})
        if path == "/api/renumber":  # 2.9.115: preview of a renumbering by date (administrator, nothing changes)
            import resequence
            try: return self._json(200,resequence.plan(self.db,self._query(parsed,"kind",""),self._query(parsed,"year","")))
            except ValueError as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/audit-report","/api/audit-verify"):  # 2.9.97: audit report and audit-trail integrity (administrator)
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            import audit_chain, audit_report
            try:
                if path=="/api/audit-verify": return self._json(200,audit_chain.verify(self.db))
                return self._json(200,ledger_reports.json_ready(audit_report.build(self.db,self._query(parsed,"date_from",""),self._query(parsed,"date_to",""),
                                                                                    self._query(parsed,"late_days","30"))))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/backups/download":
            try:
                target=self.db.backup_path(self._query(parsed,"name",""))
                return self._json(200,{"name":target.name,"content":base64.b64encode(target.read_bytes()).decode("ascii")})
            except ValueError as exc: return self._json(404,{"error":str(exc)})
            except Exception:
                log.exception("Request step failed")
                return self._json(500,{"error":"Backup could not be downloaded"})
        if path == "/api/backups/folder": return self._json(200,{"folder":str(self.db._backups_dir())})
        if path == "/api/journal/unbalanced": return self._json(200,{"items":self.db.unbalanced_entries()})
        if path == "/api/backups":
            return self._json(200,{"items":self.db.list_backups()})
        if path == "/api/settings": return self._json(200,self.db.settings())
        if path == "/api/books-lock": return self._json(200,self.db.books_lock())
        if path == "/api/currencies": return self._json(200,{"items":self.db.currencies()})
        if path == "/api/exchange-rates": return self._json(200,{"items":self.db.list_exchange_rates()})
        if path == "/api/doe/candidates":
            try: return self._json(200,self.db.doe_candidates(self._query(parsed,"date",""),self._query(parsed,"basis","LBP")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/trial-balance":
            query = parse_qs(parsed.query)
            from_date = query.get("from_date", [None])[0]
            to_date = query.get("to_date", [None])[0]
            return self._json(200, {"items": self.db.trial_balance(from_date, to_date,
                query.get("account",[None])[0],query.get("include_subaccounts",["true"])[0].lower()=="true",
                query.get("account_from",[None])[0],query.get("account_to",[None])[0],query.get("branch_id",[None])[0],query.get("posting_status",["posted"])[0])})
        if path == "/api/journal":
            query = parse_qs(parsed.query)
            return self._json(200, {"items": self.db.journal(
                query.get("from_date", [None])[0],
                query.get("to_date", [None])[0],
                query.get("currency", [None])[0],
                entry_number=query.get("entry_number", [None])[0],
                source_type=query.get("source_type", [None])[0],
            )})
        if path.startswith("/api/journal-vouchers/"):
            try: return self._json(200,self.db.journal_voucher_detail(int(path.rsplit("/",1)[-1])))
            except KeyError: return self._json(404,{"error":"Journal Voucher not found"})
        if path == "/api/profit-loss":
            query=parse_qs(parsed.query)
            convert=query.get("convert",[""])[0]=="1" and query.get("currency",[None])[0]  # 2.9.80
            return self._json(200,{"items":(self.db.profit_and_loss_converted if convert else self.db.profit_and_loss)(query.get("from_date",[None])[0],
                    query.get("to_date",[None])[0],query.get("currency",[None])[0])})
        if path == "/api/fiscal-years":
            return self._json(200,{"items":self.db.list_fiscal_years()})
        if path == "/api/general-ledger":
            query=parse_qs(parsed.query)
            return self._json(200,self.db.general_ledger(query.get("account",[None])[0],query.get("from_date",[None])[0],query.get("to_date",[None])[0],query.get("currency",[None])[0]))
        if path == "/api/balance-sheet":
            query=parse_qs(parsed.query)
            convert=query.get("convert",[""])[0]=="1" and query.get("currency",[None])[0]  # 2.9.80
            return self._json(200,{"items":(self.db.balance_sheet_converted if convert else self.db.balance_sheet)(query.get("to_date",[None])[0],query.get("currency",[None])[0])})
        if path == "/api/vat-report":
            query=parse_qs(parsed.query)
            return self._json(200,self.db.vat_report(query.get("from_date",[None])[0],query.get("to_date",[None])[0],query.get("currency",[None])[0]))
        if path == "/api/cash-flow":
            query=parse_qs(parsed.query)
            convert=query.get("convert",[""])[0]=="1" and query.get("currency",[None])[0]  # 2.9.80
            return self._json(200,{"items":(self.db.cash_flow_converted if convert else self.db.cash_flow)(query.get("from_date",[None])[0],query.get("to_date",
                    [None])[0],query.get("currency",[None])[0])})
        if path == "/api/aging":
            query=parse_qs(parsed.query)
            return self._json(200,{"items":self.db.aging_report(query.get("as_of_date",[None])[0],query.get("kind",[None])[0],query.get("currency",[None])[0])})
        if path == "/api/comparative-reports":
            query=parse_qs(parsed.query)
            try:
                from_date=query.get("from_date",[""])[0]
                prior_db=self._year_db(int(str(from_date)[:4])-1) if str(from_date)[:4].isdigit() else self.db
                result=self.db.comparative_reports(from_date,query.get("to_date",[""])[0],query.get("currency",[None])[0],prior_db=None if prior_db is self.db else prior_db)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        return self._json(404, {"error": "Not found"})

    # 2.9.88: changes are made one at a time (several users at once could get the same invoice / voucher number:
    # 80 invoices saved by 4 users got 36 numbers). Reading is never blocked; SQLite writes one at a time anyway.
    _write_lock = threading.RLock()

    def _serialized(self, method):
        if urlparse(self.path).path in ("/api/login", "/api/logout"): return method()
        with ApiHandler._write_lock: return method()

    def do_POST(self): return self._serialized(self._do_POST)

    # 2.9.93: approval (Accounting Settings > "Documents need approval"): an invoice prepared by a user without the
    # "approve" permission is saved as a draft (review); only a user with it posts it, and never the one who prepared it.
    def _approval_required(self, kind="invoices"):
        try:
            import approvals
            return kind in approvals.types_on(self.db)  # 2.9.100: chosen per company and per kind of document
        except Exception: return False

    def _hold_for_approval(self, user, kind, result):
        """2.9.100: a voucher / payment / expense of a kind that needs approval, saved by a user without 'Can approve', waits."""
        if not self._approval_required(kind) or self.master_db.user_can(user, "approve"): return None
        import approvals
        entry = approvals.entry_of(self.db, kind, result)
        if entry and approvals.hold(self.db, entry, user["id"]): return "saved as a draft: it waits for approval by another user"
        return None

    def _approval_gate(self, user, invoice, invoice_id=None):
        if not self._approval_required() or not isinstance(invoice, dict): return None
        wants_post = str(invoice.get("status") or "posted").lower() == "posted"
        if not wants_post: return None
        if not self.master_db.user_can(user, "approve"):
            invoice["status"] = "review"; return "saved as a draft for approval"
        if invoice_id and user["role"] != "admin":
            with self.db.connect() as db:
                row = db.execute("SELECT created_by,status FROM invoices WHERE id=?", (int(invoice_id),)).fetchone()
            if row and row["status"] == "review" and row["created_by"] == user["id"]:
                raise PermissionError("A document must be approved by another user than the one who prepared it")
        return None
    def do_PUT(self): return self._serialized(self._do_PUT)
    def do_DELETE(self): return self._serialized(self._do_DELETE)

    def _do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
        except Exception:
            return self._json(400, {"error": "Invalid JSON"})
        if path == "/api/licence":  # 2.9.103: a signed licence code - accepted before signing in (an ended licence blocks sign-in)
            import licence
            try:
                with self.master_db.connect() as connection: return self._json(200,licence.install(connection,body.get("code"),None))
            except ValueError as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/login":
            try: session = self.master_db.login(body.get("username", ""), body.get("password", ""), self.client_address[0])
            except PermissionError as exc: return self._json(403,{"error":str(exc)})
            if session and session.get("rate_limited"):
                return self._json(429,{"error":"Too many sign-in attempts. Try again later."})
            return self._json(200, session) if session else self._json(401, {"error": "Invalid username or password"})
        user = self._user()
        if not user:
            return self._json(401, {"error": "Unauthorized"})
        if admin_only("POST", path) and user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})  # 2.9.103
        if path == "/api/companies":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.company_manager.create_company(body,self.master_db)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"company":result})
        if path == "/api/companies/import":  # 2.9.108: a company file brought from another computer
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.company_manager.add_company_file(body.get("path"))
            except ValueError as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"company":result})
        if path == "/api/companies/year":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.company_manager.create_year(body.get("company_id"),body.get("year"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"company":result})
        if not self._select_database(): return
        fiscal_admin_paths=("/api/reports/financial-config","/api/fiscal-years/reopen","/api/fiscal-years/refresh-opening","/api/fiscal-years/delete")
        if path not in fiscal_admin_paths and self.headers.get("X-Company-ID") and self.headers.get("X-Fiscal-Year") and self.company_manager.year_status(self.headers.get("X-Company-ID"),
                self.headers.get("X-Fiscal-Year"))=="closed":
            return self._json(423,{"error":"This fiscal year is closed and read-only"})
        if user["role"] == "viewer":
            return self._json(403,{"error":"Viewer access is read-only"})
        if self._module_denied(user, path): return
        if path == "/api/reports/financial-config":
            try:
                import financial_statements
                target = self.company_manager.database(self.headers.get("X-Company-ID"),int(body["year"]))
                others = list(self.company_manager.year_databases(self.headers.get("X-Company-ID")).values())  # 2.9.83: entered once for every year
                return self._json(200,financial_statements.save_config(target,body["config"],user["id"],others,self.master_db))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/asset-categories":
            try:
                if body.get("delete"): return self._json(200,{"items":fixed_assets.delete_category(self.db,body.get("account_code"))})
                return self._json(200,{"items":fixed_assets.save_category(self.db,body,user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/asset-depreciation/post":
            try: return self._json(201,fixed_assets.post_category_month(self.db,body.get("account_code"),body.get("month"),user["id"],getattr(self.db,"fiscal_year",None)))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/fixed-assets":
            try: return self._json(201,{"asset":fixed_assets.save_asset(self.db,body,user_id=user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/fixed-assets/") and path.endswith("/attachments"):
            try:
                raw=base64.b64decode((body.get("content") or "").encode("ascii"),validate=True)
                result=fixed_assets.add_attachment(self.db,int(path.split("/")[-2]),body.get("file_name"),
                                                   body.get("mime_type"),raw,user["id"])
                return self._json(200 if result["duplicate"] else 201,result)
            except KeyError: return self._json(404,{"error":"Asset not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/fixed-assets/") and path.endswith("/post"):
            try: return self._json(201,{"voucher":fixed_assets.post_period(self.db,int(path.split("/")[-2]),body.get("period_end"),user["id"],self.headers.get("X-Fiscal-Year"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/expenses/") and path.endswith("/attachments"):
            try:
                raw=base64.b64decode(body.get("content","").encode("ascii"),validate=True)
                return self._json(201,{"attachment_id":self.db.add_expense_attachment(int(path.split("/")[-2]),body.get("file_name"),body.get("mime_type"),raw,user["id"])})
            except KeyError: return self._json(404,{"error":"Expense not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/invoices/") and path.endswith("/replace"):
            try:
                self._approval_gate(user, body.get("invoice",{}), int(path.split("/")[-2]))
                return self._json(200,{"invoice_id":self.db.replace_manual_invoice(int(path.split("/")[-2]),body.get("invoice",{}),body.get("items",[]),user["id"])})
            except KeyError: return self._json(404,{"error":"Invoice not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/invoices/") and path.endswith("/returns"):
            try:
                result=self.db.create_invoice_return(int(path.split("/")[-2]),body.get("items",[]),body.get("return_date"),user["id"],body.get("request_id"))
                return self._json(201,{"invoice":result})
            except KeyError: return self._json(404,{"error":"Invoice not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/invoices/") and path.endswith("/landed-cost"):
            try: return self._json(201,{"invoice_id":self.db.add_landed_cost(int(path.split("/")[-2]),body,user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/production/"):  # 2.9.65
            import production
            try:
                if path == "/api/production/recipes": return self._json(201,production.save_bom(self.db,body,user["id"]))
                if path == "/api/production/orders": return self._json(201,production.save_order(self.db,body.get("header",{}),body.get("lines",[]),user["id"],body.get("id")))
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/inventory/"):
            try:
                if path == "/api/inventory/items": return self._json(201,{"item":inventory.save_item(self.db,body,user["id"])})
                if path == "/api/inventory/warehouses": return self._json(201,{"item":inventory.save_warehouse(self.db,body,user["id"])})
                if path == "/api/inventory/settings": return self._json(200,inventory.save_settings(self.db,body,user["id"]))
                if path == "/api/inventory/documents":
                    return self._json(201,inventory.save_document(self.db,body.get("header",{}),body.get("lines",[]),user["id"],body.get("id")))
                if path == "/api/inventory/stock-variation": return self._json(200,inventory.post_stock_variation(self.db,body.get("year"),user["id"]))
                if path == "/api/inventory/monthly-variation": return self._json(200,inventory.post_monthly_stock_variation(self.db,body.get("month_end"),user["id"]))  # 2.9.82
                if path == "/api/inventory/categories": return self._json(200,inventory.save_category(self.db,body,user["id"]))
                if path == "/api/inventory/counts": return self._json(201,inventory.save_count(self.db,body.get("header",{}),body.get("lines",[]),user["id"],body.get("id"),bool(body.get("post"))))
                if path == "/api/inventory/item-details": return self._json(200,inventory.set_item_details(self.db,body.get("items"),user["id"]))  # 2.9.101
                if path == "/api/inventory/item-accounts": return self._json(200,inventory.set_item_accounts(self.db,body.get("item_ids"),
                        body.get("cost_account"),body.get("sales_account"),user["id"]))  # 2.9.90
                if path == "/api/inventory/find-or-create": return self._json(200,{"item":inventory.find_or_create_item(self.db,body.get("name"),
                        body.get("unit"),body.get("sku"),user["id"],body.get("supplier_id"))})
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/payments/") and path.endswith("/allocations"):
            try: return self._json(200,{"items":self.db.save_allocations(int(path.split("/")[-2]),body.get("allocations",[]),user["id"])})
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/bank/"):
            try:
                import bank_rec
                action=path.rsplit("/",1)[-1]
                if action=="import": return self._json(201,{"added":bank_rec.add_statement_lines(self.db,body.get("account"),body.get("currency"),body.get("rows",[]),user["id"])})
                if action=="auto-match": return self._json(200,{"matched":bank_rec.auto_match(self.db,body.get("account"),body.get("currency"),
                        iso_date(body.get("from")),iso_date(body.get("to")),int(body.get("days") or 5))})
                if action=="match": return self._json(200,{"ok":bank_rec.match(self.db,body.get("statement_id"),body.get("journal_line_id"))})
                if action=="unmatch": return self._json(200,{"ok":bank_rec.unmatch(self.db,body.get("statement_id"))})
                if action=="delete": return self._json(200,{"ok":bank_rec.delete_statement_line(self.db,body.get("statement_id"))})
                if action=="post": return self._json(201,{"voucher":bank_rec.post_statement_line(self.db,body.get("statement_id"),body.get("account_code"),user["id"])})
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/departments","/api/projects","/api/budgets"):
            try:
                saver={"/api/departments":self.db.save_department,"/api/projects":self.db.save_project,"/api/budgets":self.db.save_budget}[path]
                return self._json(201,{"item":saver(body,user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/vat-return/adjustments":
            try: adjustment_id=vat_return.add_adjustment(self.db,body,user["id"],user["username"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"adjustment_id":adjustment_id})
        if path == "/api/vat-return/save":
            try:
                year=body.get("year"); result=vat_return.save_return(self.db,year,body.get("quarter"),user["id"],self._previous_year_db(year),
                        body.get("credit_brought_forward"),user["username"],body.get("refund_requested"))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,vat_return.json_ready(result))
        if path == "/api/payroll/eos-provision":  # 2.9.82
            try: return self._json(201,ledger_reports.json_ready(payroll_extras.post_eos_provision(self.db,body.get("date"),user["id"])))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/leave":
            try: return self._json(201,{"id":payroll_extras.save_leave(self.db,body,user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounting-setup":  # 2.9.81: company settings (administrator)
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: return self._json(200,accounting_setup.save_setup(self.db,body,user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/tax-adviser":  # 2.9.100: record the tax adviser's check of the rules (administrator)
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            import tax_review
            try: return self._json(200,tax_review.save_adviser(self.db,body,user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/vat-ledgers","/api/vat-ledgers/create"):  # 2.9.97
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            import vat_ledgers
            try:
                if path.endswith("/create"): return self._json(200,{"created":vat_ledgers.create_vat_accounts(self.db,int(body.get("start_from") or 0))})
                return self._json(200,vat_ledgers.save_settings(self.db,body))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounting-setup/user":  # 2.9.81: what this user hides for himself
            try: return self._json(200,{"user_hidden":accounting_setup.save_user_hidden(self.master_db,user["id"],body.get("hidden"))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/vat-return/settle":  # 2.9.79: post the settlement voucher of a saved return
            try:
                year=body.get("year"); result=vat_return.post_settlement(self.db,year,body.get("quarter"),user["id"],self._previous_year_db(year),
                    body.get("payable_account"),body.get("credit_account"),body.get("non_deductible_account"))
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,vat_return.json_ready(result))
        if path == "/api/vat-return/reopen":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=vat_return.reopen_return(self.db,body.get("year"),body.get("quarter"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/vat-ratio":
            try: return self._json(200,{"ratio":vat_return.json_ready(self.db.save_vat_provisional_ratio(body.get("year"),body.get("ratio"),user["id"]))})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/vat-classification":
            try: return self._json(200,self.db.set_vat_classification(body.get("source"),body.get("id"),body.get("vat_treatment"),body.get("vat_use"),user["id"]))
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/vat-recoverable":
            try: result=self.db.set_vat_recoverable(body.get("source"),body.get("id"),body.get("recoverable",True),user["id"])
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/parties":
            try: result=self.db.save_party(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"party":result})
        if path == "/api/branches":
            try: result=self.db.save_branch(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"branch":result})
        if path == "/api/invoices/account-fix":  # 2.9.77
            try: return self._json(200,self.db.fix_sales_accounts(body.get("invoice_ids") or [],user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/invoices/set-account":  # 2.9.71: Uploaded Data - one account for all the selected rows
            try: return self._json(200,self.db.set_invoices_account(body.get("invoice_ids") or [],body.get("field"),body.get("account"),user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path in ("/api/accounts/delete","/api/accounts/move","/api/accounts/transfer-balance","/api/accounts/move-lines"):  # 2.9.66
            if user["role"]=="viewer": return self._json(403,{"error":"Viewer accounts cannot change the chart of accounts"})
            if path=="/api/accounts/delete" and not self.master_db.user_can(user,"delete"):
                return self._json(403,{"error":"You do not have permission to delete. Ask the administrator."})
            try:
                if path=="/api/accounts/delete": result=self.db.delete_accounts(body.get("codes") or [],user["id"])
                elif path=="/api/accounts/move": result=self.db.move_account(body.get("from"),body.get("to"),user["id"],bool(body.get("merge_party")))
                elif path=="/api/accounts/move-lines": result=self.db.move_lines(body.get("from"),body.get("to"),body.get("line_ids") or [],user["id"],bool(body.get("change_party",True)))
                else: result=self.db.transfer_balance(body.get("from"),body.get("to"),body.get("date"),user["id"],body.get("description") or "")
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path in ("/api/onboarding/check", "/api/onboarding/import"):  # 2.9.119: Start with Nanza (opening balances from Excel)
            import onboarding
            try:
                if path.endswith("check"):
                    result=onboarding.check(self.db,body.get("data") or {},body.get("date")); result.pop("plan",None)
                    return self._json(200,result)
                return self._json(200,onboarding.apply(self.db,body.get("data") or {},body.get("date"),user["id"]))
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounts/import":  # 2.9.116: chart of accounts from Excel (administrator; adds and names, never deletes)
            import chart_templates
            try: return self._json(200,chart_templates.import_accounts(self.db,body.get("items") or [],user["id"]))
            except ValueError as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/accounts":
            try: account=self.db.save_account(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"saved":True,"account":account})
        if path == "/api/users":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.master_db.save_user(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"user":result})
        if path == "/api/backups/create":
            return self._json(200,{"path":self.db.backup()})
        if path == "/api/backups/scheduled":
            if user["role"]=="viewer": return self._json(200,{"path":None})
            try: return self._json(200,{"path":self.db.maybe_scheduled_backup()})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/numbering":  # 2.9.116: save the naming series (administrator)
            import numbering
            try: return self._json(200,{"items":numbering.save_settings(self.db,body.get("items") or {},user["id"])})
            except ValueError as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/renumber":  # 2.9.115: renumber as previewed (administrator; safety backup + audit trail)
            import resequence
            try: return self._json(200,resequence.apply(self.db,body.get("kind"),body.get("year"),body.get("token"),user["id"]))
            except ValueError as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/books-lock":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: return self._json(200,self.db.set_books_lock(body.get("locked_until"),user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/backups/restore":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.db.restore_backup(body.get("name"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/settings":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.db.save_settings(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/currencies":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: currency=self.db.save_currency(body.get("code"),body.get("name"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"currency":currency})
        if path == "/api/exchange-rates":
            try: self.db.save_exchange_rate(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"saved":True})
        if path == "/api/exchange-rates/restore-all":
            try: result=self.db.restore_all_rates()
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/exchange-rates/restore-euro":
            try: result=self.db.restore_euro_rates()
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/payments":
            try: payment_id=self.db.add_payment(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            note=self._hold_for_approval(user,"payments",payment_id)
            return self._json(201,{"payment_id":payment_id,**({"approval":note} if note else {})})
        if path == "/api/expenses":
            try: expense_id=self.db.add_expense(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            note=self._hold_for_approval(user,"expenses",expense_id)
            return self._json(201,{"expense_id":expense_id,**({"approval":note} if note else {})})
        if path == "/api/approvals/approve":  # 2.9.100: post the selected drafts (vouchers, payments, expenses, invoices)
            if not self.master_db.user_can(user, "approve"): return self._json(403,{"error":"You do not have permission to approve documents. Ask the administrator."})
            import approvals
            try:
                other=user["role"]!="admin"; done=approvals.approve_entries(self.db,body.get("entry_ids",[]),user,other)
                if body.get("invoice_ids"):
                    inv=self.db.approve_invoices(body.get("invoice_ids"),user,require_other=other)
                    done["approved"]+=list(inv.get("approved",[])); done["skipped"]+=list(inv.get("skipped",[]))
                return self._json(200,done)
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/employees":
            try: result=self.db.save_employee(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"employee":result})
        if path == "/api/payroll/calculate":
            try: result=self.db.calculate_payroll(body)
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/payroll":
            try: result=self.db.save_payroll(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"payroll":result})
        if path.startswith("/api/payroll/") and path.endswith("/post"):
            try: result=self.db.post_payroll(int(path.split("/")[-2]),user["id"])
            except KeyError: return self._json(404,{"error":"Payroll record not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"payroll":result})
        if path == "/api/payroll/nssf-filed":
            try: return self._json(201,{"item":self.db.save_nssf_filed_wages(body,user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/nssf-payment":
            try: return self._json(201,self.db.record_nssf_payment(body,user["id"]))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/delete-period":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: return self._json(200,{"items":self.db.delete_payroll_period(body.get("date_from"),user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/apply-lebanese-rules":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: return self._json(200,{"items":self.db.apply_lebanese_payroll_rules(user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/periods":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: return self._json(200,{"items":self.db.save_payroll_periods(body.get("periods") or [],user["id"])})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/payroll/settings":
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.db.save_payroll_settings(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/income-exemptions":  # 2.9.113
            try: return self._json(200,self.db.set_income_exemption(body.get("source_id"),body.get("reason"),body.get("article","")))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/tax-flags":  # 2.9.113
            try: return self._json(200,self.db.set_tax_flag(body.get("source_type"),body.get("source_id"),bool(body.get("not_deductible"))))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/journal-vouchers":
            try: result=self.db.save_journal_voucher(body.get("voucher",{}),body.get("lines",[]),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            note=self._hold_for_approval(user,"journal_vouchers",result)
            return self._json(201,{**result,**({"approval":note} if note else {})})
        if path.startswith("/api/invoices/") and path.endswith("/items"):
            try:
                invoice_id = int(path.split("/")[-2])
                result = self.db.add_invoice_item(invoice_id, body.get("item", {}), user["id"])
            except KeyError:
                return self._json(404, {"error": "Invoice not found"})
            except Exception as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(201, {"invoice": result})
        if path.startswith("/api/invoices/") and path.endswith("/cancel") and not self.master_db.user_can(user, "delete"):
            return self._json(403,{"error":"You do not have permission to cancel invoices. Ask the administrator."})
        if path.startswith("/api/invoices/") and path.endswith("/cancel"):
            try: result=self.db.cancel_invoice(int(path.split("/")[-2]),body.get("reason"),user["id"])
            except KeyError: return self._json(404,{"error":"Invoice not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"invoice":result})
        if path.startswith("/api/invoices/") and path.endswith("/duplicate"):
            try: result=self.db.duplicate_invoice(int(path.split("/")[-2]),user["id"])
            except KeyError: return self._json(404,{"error":"Invoice not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"invoice":result})
        if path.startswith("/api/invoices/") and path.endswith("/attachments"):
            try:
                raw=base64.b64decode(body.get("content","").encode("ascii"),validate=True)
                attachment_id=self.db.add_attachment(int(path.split("/")[-2]),body.get("file_name"),body.get("mime_type"),raw,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"attachment_id":attachment_id})
        if path == "/api/document-cases":
            try: result=self.db.save_document_case(body,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"case":result})
        if path.startswith("/api/document-cases/") and path.endswith("/attachments"):
            try:
                raw=base64.b64decode(body.get("content","").encode("ascii"),validate=True)
                attachment_id=self.db.add_case_attachment(int(path.split("/")[-2]),body.get("document_role"),body.get("file_name"),body.get("mime_type"),raw,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"attachment_id":attachment_id})
        if path.startswith("/api/document-cases/") and path.endswith("/post"):
            try: result=self.db.post_document_case(int(path.split("/")[-2]),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"case":result})
        if path.startswith("/api/parties/") and path.endswith("/documents"):
            try:
                raw=base64.b64decode((body.get("content") or "").encode("ascii"),validate=True)
                document_id=self.db.add_party_document(int(path.split("/")[-2]),body,raw,user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(201,{"document_id":document_id})
        if path == "/api/fiscal-years/close":
            if user["role"] != "admin": return self._json(403,{"error":"Administrator permission required"})
            try:
                company_id=self.headers.get("X-Company-ID")
                if not company_id: raise ValueError("Select a company before closing the fiscal year")
                result=self.company_manager.close_and_open_year(company_id,body.get("year"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/fiscal-years/delete":
            if user["role"] != "admin": return self._json(403,{"error":"Administrator permission required"})
            try:
                company_id=self.headers.get("X-Company-ID")
                if not company_id: raise ValueError("Select a company first")
                result=self.company_manager.delete_year(company_id,body.get("year"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/fiscal-years/reopen":
            if user["role"] != "admin": return self._json(403,{"error":"Administrator permission required"})
            try:
                company_id=self.headers.get("X-Company-ID")
                if not company_id: raise ValueError("Select a company before reopening the fiscal year")
                result=self.company_manager.reopen_year(company_id,body.get("year"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/fiscal-years/refresh-opening":
            if user["role"] != "admin": return self._json(403,{"error":"Administrator permission required"})
            try:
                company_id=self.headers.get("X-Company-ID")
                if not company_id: raise ValueError("Select a company first")
                result=self.company_manager.refresh_opening(company_id,body.get("source_year"),user["id"])
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path == "/api/invoices/approve":  # 2.9.93: post the selected drafts (approval)
            if not self.master_db.user_can(user, "approve"): return self._json(403,{"error":"You do not have permission to approve documents. Ask the administrator."})
            try: return self._json(200,self.db.approve_invoices(body.get("ids",[]),user, require_other=user["role"]!="admin"))
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path == "/api/invoices/duplicates":
            try: return self._json(200, {"items": self.db.find_invoice_duplicates(body.get("items") or [])})
            except Exception as exc: return self._json(400, {"error": str(exc)})
        if path == "/api/invoices/payment-entries":
            try: return self._json(200, self.db.create_missing_invoice_payments(user["id"]))
            except Exception as exc: return self._json(400, {"error": str(exc)})
        if path == "/api/invoices/manual":
            invoice = body.get("invoice", {})
            items = body.get("items", [])
            if not isinstance(invoice, dict) or not isinstance(items, list) or len(items) > 500:
                return self._json(400, {"error": "Invalid manual invoice"})
            required = ("invoice_date", "party_name", "kind", "currency")
            missing = [field for field in required if not str(invoice.get(field) or "").strip()]
            if missing:
                return self._json(400, {"error": "Missing fields: " + ", ".join(missing)})
            try:
                note = self._approval_gate(user, invoice)
                invoice_id = self.db.create_manual_invoice(invoice, items, user["id"])
            except Exception as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(201, {"invoice_id": invoice_id, **({"approval": note} if note else {})})
        if path == "/api/invoices/import":
            items = body.get("items", [])
            if not isinstance(items, list) or len(items) > 5000:
                return self._json(400, {"error": "Invalid import batch"})
            for entry in items:
                if isinstance(entry, dict) and "status" not in entry: entry["status"] = "posted"
                self._approval_gate(user, entry)  # 2.9.93
            if body.get("replace_existing", False) and not self.master_db.user_can(user, "delete"):
                return self._json(403,{"error":"You do not have permission to replace all invoices. Ask the administrator."})
            if body.get("replace_existing", False):
                # Validate the entire replacement on a private SQLite snapshot first.
                # A failed row leaves the live database untouched.
                with self.db._lock, tempfile.TemporaryDirectory() as directory:
                    stage_path=Path(directory)/"replacement.db"
                    with closing(sqlite3.connect(self.db.path)) as source, closing(sqlite3.connect(stage_path)) as stage:
                        source.backup(stage)
                    stage_db=Database(stage_path)
                    try: replacement=stage_db.clear_invoices(user["id"],make_backup=False)
                    except Exception as exc: return self._json(400,{"error":str(exc)})
                    ids,errors=[],[]
                    for index,item in enumerate(items):
                        try: ids.append(stage_db.import_invoice(item,user["id"]))
                        except Exception as exc: errors.append({"index":index,"invoice_number":item.get("invoice_number") if isinstance(item,dict) else None,"error":str(exc)})
                    if errors:
                        return self._json(400,{"error":"Replacement cancelled; no existing data was changed","errors":errors})
                    try:
                        safety=self.db.backup("safety")
                        with closing(sqlite3.connect(stage_path)) as source,closing(sqlite3.connect(self.db.path)) as target:
                            source.backup(target)
                    except Exception as exc: return self._json(500,{"error":f"Replacement could not be saved: {exc}"})
                    return self._json(200,{"imported":len(ids),"ids":ids,"errors":[],"deleted":replacement["deleted"],"backup":safety})
            replacement={"deleted":0,"backup":None}
            ids, errors = [], []
            for index, item in enumerate(items):
                try:
                    ids.append(self.db.import_invoice(item, user["id"]))
                except Exception as exc:
                    errors.append({"index": index, "invoice_number": item.get("invoice_number"), "error": str(exc)})
            return self._json(200, {"imported": len(ids), "ids": ids, "errors": errors, "deleted": replacement["deleted"], "backup": replacement["backup"]})
        return self._json(404, {"error": "Not found"})

    def _do_PUT(self):
        path = urlparse(self.path).path
        user = self._user()
        if not user:
            return self._json(401, {"error": "Unauthorized"})
        if admin_only("PUT", path) and user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})  # 2.9.103
        if path.startswith("/api/companies/"):
            if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
            try: result=self.company_manager.update_company(path.rsplit("/",1)[-1],self._body())
            except KeyError: return self._json(404,{"error":"Company not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"company":result})
        if not self._select_database(): return
        if self.headers.get("X-Company-ID") and self.headers.get("X-Fiscal-Year") and self.company_manager.year_status(self.headers.get("X-Company-ID"),self.headers.get("X-Fiscal-Year"))=="closed":
            return self._json(423,{"error":"This fiscal year is closed and read-only"})
        if user["role"] == "viewer":
            return self._json(403,{"error":"Viewer access is read-only"})
        if path.startswith("/api/party-documents/"):
            try:
                body=self._body(); raw=base64.b64decode((body.get("content") or "").encode("ascii"),validate=True)
                return self._json(200,{"document_id":self.db.update_party_document(int(path.rsplit("/",1)[-1]),body,raw,user["id"])})
            except KeyError: return self._json(404,{"error":"Party document not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/fixed-assets/"):
            try: return self._json(200,{"asset":fixed_assets.save_asset(self.db,self._body(),int(path.rsplit("/",1)[-1]),user["id"])})
            except KeyError: return self._json(404,{"error":"Asset not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
        if path.startswith("/api/payments/") or path.startswith("/api/expenses/"):
            try:
                body=self._body(); record_id=int(path.rsplit("/",1)[-1])
                result=self.db.update_payment(record_id,body,user["id"]) if path.startswith("/api/payments/") else self.db.update_expense(record_id,body,user["id"])
            except KeyError as exc: return self._json(404,{"error":str(exc).strip("'")})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"id":result})
        if path.startswith("/api/journal-vouchers/"):
            try:
                body=self._body(); result=self.db.save_journal_voucher(body.get("voucher",{}),body.get("lines",[]),user["id"],int(path.rsplit("/",1)[-1]))
            except KeyError: return self._json(404,{"error":"Journal Voucher not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,result)
        if path.startswith("/api/invoices/"):
            try:
                invoice_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                return self._json(400, {"error": "Invalid invoice ID"})
            try:
                body = self._body()
                invoice = body.get("invoice", {})
                if not isinstance(invoice, dict):
                    raise ValueError("Invalid invoice details")
                self._approval_gate(user, invoice, invoice_id)
                updated = self.db.update_invoice(invoice_id, invoice, user["id"])
            except KeyError:
                return self._json(404, {"error": "Invoice not found"})
            except Exception as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200, {"invoice": updated})
        if path.startswith("/api/accounts/"):
            code=path.rsplit("/",1)[-1]
            body=self._body()
            try: account=self.db.rename_account(code,body.get("name_en"),user["id"],body.get("name_fr"),body.get("name_ar"),body.get("type"))
            except KeyError: return self._json(404,{"error":"Account not found"})
            except Exception as exc: return self._json(400,{"error":str(exc)})
            return self._json(200,{"account":account})
        return self._json(404, {"error": "Not found"})

    def _do_DELETE(self):
        path=urlparse(self.path).path; user=self._user()
        if not user: return self._json(401,{"error":"Unauthorized"})
        if admin_only("DELETE", path) and user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})  # 2.9.103
        if not self._select_database(): return
        if self.headers.get("X-Company-ID") and self.headers.get("X-Fiscal-Year") and self.company_manager.year_status(self.headers.get("X-Company-ID"),self.headers.get("X-Fiscal-Year"))=="closed":
            return self._json(423,{"error":"This fiscal year is closed and read-only"})
        if user["role"]=="viewer": return self._json(403,{"error":"Viewer access is read-only"})
        try:
            if self._module_denied(user, path): return
            if not self.master_db.user_can(user, "delete"):
                return self._json(403,{"error":"You do not have permission to delete. Ask the administrator."})
            if path.startswith("/api/fixed-assets/"): result=fixed_assets.delete_asset(self.db,int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/vat-return/adjustments/"): result=vat_return.delete_adjustment(self.db,int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/payroll/leave/"): result=payroll_extras.delete_leave(self.db,int(path.rsplit("/",1)[-1]),user["id"])  # 2.9.82
            elif path.startswith("/api/inventory/documents/"): result=inventory.delete_document(self.db,int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/production/recipes/"):
                import production; from urllib.parse import unquote
                result=production.delete_bom(self.db,unquote(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/payments/"): result=self.db.delete_payment(int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/expenses/"): result=self.db.delete_expense(int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/invoices/"): result=self.db.mark_invoice_deleted(int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/journal/"): result=self.db.delete_journal_voucher(int(path.rsplit("/",1)[-1]),user["id"])
            elif path.startswith("/api/opening-vouchers/"):
                if user["role"]!="admin": return self._json(403,{"error":"Administrator permission required"})
                result=self.db.delete_opening_voucher(int(path.rsplit("/",1)[-1]),user["id"])
            else: return self._json(404,{"error":"Not found"})
        except KeyError: return self._json(404,{"error":"Entry not found"})
        except Exception as exc: return self._json(400,{"error":str(exc)})
        return self._json(200,result)

def _keep_alive_safe(method):
    """Read the whole request body first and always answer, so a kept-open connection stays in step."""
    def handle(self):
        self._responded = False
        raw_length=self.headers.get("Content-Length", "0") or "0"
        try: length = int(raw_length)
        except (TypeError,ValueError):
            self.close_connection=True
            self._json(400,{"error":"Invalid request length"})
            return
        if length<0:
            self.close_connection=True
            self._json(400,{"error":"Invalid request length"})
            return
        if self.headers.get("Transfer-Encoding"):
            self.close_connection=True
            self._json(400,{"error":"Chunked request bodies are not supported"})
            return
        if length>MAX_REQUEST_BODY_BYTES:
            self.close_connection=True
            self._json(413,{"error":"Request body exceeds the 22 MB limit"})
            return
        self._raw_body = self.rfile.read(length) if length > 0 else b""
        if len(self._raw_body)!=length:
            self.close_connection=True
            self._json(400,{"error":"Request body was incomplete"})
            return
        if self._key_refused(): return
        import inventory
        try:
            # The user confirmed the negative-stock alert for this request (the desktop resends it with this header).
            with inventory.negative_stock_allowed(self.headers.get("X-Allow-Negative-Stock") == "1"):
                method(self)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True; return
        except Exception as exc:
            log.exception("Request failed: %s %s", self.command, urlparse(self.path).path)
            if self._responded: self.close_connection = True; return
            # 2.9.61: say what failed (short), so a screenshot is enough to find the cause; full details in logs/saber.log
            detail = f"{type(exc).__name__}: {str(exc)[:160]}".rstrip(": ")
            try: self._json(500, {"error": f"The data service could not complete the request\n({self.command} {urlparse(self.path).path} - {detail})"})
            except Exception: self.close_connection = True
            return
        if not self._responded:
            self._json(500, {"error": "The data service did not answer this request"})
    handle.__name__ = method.__name__; handle.__doc__ = method.__doc__
    return handle

for _verb in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
    setattr(ApiHandler, _verb, _keep_alive_safe(getattr(ApiHandler, _verb)))

def run_server(host="127.0.0.1", port=8765, database="saber_accounting.db", admin_password=None, tls_cert=None, tls_key=None, allow_insecure_lan=False,
               local_key=None, on_ready=None):
    """port=0 lets Windows choose a free port; on_ready(port) is called once requests are accepted.
    local_key: when given, every request must send it in the X-Saber-Key header (private desktop service)."""
    if bool(tls_cert)!=bool(tls_key): raise ValueError("Provide both TLS certificate and private key")
    if host not in ("127.0.0.1","localhost","::1") and not tls_cert and not allow_insecure_lan:
        raise ValueError("Shared network access requires --tls-cert and --tls-key (or explicit --allow-insecure-lan for a trusted VPN)")
    admin_password = admin_password or os.environ.get("SABER_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    db = Database(database, pooled=True)
    db.initialize_if_needed(admin_password)
    ApiHandler.local_key = local_key
    ApiHandler.db = db; ApiHandler.master_db=db; ApiHandler.company_manager=CompanyManager(database, pooled=True)
    # Company data lives in companies/<Company Name>/<Company Name>_<year>.db (moved there once, safely).
    try:
        for source,target in ApiHandler.company_manager.organize_files(): log.info("Company file moved: %s -> %s", source, target)
    except Exception as exc: log.warning("Company files were not reorganised this time: %s", exc)
    try:  # 2.9.108: company files copied into the companies folder from another computer appear in the list
        for path,name,year in ApiHandler.company_manager.discover_files(): log.info("Company file added: %s (%s %s)", path, name, year)
    except (OSError, ValueError) as exc: log.warning("Company folder not scanned: %s", exc)
    server = ThreadingHTTPServer((host, port), ApiHandler)
    if tls_cert:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_cert,tls_key)
        server.socket=context.wrap_socket(server.socket,server_side=True)
    port = server.server_address[1]
    log.info("Data service running at %s://%s:%s", 'https' if tls_cert else 'http', host, port)
    print(f"Nanza Accounting server running at {'https' if tls_cert else 'http'}://{host}:{port}")
    print("For a new database, sign in as admin with this one-time initial password:")
    print(admin_password)
    if on_ready: on_ready(port)
    server.serve_forever()

def main():
    parser = argparse.ArgumentParser(description="Nanza Accounting shared server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", default=None, help="Main data file (default: the Nanza data folder)")
    parser.add_argument("--admin-password", default=None,
                        help="Initial admin password (or set SABER_ADMIN_PASSWORD)")
    parser.add_argument("--tls-cert",help="Path to a trusted TLS certificate chain (PEM)")
    parser.add_argument("--tls-key",help="Path to the matching TLS private key (PEM)")
    parser.add_argument("--allow-insecure-lan",action="store_true",help="Explicitly permit plaintext on a trusted VPN/LAN")
    parser.add_argument("--make-certificate",metavar="NAMES",help="Make an office certificate for these server names / IPs (comma separated) and exit")
    args = parser.parse_args()
    if args.make_certificate:
        import app_runtime, office_tls
        cert, key = office_tls.make_certificate(app_runtime.data_dir(), args.make_certificate)
        print(f"Certificate: {cert}\nPrivate key (keep on this computer only): {key}")
        print(f"Copy the certificate to each office PC as <Nanza data folder>\\{office_tls.TRUSTED_CERT_NAME}, then start the server with:")
        print(f"  run_server.py --host 0.0.0.0 --tls-cert \"{cert}\" --tls-key \"{key}\"")
        return
    if not args.database:
        import app_runtime
        args.database = str(app_runtime.main_database_path())
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    run_server(args.host,args.port,args.database,args.admin_password,args.tls_cert,args.tls_key,args.allow_insecure_lan)

if __name__ == "__main__":
    main()
