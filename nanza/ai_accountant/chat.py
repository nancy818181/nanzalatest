"""Free local books chat: model intent proposals, never model-generated SQL.

The host supplies a company-scoped Database and already-authorized principal.
No global default database is opened; ask_books(question) alone returns a
configuration message. All queries are read-only and parameterized.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from decimal import Decimal
import json
import re

_CONTEXT = ContextVar("nanza_books_context", default=None)
_SQL = """SELECT e.id,e.entry_number,e.entry_date,
    COALESCE(NULLIF(j.line_currency,''),e.currency) currency,
    j.debit,j.credit,j.line_currency,j.amount
    FROM journal_lines j JOIN journal_entries e ON e.id=j.entry_id
    JOIN accounts a ON a.id=j.account_id
    WHERE e.posting_status='posted' AND a.type='expense'
    AND a.active=1 AND a.id IN ({accounts})
    AND (CASE WHEN e.entry_date GLOB '??-??-????'
         THEN substr(e.entry_date,7,4)||'-'||substr(e.entry_date,4,2)||'-'||substr(e.entry_date,1,2)
         ELSE e.entry_date END) BETWEEN ? AND ?
    ORDER BY e.id,j.id LIMIT 50001"""


@contextmanager
def books_context(database, user):
    """Bind context for ask_books(question); host must enforce company access."""
    if not user:
        raise PermissionError("Authenticated company access is required")
    token = _CONTEXT.set((database, user))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _ollama_intent(question):
    try:
        import ollama
        import httpx
        client = ollama.Client(host="http://127.0.0.1:11434", timeout=5.0, trust_env=False)
        response = client.chat(model="llama3.1:8b", stream=False,
            messages=[{"role": "system", "content":
                       "Return only JSON {intent: expense_total|unsupported, category: fuel|rent|utilities|all, "
                       "period: last_month|this_month|this_year}. Classify the question; never write SQL."},
                      {"role": "user", "content": question}],
            format="json", options={"temperature": 0, "num_predict": 120})
        content = response["message"]["content"]
        if not isinstance(content, str) or len(content) > 4000: return None
        result = json.loads(content)
        if not isinstance(result, dict) or set(result) != {"intent", "category", "period"}: return None
        if result["intent"] not in ("expense_total", "unsupported"): return None
        if result["category"] not in ("fuel", "rent", "utilities", "all"): return None
        if result["period"] not in ("last_month", "this_month", "this_year"): return None
        return result
    except ImportError:
        return None
    except (ollama.ResponseError, httpx.HTTPError, OSError, RuntimeError, ValueError, KeyError, TypeError):
        return None
    # ollama.ResponseError is handled by the caller only after optional import.


def _rules(question):
    text = question.casefold()
    if re.search(r"\b(drop|delete|insert|update|alter|pragma|attach|select|union)\b|[;]", text): return None
    if not any(word in text for word in ("spend", "expense", "fuel", "rent", "مصاريف", "صرف", "بنزين", "ايجار", "إيجار")):
        return None
    period = "last_month" if any(x in text for x in ("last month", "الشهر الماضي", "الشهر السابق")) else None
    if any(x in text for x in ("this month", "هالشهر", "هذا الشهر")): period = "this_month"
    if any(x in text for x in ("this year", "هالسنة", "هذه السنة")): period = "this_year"
    if not period: return None
    aliases = {"fuel": ("fuel", "diesel", "petrol", "بنزين", "محروقات", "مازوت"),
               "rent": ("rent", "loyer", "ايجار", "إيجار"),
               "utilities": ("utilities", "electricity", "كهرباء", "مياه")}
    categories = [c for c, words in aliases.items() if any(w in text for w in words)]
    if len(categories) > 1: return None
    return {"intent": "expense_total", "category": categories[0] if categories else "all", "period": period}


def ask_books(question, *, database=None, user=None, today=None, use_ollama=True):
    """Return {question, sql, answer} plus parameters/totals/sources/status.

    A local model is tried when available, but its intent must agree with the
    rule validator. Unsupported/ambiguous questions abstain. No remote API used.
    """
    question = str(question or "").strip()
    if not question or len(question) > 1000: raise ValueError("Question must contain 1-1000 characters")
    if database is None:
        context = _CONTEXT.get()
        if context is not None: database, user = context
    base = {"question": question, "sql": None, "answer": "", "parameters": [], "totals": {}, "sources": []}
    if database is None or not user:
        return {**base, "ok": False, "answer": "Select an authenticated company before querying its books."}
    intent = _rules(question)
    model_intent = None
    if use_ollama:
        try:
            model_intent = _ollama_intent(question)
        except (ConnectionError, TimeoutError):
            model_intent = None
        # ollama's HTTP error is optional and should not require the library to import this module.
        except RuntimeError:
            model_intent = None
    if intent is None:
        return {**base, "ok": False, "answer": "Supported: fuel/rent/utilities or all expenses last month, this month or this year."}
    if model_intent is not None and model_intent != intent:
        model_intent = None  # deterministic financial scope wins; don't silently expand it
    reference = today or date.today()
    if isinstance(reference, str): reference = date.fromisoformat(reference)
    first = reference.replace(day=1)
    if intent["period"] == "last_month":
        end = first-timedelta(days=1); start = end.replace(day=1)
    elif intent["period"] == "this_month":
        start, end = first, reference
    else:
        start, end = reference.replace(month=1, day=1), reference
    # Resolve active expense accounts from the selected company's real chart.
    from .classifier import RULES
    aliases = RULES.get(intent["category"], ())
    with database.connect() as connection:
        accounts = [dict(row) for row in connection.execute(
            "SELECT id,code,name_en,name_ar,name_fr FROM accounts WHERE type='expense' AND active=1")]
        if aliases:
            accounts = [row for row in accounts if any(
                word.casefold() in " ".join(str(row.get(k) or "") for k in ("name_en", "name_ar", "name_fr")).casefold()
                for word in aliases)]
        if intent["category"] == "all":
            # All-expense scope can disclose payroll. Require payroll capability through host Database.
            if not database.user_can(user, "payroll"):
                return {**base, "ok": False, "answer": "All-expense totals require payroll permission; choose fuel, rent or utilities."}
        if not accounts:
            return {**base, "ok": False, "answer": "No active expense account matches the requested category."}
        sql = _SQL.format(accounts=",".join("?" for _ in accounts))
        params = [row["id"] for row in accounts]+[start.isoformat(), end.isoformat()]
        rows = connection.execute(sql, params).fetchall()
    if len(rows) > 50000:
        return {**base, "ok": False, "answer": "More than 50,000 lines; narrow the period."}
    totals = {}; sources = []
    for row in rows:
        signed = Decimal(str(row["debit"] or 0))-Decimal(str(row["credit"] or 0))
        if row["line_currency"] and row["amount"] not in (None, ""):
            signed = abs(Decimal(str(row["amount"]))) * (1 if signed >= 0 else -1)
        if not signed.is_finite(): raise ValueError("Invalid ledger amount")
        currency = row["currency"]
        totals[currency] = totals.get(currency, Decimal(0))+signed
        sources.append({"entry_id": row["id"], "entry_number": row["entry_number"], "date": row["entry_date"]})
    exact = {currency: str(value) for currency, value in totals.items()}
    answer = "; ".join(f"{currency} {value}" for currency, value in exact.items()) or "No posted expenses in this scope."
    return {**base, "ok": True, "sql": sql, "parameters": params, "totals": exact,
            "sources": sources, "answer": answer, "intent": intent,
            "engine": "ollama_validated" if model_intent else "rules"}
