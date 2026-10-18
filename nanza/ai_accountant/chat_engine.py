"""Safe intent classification for the analytic assistant; never executes user SQL."""
from __future__ import annotations

import re

from nanza.ui.i18n import tr


def classify_question(question):
    text = str(question or "").casefold()
    fuel_topic = any(token in text for token in (
        "fuel", "diesel", "petrol", "gasoline", "carburant", "essence", "محروقات", "وقود", "بنزين", "مازوت"
    ))
    quarter_match = re.search(r"\b(?:q|t)\s*([1-4])\s*(20\d{2})\b", text)
    months_match = re.search(r"\b(\d{1,2})\s*(?:months?|mois|shhour|shahr|shhor|شهور|أشهر)\b", text)
    last_quarter = any(token in text for token in (
        "last quarter", "previous quarter", "dernier trimestre", "trimestre précédent",
        "الربع الماضي", "الربع السابق"
    ))
    budget_question = any(token in text for token in (
        "budget vs actual", "budget actual", "budget réalisé", "écart budgétaire",
        "الموازنة", "الموازنه"
    ))
    if budget_question and last_quarter:
        return {"intent": "budget_vs_actual", "period": "last_quarter",
                **({"topic": "fuel"} if fuel_topic else {})}
    if any(token in text for token in (
        "cashflow", "cash flow", "flux de trésorerie", "trésorerie", "تدفق", "مصاري"
    )) and quarter_match:
        return {"intent": "cashflow_quarter", "quarter": int(quarter_match.group(1)),
                "year": int(quarter_match.group(2)), **({"topic": "fuel"} if fuel_topic else {})}
    if budget_question:
        return {"intent": "budget_vs_actual", "months": int(months_match.group(1)) if months_match else None,
                **({"topic": "fuel"} if fuel_topic else {})}
    if any(token in text for token in ("analytic", "study", "analyse", "étude", "تحليل", "دراسة")):
        return {"intent": "analytic_study", "months": int(months_match.group(1)) if months_match else None,
                "topic": "fuel" if fuel_topic else "all"}
    if any(token in text for token in ("report", "rapport", "تقرير", "banzen", "بالعربي")):
        return {"intent": "custom_report", "months": int(months_match.group(1)) if months_match else 3,
                **({"topic": "fuel"} if fuel_topic else {})}
    if fuel_topic:
        return {"intent": "custom_report", "topic": "fuel", "months": 3}
    return {"intent": "unknown", "months": int(months_match.group(1)) if months_match else None}


def answer_question(question, study=None, report_builder=None, language="en"):
    """Return a structured response for the desktop assistant to render/export."""
    intent = classify_question(question)
    if intent["intent"] == "unknown":
        return {"intent": "unknown", "message": tr(language, "analytic_unknown_prompt"),
                "report": None, "filters": intent}
    if intent.get("topic") == "fuel":
        return {"intent": intent["intent"], "message": tr(language, "analytic_fuel_unsupported"),
                "report": None, "filters": intent, "needs_data": False}
    report = None
    if study is not None:
        if report_builder is None:
            from nanza.reports.analytic_report import build_report
            report_builder = build_report
        report = report_builder(study, {**intent, "language": language})
    message = tr(language, f"analytic_intent_{intent['intent']}")
    if intent["intent"] == "cashflow_quarter":
        message = message.format(quarter=intent["quarter"], year=intent["year"])
    return {"intent": intent["intent"], "message": message, "filters": intent, "report": report,
            "needs_data": study is None}
