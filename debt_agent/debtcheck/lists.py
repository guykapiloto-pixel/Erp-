"""Collection work lists – everything that can be collected, by what has to be done to collect it.

Each list answers one question for the collections team. A customer can appear in more than one list.

  1  פנייה לגבייה עכשיו            debt that is due now (the agent's main calculation)
  2  גבייה עד סוף השנה             due now + the months of the current year still ahead in the open annual account
  3  דוחות ומאזנים – לאמת הגשה      annual report / balance sheet fees issued in a transaction account, not counted
                                    as debt only because there is no record that the report was filed
  4  חשבוניות מס פתוחות             tax invoices that are open in Hyp (VAT already paid) – verify payment, collect
  5  חודשים חסרים                  months between a customer's paid months that have no payment and no open charge
  6  חיוב אוטומטי שנכשל            standing charges that failed and were not handled
  7  לא שילמו מעולם                open debt of customers with no payment at all since the company opened
  8  לביטול / סגירה ב-Hyp           open documents that are cancelled, or already paid and not linked
  9  משפטי                         customers marked on the board as bankrupt / legal
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .classify import parse_period
from .hyp import IR, I, R, T, Customer

D0 = Decimal("0")


@dataclass
class WorkList:
    key: str
    title: str
    owner: str          # who acts
    action: str         # what to do
    columns: list
    rows: list = field(default_factory=list)       # each row: list matching columns; row[1] = amount
    amount_col: int = 1

    @property
    def total(self) -> Decimal:
        return sum((Decimal(str(r[self.amount_col] or 0)) for r in self.rows), D0)


def _months_between(a: tuple, b: tuple):
    y, m = a
    while (y, m) <= b:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _ym(d: date) -> tuple:
    return d.year, d.month


def build(custs: list[Customer], as_of: date, tx_items: dict, pay_items: dict, cfg: dict) -> list[WorkList]:
    last_ended = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
    year_end = (as_of.year, 12)
    excluded = {"מוחרג", "בוטל – לסגור ב-Hyp", "משפטי"}
    L = {}

    def wl(key, title, owner, action, cols):
        L[key] = WorkList(key, title, owner, action, cols)
        return L[key]

    l1 = wl("now", "פנייה לגבייה עכשיו", "מנהלת הגבייה", "לפנות ללקוח ולגבות את החוב שהגיע",
            ["לקוח", "לגבייה עכשיו ₪", "עדיפות", "מתי לפנות", "טלפון", "ממה מורכב החוב"])
    l2 = wl("year", "גבייה עד סוף השנה", "מנהלת הגבייה",
            "לגבות עכשיו את החוב, ולתאם תשלום של יתרת השנה (חודשים שנותרו בחשבון העסקה השנתי)",
            ["לקוח", "סה\"כ עד סוף השנה ₪", "חוב עכשיו ₪", "חודשים שנותרו בשנה ₪", "חיוב קבוע", "טלפון"])
    l3 = wl("reports", "דוחות ומאזנים – לאמת הגשה ולגבות", "רו\"ח / מנה\"ח מטפל",
            "לבדוק אם הדוח / המאזן הוגש. אם כן – לסמן בלוח \"הדוח הוגש\" והסכום עובר לגבייה",
            ["לקוח", "סכום פתוח ₪", "סוג", "שנה", "חשבון עסקה", "פירוט", "מטפל"])
    l4 = wl("tax", "חשבוניות מס פתוחות – לא שולמו", "מנה\"ח + מנהלת הגבייה",
            "לבדוק אם התקבל תשלום. אם לא – לגבות (המע\"מ כבר דווח ושולם)",
            ["לקוח", "יתרה פתוחה ₪", "חשבונית מס", "תאריך", "ימים", "טלפון"])
    l5 = wl("gaps", "חודשים חסרים – לא חויבו או לא שולמו", "מנהלת הגבייה",
            "לבדוק אם השירות ניתן בחודשים האלה. אם כן – להפיק חשבון עסקה ולגבות",
            ["לקוח", "אומדן ₪", "חודשים חסרים", "תשלום חודשי מקובל ₪", "חודשים ששולמו", "טלפון"])
    l6 = wl("failed", "חיוב אוטומטי שנכשל", "מנהלת הגבייה",
            "לפנות ללקוח לעדכון אמצעי התשלום ולחייב מחדש",
            ["לקוח", "לגבייה ₪", "נכשל בתאריך", "טלפון"])
    l7 = wl("never", "לא שילמו מעולם – לאמת שהחיוב בתוקף", "מנהלת הגבייה + שותף",
            "לוודא שהחיוב לא בוטל ושהלקוח פעיל, ורק אז לפנות",
            ["לקוח", "פתוח ב-Hyp ₪", "מסמכים פתוחים", "חשבון עסקה ראשון", "טלפון"])
    l8 = wl("close", "לביטול / סגירה ב-Hyp", "מנה\"ח",
            "לסגור או לבטל ב-Hyp את המסמך הפתוח, כדי שהיתרה ב-Hyp תהיה נכונה",
            ["לקוח", "פתוח ב-Hyp ₪", "סיבה", "מסמכים"])
    l9 = wl("legal", "משפטי / פשיטת רגל", "שותף",
            "להחליט על המשך טיפול משפטי או מחיקה",
            ["לקוח", "פתוח ב-Hyp ₪", "הערה", "טלפון"])

    for c in custs:
        if c.open_debt <= 0 and not c.payments:
            continue
        docs_label = ", ".join(f"{o.num} ({float(o.remaining):,.0f})" for o in sorted(c.open_docs, key=lambda o: o.doc_date))
        from .hyp import explain
        x = explain(c) if c.accrual_based else {"sentence": c.reasons[0] if c.reasons else ""}

        if c.priority in ("דחוף", "לטיפול", "מעקב") and c.net_to_collect > 0:
            l1.rows.append([c.name, float(c.net_to_collect), c.priority, c.when, c.phone, x["sentence"]])

        if c.priority not in excluded and c.priority != "נבדק – תקין":
            ahead = D0
            for o in c.open_docs:
                if o.type != T:
                    continue
                for ic, amt, due in o.lines:
                    if ic.kind == "period" and ic.period and ic.period[0] == as_of.year and amt > due:
                        ahead += amt - due
            now = c.net_to_collect if c.priority in ("דחוף", "לטיפול", "מעקב", "ממתין להנהלה") else D0
            if now + ahead > 0 and (now > 0 or not c.auto_charge):
                l2.rows.append([c.name, float(now + ahead), float(now), float(ahead), "כן" if c.auto_charge else "", c.phone])

        if c.priority not in excluded:
            for o in c.open_docs:
                for ic, amt, due in o.lines:
                    if ic.kind in ("annual", "balance") and amt > due and "אין תיעוד" in ic.reason:
                        l3.rows.append([c.name, float(amt - due), "מאזן / ביקורת" if ic.kind == "balance" else "דו\"ח שנתי",
                                        ic.year, o.num, ic.desc, c.handler])
            for o in c.open_docs:
                if o.type == I and o.remaining > 0 and not c.excluded:
                    l4.rows.append([c.name, float(o.remaining), o.num, o.doc_date.strftime("%d/%m/%Y"),
                                    (as_of - o.doc_date).days, c.phone])

        if c.failed_charge and c.priority not in excluded:
            l6.rows.append([c.name, float(c.net_to_collect), c.failed_charge.strftime("%d/%m/%Y"), c.phone])

        if c.open_debt > 0 and not any(d.type in (IR, R) and d.total > 0 for d in c.docs + c.later_docs) \
                and c.priority not in excluded:
            first = min((o.doc_date for o in c.open_docs), default=None)
            l7.rows.append([c.name, float(c.open_debt), len(c.open_docs), first.strftime("%d/%m/%Y") if first else "",
                            c.phone])

        if c.priority in ("לסגירה ב-Hyp", "בוטל – לסגור ב-Hyp"):
            l8.rows.append([c.name, float(c.open_debt), c.reasons[0] if c.reasons else "", docs_label])
        if c.priority == "משפטי":
            l9.rows.append([c.name, float(c.open_debt), c.fb_note, c.phone])

        # חודשים חסרים: בין החודש הראשון ששולם לחודש האחרון שהסתיים, חודש בלי תשלום ובלי חיוב פתוח
        if c.priority in excluded or not c.payments:
            continue
        paid_m, amounts = set(), Counter()
        for dt, amt, what in c.payments:
            if amt <= 0:
                continue
            # רק הפירוט שבסוגריים – לא תאריך המסמך שבתווית
            desc = what[what.find("(") + 1:what.rfind(")")] if "(" in what else ""
            p = parse_period(desc)
            if p:
                for m in range(p[1], p[2] + 1):
                    paid_m.add((p[0], m))
                if p[1] == p[2]:
                    amounts[round(float(amt))] += 1
            else:
                paid_m.add(_ym(dt))
                amounts[round(float(amt))] += 1
        for d in c.docs + c.later_docs:            # תשלום שהופק מתוך חשבון עסקה: החודשים שעליו
            if d.type in (IR, I) and d.total > 0:
                items = (pay_items.get((d.type, d.num)) or {}).get("items") or []
                for it in items:
                    p = parse_period(it.get("desc", ""))
                    if p:
                        for m in range(p[1], p[2] + 1):
                            paid_m.add((p[0], m))
        open_m = set()
        for o in c.open_docs:
            for ic, amt, due in o.lines:
                if ic.period:
                    open_m |= {(ic.period[0], m) for m in range(ic.period[1], ic.period[2] + 1)}
        if len(paid_m) < 4 or not amounts:
            continue
        fee, freq = amounts.most_common(1)[0]
        if freq < 3:
            continue
        start = min(paid_m)
        missing = [m for m in _months_between(start, last_ended) if m not in paid_m and m not in open_m]
        # רצף של יותר מ-6 חודשים חסרים בסוף התקופה = הלקוח כנראה עזב, לא חוב
        tail = 0
        for m in reversed(list(_months_between(start, last_ended))):
            if m in paid_m or m in open_m:
                break
            tail += 1
        if tail > 6:
            missing = missing[:-tail] if tail <= len(missing) else []
        if missing:
            l5.rows.append([c.name, fee * len(missing), ", ".join(f"{m:02d}/{y % 100:02d}" for y, m in missing),
                            fee, len(paid_m), c.phone])

    for k in L.values():
        k.rows.sort(key=lambda r: -(r[k.amount_col] or 0))
    return list(L.values())


def _sheet(i: int, l: WorkList) -> str:
    import re
    return f"{i}. " + re.sub(r"[\\/*?:\[\]]", "-", l.title)[:27]


def write_excel(path, lists: list[WorkList], as_of: date):
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "סיכום הרשימות"
    ws.sheet_view.rightToLeft = True
    ws.append([f"רשימות גבייה נכון ל-{as_of:%d/%m/%Y}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["#", "רשימה", "לקוחות", "סכום ₪", "מי מטפל", "מה עושים"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for i, l in enumerate(lists, 1):
        ws.append([i, l.title, len(l.rows), float(l.total), l.owner, l.action])
        ws.cell(ws.max_row, 4).number_format = "#,##0"
        ws.cell(ws.max_row, 2).hyperlink = f"#'{_sheet(i, l)}'!A1"
    ws.append([])
    ws.append(["", "לקוח יכול להופיע ביותר מרשימה אחת, ולכן אין לחבר את הסכומים."])
    for col, w in zip("ABCDEF", (4, 40, 9, 14, 22, 90)):
        ws.column_dimensions[col].width = w
    for i, l in enumerate(lists, 1):
        s = wb.create_sheet(_sheet(i, l))
        s.sheet_view.rightToLeft = True
        s.append([l.title])
        s["A1"].font = Font(bold=True, size=13)
        s.append([f"מי מטפל: {l.owner} · מה עושים: {l.action}"])
        s.append([f"{len(l.rows)} לקוחות · {float(l.total):,.0f} ₪"])
        s.append(l.columns + ["טופל", "הערה"])
        for c in s[4]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True)
        for r in l.rows:
            s.append(r)
            s.cell(s.max_row, l.amount_col + 1).number_format = "#,##0"
        s.freeze_panes = "B5"
        for i in range(1, len(l.columns) + 3):
            s.column_dimensions[get_column_letter(i)].width = 30 if i == 1 else (80 if i == len(l.columns) and
                                                                                l.key == "now" else 16)
        if s.max_row > 4:
            s.auto_filter.ref = f"A4:{get_column_letter(len(l.columns) + 2)}{s.max_row}"
    wb.save(path)
    return path
