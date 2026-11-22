"""Turning raw board rows (dict: column -> text) into validated Documents.

Every parsing failure becomes an Issue instead of being silently dropped, so the report shows exactly which rows
were not counted and why.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .models import DocType, Document, Issue

_QUOTES = str.maketrans({"״": '"', "”": '"', "“": '"', "׳": "'", "’": "'", "‘": "'", "`": "'"})


def norm_text(s: Any) -> str:
    """Whitespace/quote normalisation used for display and comparisons."""
    if s is None:
        return ""
    s = str(s).translate(_QUOTES).replace("‏", "").replace("‎", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def label_key(s: Any) -> str:
    """Key for matching document-type labels: ignore spaces, quotes, slashes, hyphens and case."""
    return re.sub(r"[\s\"'/\\\-_.]", "", norm_text(s)).lower()


_LEGAL_SUFFIX = re.compile(r"\b(בע\"?מ|בעמ|ltd\.?|limited|inc\.?)$", re.IGNORECASE)


def customer_key(name: str, customer_id: str = "") -> str:
    cid = re.sub(r"\D", "", norm_text(customer_id))
    if cid:
        return f"id:{cid.lstrip('0') or '0'}"
    n = norm_text(name)
    n = _LEGAL_SUFFIX.sub("", n).strip(" ,-")
    return "name:" + re.sub(r"[\"'.,]", "", n).lower()


_AMOUNT_JUNK = re.compile(r"[₪$€\s,]|ש\"ח|שח|ils|nis", re.IGNORECASE)


def parse_amount(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    s = norm_text(raw)
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = _AMOUNT_JUNK.sub("", s)
    s = s.replace("−", "-")  # minus sign
    if s.endswith("-"):           # "1500-" נפוץ בייצוא מהנה"ח
        neg, s = not neg, s[:-1]
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    try:
        v = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -v if neg else v


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y", "%Y-%m-%d %H:%M:%S",
                 "%Y-%m-%dT%H:%M:%S", "%b %d, %Y", "%d %b %Y", "%B %d, %Y")


def parse_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = norm_text(raw)
    if not s:
        return None
    s = s.split(" ")[0] if re.match(r"\d{4}-\d{2}-\d{2} ", s) else s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class TypeMapper:
    def __init__(self, doc_types: dict[str, list[str]]):
        self._map: dict[str, DocType] = {}
        for cat, labels in doc_types.items():
            dt = DocType(cat)
            for lab in labels or []:
                k = label_key(lab)
                if k in self._map and self._map[k] != dt:
                    raise ValueError(f"התווית '{lab}' ממופה לשני סוגי מסמכים")
                self._map[k] = dt

    def __call__(self, raw: str) -> DocType | None:
        return self._map.get(label_key(raw))


def _get(row: dict[str, Any], col: str | None) -> Any:
    if not col:
        return None
    return row.get(col)


def rows_to_documents(rows: Iterable[dict[str, Any]], cfg: dict) -> tuple[list[Document], list[Issue]]:
    cols = cfg["columns"]
    mapper = TypeMapper(cfg["doc_types"])
    cancelled = {label_key(s) for s in cfg.get("cancelled_statuses", [])}
    docs: list[Document] = []
    issues: list[Issue] = []
    seen_numbers: dict[tuple[str, str], str] = {}

    for row in rows:
        ref = str(row.get("__ref__", ""))
        name = norm_text(_get(row, cols["customer"]))
        cid = norm_text(_get(row, cols.get("customer_id")))
        if not name and not cid:
            if any(norm_text(v) for k, v in row.items() if not k.startswith("__")):
                issues.append(Issue("error", "NO_CUSTOMER", "שורה ללא שם/מספר לקוח – לא נספרה", ref))
            continue

        status = label_key(_get(row, cols.get("status")))
        if status and status in cancelled:
            issues.append(Issue("info", "CANCELLED", "מסמך מבוטל – לא נספר", ref, name))
            continue

        raw_type = norm_text(_get(row, cols["doc_type"]))
        dt = mapper(raw_type)
        if dt is None:
            issues.append(Issue("error", "UNKNOWN_TYPE", f"סוג מסמך לא מוכר: '{raw_type or '(ריק)'}' – לא נספר",
                                ref, name))
            continue

        raw_amount = _get(row, cols["amount"])
        amount = parse_amount(raw_amount)
        if amount is None:
            issues.append(Issue("error", "BAD_AMOUNT", f"סכום לא קריא: '{norm_text(raw_amount) or '(ריק)'}' – לא נספר",
                                ref, name))
            continue

        raw_date = _get(row, cols.get("date"))
        d = parse_date(raw_date)
        if cols.get("date") and d is None and dt != DocType.IGNORED:
            issues.append(Issue("warning", "BAD_DATE", f"תאריך חסר/לא קריא: '{norm_text(raw_date)}' – נספר, ללא גיול",
                                ref, name))

        number = norm_text(_get(row, cols.get("doc_number")))
        key = customer_key(name, cid)
        if dt == DocType.IGNORED:
            issues.append(Issue("info", "IGNORED_TYPE", f"'{raw_type}' {amount:,.2f} – לא נכלל בהגדרת החוב", ref, name))
            continue
        if amount < 0 and dt != DocType.CREDIT:
            issues.append(Issue("warning", "NEGATIVE_AMOUNT", f"{raw_type} בסכום שלילי {amount:,.2f} – נספר כפי שהוא",
                                ref, name))
        if number:
            dup_key = (dt.value, number)
            if dup_key in seen_numbers:
                issues.append(Issue("error", "DUPLICATE_DOC", f"{raw_type} מס' {number} מופיע פעמיים "
                                    f"(שורות {seen_numbers[dup_key]}, {ref}) – נספר פעמיים, יש לבדוק", ref, name))
            else:
                seen_numbers[dup_key] = ref

        docs.append(Document(ref, key, name or cid, dt, amount, d, number, raw_type,
                             norm_text(_get(row, cols.get("contact"))), str(row.get("__group__", ""))))
    return docs, issues


def summary_rows_to_documents(rows: Iterable[dict[str, Any]], cfg: dict) -> tuple[list[Document], list[Issue]]:
    """layout=summary: one row per customer, a column per document category."""
    cols, scols = cfg["columns"], cfg["summary_columns"]
    docs: list[Document] = []
    issues: list[Issue] = []
    for row in rows:
        ref = str(row.get("__ref__", ""))
        name = norm_text(_get(row, cols["customer"]))
        cid = norm_text(_get(row, cols.get("customer_id")))
        if not name and not cid:
            continue
        key = customer_key(name, cid)
        for cat, col in scols.items():
            raw = _get(row, col)
            if norm_text(raw) == "":
                continue
            amount = parse_amount(raw)
            if amount is None:
                issues.append(Issue("error", "BAD_AMOUNT", f"{col}: סכום לא קריא '{norm_text(raw)}' – לא נספר",
                                    ref, name))
                continue
            docs.append(Document(ref, key, name or cid, DocType(cat), amount, None, "", col,
                                 norm_text(_get(row, cols.get("contact"))), str(row.get("__group__", ""))))
    return docs, issues
