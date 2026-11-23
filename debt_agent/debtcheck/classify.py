"""What is each open charge for, and is the money already owed?

A transaction account is often issued before the fee is owed: an annual report / balance sheet for a tax year whose
work has not been done or filed yet, or a fee for months that have not arrived. Each item line of an open document
is classified from its text (פירוט), its catalogue number (מק"ט) and the document title:

    kind      annual (דו"ח שנתי) · balance (מאזן / ביקורת) · period (הנה"ח / שכ"ט לתקופה) · other
    status    due          – owed now, goes to collection
              not_due      – not owed yet (report/balance of a year not filed yet; future months)
              unknown      – no item text to decide by (treated as due, flagged)

Evidence that a report was filed (then the fee is due): the board's "שידור דוחות" list, or a correction left for the
agent on the board.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

D0 = Decimal("0")
ANNUAL_SKU = ("102",)
BALANCE_SKU = ("103",)
_ANNUAL = re.compile(r"דו\"?ח|דוח|הצהרת הון")
_BALANCE = re.compile(r"מאזן|ביקורת")
_PERIOD_KIND = re.compile(r"הנהלת חשבונות|הנה\"?ח|הנהח|שכ\"?ט|שכר|תלושים|ניכויים|שירותי")
# 01-12/26 · 1-3/ 26 · 09/2026 · 12/25
_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})\s*/\s*(\d{4}|\d{2})(?!\d)")
_MONTH = re.compile(r"(?<![\d-])(\d{1,2})\s*/\s*(\d{4}|\d{2})(?!\d)")
_YEAR = re.compile(r"(?<![\d/])(20\d{2}|\d{2})(?![\d/])")


@dataclass
class ItemClass:
    desc: str
    kind: str
    year: int | None
    period: tuple | None        # (year, first month, last month)
    status: str                 # due / not_due / unknown
    due_share: Decimal          # 0..1 of the item that is owed now
    reason: str


def _yr(s: str) -> int | None:
    y = int(s)
    if y < 100:
        y += 2000
    return y if 2015 <= y <= 2040 else None


def parse_period(text: str):
    m = _RANGE.search(text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _yr(m.group(3))
        if y and 1 <= a <= b <= 12:
            return y, a, b
    m = _MONTH.search(text)
    if m:
        a, y = int(m.group(1)), _yr(m.group(2))
        if y and 1 <= a <= 12:
            return y, a, a
    return None


def parse_year(text: str) -> int | None:
    t = _RANGE.sub(" ", _MONTH.sub(" ", text))
    for m in _YEAR.finditer(t):
        y = _yr(m.group(1))
        if y:
            return y
    return None


def kind_of(desc: str, sku: str) -> str:
    sku3 = (sku or "")[:3]
    if _BALANCE.search(desc):
        return "balance"
    if re.search(r"דו\"?ח|דוח", desc) and not re.search(r"הנה\"?ח ודו\"?ח", desc):
        return "annual"
    if _PERIOD_KIND.search(desc):
        return "period"
    if sku3 in BALANCE_SKU:
        return "balance"
    if sku3 in ANNUAL_SKU:
        return "annual"
    if sku3 in ("101", "107", "106"):
        return "period"
    return "other"


def classify_item(desc: str, sku: str, title: str, doc_date: date, as_of: date, *, filed_years: set,
                  override: str | None, cfg: dict) -> ItemClass:
    """filed_years: tax years for which this customer's report is known to be filed. override: due / not_due."""
    first_year = int(cfg.get("not_due_from_year", 2025))
    prorate = bool(cfg.get("prorate_future_periods", True))
    text = desc or ""
    kind = kind_of(text, sku)
    if kind == "other" and title:
        kind = kind_of(title, sku) if not text else kind
    period = parse_period(text) or (parse_period(title) if kind == "period" else None)
    year = parse_year(text)
    inferred = False
    if year is None and kind in ("annual", "balance"):
        year = parse_year(title or "")
        if year is None:
            year, inferred = doc_date.year - 1, True      # מאזן/דו"ח ללא שנה: שנת המס שקדמה למועד ההפקה
    if year is None and kind == "period" and period is None:
        year = parse_year(title or "")

    if override in ("due", "not_due"):
        return ItemClass(text, kind, year, period, override, Decimal(1 if override == "due" else 0),
                         "תוקן ידנית בלוח: " + ("מגיע לגבייה" if override == "due" else "טרם מגיע"))
    if not text and not title:
        return ItemClass(text, "other", None, None, "unknown", Decimal(1), "אין פירוט במסמך – נספר כחוב")

    if kind in ("annual", "balance"):
        what = "מאזן / ביקורת" if kind == "balance" else "דו\"ח שנתי"
        ytxt = f"{year}" + (" (שנה משוערת לפי מועד ההפקה)" if inferred else "")
        if year >= as_of.year:
            return ItemClass(text, kind, year, None, "not_due", D0, f"{what} {ytxt}: שנת המס טרם הסתיימה")
        if year >= first_year and year not in filed_years:
            return ItemClass(text, kind, year, None, "not_due", D0,
                             f"{what} {ytxt}: אין תיעוד בלוח שהדוח הוגש")
        return ItemClass(text, kind, year, None, "due", Decimal(1),
                         f"{what} {ytxt}: " + ("הדוח שודר" if year in filed_years else "שנה שנסגרה"))

    if kind == "period":
        if period:
            y, a, b = period
        elif year:
            y, a, b = year, 1, 12
        else:
            return ItemClass(text, kind, None, None, "due", Decimal(1), "שכ\"ט שוטף ללא תקופה")
        total = b - a + 1
        if y < as_of.year:
            elapsed = total
        elif y > as_of.year:
            elapsed = 0
        else:
            elapsed = max(0, min(b, as_of.month) - a + 1)
        if not prorate or elapsed >= total:
            return ItemClass(text, kind, y, (y, a, b), "due", Decimal(1), f"תקופה {a:02d}-{b:02d}/{y}: הסתיימה")
        share = Decimal(elapsed) / Decimal(total)
        st = "not_due" if elapsed == 0 else "due"
        return ItemClass(text, kind, y, (y, a, b), st, share,
                         f"תקופה {a:02d}-{b:02d}/{y}: {elapsed} מתוך {total} חודשים הגיעו")

    return ItemClass(text, kind, year, period, "due", Decimal(1), "חיוב אחר")
