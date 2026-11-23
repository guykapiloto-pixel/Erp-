"""Excel work report for the Hyp collections analysis."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from .hyp import AGING, C, I, IR, R, T, Customer, Issue

AG = [a[2] for a in AGING]
FILL = {"דחוף": "F8CBAD", "לטיפול": "FCE4D6", "לבדיקה": "FFE699", "מעקב": "DDEBF7", "חיוב אוטומטי": "E2EFDA",
        "מוחרג": "D9D9D9", "תקין": "FFFFFF"}
SEV = {"error": "שגיאה", "warning": "אזהרה", "info": "מידע"}


def _f(v) -> float:
    return float(v or 0)


def _dt(d):
    return d.strftime("%d/%m/%Y") if d else ""


def write(path: str | Path, custs: list[Customer], issues: list[Issue], summary: dict, gap_tol=100) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    money = '#,##0;[Red]-#,##0'
    as_of: date = summary["as_of"]

    def sheet(title, headers, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "B2"
        return ws

    def finish(ws, widths, money_cols=(), link_col=None):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for col in money_cols:
            for (cell,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                cell.number_format = money
        if link_col:
            for (cell,) in ws.iter_rows(min_row=2, min_col=link_col, max_col=link_col):
                if cell.value:
                    cell.hyperlink, cell.value, cell.style = cell.value, "העתק", "Hyperlink"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions

    # 1. סיכום
    ws = sheet("סיכום", ["נושא", "ערך"], first=True)
    pr = Counter(c.priority for c in custs)
    tot = lambda attr, cond=lambda c: True: sum((getattr(c, attr) for c in custs if cond(c)), Decimal(0))
    rows = [
        ("תמונת מצב הלוח (מסמכים פתוחים ב-Hyp)", summary["snapshot"]),
        ("מקור היסטוריה", summary.get("history", "")),
        ("תאריך גיול", _dt(as_of)),
        ("לקוחות בניתוח", summary["customers"]),
        ("מסמכים בהיסטוריה (קובץ Hyp)", summary["docs"]),
        ("חוב פתוח לפי Hyp", _f(summary["open_total"])),
        ("  מתוכו חשבונות עסקה", _f(tot("open_tx"))),
        ("  מתוכו חשבוניות מס שלא שולמו", _f(tot("open_tax"))),
        ("  ייתכן ששולם (תשלום באותו סכום שלא שויך)", _f(tot("possibly_paid"))),
        ("  התקבל אחרי עדכון הלוח", _f(tot("paid_after_snapshot"))),
        ("  מוחרגים", _f(tot("open_debt", lambda c: c.excluded))),
        ("חוב נטו לגבייה (אומדן)", _f(tot("net_to_collect", lambda c: not c.excluded))),
        ("חוב לפי הנוסחה (עסקה − מס − מס קבלה + זיכוי)", _f(tot("formula"))),
        ("", ""),
    ] + [(f"גיול {a}", _f(sum((c.aging.get(a, 0) for c in custs), Decimal(0)))) for a in AG] + [("", "")] + \
        [(f"לקוחות – {k}", pr.get(k, 0)) for k in FILL] + [("", ""),
         ("שגיאות נתונים", sum(i.severity == "error" for i in issues)),
         ("אזהרות", sum(i.severity == "warning" for i in issues))]
    for r in rows:
        ws.append(list(r))
    for (cell,) in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        if isinstance(cell.value, float):
            cell.number_format = money
    finish(ws, [48, 28])

    # 1א. רשימת השבוע – למי לפנות ומתי
    wk = summary.get("week_end")
    ws = sheet("רשימת השבוע", ["מתי", "עדיפות", "לקוח", "טלפון", "מייל", "איש קשר", "לגבייה (נטו)", "מסמך פתוח ותיק",
                               "ימים", "תשלום אחרון", "פנייה אחרונה", "הערה אחרונה בלוח", "מס' הנה\"ח", "מה לבקש / סיבה"])
    week = [c for c in custs if c.contact_on and wk and c.contact_on <= wk]
    week.sort(key=lambda c: (c.contact_on, {"דחוף": 0, "לטיפול": 1, "מעקב": 2}.get(c.priority, 3), -c.score))
    for c in week:
        lp = c.last_payment
        ws.append([c.when, c.priority, c.name, c.phone, c.email, c.contact, _f(c.net_to_collect), _dt(c.oldest_open),
                   c.oldest_days, f"{_dt(lp.doc_date)} ({_f(lp.total):,.0f})" if lp else "אין", _dt(c.last_contact),
                   c.last_note[:200], c.bk, " | ".join(c.reasons)])
        ws.cell(ws.max_row, 2).fill = PatternFill("solid", fgColor=FILL.get(c.priority, "FFFFFF"))
    finish(ws, [26, 9, 30, 13, 24, 12, 12, 11, 6, 18, 11, 40, 9, 90], money_cols=(7,))
    ws.insert_rows(1)
    ws["A1"] = (f"רשימת פניות לשבוע עד {_dt(wk)} – {len(week)} לקוחות, "
                f"{sum((c.net_to_collect for c in week), Decimal(0)):,.0f} ₪ לגבייה")
    ws["A1"].font = Font(bold=True, size=13)
    ws.freeze_panes = "D3"
    ws.auto_filter.ref = f"A2:{get_column_letter(ws.max_column)}{ws.max_row}"

    # 2. למי לפנות
    ws = sheet("למי לפנות", ["עדיפות", "פעולה", "מתי", "לקוח", "ח.פ/ת.ז", "מס' הנה\"ח", "טלפון", "מייל", "איש קשר", "חוב פתוח ב-Hyp",
                              "ייתכן ששולם", "שולם אחרי עדכון", "לגבייה (נטו)", "מסמך פתוח ותיק", "ימים", "מס' מסמכים פתוחים",
                              "תשלום אחרון", "סכום תשלום אחרון", "נגבה 12 חודשים", "חיוב אוטומטי", "סיבות"])
    for c in custs:
        if c.priority == "תקין":
            continue
        lp = c.last_payment
        ws.append([c.priority, c.action, c.when, c.name, c.crn, c.bk, c.phone, c.email, c.contact, _f(c.open_debt), _f(c.possibly_paid),
                   _f(c.paid_after_snapshot), _f(c.net_to_collect), _dt(c.oldest_open), c.oldest_days,
                   len(c.open_docs), _dt(lp.doc_date) if lp else "", _f(lp.total) if lp else None, _f(c.paid_12m),
                   "כן" if c.auto_charge else "", " | ".join(c.reasons)])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=FILL.get(c.priority, "FFFFFF"))
    finish(ws, [11, 16, 26, 30, 11, 9, 13, 24, 12, 12, 11, 11, 12, 12, 7, 8, 11, 11, 12, 8, 90],
           money_cols=(10, 11, 12, 13, 18, 19))

    # 3. פירוק חוב
    ws = sheet("פירוק חוב", ["לקוח", "ח.פ/ת.ז", "חשבונות עסקה", "חשבוניות מס", "חשבוניות מס קבלה", "קבלות", "זיכויים",
                             "חוב לפי הנוסחה", "חוב פתוח ב-Hyp", "  חשבונות עסקה פתוחים", "  חשבוניות מס פתוחות",
                             "פער (נוסחה − Hyp)", "חשבונות עסקה שנסגרו", "שולם חלקית על מסמכים פתוחים", "עדיפות"]
               + [f"גיול {a}" for a in AG])
    for c in custs:
        s = c.sums
        ws.append([c.name, c.crn, _f(s[T]), _f(s[I]), _f(s[IR]), _f(s[R]), _f(s[C]), _f(c.formula), _f(c.open_debt),
                   _f(c.open_tx), _f(c.open_tax), _f(c.gap), _f(c.closed_tx), _f(c.partial_applied), c.priority]
                  + [_f(c.aging.get(a)) for a in AG])
    n = ws.max_row
    ws.append(["סה\"כ", ""] + [f"=SUM({get_column_letter(k)}2:{get_column_letter(k)}{n})" for k in range(3, 15)]
              + [""] + [f"=SUM({get_column_letter(k)}2:{get_column_letter(k)}{n})" for k in range(16, 16 + len(AG))])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    finish(ws, [30, 11] + [12] * 12 + [10] + [11] * len(AG), money_cols=tuple(range(3, 15)) + tuple(range(16, 16 + len(AG))))

    # 3א. בקרת פערים מול הנוסחה
    ws = sheet("בקרת פערים", ["לקוח", "ח.פ/ת.ז", "חוב לפי הנוסחה", "חוב פתוח ב-Hyp", "פער", "חשבונות עסקה שנסגרו",
                              "חשבוניות מס + מס קבלה − זיכויים", "קבלות", "פירוש"])
    for c in sorted(custs, key=lambda c: -abs(c.gap)):
        if abs(c.gap) <= gap_tol:
            continue
        s_ = c.sums
        ws.append([c.name, c.crn, _f(c.formula), _f(c.open_debt), _f(c.gap), _f(c.closed_tx),
                   _f(s_[I] + s_[IR] - s_[C]), _f(s_[R]),
                   "חשבונות עסקה נסגרו ללא חשבונית/תשלום – לוודא שהסגירה מוצדקת" if c.gap > 0 else
                   "חיוב ישיר/הוראת קבע ללא חשבון עסקה, או חשבוניות מס פתוחות שהנוסחה מנכה"])
    finish(ws, [30, 11, 13, 13, 13, 13, 16, 12, 70], money_cols=(3, 4, 5, 6, 7, 8))

    # 4. מסמכים פתוחים
    ws = sheet("מסמכים פתוחים", ["לקוח", "סוג", "מספר", "תאריך", "ימים", "גיול", "סכום מקורי", "יתרה פתוחה",
                                 "לפני מע\"מ", "תיאור", "ייתכן ששולם ע\"י", "תאריך התשלום", "מסמך"])
    for c in custs:
        for o in sorted(c.open_docs, key=lambda o: o.doc_date):
            p = o.possibly_paid_by
            days = (as_of - o.doc_date).days
            from .hyp import bucket
            ws.append([c.name, o.type, o.num, _dt(o.doc_date), days, bucket(days), _f(o.total), _f(o.remaining),
                       _f(o.before_vat), o.description, f"{p.type} {p.num}" if p else "", _dt(p.doc_date) if p else "",
                       o.url])
    finish(ws, [30, 14, 9, 11, 7, 9, 12, 12, 11, 30, 20, 11, 8], money_cols=(7, 8, 9), link_col=13)

    # 5. בעיות נתונים
    ws = sheet("בעיות נתונים", ["חומרה", "קוד", "לקוח", "תיאור", "מסמך"])
    order = {"error": 0, "warning": 1, "info": 2}
    for i in sorted(issues, key=lambda x: order.get(x.severity, 9)):
        ws.append([SEV.get(i.severity, i.severity), i.code, i.customer, i.message, i.ref])
    finish(ws, [9, 20, 30, 100, 18])

    # 6. הגדרות ושיטה
    ws = sheet("שיטה", ["נושא", "הסבר"])
    for r in [
        ("חוב פתוח", "יתרת המסמכים הפתוחים ב-Hyp (חשבונות עסקה + חשבוניות מס שלא שולמו), לפי הלוח"),
        ("חוב לפי הנוסחה", "Σ חשבונות עסקה − Σ חשבוניות מס − Σ חשבוניות מס קבלה + Σ זיכויים, מכל ההיסטוריה עד תאריך הלוח"),
        ("פער", "הפרש בין השניים. חיובי = חשבונות עסקה שנסגרו ב-Hyp ללא חשבונית. שלילי = חיוב ישיר/הוראת קבע/חשבוניות מס פתוחות"),
        ("ייתכן ששולם", "מסמך פתוח שקיים אחריו תשלום (חשבונית מס קבלה/קבלה) באותו סכום שלא שויך למסמך אחר – יש לאמת ולסגור ב-Hyp"),
        ("לגבייה (נטו)", "חוב פתוח − ייתכן ששולם − תשלומים שהתקבלו אחרי עדכון הלוח"),
        ("עדיפות", "דחוף: נטו ≥ סף סכום או מסמך ≥ ימי דחיפות. לטיפול: ≥ ימי מעקב. לבדיקה: הכל מכוסה/פער. "
                   "חיוב אוטומטי: בחיוב פעיל ומסמך צעיר"),
    ]:
        ws.append(list(r))
    finish(ws, [20, 120])

    wb.move_sheet("רשימת השבוע", offset=-wb.sheetnames.index("רשימת השבוע"))
    wb.active = 0
    path = Path(path)
    wb.save(path)
    return path
