from __future__ import annotations
import logging

import json
import base64
import http.client
import socket
import ssl
import threading
import time
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit

class SessionExpired(RuntimeError):
    """Raised when the server no longer accepts the saved sign-in."""


# Reference lists the screens ask for again and again while they are built (the chart of accounts
# alone was requested ~40 times when a company opened). Their answers are kept for a few seconds
# and dropped immediately after ANY change the program sends, so what you see is always current.
CACHED_PATHS = ("/api/accounts", "/api/branches", "/api/currencies", "/api/exchange-rates", "/api/parties",
                "/api/projects", "/api/departments", "/api/settings", "/api/dimension-settings", "/api/inventory/items",
                "/api/inventory/warehouses", "/api/inventory/categories", "/api/me")
CACHE_SECONDS = 60.0  # 2.9.91: lists that rarely change (chart, parties...); any change made here clears them at once


class ApiClient:
    def __init__(self, base_url="http://127.0.0.1:8765", on_unauthorized=None):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.company_id = None
        self.fiscal_year = None
        self.on_unauthorized = on_unauthorized
        self.confirm_negative_stock = None  # callable(message) -> bool, set by the desktop window
        self.confirm_duplicate = None  # 2.9.103: callable(message) -> bool - an invoice / expense with the same number is already saved
        self._local = threading.local()      # one kept-open connection per thread
        self._cache = {}; self._cache_lock = threading.Lock()

    # ------------------------------------------------------------ connection handling
    def _connection(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise URLError(f"invalid server address {self.base_url}")
            if parts.scheme == "https":
                context = ssl.create_default_context()
                try:  # 2.9.94: the office server certificate copied to this PC (see office_tls.py)
                    import office_tls
                    trusted = office_tls.trusted_certificate()
                    if trusted: context.load_verify_locations(cafile=str(trusted))
                except (OSError, ssl.SSLError) as exc:
                    logging.getLogger("saber.client").warning("Office server certificate not loaded: %s", exc)
                connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=60, context=context)
            else:
                connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)
            connection.connect()
            try: connection.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (OSError, AttributeError): pass
            self._local.connection = connection; self._local.prefix = parts.path.rstrip("/")
        return connection

    def _drop_connection(self):
        connection = getattr(self._local, "connection", None); self._local.connection = None
        if connection is not None:
            try: connection.close()
            except Exception: pass  # closing a connection; may run while Python shuts down

    def _send(self, method, path, data, headers):
        """One HTTP exchange on the kept-open connection. A connection the server already closed is
        reopened once; only a GET is ever repeated after it may have reached the server."""
        for attempt in (1, 2):
            sent = False
            try:
                connection = self._connection()
                connection.request(method, self._local.prefix + path, body=data, headers=headers); sent = True
                response = connection.getresponse(); payload = response.read()
                if response.getheader("Connection", "").lower() == "close" or response.version == 10: self._drop_connection()
                return response.status, payload
            except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, http.client.CannotSendRequest, http.client.BadStatusLine) as exc:
                self._drop_connection()
                if attempt == 2 or (sent and method != "GET"): raise URLError(exc) from exc
            except socket.timeout as exc:
                self._drop_connection(); raise TimeoutError(str(exc)) from exc
            except OSError as exc:
                self._drop_connection(); raise URLError(exc) from exc

    def close(self):
        self._drop_connection()

    def __del__(self):
        try: self._drop_connection()
        except Exception: pass  # runs while Python shuts down: no logging here

    def _local_key(self):
        """The secret of the private data service - sent only to that exact address, never to a shared server."""
        try:
            import app_runtime
        except ImportError:
            return None
        if app_runtime.LOCAL_KEY and app_runtime.LOCAL_URL and self.base_url == app_runtime.LOCAL_URL.rstrip("/"):
            return app_runtime.LOCAL_KEY
        return None

    def clear_cache(self):
        with self._cache_lock: self._cache.clear()

    def request(self, method, path, body=None):
        cacheable = method == "GET" and path.split("?", 1)[0] in CACHED_PATHS
        key = (self.token, self.company_id, self.fiscal_year, path)
        if cacheable:
            with self._cache_lock: hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS: return json.loads(hit[1])
        elif method != "GET":
            self.clear_cache()  # anything may have changed
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.company_id: headers["X-Company-ID"]=str(self.company_id)
        if self.fiscal_year: headers["X-Fiscal-Year"]=str(self.fiscal_year)
        key = self._local_key()
        if key: headers["X-Saber-Key"] = key
        try:
            status, payload = self._send(method, path, data, headers)
        except URLError as exc:
            raise RuntimeError(f"Cannot reach the Saber Accounting data service at {self.base_url}. "
                               "Check that the server computer is on and the address is correct.") from exc
        except TimeoutError as exc:
            raise RuntimeError("The data service took too long to answer. Please try again.") from exc
        if status >= 400 and not headers.get("X-Allow-Negative-Stock"):
            try: text = json.loads(payload.decode("utf-8")).get("error", "")
            except Exception: text = ""
            # Negative stock: ask the user (callback set by the window); when confirmed, send the same request again.
            if str(text).startswith("[NEGATIVE_STOCK] ") and self.confirm_negative_stock:
                if self.confirm_negative_stock(text[len("[NEGATIVE_STOCK] "):]):
                    headers["X-Allow-Negative-Stock"] = "1"
                    self.clear_cache()
                    status, payload = self._send(method, path, data, headers)
                else:
                    raise RuntimeError("Not saved: stock would go below zero.")
        if status >= 400:
            try: message = json.loads(payload.decode("utf-8")).get("error", f"HTTP Error {status}")
            except Exception: message = f"The server returned an error ({status}). Please try again."
            message = str(message).replace("[NEGATIVE_STOCK] ", "")
            if status == 401 and path != "/api/login" and self.token:
                self.token = None; self.clear_cache()
                if self.on_unauthorized:
                    try: self.on_unauthorized()
                    except Exception: logging.getLogger("saber.client").warning("Sign-out screen could not be shown", exc_info=True)
                raise SessionExpired("Your session has ended. Please sign in again.")
            raise RuntimeError(message)
        result = json.loads(payload.decode("utf-8"))
        if cacheable:
            with self._cache_lock: self._cache[key] = (time.monotonic(), payload)
        return result

    def login(self, username, password):
        result = self.request("POST", "/api/login", {"username": username, "password": password})
        self.token = result["token"]
        return result

    def dashboard(self): return self.request("GET", "/api/dashboard")["items"]
    def companies(self): return self.request("GET","/api/companies")["items"]
    def create_company(self,item): return self.request("POST","/api/companies",item)["company"]
    def update_company(self,company_id,item): return self.request("PUT",f"/api/companies/{company_id}",item)["company"]
    def import_company_file(self,path): return self.request("POST","/api/companies/import",{"path":str(path)})["company"]  # 2.9.108
    def create_fiscal_year(self,company_id,year): return self.request("POST","/api/companies/year",{"company_id":company_id,"year":year})["company"]
    def select_company_year(self,company_id,year): self.company_id=company_id; self.fiscal_year=int(year)
    def professional_dashboard(self): return self.request("GET","/api/dashboard/professional")
    def dashboard_conversion(self,source,target,date):
        return self.request("GET","/api/dashboard/conversion?"+urlencode({"source":source,"target":target,"date":date}))
    def invoices(self): return self.request("GET", "/api/invoices")["items"]
    def accounts(self): return self.request("GET", "/api/accounts")["items"]
    def next_account_number(self,prefix): return self.request("GET",f"/api/accounts/next-number?{urlencode({'prefix':prefix})}")["account_number"]
    def save_account(self,item): return self.request("POST","/api/accounts",item)["account"]
    def rename_account(self,code,name): return self.request("PUT",f"/api/accounts/{code}",{"name_en":name})["account"]
    def account_usage(self,codes=None): return self.request("GET","/api/accounts/usage?"+urlencode({"codes":",".join(codes or [])}))["items"]
    def unused_accounts(self,scope="all"): return self.request("GET","/api/accounts/unused?"+urlencode({"scope":scope}))["items"]
    def delete_accounts(self,codes): return self.request("POST","/api/accounts/delete",{"codes":list(codes)})
    def move_account(self,source,target,merge_party=False): return self.request("POST","/api/accounts/move",{"from":source,"to":target,"merge_party":merge_party})
    def account_lines(self,code,date_from=None,date_to=None): return self.request("GET","/api/accounts/lines?"+urlencode({k:v for k,v in {"code":code,
            "from":date_from,"to":date_to}.items() if v}))["items"]
    def sales_account_problems(self): return self.request("GET","/api/invoices/account-check")["items"]
    def fix_sales_accounts(self,invoice_ids): return self.request("POST","/api/invoices/account-fix",{"invoice_ids":list(invoice_ids)})
    def set_invoices_account(self,invoice_ids,field,account): return self.request("POST","/api/invoices/set-account",{"invoice_ids":list(invoice_ids),"field":field,"account":account})
    def move_account_lines(self,source,target,line_ids,change_party=True): return self.request("POST","/api/accounts/move-lines",{"from":source,"to":target,
            "line_ids":list(line_ids),"change_party":change_party})
    def transfer_account_balance(self,source,target,date,description=""): return self.request("POST","/api/accounts/transfer-balance",{"from":source,"to":target,"date":date,"description":description})
    def update_account(self,code,item): return self.request("PUT",f"/api/accounts/{code}",item)["account"]
    def parties(self): return self.request("GET", "/api/parties")["items"]
    def branches(self): return self.request("GET","/api/branches")["items"]
    def save_branch(self,name): return self.request("POST","/api/branches",{"name":name})["branch"]
    def statement(self, party_id, from_date=None, to_date=None, currency=None, include_opening=True, display_currency=None, branch_id=None):
        query = urlencode({key:value for key,value in {
            "party_id":party_id,"from_date":from_date,"to_date":to_date,"currency":currency,
            "include_opening":"true" if include_opening else "false","display_currency":display_currency,"branch_id":branch_id
        }.items() if value})
        return self.request("GET", f"/api/statement?{query}")
    def add_invoice_item(self, invoice_id, item):
        return self.request("POST", f"/api/invoices/{invoice_id}/items", {"item":item})["invoice"]
    def trial_balance(self, from_date=None, to_date=None, account=None, include_subaccounts=True, account_from=None, account_to=None, branch_id=None, posting_status="posted"):
        query = urlencode({key: value for key, value in {
            "from_date": from_date, "to_date": to_date,"account":account,"include_subaccounts":"true" if include_subaccounts else "false",
                    "account_from":account_from,"account_to":account_to,"branch_id":branch_id,"posting_status":posting_status
        }.items() if value})
        path = "/api/trial-balance" + (f"?{query}" if query else "")
        return self.request("GET", path)["items"]
    def journal(self, from_date=None, to_date=None, currency=None, entry_number=None, source_type=None):
        query = urlencode({key: value for key, value in {
            "from_date": from_date, "to_date": to_date, "currency": currency, "entry_number": entry_number, "source_type": source_type
        }.items() if value})
        path = "/api/journal" + (f"?{query}" if query else "")
        return self.request("GET", path)["items"]
    def import_invoices(self, items, replace_existing=True): return self.request("POST", "/api/invoices/import", {"items": items, "replace_existing": replace_existing})
    def create_manual_invoice(self, invoice, items):
        invoice = dict(invoice); checked = invoice.pop("duplicate_ok", False)
        if not checked: self._check_duplicate_invoice(invoice)
        return self.request("POST", "/api/invoices/manual", {"invoice": invoice, "items": items})

    def _check_duplicate_invoice(self, invoice):
        """2.9.103: on every screen (purchases, expenses as invoices, sales, assets, uploads): the same supplier / customer and
        the same invoice number already saved -> warning; not saved unless the user confirms."""
        if not self.confirm_duplicate or not str(invoice.get("invoice_number") or "").strip(): return
        try: found = self.invoice_duplicates([invoice])[0]
        except Exception: return
        if not found: return
        old = found[0]
        text = (f"WARNING - already saved: invoice {invoice.get('invoice_number')} of {old.get('party_name') or invoice.get('party_name')} "
                f"(ID {old['id']}, {old.get('invoice_date')}, total {float(old.get('total') or 0):,.2f} {old.get('currency') or ''})"
                + (f" and {len(found) - 1} more" if len(found) > 1 else "") + ".\n\nSave it again anyway?")
        if not self.confirm_duplicate(text): raise RuntimeError(f"Not saved: invoice {invoice.get('invoice_number')} of this supplier / customer is already saved.")
    def update_invoice(self, invoice_id, invoice): return self.request("PUT", f"/api/invoices/{invoice_id}", {"invoice": invoice})
    def invoice_duplicates(self, items): return self.request("POST","/api/invoices/duplicates",{"items":items})["items"]
    def create_missing_invoice_payments(self): return self.request("POST","/api/invoices/payment-entries",{})
    def delete_invoice(self,invoice_id): return self.request("DELETE",f"/api/invoices/{invoice_id}")
    def delete_journal_voucher(self,entry_id): return self.request("DELETE",f"/api/journal/{entry_id}")
    def delete_opening_voucher(self,entry_id): return self.request("DELETE",f"/api/opening-vouchers/{entry_id}")
    def journal_voucher(self,entry_id): return self.request("GET",f"/api/journal-vouchers/{entry_id}")
    def save_journal_voucher(self,voucher,lines,entry_id=None): return self.request("PUT" if entry_id else "POST",
            f"/api/journal-vouchers/{entry_id}" if entry_id else "/api/journal-vouchers",{"voucher":voucher,"lines":lines})
    def fixed_assets(self): return self.request("GET","/api/fixed-assets")["items"]
    def asset_schedule(self,asset_id): return self.request("GET",f"/api/fixed-assets/{asset_id}/schedule")["items"]
    def asset_rollforward(self,year): return self.request("GET",f"/api/fixed-assets/rollforward?year={year}")
    def save_asset(self,item,asset_id=None): return self.request("PUT" if asset_id else "POST",f"/api/fixed-assets/{asset_id}" if asset_id else "/api/fixed-assets",item)["asset"]
    def asset_attachments(self,asset_id): return self.request("GET",f"/api/fixed-assets/{asset_id}/attachments")["items"]
    def upload_asset_attachment(self,asset_id,file_name,mime_type,content):
        if not content or len(content)>15*1024*1024:
            raise ValueError("Asset PDF attachment must be non-empty and cannot exceed 15 MB")
        return self.request("POST",f"/api/fixed-assets/{asset_id}/attachments",{
            "file_name":file_name,"mime_type":mime_type,"content":base64.b64encode(content).decode("ascii")})
    def download_asset_attachment(self,attachment_id):
        result=self.request("GET",f"/api/fixed-asset-attachments/{attachment_id}")
        result["content"]=base64.b64decode(result["content"])
        return result
    def post_asset_period(self,asset_id,period_end): return self.request("POST",f"/api/fixed-assets/{asset_id}/post",{"period_end":period_end})["voucher"]
    def delete_asset(self,asset_id): return self.request("DELETE",f"/api/fixed-assets/{asset_id}")
    def invoice_detail(self, invoice_id): return self.request("GET",f"/api/invoices/{invoice_id}/detail")
    def create_invoice_return(self, invoice_id, items, return_date=None, request_id=None):
        return self.request("POST",f"/api/invoices/{invoice_id}/returns",{
            "items":items,"return_date":return_date,"request_id":request_id})["invoice"]
    def cancel_invoice(self, invoice_id, reason): return self.request("POST",f"/api/invoices/{invoice_id}/cancel",{"reason":reason})["invoice"]
    def duplicate_invoice(self, invoice_id): return self.request("POST",f"/api/invoices/{invoice_id}/duplicate",{})["invoice"]
    def invoice_history(self, invoice_id): return self.request("GET",f"/api/invoices/{invoice_id}/history")["items"]
    def cash_check(self, account, currency, date, amount): return self.request("GET","/api/cash-check?"+urlencode({"account":account,"currency":currency,"date":date,"amount":amount}))  # 2.9.84
    def audit_log(self, **filters): return self.request("GET","/api/audit-log?"+urlencode({k:v for k,v in filters.items() if v not in (None,"")}))  # 2.9.84
    def attachments(self, invoice_id): return self.request("GET",f"/api/invoices/{invoice_id}/attachments")["items"]
    def upload_attachment(self, invoice_id, file_name, mime_type, content):
        return self.request("POST",f"/api/invoices/{invoice_id}/attachments",{
            "file_name":file_name,"mime_type":mime_type,"content":base64.b64encode(content).decode("ascii")})
    def download_attachment(self, attachment_id):
        result=self.request("GET",f"/api/attachments/{attachment_id}"); result["content"]=base64.b64decode(result["content"]); return result
    def document_cases(self): return self.request("GET","/api/document-cases")["items"]
    def save_document_case(self,item): return self.request("POST","/api/document-cases",item)["case"]
    def post_document_case(self,case_id): return self.request("POST",f"/api/document-cases/{case_id}/post",{})["case"]
    def case_attachments(self,case_id): return self.request("GET",f"/api/document-cases/{case_id}/attachments")["items"]
    def upload_case_attachment(self,case_id,role,file_name,mime_type,content):
        return self.request("POST",f"/api/document-cases/{case_id}/attachments",{"document_role":role,"file_name":file_name,"mime_type":mime_type,"content":base64.b64encode(content).decode("ascii")})
    def download_case_attachment(self,attachment_id):
        result=self.request("GET",f"/api/case-attachments/{attachment_id}"); result["content"]=base64.b64decode(result["content"]); return result
    def party_documents(self,party_id): return self.request("GET",f"/api/parties/{party_id}/documents")["items"]
    def upload_party_document(self,party_id,item,content=b""):
        return self.request("POST",f"/api/parties/{party_id}/documents",{**item,"content":base64.b64encode(content or b"").decode("ascii")})
    def update_party_document(self,document_id,item,content=b""):
        return self.request("PUT",f"/api/party-documents/{document_id}",{**item,"content":base64.b64encode(content or b"").decode("ascii")})
    def download_party_document(self,document_id):
        result=self.request("GET",f"/api/party-documents/{document_id}"); result["content"]=base64.b64decode(result["content"]); return result
    def profit_loss(self, from_date=None, to_date=None, currency=None, convert=False):
        # 2.9.80: convert=True gives every transaction converted into the currency (planning tools); False = entered in it
        query=urlencode({k:v for k,v in {"from_date":from_date,"to_date":to_date,"currency":currency,"convert":"1" if convert else None}.items() if v})
        return self.request("GET","/api/profit-loss"+(f"?{query}" if query else ""))["items"]
    def fiscal_years(self): return self.request("GET","/api/fiscal-years")["items"]
    def close_fiscal_year(self, year): return self.request("POST","/api/fiscal-years/close",{"year":year})
    def reopen_fiscal_year(self, year): return self.request("POST","/api/fiscal-years/reopen",{"year":year})
    def refresh_opening(self, source_year): return self.request("POST","/api/fiscal-years/refresh-opening",{"source_year":source_year})
    def fiscal_year_profit_loss(self,year,from_date=None,to_date=None,currency=None,convert=False):
        query=urlencode({k:v for k,v in {"year":year,"from_date":from_date,"to_date":to_date,"currency":currency,"convert":"1" if convert else None}.items() if v})
        return self.request("GET",f"/api/fiscal-year/profit-loss?{query}")["items"]
    def fiscal_year_cash_flow(self,year,from_date=None,to_date=None,currency=None,convert=False):
        query=urlencode({k:v for k,v in {"year":year,"from_date":from_date,"to_date":to_date,"currency":currency,"convert":"1" if convert else None}.items() if v})
        return self.request("GET",f"/api/fiscal-year/cash-flow?{query}")["items"]
    def fiscal_year_balance_sheet(self,year,to_date=None,currency=None,convert=False):
        query=urlencode({k:v for k,v in {"year":year,"to_date":to_date,"currency":currency,"convert":"1" if convert else None}.items() if v})
        return self.request("GET",f"/api/fiscal-year/balance-sheet?{query}")["items"]
    def fiscal_year_journal(self,year,from_date=None,to_date=None,currency=None):
        query=urlencode({k:v for k,v in {"year":year,"from_date":from_date,"to_date":to_date,"currency":currency}.items() if v})
        return self.request("GET",f"/api/fiscal-year/journal?{query}")["items"]
    def save_party(self, item): return self.request("POST","/api/parties",item)["party"]
    def payments(self): return self.request("GET","/api/payments")["items"]
    def add_payment(self, item): return self.request("POST","/api/payments",item)
    def expenses(self): return self.request("GET","/api/expenses")["items"]
    def tax_flags(self,source_type): return set(self.request("GET",f"/api/tax-flags?source_type={source_type}")["ids"])  # 2.9.113
    def set_tax_flag(self,source_type,source_id,not_deductible):
        return self.request("POST","/api/tax-flags",{"source_type":source_type,"source_id":source_id,"not_deductible":bool(not_deductible)})
    def non_deductible_expenses(self,year=None): return self.request("GET","/api/expenses/non-deductible"+(f"?year={year}" if year else ""))["items"]  # 2.9.110
    def add_expense(self, item):
        item = dict(item); checked = item.pop("duplicate_ok", False)
        reference = str(item.get("reference") or "").strip()
        if reference and not checked and self.confirm_duplicate:  # 2.9.103: the same invoice / reference number already saved
            try: same = [e for e in self.expenses() if str(e.get("reference") or "").strip().casefold() == reference.casefold()
                         and str(e.get("status") or "posted") not in ("cancelled", "deleted")]
            except Exception: same = []
            if same:
                old = same[0]
                text = (f"WARNING - already saved: expense with invoice / reference {reference} ({old.get('expense_number') or old.get('id')}, "
                        f"{old.get('expense_date')}, {old.get('description') or ''}).\n\nSave it again anyway?")
                if not self.confirm_duplicate(text): raise RuntimeError(f"Not saved: an expense with reference {reference} is already saved.")
        return self.request("POST","/api/expenses",item)
    def general_ledger(self, account=None, from_date=None, to_date=None, currency=None):
        query=urlencode({k:v for k,v in {"account":account,"from_date":from_date,"to_date":to_date,"currency":currency}.items() if v})
        return self.request("GET","/api/general-ledger"+(f"?{query}" if query else ""))
    def balance_sheet(self, to_date=None, currency=None, convert=False):
        query=urlencode({k:v for k,v in {"to_date":to_date,"currency":currency,"convert":"1" if convert else None}.items() if v})
        return self.request("GET","/api/balance-sheet"+(f"?{query}" if query else ""))["items"]
    def vat_report(self, from_date=None, to_date=None, currency=None):
        query=urlencode({k:v for k,v in {"from_date":from_date,"to_date":to_date,"currency":currency}.items() if v})
        return self.request("GET","/api/vat-report"+(f"?{query}" if query else ""))
    def cash_flow(self,from_date=None,to_date=None,currency=None,convert=False):
        query=urlencode({k:v for k,v in {"from_date":from_date,"to_date":to_date,"currency":currency,
                "convert":"1" if convert else None}.items() if v}); return self.request("GET","/api/cash-flow"+(f"?{query}" if query else ""))["items"]
    def aging(self,as_of_date=None,kind=None,currency=None):
        query=urlencode({k:v for k,v in {"as_of_date":as_of_date,"kind":kind,"currency":currency}.items() if v}); return self.request("GET","/api/aging"+(f"?{query}" if query else ""))["items"]
    def comparative_reports(self,from_date,to_date,currency=None):
        query=urlencode({k:v for k,v in {"from_date":from_date,"to_date":to_date,"currency":currency}.items() if v}); return self.request("GET",f"/api/comparative-reports?{query}")
    def users(self): return self.request("GET","/api/users")["items"]
    def save_user(self,item): return self.request("POST","/api/users",item)["user"]
    def backups(self): return self.request("GET","/api/backups")["items"]
    def create_backup(self): return self.request("POST","/api/backups/create",{})
    def scheduled_backup(self): return self.request("POST","/api/backups/scheduled",{})
    def books_lock(self): return self.request("GET","/api/books-lock")
    def set_books_lock(self,date): return self.request("POST","/api/books-lock",{"locked_until":date})
    def restore_backup(self,name): return self.request("POST","/api/backups/restore",{"name":name})
    def settings(self): return self.request("GET","/api/settings")
    def save_settings(self,item): return self.request("POST","/api/settings",item)
    def exchange_rates(self): return self.request("GET","/api/exchange-rates")["items"]
    def currencies(self): return self.request("GET","/api/currencies")["items"]
    def save_currency(self,code,name): return self.request("POST","/api/currencies",{"code":code,"name":name})["currency"]
    def save_exchange_rate(self,item): return self.request("POST","/api/exchange-rates",item)
    def restore_euro_rates(self): return self.request("POST","/api/exchange-rates/restore-euro",{})
    def restore_all_rates(self): return self.request("POST","/api/exchange-rates/restore-all",{})
    def employees(self): return self.request("GET","/api/employees")["items"]
    def next_employee_number(self,prefix="1000"):
        return self.request("GET",f"/api/employees/next-number?{urlencode({'prefix':prefix})}")["employee_number"]
    def save_employee(self,item): return self.request("POST","/api/employees",item)["employee"]
    def payroll(self,from_date=None,to_date=None):
        query=urlencode({k:v for k,v in {"from_date":from_date,"to_date":to_date}.items() if v})
        return self.request("GET","/api/payroll"+(f"?{query}" if query else ""))["items"]
    def calculate_payroll(self,item): return self.request("POST","/api/payroll/calculate",item)
    def save_payroll(self,item): return self.request("POST","/api/payroll",item)["payroll"]
    def post_payroll(self,payroll_id): return self.request("POST",f"/api/payroll/{payroll_id}/post",{})["payroll"]
    def payroll_settings(self,date=None):
        return self.request("GET","/api/payroll/settings"+(f"?{urlencode({'date':date})}" if date else ""))
    def save_payroll_settings(self,item): return self.request("POST","/api/payroll/settings",item)
    def me(self): return self.request("GET","/api/me")
    def payroll_settings_list(self): return self.request("GET","/api/payroll/settings/list")["items"]
    def payroll_report(self,report,period_type,year,index=1,group="both",include_drafts=False):
        query=urlencode({"report":report,"period_type":period_type,"year":year,"index":index,"group":group,"include_drafts":"true" if include_drafts else "false"})
        return self.request("GET",f"/api/payroll/reports?{query}")
    def nssf_filed_wages(self,year): return self.request("GET",f"/api/payroll/nssf-filed?{urlencode({'year':year})}")["items"]
    def save_nssf_filed_wages(self,item): return self.request("POST","/api/payroll/nssf-filed",item)["item"]
    def vat_return(self,year,quarter,currency=None,include_review=False,credit_brought_forward=None,refund_requested=None):
        query=urlencode({k:v for k,v in {"year":year,"quarter":quarter,"currency":currency,"include_review":"true" if include_review else "false",
            "credit_brought_forward":credit_brought_forward,"refund_requested":refund_requested}.items() if v not in (None,"")})
        return self.request("GET",f"/api/vat-return?{query}")
    def vat_returns(self): return self.request("GET","/api/vat-returns")["items"]
    def eos_provision(self,date): return self.request("GET",f"/api/payroll/eos-provision?{urlencode({'date':date})}")
    def post_eos_provision(self,date): return self.request("POST","/api/payroll/eos-provision",{"date":date})
    def leave_records(self,year=None): return self.request("GET","/api/payroll/leave"+(f"?{urlencode({'year':year})}" if year else ""))["items"]
    def save_leave(self,item): return self.request("POST","/api/payroll/leave",item)
    def delete_leave(self,leave_id): return self.request("DELETE",f"/api/payroll/leave/{leave_id}")
    def leave_balances(self,date): return self.request("GET",f"/api/payroll/leave-balances?{urlencode({'date':date})}")
    def payslips(self,month_end): return self.request("GET",f"/api/payroll/payslips?{urlencode({'month_end':month_end})}")["sections"]
    def management_pack(self,month_end,currency="USD"): return self.request("GET",f"/api/management-pack?{urlencode({'month_end':month_end,'currency':currency})}")
    def budget_alerts(self,year,month,currency="USD",threshold=10): return self.request("GET",
            f"/api/budget-alerts?{urlencode({'year':year,'month':month,'currency':currency,'threshold':threshold})}")["items"]
    def accounting_setup(self): return self.request("GET","/api/accounting-setup")
    def save_accounting_setup(self,item): return self.request("POST","/api/accounting-setup",item)
    def save_my_hidden(self,hidden): return self.request("POST","/api/accounting-setup/user",{"hidden":list(hidden)})["user_hidden"]
    def year_end_check(self,year): return self.request("GET",f"/api/year-end-check?{urlencode({'year':year})}")
    def vat_check(self,year,quarter,credit_brought_forward=None,refund_requested=None,payable_account=None,credit_account=None,non_deductible_account=None):
        query=urlencode({k:v for k,v in {"year":year,"quarter":quarter,"credit_brought_forward":credit_brought_forward,"refund_requested":refund_requested,
            "payable_account":payable_account,"credit_account":credit_account,"non_deductible_account":non_deductible_account}.items() if v not in (None,"")})
        return self.request("GET",f"/api/vat-return/check?{query}")
    def post_vat_settlement(self,year,quarter,payable_account=None,credit_account=None,non_deductible_account=None):
        return self.request("POST","/api/vat-return/settle",{"year":year,"quarter":quarter,"payable_account":payable_account,"credit_account":credit_account,
                "non_deductible_account":non_deductible_account})
    def add_vat_adjustment(self,item): return self.request("POST","/api/vat-return/adjustments",item)
    def delete_vat_adjustment(self,adjustment_id): return self.request("DELETE",f"/api/vat-return/adjustments/{adjustment_id}")
    def save_vat_return(self,year,quarter,credit_brought_forward=None,refund_requested=None):
        return self.request("POST","/api/vat-return/save",{"year":year,"quarter":quarter,"credit_brought_forward":credit_brought_forward,"refund_requested":refund_requested})
    def save_vat_ratio(self,year,ratio): return self.request("POST","/api/vat-ratio",{"year":year,"ratio":ratio})["ratio"]
    def set_vat_classification(self,source,document_id,vat_treatment=None,vat_use=None):
        return self.request("POST","/api/vat-classification",{"source":source,"id":document_id,"vat_treatment":vat_treatment,"vat_use":vat_use})
    def reopen_vat_return(self,year,quarter): return self.request("POST","/api/vat-return/reopen",{"year":year,"quarter":quarter})
    def set_vat_recoverable(self,source,document_id,recoverable):
        return self.request("POST","/api/vat-recoverable",{"source":source,"id":document_id,"recoverable":bool(recoverable)})
    def document_alerts(self,days=30): return self.request("GET",f"/api/alerts/documents?{urlencode({'days':days})}")
    def next_invoice_number(self,kind="sale",date=None):
        return self.request("GET","/api/invoices/next-number?"+urlencode({k:v for k,v in {"kind":kind,"date":date}.items() if v}))["invoice_number"]
    def next_party_account_number(self,prefix): return self.request("GET",f"/api/parties/next-number?{urlencode({'prefix':prefix})}")["account_number"]
    def invoice_items(self,invoice_id): return self.request("GET",f"/api/invoices/{invoice_id}/items")["items"]
    def account_report(self,options): return self.request("GET","/api/reports/accounts?"+urlencode({"options":json.dumps(options)}))
    def suggested_rates(self,currency,date=None): return self.request("GET","/api/rates/suggest?"+urlencode({k:v for k,v in {"currency":currency,"date":date}.items() if v}))
    def doe_candidates(self,date,basis="LBP"): return self.request("GET","/api/doe/candidates?"+urlencode({"date":date,"basis":basis}))
    def departments(self): return self.request("GET","/api/departments")["items"]
    def save_department(self,item): return self.request("POST","/api/departments",item)["item"]
    def projects(self): return self.request("GET","/api/projects")["items"]
    def save_project(self,item): return self.request("POST","/api/projects",item)["item"]
    def budgets(self,year,currency="USD",department=None,project=None):
        return self.request("GET","/api/budgets?"+urlencode({k:v for k,v in {"year":year,"currency":currency,"department":department,"project":project}.items() if v}))["items"]
    def save_budget(self,item): return self.request("POST","/api/budgets",item)["item"]
    def next_document_number(self,kind,date=None): return self.request("GET","/api/documents/next-number?"+urlencode({k:v for k,v in {"kind":kind,"date":date}.items() if v}))["number"]
    def update_payment(self,payment_id,item): return self.request("PUT",f"/api/payments/{payment_id}",item)["id"]
    def delete_payment(self,payment_id): return self.request("DELETE",f"/api/payments/{payment_id}")
    def update_expense(self,expense_id,item): return self.request("PUT",f"/api/expenses/{expense_id}",item)["id"]
    def delete_expense(self,expense_id): return self.request("DELETE",f"/api/expenses/{expense_id}")
    def expense_attachments(self,expense_id): return self.request("GET",f"/api/expenses/{expense_id}/attachments")["items"]
    def upload_expense_attachment(self,expense_id,file_name,mime_type,content):
        return self.request("POST",f"/api/expenses/{expense_id}/attachments",{"file_name":file_name,"mime_type":mime_type,"content":base64.b64encode(content).decode("ascii")})
    def download_expense_attachment(self,attachment_id):
        result=self.request("GET",f"/api/expense-attachments/{attachment_id}"); result["content"]=base64.b64decode(result["content"]); return result
    def replace_invoice(self,invoice_id,invoice,items): return self.request("POST",f"/api/invoices/{invoice_id}/replace",{"invoice":invoice,"items":items})["invoice_id"]
    def add_landed_cost(self,purchase_id,item): return self.request("POST",f"/api/invoices/{purchase_id}/landed-cost",item)["invoice_id"]
    def landed_costs(self,purchase_id): return self.request("GET",f"/api/invoices/{purchase_id}/landed-costs")["items"]
    def closing_preview(self,year): return self.request("GET",f"/api/fiscal-years/closing-preview?{urlencode({'year':year})}")
    def apply_lebanese_payroll_rules(self): return self.request("POST","/api/payroll/apply-lebanese-rules",{})["items"]
    def inventory_items(self,date=None): return self.request("GET","/api/inventory/items"+(f"?{urlencode({'date':date})}" if date else ""))["items"]
    def save_inventory_item(self,item): return self.request("POST","/api/inventory/items",item)["item"]
    def warehouses(self): return self.request("GET","/api/inventory/warehouses")["items"]
    def save_warehouse(self,item): return self.request("POST","/api/inventory/warehouses",item)["item"]
    def inventory_settings(self): return self.request("GET","/api/inventory/settings")
    def inventory_brands(self): return self.request("GET","/api/inventory/brands")["items"]
    def similar_items(self,name): return self.request("GET","/api/inventory/similar?"+urlencode({"name":name}))["items"]
    def save_inventory_settings(self,item): return self.request("POST","/api/inventory/settings",item)
    def stock_documents(self): return self.request("GET","/api/inventory/documents")["items"]
    def stock_document(self,document_id): return self.request("GET",f"/api/inventory/documents/{document_id}")
    def save_stock_document(self,header,lines,document_id=None): return self.request("POST","/api/inventory/documents",{"header":header,"lines":lines,"id":document_id})
    def delete_stock_document(self,document_id): return self.request("DELETE",f"/api/inventory/documents/{document_id}")
    def next_stock_number(self,doc_type,date): return self.request("GET","/api/inventory/next-number?"+urlencode({"type":doc_type,"date":date}))["number"]
    def inventory_report(self,report,options): return self.request("GET","/api/inventory/report?"+urlencode({"report":report,"options":json.dumps(options)}))
    def post_stock_variation(self,year): return self.request("POST","/api/inventory/stock-variation",{"year":year})
    def post_monthly_stock_variation(self,month_end): return self.request("POST","/api/inventory/monthly-variation",{"month_end":month_end})
    def record_nssf_payment(self,item): return self.request("POST","/api/payroll/nssf-payment",item)
    def open_documents(self,party_id): return self.request("GET",f"/api/parties/{party_id}/open-documents")["items"]
    def payment_allocations(self,payment_id): return self.request("GET",f"/api/payments/{payment_id}/allocations")["items"]
    def save_allocations(self,payment_id,allocations): return self.request("POST",f"/api/payments/{payment_id}/allocations",{"allocations":allocations})["items"]
    def item_categories(self): return self.request("GET","/api/inventory/categories")
    def save_item_category(self,item): return self.request("POST","/api/inventory/categories",item)
    def count_sheet(self,warehouse_id,date): return self.request("GET","/api/inventory/count-sheet?"+urlencode({"warehouse_id":warehouse_id,"date":date}))["items"]
    def physical_counts(self): return self.request("GET","/api/inventory/counts")["items"]
    def physical_count(self,count_id): return self.request("GET",f"/api/inventory/counts/{count_id}")
    def save_physical_count(self,header,lines,count_id=None,post=False): return self.request("POST","/api/inventory/counts",{"header":header,"lines":lines,"id":count_id,"post":post})
    # 2.9.65: production (recipes and production orders)
    def production_recipes(self): return self.request("GET","/api/production/recipes")["items"]
    def production_recipe(self,item): return self.request("GET","/api/production/recipe?"+urlencode({"item":item}))
    def save_production_recipe(self,item): return self.request("POST","/api/production/recipes",item)
    def delete_production_recipe(self,sku): return self.request("DELETE","/api/production/recipes/"+quote(str(sku),safe=""))
    def production_plan(self,item,quantity,warehouse=None,date=None): return self.request("GET","/api/production/plan?"+urlencode({k:v for k,v in {"item":item,
            "quantity":quantity,"warehouse":warehouse,"date":date}.items() if v not in (None,"")}))
    def production_orders(self): return self.request("GET","/api/production/orders")["items"]
    def production_order(self,order_id): return self.request("GET",f"/api/production/orders/{order_id}")
    def save_production_order(self,header,lines,order_id=None): return self.request("POST","/api/production/orders",{"header":header,"lines":lines,"id":order_id})
    def production_report(self,date_from,date_to): return self.request("GET","/api/production/report?"+urlencode({"from":date_from,"to":date_to}))
    def audit_report(self,date_from,date_to,late_days=30): return self.request("GET","/api/audit-report?"+urlencode({"date_from":date_from,"date_to":date_to,"late_days":late_days}))  # 2.9.97
    def approvals(self): return self.request("GET","/api/approvals")  # 2.9.100
    def approve_documents(self,entry_ids,invoice_ids=()): return self.request("POST","/api/approvals/approve",{"entry_ids":list(entry_ids),"invoice_ids":list(invoice_ids)})
    def tax_settings_report(self,date): return self.request("GET","/api/tax-settings-report?"+urlencode({"date":date}))  # 2.9.100
    def tax_adviser(self): return self.request("GET","/api/tax-adviser")
    def save_tax_adviser(self,item): return self.request("POST","/api/tax-adviser",item)
    def licence(self): return self.request("GET","/api/licence")  # 2.9.103: Installation ID and licence state (no sign-in needed)
    def install_licence(self,code): return self.request("POST","/api/licence",{"code":code})  # a code signed by the seller
    def tax_review(self,date): return self.request("GET","/api/tax-review?"+urlencode({"date":date}))  # 2.9.98
    def verify_audit_trail(self): return self.request("GET","/api/audit-verify")
    def vat_ledgers(self): return self.request("GET","/api/vat-ledgers")  # 2.9.97
    def save_vat_ledgers(self,item): return self.request("POST","/api/vat-ledgers",item)
    def create_vat_accounts(self,start_from=0): return self.request("POST","/api/vat-ledgers/create",{"start_from":start_from})
    def test_vat_accounts(self): return self.request("GET","/api/vat-ledgers/test")
    def approve_invoices(self,ids): return self.request("POST","/api/invoices/approve",{"ids":list(ids)})  # 2.9.93
    def set_item_details(self,items): return self.request("POST","/api/inventory/item-details",{"items":list(items)})  # 2.9.101
    def set_item_accounts(self,item_ids,cost_account=None,sales_account=None): return self.request("POST","/api/inventory/item-accounts",
            {"item_ids":list(item_ids),"cost_account":cost_account,"sales_account":sales_account})  # 2.9.90
    def find_or_create_item(self,name,unit="unit",sku=None,supplier_id=None): return self.request("POST","/api/inventory/find-or-create",{"name":name,
            "unit":unit,"sku":sku,"supplier_id":supplier_id})["item"]
    def delete_fiscal_year(self,year): return self.request("POST","/api/fiscal-years/delete",{"year":year})
    def download_backup(self,name):
        result=self.request("GET","/api/backups/download?"+urlencode({"name":name})); result["content"]=base64.b64decode(result["content"]); return result
    def backup_folder(self): return self.request("GET","/api/backups/folder")["folder"]
    def unbalanced_entries(self): return self.request("GET","/api/journal/unbalanced")["items"]
    def financial_config(self,year): return self.request("GET","/api/reports/financial-config?"+urlencode({"year":year}))
    def save_financial_config(self,year,config): return self.request("POST","/api/reports/financial-config",{"year":year,"config":config})
    def business_report(self,report,options): return self.request("GET","/api/reports/business?"+urlencode({"report":report,"options":json.dumps(options)}))
    def save_payroll_periods(self,periods): return self.request("POST","/api/payroll/periods",{"periods":periods})["items"]
    def delete_payroll_period(self,date_from): return self.request("POST","/api/payroll/delete-period",{"date_from":date_from})["items"]
    def dashboard_charts(self,year,basis="USD"): return self.request("GET","/api/reports/dashboard-charts?"+urlencode({"year":year,"basis":basis}))
    def bank_lines(self,account,currency,date_from,date_to,balance=None):
        return self.request("GET","/api/bank/lines?"+urlencode({k:v for k,v in {"account":account,"currency":currency,"from":date_from,"to":date_to,"balance":balance}.items() if v not in (None,"")}))
    def bank_action(self,action,item): return self.request("POST",f"/api/bank/{action}",item)
    def asset_categories(self): return self.request("GET","/api/asset-categories")["items"]
    def save_asset_category(self,item): return self.request("POST","/api/asset-categories",item)["items"]
    def asset_depreciation(self,month,account=None): return self.request("GET","/api/asset-depreciation?"+urlencode({k:v for k,v in {"month":month,"account":account}.items() if v}))
    def post_asset_depreciation(self,account_code,month): return self.request("POST","/api/asset-depreciation/post",{"account_code":account_code,"month":month})

