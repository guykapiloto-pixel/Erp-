"""Debt calculation, aging and alerting.

Definition (user-defined, see docs/README):
    debt = Σ transaction accounts − Σ tax invoices − Σ tax invoice-receipts + Σ credits

Aging: the reductions (invoices − credits) are allocated FIFO against the transaction accounts, oldest first. The
transaction accounts that remain (fully or partly) uncovered are the open debt, and their dates give the age. This
is an estimate: the board does not say which invoice closed which transaction account.
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .models import CustomerBalance, DocType, Document, Issue

ZERO = Decimal("0")
AGING_BUCKETS = [(0, 30, "0-30"), (31, 60, "31-60"), (61, 90, "61-90"), (91, 180, "91-180"), (181, 10**9, "180+")]


def _bucket(days: int | None) -> str:
    if days is None:
        return "ללא תאריך"
    for lo, hi, name in AGING_BUCKETS:
        if lo <= days <= hi:
            return name
    return "עתידי"  # תאריך עתידי (days < 0)


def compute(docs: list[Document], cfg: dict, as_of: date) -> tuple[list[CustomerBalance], list[Issue]]:
    credit_abs = cfg.get("credit_sign", "abs") == "abs"
    a = cfg.get("alerts", {})
    min_debt = Decimal(str(a.get("min_debt", 1)))
    urgent_amount = Decimal(str(a.get("urgent_amount", 20000)))
    urgent_days = int(a.get("urgent_days", 90))
    followup_days = int(a.get("followup_days", 30))
    neg_thr = Decimal(str(a.get("negative_balance", -1)))

    by_cust: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        by_cust[d.customer_key].append(d)

    issues: list[Issue] = []
    out: list[CustomerBalance] = []
    for key, cdocs in by_cust.items():
        names = sorted({d.customer_name for d in cdocs}, key=lambda n: (-sum(x.customer_name == n for x in cdocs), n))
        cb = CustomerBalance(key, names[0], next((d.contact for d in cdocs if d.contact), ""))
        cb.documents = sorted(cdocs, key=lambda d: (d.doc_date or date.max, d.row_ref))
        counts: dict[str, int] = defaultdict(int)
        for d in cdocs:
            counts[d.doc_type.value] += 1
            if d.doc_type == DocType.TRANSACTION:
                cb.transactions += d.amount
                d.effect = d.amount
            elif d.doc_type == DocType.TAX_INVOICE:
                cb.tax_invoices += d.amount
                d.effect = -d.amount
            elif d.doc_type == DocType.TAX_INVOICE_RECEIPT:
                cb.tax_invoice_receipts += d.amount
                d.effect = -d.amount
            elif d.doc_type == DocType.CREDIT:
                d.effect = abs(d.amount) if credit_abs else d.amount
                cb.credits += d.effect
        cb.counts = dict(counts)
        cb.debt = cb.transactions - cb.tax_invoices - cb.tax_invoice_receipts + cb.credits

        _age(cb, as_of)
        _classify(cb, min_debt, urgent_amount, urgent_days, followup_days, neg_thr)
        if len(names) > 1:
            issues.append(Issue("info", "NAME_VARIANTS", f"הלקוח מופיע בכמה כתיבים: {' | '.join(names)} – אוחדו",
                                customer=cb.customer_name))
        out.append(cb)

    issues += _similar_names(out, float(a.get("similar_name_ratio", 0.80)))
    order = {"דחוף": 0, "חריג": 1, "לטיפול": 2, "מעקב": 3, "תקין": 4}
    out.sort(key=lambda c: (order.get(c.priority, 9), -c.debt))
    return out, issues


def _age(cb: CustomerBalance, as_of: date) -> None:
    trans = sorted((d for d in cb.documents if d.doc_type == DocType.TRANSACTION),
                   key=lambda d: (d.doc_date or date.max, d.row_ref))
    pool = cb.tax_invoices + cb.tax_invoice_receipts - cb.credits   # מה שסגר חשבונות עסקה
    aging: dict[str, Decimal] = defaultdict(lambda: ZERO)
    open_tx = []
    for t in trans:
        if t.amount <= 0:
            continue
        covered = min(max(pool, ZERO), t.amount)
        pool -= covered
        remaining = t.amount - covered
        if remaining > 0:
            open_tx.append((t, remaining))
    open_total = sum((r for _, r in open_tx), ZERO)
    # יתרת חוב שאינה מוסברת ע"י חשבונות עסקה (למשל זיכויים שעולים על החשבוניות) – ללא גיול
    unexplained = cb.debt - open_total
    for t, rem in open_tx:
        days = (as_of - t.doc_date).days if t.doc_date else None
        aging[_bucket(days)] += rem
    if unexplained > 0:
        aging["לא משויך לחשבון עסקה"] += unexplained
    cb.open_transactions = open_tx
    cb.aging = dict(aging)
    dated = [t.doc_date for t, _ in open_tx if t.doc_date]
    if dated and cb.debt > 0:
        cb.oldest_open_date = min(dated)
        cb.oldest_open_days = (as_of - cb.oldest_open_date).days


def _classify(cb, min_debt, urgent_amount, urgent_days, followup_days, neg_thr) -> None:
    r = cb.reasons
    if cb.debt < neg_thr:
        cb.priority = "חריג"
        r.append(f"יתרה שלילית {cb.debt:,.2f}: חשבוניות/זיכויים עולים על חשבונות העסקה – "
                 "ייתכן חשבון עסקה חסר בלוח, זיכוי כפול או יתרת זכות ללקוח")
        return
    if cb.credits > 0 and cb.credits > cb.tax_invoices + cb.tax_invoice_receipts:
        r.append("זיכויים גבוהים מסך החשבוניות – יש לוודא שהזיכוי לא נרשם פעמיים")
    if cb.debt < min_debt:
        cb.priority = "תקין" if not r else "חריג"
        return
    days = cb.oldest_open_days
    if cb.debt >= urgent_amount:
        r.append(f"חוב {cb.debt:,.2f} ₪ מעל סף {urgent_amount:,.0f}")
    if days is not None and days >= urgent_days:
        r.append(f"חשבון עסקה פתוח מ-{cb.oldest_open_date:%d/%m/%Y} ({days} ימים)")
    if cb.debt >= urgent_amount or (days is not None and days >= urgent_days):
        cb.priority = "דחוף"
    elif days is None or days >= followup_days:
        cb.priority = "לטיפול"
        if days is None:
            r.append("חוב פתוח ללא תאריך לגיול")
        else:
            r.append(f"חשבון עסקה פתוח {days} ימים")
    else:
        cb.priority = "מעקב"
        r.append(f"חוב שוטף ({days} ימים)")


def _similar_names(balances: list[CustomerBalance], ratio: float) -> list[Issue]:
    """Flags customers that are probably the same entity written differently (only name-keyed customers)."""
    issues = []
    import re
    named = [(b.customer_key[5:], b) for b in balances if b.customer_key.startswith("name:")]
    named.sort(key=lambda x: x[0])
    digits = {id(b): re.findall(r"\d+", k) for k, b in named}
    for i, (ki, bi) in enumerate(named):
        for kj, bj in named[i + 1:]:
            if ki[:2] != kj[:2]:
                break  # רשימה ממוינת – אין טעם להמשיך מעבר לתחילית שונה
            if digits[id(bi)] != digits[id(bj)]:
                continue  # "פרויקט 12" ו"פרויקט 13" הם לקוחות שונים
            if abs(len(ki) - len(kj)) > (1 - ratio) * (len(ki) + len(kj)):
                continue  # הפרש אורך שמונע מראש יחס דמיון מעל הסף
            sm = difflib.SequenceMatcher(None, ki, kj)
            if sm.real_quick_ratio() >= ratio and sm.quick_ratio() >= ratio and sm.ratio() >= ratio:
                issues.append(Issue("warning", "SIMILAR_NAMES",
                                    f"ייתכן שזה אותו לקוח: '{bi.customer_name}' ({bi.debt:,.2f}) ו-'{bj.customer_name}' "
                                    f"({bj.debt:,.2f}) – החוב חושב בנפרד", customer=bi.customer_name))
    return issues
