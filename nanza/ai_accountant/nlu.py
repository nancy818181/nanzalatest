"""Deterministic multilingual intents and filters for the local accountant assistant."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

ACCOUNT_KEYWORDS = {
    "fuel": ("fuel", "petrol", "gasoline", "diesel", "carburant", "essence",
             "بنزين", "مازوت", "وقود", "محروقات"),
    "rent": ("rent", "rental", "loyer", "إيجار", "الايجار", "الإيجار"),
    "salary": ("salary", "salaries", "payroll", "wage", "wages", "staff",
               "personnel", "salaire", "salaires", "رواتب", "راتب", "أجور"),
}
PERIOD_KEYWORDS = {
    "last_month": ("last month", "previous month", "le mois dernier", "الشهر الماضي"),
    "this_month": ("this month", "ce mois", "هيدا الشهر", "هذا الشهر"),
}
INTENT_KEYWORDS = {
    "ar_aging": ("ar aging", "receivables aging", "aged receivables", "accounts receivable aging",
                 "créances échues", "balance agee client", "balance agee clients",
                 "أعمار الذمم المدينة", "ذمم العملاء", "اعمار ديون العملاء"),
    "ap_aging": ("ap aging", "payables aging", "aged payables", "accounts payable aging",
                 "dettes fournisseurs", "balance agee fournisseur", "balance agee fournisseurs",
                 "أعمار الذمم الدائنة", "ذمم الموردين", "اعمار ديون الموردين"),
    "cash_forecast": ("cash forecast", "cashflow", "cash flow", "13 week cash",
                      "prévision de trésorerie", "prevision de tresorerie",
                      "prévision de cash", "توقع التدفق النقدي", "التدفق النقدي", "توقعات النقد"),
    "duplicate_check": ("duplicate invoice", "duplicate check", "possible duplicates",
                        "doublon", "doublons", "facture en double", "factures en double",
                        "فاتورة مكررة", "فواتير مكررة", "كشف التكرار"),
    "profit_why": ("why profit", "why did profit", "profit decline", "profit down",
                   "why loss", "bénéfice", "benefice", "baisse du bénéfice",
                   "baisse du benefice", "pourquoi le résultat", "pourquoi le resultat",
                   "لماذا انخفض الربح", "سبب انخفاض الربح", "سبب الخسارة"),
    "expense_report": ("expense", "expenses", "spend", "dépense", "dépenses", "مصاريف", "مصروف"),
}


def _normalize(text):
    folded = str(text or "").casefold()
    return "".join(character for character in unicodedata.normalize("NFD", folded)
                   if unicodedata.category(character) != "Mn")


def parse_question(text, today=None):
    normalized = _normalize(text).strip()
    if not normalized:
        return {"intent": "unknown", "entities": {}, "unsupported": ["empty question"]}
    accounts = [key for key, words in ACCOUNT_KEYWORDS.items()
                if any(_normalize(word) in normalized for word in words)]
    periods = [key for key, words in PERIOD_KEYWORDS.items()
               if any(_normalize(word) in normalized for word in words)]
    intent = next((name for name, words in INTENT_KEYWORDS.items()
                   if any(_normalize(word) in normalized for word in words)), None)
    if intent is None:
        intent = "expense_report" if accounts else "unknown"
    entities = {}
    if len(accounts) == 1:
        entities["account"] = accounts[0]
    elif len(accounts) > 1:
        entities["account"] = accounts
    if len(periods) == 1:
        entities["period"] = periods[0]
    elif len(periods) > 1:
        entities["period"] = periods
    # Explicit, bounded project/vendor phrase extraction; database-name matching
    # is performed by the query layer before any SQL is executed.
    for kind, patterns in (
        ("project", (r"\bproject\s+(.+?)(?:\s+(?:last|this)\s+month)?$", r"مشروع\s+(.+)$")),
        ("vendor", (r"\bvendor\s+(.+?)(?:\s+(?:last|this)\s+month)?$", r"fournisseur\s+(.+)$",
                    r"مورد\s+(.+)$")),
    ):
        match = next((re.search(pattern, normalized) for pattern in patterns
                      if re.search(pattern, normalized)), None)
        if match:
            entities[kind] = match.group(1).strip(" .?!")
    reference_day = today or date.today()
    if not isinstance(reference_day, date):
        reference_day = date.fromisoformat(str(reference_day)[:10])
    if entities.get("period") == "last_month":
        end = reference_day.replace(day=1)
        month_end = end - timedelta(days=1)
        entities["date_from"] = month_end.replace(day=1).isoformat()
        entities["date_to"] = month_end.isoformat()
    elif entities.get("period") == "this_month":
        entities["date_from"] = reference_day.replace(day=1).isoformat()
        entities["date_to"] = reference_day.isoformat()
    return {"intent": intent, "entities": entities, "unsupported": []}
