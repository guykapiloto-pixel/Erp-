"""Agent results in the shape the collections board reads (db docs agent/meta and agent/r0..rN).

Only customers with an open balance in Hyp are exported. Customer data – written outside the repository.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .hyp import IR, T, Customer

CHUNK = 120
LIVE = ("דחוף", "לטיפול", "מעקב", "ממתין להנהלה", "טרם מגיע", "לסגירה ב-Hyp", "תקין")
KIND = {"annual": "דו\"ח שנתי", "balance": "מאזן / ביקורת", "period": "שכ\"ט תקופתי", "other": "אחר"}


def fb_key(c: Customer) -> str:
    """Document id of the customer's feedback on the board (collection agentFb)."""
    return f"h{c.hyp_id}" if c.hyp_id else "n" + hashlib.md5(c.name.encode("utf-8")).hexdigest()[:14]


def _n(v) -> float:
    return round(float(v or 0), 2)


def _row(c: Customer) -> dict:
    lp = c.last_payment
    docs = []
    for o in sorted(c.open_docs, key=lambda o: o.doc_date):
        docs.append({"d": o.doc_date.isoformat(), "n": o.num, "t": 300 if o.type == T else 305, "rem": _n(o.remaining),
                     "due": _n(o.due if o.lines else o.remaining), "nd": _n(o.not_due), "title": o.title,
                     "u": o.url, "pp": f"{o.possibly_paid_by.type} {o.possibly_paid_by.num}" if o.possibly_paid_by else "",
                     "ln": [[ic.desc, _n(amt), _n(due), KIND.get(ic.kind, ""), ic.reason] for ic, amt, due in o.lines]})
    s = c.sums
    return {"k": fb_key(c), "h": c.hyp_id, "n": c.name, "p": c.priority, "a": c.action, "w": c.when,
            "on": c.contact_on.isoformat() if c.contact_on else "", "net": _n(c.net_to_collect), "open": _n(c.open_debt),
            "dbl": _n(c.double_counted), "nd": _n(c.not_due), "tax": _n(c.tax_unverified),
            "chq": _n(c.cheques_pending), "after": _n(c.paid_after_snapshot), "days": c.oldest_days,
            "lp": lp.doc_date.isoformat() if lp else "", "lpa": _n(lp.total) if lp else 0, "auto": c.auto_charge,
            "f": {"t": _n(s[T]), "i": _n(s["חשבונית מס"]), "ir": _n(s[IR]), "c": _n(s["חשבונית זיכוי"]),
                  "f": _n(c.formula)} if c.has_history else None,
            "why": c.reasons, "docs": docs}


def summary_lines(custs: list[Customer], summary: dict) -> list:
    Z = Decimal(0)
    tot = lambda attr, cond=lambda c: True: sum((getattr(c, attr) for c in custs if cond(c)), Z)
    grp = lambda k: sum((c.open_debt - c.double_counted - c.tax_unverified for c in custs if c.priority == k), Z)
    return [
        ["חוב פתוח ב-Hyp (ברוטו)", _n(summary["open_total"])],
        ["נספר כפול: מסמך פתוח שכבר מכוסה בחשבונית / תשלום שלא שויכו", -_n(tot("double_counted"))],
        ["שכ\"ט שהופק אך טרם מגיע (דוח / מאזן שטרם הוגש, חודשים עתידיים)", -_n(tot("not_due", lambda c: c.priority in LIVE))],
        ["לקוחות בחיוב קבוע – לא נספרים", -_n(grp("חיוב קבוע"))],
        ["יעל בדקה: תקין, ירד מהיתרה", -_n(grp("נבדק – תקין"))],
        ["מוחרגים / הוסתרו", -_n(grp("מוחרג"))],
        ["חשבוניות מס פתוחות – לאימות תשלום", -_n(tot("tax_unverified"))],
        ["שיקים דחויים ותשלומים אחרי העדכון",
         -_n(sum((c.open_debt - c.double_counted - c.tax_unverified - c.not_due - c.net_to_collect
                  for c in custs if c.priority in LIVE), Z))],
        ["ממתין לתשובת גיא / דקל", -_n(tot("net_to_collect", lambda c: c.priority == "ממתין להנהלה"))],
        ["חוב לגבייה – לפנייה ללקוחות", _n(tot("collectible"))],
    ]


def build(custs: list[Customer], issues: list, summary: dict) -> dict:
    rows = [_row(c) for c in custs if c.open_debt > 0]
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)] or [[]]
    meta = {"runAt": datetime.now().astimezone().isoformat(timespec="seconds"), "asOf": summary["as_of"].isoformat(),
            "snapshot": summary["snapshot"], "history": summary.get("history", ""), "chunks": len(chunks),
            "count": len(rows), "weekEnd": summary["week_end"].isoformat(), "summary": summary_lines(custs, summary),
            "issues": [[i.severity, i.code, i.customer, i.message] for i in issues if i.severity in ("error", "warning")][:80]}
    out = {"meta": meta}
    for i, ch in enumerate(chunks):
        out[f"r{i}"] = {"rows": ch}
    return out


def write(out_dir: str | Path, custs, issues, summary) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("r*.json"):
        old.unlink()
    for name, doc in build(custs, issues, summary).items():
        (d / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d
