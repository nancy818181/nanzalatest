"""2.9.113: income lawfully left out of the income tax computation (already taxed elsewhere or exempt by law).
Each one needs its legal reason and is listed in the tax adjustments schedule."""

EXEMPT_REASONS = (
    "Interest taxed at source | فوائد خضعت لضريبة الدخل في المصدر",
    "Dividends already taxed | أنصبة أرباح سبق إخضاعها للضريبة",
    "Capital gain taxed separately | ربح تحسيني خاضع لضريبة مستقلة",
    "Exempt by law - article | معفى بموجب القانون - المادة",
)
NEEDS_ARTICLE = EXEMPT_REASONS[3]


def reason_text(reason, article=""):
    """The reason saved with the invoice; "exempt by law" needs the article / law."""
    reason = str(reason or "").strip()
    if not reason: return ""
    if reason not in EXEMPT_REASONS: raise ValueError("Choose the legal reason from the list")
    if reason == NEEDS_ARTICLE:
        article = str(article or "").strip()
        if not article: raise ValueError("Write the article / law that exempts this income")
        return f"{reason} {article}"
    return reason
