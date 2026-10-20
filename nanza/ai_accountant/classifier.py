from __future__ import annotations

import re


RULES = {
    "fuel": ("fuel", "petrol", "gasoline", "diesel", "carburant", "essence", "محروقات", "وقود", "بنزين", "مازوت"),
    "rent": ("rent", "lease", "loyer", "إيجار", "كراء"),
    "salary": ("salary", "payroll", "wage", "salaire", "رواتب", "أجور"),
    "utilities": ("utilities", "electricity", "water", "utility", "électricité", "eau", "كهرباء", "ماء"),
    "travel": ("travel", "transport", "transportation", "voyage", "transport", "سفر", "نقل"),
    "office": ("office", "stationery", "supplies", "bureau", "fournitures", "مكتبي", "قرطاسية"),
    "maintenance": ("maintenance", "repair", "entretien", "réparation", "صيانة", "إصلاح"),
}


def _active(value):
    return value is True or value == 1 or str(value).strip().casefold() in {"true", "yes", "1"}


def _tokens(value):
    return set(re.findall(r"[^\W_]+", str(value or "").casefold(), flags=re.UNICODE))


def _score_account(account, topic_terms, input_tokens):
    names = [
        account.get("name"), account.get("name_en"), account.get("name_fr"),
        account.get("name_ar"), account.get("description"),
    ]
    account_tokens = set().union(*(_tokens(name) for name in names))
    matched = topic_terms & account_tokens
    if not matched:
        return 0.0
    topic_coverage = len(matched) / max(1, len(account_tokens))
    input_coverage = len(matched & input_tokens) / len(topic_terms)
    return min(1.0, 0.55 + 0.25 * topic_coverage + 0.20 * input_coverage)


def classify_expense(description, accounts):
    """Suggest an active posting account, abstaining on weak or ambiguous matches."""
    text = str(description or "").casefold()
    tokens = _tokens(text)
    ranked = []
    for topic, keywords in RULES.items():
        topic_terms = set().union(*(_tokens(word) for word in keywords))
        if not (topic_terms & tokens):
            continue
        for account in accounts or ():
            if not _active(account.get("is_active")) or not _active(account.get("is_posting")):
                continue
            if not (account.get("code") or account.get("account_code")):
                continue
            score = _score_account(account, topic_terms, tokens)
            if score:
                ranked.append((score, topic, account))
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
                {"account_code": account.get("code") or account.get("account_code"),
                 "name": account.get("name_en") or account.get("name") or account.get("name_fr") or account.get("name_ar"),
                 "heuristic_score": score}
                for score, _, account in [ranked[0]] + ambiguous
            ],
            "topic": best_topic,
        }
    if best_score < 0.8:
        return {"account_code": None, "heuristic_score": best_score, "abstain": True, "topic": best_topic}
    account_code = best_account.get("code") or best_account.get("account_code")
    if not account_code:
        return {"account_code": None, "heuristic_score": best_score, "abstain": True, "topic": best_topic}
    return {
        "account_code": account_code,
        "heuristic_score": best_score,
        "abstain": False,
        "topic": best_topic,
    }


def suggest_account(description, accounts=(), account_type="expense"):
    chart = [
        account for account in accounts or ()
        if str(account.get("type") or account.get("account_type") or "expense").casefold() == account_type.casefold()
    ]
    result = classify_expense(description, chart)
    result["account_name"] = ""
    result["category"] = result.get("topic", "")
    result["requires_review"] = True
    if result.get("account_code") is not None:
        selected = next((account for account in chart
                         if (account.get("code") or account.get("account_code")) == result["account_code"]), {})
        result["account_name"] = (
            selected.get("name_en") or selected.get("name") or selected.get("name_fr")
            or selected.get("name_ar") or ""
        )
        result["label"] = f"Suggested {result['heuristic_score']:.0%} heuristic score (rule-based)"
    else:
        result["label"] = "No suggestion"
    return result


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
