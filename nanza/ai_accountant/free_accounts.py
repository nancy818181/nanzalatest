"""Free keyword-based chart suggestions and detailed account creation."""
from __future__ import annotations

import ast
import glob
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHART_PATTERNS = ("**/*.xls", "**/*.xlsx", "**/PLAN_COMPTABLE*", "**/chart*.py", "**/chart*.json")
RULES = {
    "كهربا,كهرباء,electricity,edl,مولد,generator": "6263.4",
    "مي,مياه,ماء,water,eau": "6263.3",
    "ايجار,إيجار,rent,loyer,بدلات": "6263.1",
    "انترنت,internet,اتصالات,telecom,post,ogero,wifi": "6261.5",
    "نقل,transport,توصيل,شحن": "6261.1",
    "صيانة,maintenance,تصليح,entretien": "6262",
    "ضيافة,reception,تشريفات,قهوة": "6264.1",
    "سفر,travel,voyage": "6264.2",
    "بضاعة,شراء,goods,مخزون": "6011",
    "زبون,زبائن,client,customer": "4111",
    "مورد,supplier,fournisseur": "4011",
    "راتب,رواتب,salary,salaire": "4211",
    "مازوت,diesel,بنزين,fuel,محروقات": "6263.4",
}
DETAIL_MARKERS = (
    "المولد", "مولد", "الادارة", "الإدارة", "المستودع", "مستودع", "مكتب", "المكتب",
    "office", "generator", "administration", "warehouse", "store", "branch", "floor", "unit",
)
NON_DETAIL_WORDS = {
    "فاتورة", "الفاتورة", "مصروف", "مصاريف", "expense", "expenses", "invoice", "bill",
    "the", "for", "of", "from", "edl", "ogero", "internet", "wifi", "eau", "water",
}


