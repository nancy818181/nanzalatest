from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


RULES = {
    "fuel": ("fuel", "petrol", "gasoline", "diesel", "carburant", "essence", "محروقات", "وقود", "بنزين", "مازوت"),
    "telecom": ("telephone", "telecommunications", "landline", "mobile", "touch", "alfa", "ogero", "هاتف", "اتصالات", "خلوي"),
    "rent": ("rent", "lease", "loyer", "إيجار", "كراء"),
    "salary": ("salary", "payroll", "wage", "salaire", "رواتب", "أجور"),
    "utilities": ("utilities", "edl", "electricity", "water", "utility", "électricité", "eau", "كهرباء", "ماء"),
    "travel": ("travel", "transport", "transportation", "voyage", "transport", "سفر", "نقل"),
    "office": ("office", "stationery", "supplies", "bureau", "fournitures", "مكتبي", "قرطاسية"),
    "maintenance": ("maintenance", "repair", "entretien", "réparation", "صيانة", "إصلاح"),
}


def _active(value):
    return value is True or value == 1 or str(value).strip().casefold() in {"true", "yes", "1"}


def _tokens(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[\u064b-\u065f\u0670ـ]", "", value)
    return set(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _score_account(account, topic_terms, input_tokens):
    names = [
        account.get("name"), account.get("name_en"), account.get("name_fr"),
        account.get("name_ar"), account.get("description"),
    ]
    account_tokens = set().union(*(_tokens(name) for name in names))
    matched = topic_terms & account_tokens
    if not matched:
        return 0.0
    # Synonyms in different languages are equivalent evidence, not a penalty.
    return 0.85 + 0.10 * len(matched & input_tokens) / max(1, len(input_tokens))


def classify_expense(description, accounts):
    """Suggest an active posting account, abstaining on weak or ambiguous matches."""
    text = str(description or "").casefold()
    tokens = _tokens(text)
    detected_topics = {topic for topic, keywords in RULES.items()
                       if any(_tokens(word) <= tokens for word in keywords)}
    if len(detected_topics) > 1:
        return {"account_code": None, "heuristic_score": 0.0, "abstain": True,
                "ambiguous": True, "reason": "Itemize distinct expense categories with their amounts"}
    ranked_by_code = {}
    accounts = list(accounts or ())
    for topic, keywords in RULES.items():
        topic_terms = set().union(*(_tokens(word) for word in keywords))
        if not (topic_terms & tokens):
            continue
        for account in accounts or ():
            if not _active(account.get("is_active")) or not _active(account.get("is_posting")):
                continue
            code = str(account.get("code") or account.get("account_code") or "")
            if not re.fullmatch(r"6[0-9]*(?:\.[0-9]+)?", code):  # 2.9.132: any class 6 code of the chart (6263.1, 6262, 626310001)
                continue
            if str(account.get("type") or account.get("account_type") or "expense").casefold() != "expense":
                continue
            score = _score_account(account, topic_terms, tokens)
            if score:
                previous = ranked_by_code.get(code)
                if previous is None or score > previous[0]:
                    ranked_by_code[code] = (score, topic, account)
    ranked = list(ranked_by_code.values())
    ranked.sort(key=lambda item: (-item[0], str(item[2].get("code") or item[2].get("account_code") or "")))
    if not ranked:
        return {"account_code": None, "heuristic_score": 0.0, "abstain": True}

    best_score, best_topic, best_account = ranked[0]
    ambiguous = [item for item in ranked[1:] if best_score - item[0] <= 0.15]
    if ambiguous:
        return {
            "account_code": None,
            "heuristic_score": best_score,
            "abstain": True,
            "ambiguous": True,
            "candidates": [
                {"account_code": str(account.get("code") or account.get("account_code")),
                 "name": account.get("name_en") or account.get("name") or account.get("name_fr") or account.get("name_ar"),
                 "heuristic_score": score}
                for score, _, account in [ranked[0]] + ambiguous
            ],
            "topic": best_topic,
        }
    if best_score < 0.8:
        return {"account_code": None, "heuristic_score": best_score, "abstain": True, "topic": best_topic}
    account_code = str(best_account.get("code") or best_account.get("account_code"))
    if not account_code:
        return {"account_code": None, "heuristic_score": best_score, "abstain": True, "topic": best_topic}
    return {
        "account_code": account_code,
        "heuristic_score": best_score,
        "abstain": False,
        "topic": best_topic,
    }


def _keyword_fallback(description, chart):
    """2.9.132 (Phase 2): the English / French / Arabic keyword categories of the invoice reader, resolved to an account
    that EXISTS (active, posting) in the given chart; None when ambiguous, unknown or not in the chart."""
    import pdf_import
    found = pdf_import.expense_classification(description)
    if found["status"] != "suggested": return None, found["status"]
    label, dotted, nine, _name = found["category"]
    codes = {str(a.get("code") or a.get("account_code")): a for a in chart
             if _active(a.get("is_active", True)) and _active(a.get("is_posting", True))}
    code = dotted if dotted in codes else nine if nine in codes else None
    if not code: return None, "not_in_chart"
    evidence = found["candidates"][0]["evidence"]
    return {"account_code": code, "heuristic_score": 0.86 if len(evidence) >= 2 else 0.78, "abstain": False, "topic": label,
            "source": "keywords", "evidence": [{"kind": "extracted", "text": "Words on the document: " + ", ".join(evidence)},
                                               {"kind": "inferred", "text": f"Category '{label}' -> account {code} of this chart"}]}, "suggested"


def suggest_account(description, accounts=(), account_type="expense"):
    chart = [
        account for account in accounts or ()
        if str(account.get("type") or account.get("account_type") or "expense").casefold() == account_type.casefold()
    ]
    result = classify_expense(description, chart)
    if result.get("account_code") is None and account_type == "expense":
        fallback, _status = _keyword_fallback(description, chart)
        # a broad topic ("utilities": water and electricity) is narrowed only by a more specific category among its candidates
        if fallback and (not result.get("ambiguous") or fallback["account_code"] in {c["account_code"] for c in result.get("candidates", [])}):
            result = fallback
    result["account_name"] = ""
    result["category"] = result.get("topic", "")
    result["requires_review"] = True
    if result.get("account_code") is not None:
        selected = next((account for account in chart
                         if str(account.get("code") or account.get("account_code")) == result["account_code"]), {})
        result["account_name"] = (
            selected.get("name_en") or selected.get("name") or selected.get("name_fr")
            or selected.get("name_ar") or ""
        )
        result["label"] = f"Suggested {result['heuristic_score']:.0%} heuristic score (rule-based)"
        result.setdefault("evidence", [{"kind": "inferred", "text": f"Keyword topic '{result.get('topic')}' matches the account name"}])
        # 2.9.132: a plain reason, and the reminder that the score is a rule score, not a measured accuracy
        result["explanation"] = " ".join(e["text"] for e in result["evidence"]) + \
            f". Score {result['heuristic_score']:.2f} (rule score, not a measured accuracy). Review before saving."
    else:
        result["label"] = "No suggestion"
        result["explanation"] = ("Several expense kinds are mentioned; choose the account." if result.get("ambiguous") else
                                 "No recognised words and no matching account in this chart; choose the account.")
    return result


_NON_DEDUCTIBLE_TERMS = {
    "EDL": ("edl", "electricite du liban", "électricité du liban", "electricity", "كهرباء"),
    "TEL": ("tel", "ogero", "landline", "telephone", "telecommunications", "هاتف", "اتصالات"),
    "CELL": ("cell", "touch", "alfa", "mobile", "cellular", "خلوي"),
    "FUEL": RULES["fuel"],
}


def _non_deductible_category(item):
    category = str(item.get("expense_category") or "").upper()
    if category in _NON_DEDUCTIBLE_TERMS:
        return category
    tokens = _tokens(item.get("description"))
    for category, phrases in _NON_DEDUCTIBLE_TERMS.items():
        if any(_tokens(phrase) <= tokens for phrase in phrases):
            return category
    return None


def _money(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be a finite non-negative amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a finite non-negative amount")
    return amount


def split_invoice_expenses(items, accounts, *, currency, invoice_total=None):
    """Build reviewable expense allocations from explicit, exclusive-VAT subtotals.

    Each item needs description, subtotal (or gross total), and vat_amount,
    including explicit zero VAT. Amounts are exact Decimal values; no estimated
    percentages or equal splits are invented. A total-only mixed invoice must
    be itemized by the caller. This does not post journals or select VAT accounts.
    Existing VAT rules remain authoritative for all other categories.
    """
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("An explicit invoice currency is required")
    currency = currency.strip().upper()
    accounts = list(accounts or ())
    rows, grouped = [], {}
    gross_total = Decimal("0")
    for index, item in enumerate(items):
        if str(item.get("currency", currency)).upper() != currency:
            raise ValueError("Invoice lines must use the invoice currency")
        vat = _money(item.get("vat_amount"), "vat_amount")
        if item.get("subtotal") is not None:
            net = _money(item["subtotal"], "subtotal")
        elif item.get("total") is not None:
            net = _money(item["total"], "total") - vat
            if net < 0:
                raise ValueError("VAT cannot exceed the gross line total")
        else:
            raise ValueError("Each line requires subtotal or gross total; no estimated splitting")
        gross = net + vat
        if item.get("total") is not None and _money(item["total"], "total") != gross:
            raise ValueError("Line subtotal plus VAT does not match its gross total")
        category = _non_deductible_category(item)
        capitalized_vat = vat if category else Decimal("0")
        expense_cost = net + capitalized_vat
        # Establish VAT-inclusive expense cost before selecting an expense account.
        description = item.get("description") or ""
        if category:
            description = str(description) + " " + {"EDL": "electricity", "TEL": "telephone",
                                                    "CELL": "mobile", "FUEL": "fuel"}[category]
        suggestion = suggest_account(description, accounts)
        row = {**suggestion, "line_index": index, "description": item.get("description", ""),
               "currency": currency, "subtotal": net, "vat_amount": vat,
               "expense_cost": expense_cost, "gross_total": gross,
               "non_deductible_category": category, "non_deductible_vat": capitalized_vat,
               "vat_action": "capitalize_in_expense" if category else "preserve_existing_rules"}
        rows.append(row)
        gross_total += gross
        code = suggestion.get("account_code")
        if code is not None:
            allocation = grouped.setdefault(code, {"account_code": code, "currency": currency,
                "expense_cost": Decimal("0"), "non_deductible_vat": Decimal("0"), "line_indexes": []})
            allocation["expense_cost"] += expense_cost
            allocation["non_deductible_vat"] += capitalized_vat
            allocation["line_indexes"].append(index)
    reconciled = invoice_total is None or gross_total == _money(invoice_total, "invoice_total")
    unresolved = [row["line_index"] for row in rows if row["abstain"]]
    return {"lines": rows, "allocations": list(grouped.values()), "currency": currency,
            "gross_total": gross_total, "unresolved_line_indexes": unresolved,
            "reconciled": reconciled, "complete": bool(rows) and not unresolved and reconciled,
            "requires_review": True}


class ExpenseClassifier:
    """Local, review-first Arabic/English classifier with auditable learning.

    Optional SQLite storage persists labels rather than unsafe pickle models.
    Use a separate company scope; learning never changes accounting records.
    """
    def __init__(self, storage_path=None, *, company_id="local"):
        self.storage_path = storage_path
        self.company_id = str(company_id)
        self._learned = {}
        self._model = None
        if storage_path is not None:
            import sqlite3
            with sqlite3.connect(str(storage_path)) as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS expense_training_labels (
                    company_scope TEXT NOT NULL, description TEXT NOT NULL,
                    category TEXT NOT NULL, PRIMARY KEY(company_scope,description))""")
                self._learned = dict(connection.execute(
                    "SELECT description,category FROM expense_training_labels WHERE company_scope=?",
                    (self.company_id,)))
        self._fit()

    @staticmethod
    def _text(description):
        import unicodedata
        text = unicodedata.normalize("NFKC", str(description or "")).casefold().strip()
        text = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text)
        return " ".join(text.split())

    def _fit(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        samples = {self._text(word): category
                   for category, words in RULES.items() for word in words}
        samples.update(self._learned)
        if len(set(samples.values())) < 2:
            self._model = None
            return
        self._model = make_pipeline(
            TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), max_features=30000),
            LogisticRegression(max_iter=500, random_state=42))
        self._model.fit(list(samples), list(samples.values()))

    def learn(self, description, category):
        text = self._text(description)
        category = str(category or "").strip()
        if not text or len(text) > 2000 or not category or len(category) > 100:
            raise ValueError("A description (1-2000 chars) and category (1-100 chars) are required")
        if self.storage_path is not None:
            import sqlite3
            with sqlite3.connect(str(self.storage_path)) as connection:
                connection.execute("""INSERT INTO expense_training_labels VALUES(?,?,?)
                    ON CONFLICT(company_scope,description) DO UPDATE SET category=excluded.category""",
                    (self.company_id, text, category))
        self._learned[text] = category
        self._fit()
        return {"learned": True, "category": category, "requires_review": True}

    def categorize(self, description):
        text = self._text(description)
        if not text or len(text) > 2000:
            return {"category": None, "confidence": 0.0, "requires_review": True, "source": "abstain"}
        if text in self._learned:
            return {"category": self._learned[text], "confidence": None,
                    "requires_review": True, "source": "reviewed_example"}
        tokens = _tokens(text)
        matches = {category for category, words in RULES.items()
                   if any(_tokens(self._text(word)) <= tokens for word in words)}
        if len(matches) == 1:
            return {"category": matches.pop(), "confidence": None,
                    "requires_review": True, "source": "keyword_rule"}
        if len(matches) > 1 or self._model is None:
            return {"category": None, "confidence": 0.0,
                    "requires_review": True, "source": "ambiguous"}
        scores = self._model.predict_proba([text])[0]
        ranking = sorted(zip(scores, self._model.classes_), reverse=True)
        score, category = ranking[0]
        margin = score-ranking[1][0] if len(ranking) > 1 else score
        return {"category": str(category) if score >= .65 and margin >= .20 else None,
                "confidence": float(score), "requires_review": True, "source": "sklearn_uncalibrated"}