def _active_source(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    return not parts.intersection({"nanza_backup", "nanza_delivery", "tests", "test", "__pycache__"})


def _chart_candidates():
    candidates = []
    for pattern in CHART_PATTERNS:
        candidates.extend(Path(path) for path in glob.glob(str(ROOT / pattern), recursive=True))
    candidates.extend(ROOT.glob("**/lebanese_accounts.py"))
    seen = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file() or not _active_source(resolved):
            continue
        if ROOT.resolve() not in resolved.parents:
            continue
        seen.add(resolved)
        yield resolved


def _python_chart(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "LEBANESE_ACCOUNTS" for target in targets):
                value = node.value
                if value is not None:
                    return ast.literal_eval(value)
    return None


def _read_chart(path: Path):
    suffix = path.suffix.casefold()
    if suffix == ".py":
        rows = _python_chart(path)
        if rows is None:
            return None
        return {
            str(row[0]).strip(): {
                "name_en": str(row[1] or "").strip(),
                "name_ar": str(row[2] or "").strip(),
                "name_fr": str(row[3] or "").strip(),
                "type": str(row[4] or "expense").strip().lower(),
                "parent_code": str(row[5]).strip() if len(row) > 5 and row[5] else None,
            }
            for row in rows if len(row) >= 5 and str(row[0]).strip()
        }
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value.get("accounts", value) if isinstance(value, dict) else value
        chart = {}
        for row in rows:
            if isinstance(row, dict):
                code = str(row.get("code") or "").strip()
                if code:
                    chart[code] = {
                        "name_en": str(row.get("name_en") or "").strip(),
                        "name_ar": str(row.get("name_ar") or "").strip(),
                        "name_fr": str(row.get("name_fr") or "").strip(),
                        "type": str(row.get("type") or "expense").strip().lower(),
                        "parent_code": str(row.get("parent_code") or "").strip() or None,
                    }
        return chart
    if suffix in (".xls", ".xlsx"):
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError(f"Cannot read chart workbook {path}: install the project's Excel dependencies") from exc
        engine = "xlrd" if suffix == ".xls" else None
        frame = pd.read_excel(path, engine=engine, header=None, skiprows=6)
        chart = {}
        for row in frame.itertuples(index=False, name=None):
            if len(row) < 5 or pd.isna(row[0]):
                continue
            code = str(row[0]).strip()
            if code.endswith(".0"):
                code = code[:-2]
            chart[code] = {
                "name_ar": "" if pd.isna(row[1]) else str(row[1]).strip(),
                "name_en": "" if pd.isna(row[2]) else str(row[2]).strip(),
                "name_fr": "" if pd.isna(row[3]) else str(row[3]).strip(),
                "type": "expense" if pd.isna(row[4]) else str(row[4]).strip().lower(),
                "parent_code": None,
            }
        return chart
    return None


def _load_chart():
    # PyInstaller bundles Python modules as importable bytecode, not as source
    # files that glob/ast discovery can reliably find.  The Lebanese chart is
    # the application's authoritative built-in chart, so load it through the
    # import system first.  Keep file discovery below for development charts.
    try:
        import lebanese_accounts
        rows = lebanese_accounts.LEBANESE_ACCOUNTS
        chart = {
            str(row[0]).strip(): {
                "name_en": str(row[1] or "").strip(),
                "name_ar": str(row[2] or "").strip(),
                "name_fr": str(row[3] or "").strip(),
                "type": str(row[4] or "expense").strip().lower(),
                "parent_code": str(row[5]).strip() if len(row) > 5 and row[5] else None,
            }
            for row in rows if len(row) >= 5 and str(row[0]).strip()
        }
        if chart and all(code in chart for code in ("6263.4", "6263.3", "6263.1", "6261.5", "4011", "4111")):
            return Path(lebanese_accounts.__file__).resolve(), chart
    except (ImportError, AttributeError, TypeError, ValueError):
        pass
    last_error = None
    for path in _chart_candidates():
        try:
            chart = _read_chart(path)
        except (OSError, ValueError, SyntaxError, ImportError, RuntimeError) as exc:
            last_error = exc
            continue
        if chart and all(code in chart for code in ("6263.4", "6263.3", "6263.1", "6261.5", "4011", "4111")):
            return path, chart
    message = "Could not discover the active chart containing the configured real account codes"
    if last_error:
        raise RuntimeError(message) from last_error
    raise FileNotFoundError(message)


CHART_PATH, CHART_RECORDS = _load_chart()
REAL_CHART = {code: row["name_ar"] for code, row in CHART_RECORDS.items()}
print(f"Chart found at: {CHART_PATH}")


def _matched_base(description: str):
    text = str(description or "").casefold()
    matches = []
    for keywords, code in RULES.items():
        for keyword in keywords.split(","):
            keyword = keyword.strip().casefold()
            if keyword and keyword in text:
                matches.append((len(keyword), code))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _has_detail(description: str, matched_code: str) -> bool:
    text = str(description or "").casefold()
    if any(marker.casefold() in text for marker in DETAIL_MARKERS):
        return True
    tokens = [token.casefold() for token in text.split()]
    matched_terms = {
        keyword.strip().casefold()
        for keywords, code in RULES.items() if code == matched_code
        for keyword in keywords.split(",")
    }
    meaningful = [
        token.strip(".,:;()[]{}\"'؟،")
        for token in tokens
        if token.strip(".,:;()[]{}\"'؟،") not in NON_DETAIL_WORDS
        and not any(term and term in token for term in matched_terms)
    ]
    return bool(meaningful)


def create_account_in_system(client, code: str, name: str, parent: str, account_type: str):
    """Create an account through the authenticated company-scoped client."""
    return client.save_account({
        "code": code,
        "name_en": name,
        "name_ar": name,
        "name_fr": name,
        "parent_code": parent,
        "type": account_type,
    })


def suggest_and_autocreate(description: str, client=None):
    """Suggest the real chart account and create a 9-digit child when detail is present.

    When no API client is supplied this remains a side-effect-free suggestion lookup.
    """
    base_code = _matched_base(description)
    if not base_code or base_code not in CHART_RECORDS:
        return {"found": False}

    base = CHART_RECORDS[base_code]
    result = {
        "found": True,
        "base_code": base_code,
        "base_name": REAL_CHART[base_code] or base.get("name_en") or "",
        "new_9digit_code": None,
        "auto_created": False,
        "message": f"اقتراح: {base_code} - {REAL_CHART[base_code] or base.get('name_en') or ''}",
    }
    if not _has_detail(description, base_code):
        return result

    clean = base_code.replace(".", "").replace("-", "")
    base_6 = clean.ljust(6, "0")[:6]
    live_accounts = client.accounts() if client is not None else []
    known_codes = set(CHART_RECORDS)
    known_codes.update(str(row.get("code") or "") for row in live_accounts)
    existing = next(
        (
            row for row in live_accounts
            if row.get("parent_code") == base_code
            and str(row.get("name_ar") or "").strip().casefold() == str(description).strip().casefold()
        ),
        None,
    )
    if existing:
        result["new_9digit_code"] = str(existing["code"])
        result["message"] += f" - الحساب موجود: {existing['code']}"
        return result

    child_codes = [
        int(code) for code in known_codes
        if len(code) == 9 and code.isdigit() and code.startswith(base_6)
    ]
    next_number = max(child_codes, default=int(base_6 + "000")) + 1
    if next_number > int(base_6 + "999"):
        raise ValueError(f"No 9-digit detail account numbers remain under {base_code}")
    new_code = f"{next_number:09d}"
    result["new_9digit_code"] = new_code
    if client is None:
        result["message"] += f" - حساب مقترح: {new_code}"
        return result
    if not any(str(row.get("code") or "") == base_code for row in live_accounts):
        raise ValueError(f"Base account {base_code} is not available in the selected company chart")

    create_account_in_system(
        client,
        code=new_code,
        name=str(description).strip(),
        parent=base_code,
        account_type=base.get("type") or "expense",
    )
    result["auto_created"] = True
    result["message"] += f" - تم إنشاء {new_code}"
    return result
