"""Excel report: who to contact, per-customer debt breakdown, document trail, data issues."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from .engine import AGING_BUCKETS
from .models import DOC_TYPE_HE, CustomerBalance, Issue

AGING_COLS = [b[2] for b in AGING_BUCKETS] + ["ללא תאריך", "עתידי", "לא משויך לחשבון עסקה"]
_FILL = {"דחוף": "F8CBAD", "חריג": "FFE699", "לטיפול": "FCE4D6", "מעקב": "DDEBF7", "תקין": "E2EFDA"}
_SEV_HE = {"error": "שגיאה", "warning": "אזהרה", "info": "מידע"}


def _f(v: Decimal) -> float:
    return float(v)


def write_excel(path: str | Path, balances: list[CustomerBalance], issues: list[Issue], *, board: str,
                as_of: date) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    money = '#,##0.00;[Red]-#,##0.00'

    def sheet(title, headers, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
        return ws

    def finish(ws, widths, money_cols=()):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for col in money_cols:
            for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                row[0].number_format = money
        ws.auto_filter.ref = ws.dimensions

    # 1. למי לפנות
    ws = sheet("למי לפנות", ["עדיפות", "לקוח", "יתרת חוב", "חשבון עסקה פתוח הוותיק", "ימים", "סיבה", "איש קשר",
                              "מס' חשבונות עסקה פתוחים"], first=True)
    for b in balances:
        if b.priority in ("תקין",):
            continue
        ws.append([b.priority, b.customer_name, _f(b.debt),
                   b.oldest_open_date.strftime("%d/%m/%Y") if b.oldest_open_date else "",
                   b.oldest_open_days if b.oldest_open_days is not None else "", "; ".join(b.reasons), b.contact,
                   len(b.open_transactions)])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=_FILL.get(b.priority, "FFFFFF"))
    finish(ws, [10, 32, 14, 16, 8, 70, 24, 12], money_cols=(3,))

    # 2. פירוק חוב – כל הלקוחות
    ws = sheet("פירוק חוב", ["לקוח", "חשבונות עסקה", "חשבוניות מס", "חשבוניות מס קבלה", "זיכויים", "יתרת חוב",
                             "נוסחה", "עדיפות"] + [f"גיול {c}" for c in AGING_COLS])
    tot = [Decimal(0)] * 5
    for b in balances:
        vals = [b.transactions, b.tax_invoices, b.tax_invoice_receipts, b.credits, b.debt]
        tot = [t + v for t, v in zip(tot, vals)]
        ws.append([b.customer_name] + [_f(v) for v in vals] + [b.formula, b.priority]
                  + [_f(b.aging.get(c, Decimal(0))) for c in AGING_COLS])
    ws.append(["סה\"כ"] + [_f(v) for v in tot])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    finish(ws, [32, 14, 14, 14, 14, 14, 52, 10] + [12] * len(AGING_COLS),
           money_cols=tuple(range(2, 7)) + tuple(range(9, 9 + len(AGING_COLS))))

    # 3. חשבונות עסקה פתוחים (הקצאת FIFO)
    ws = sheet("חשבונות עסקה פתוחים", ["לקוח", "מס' מסמך", "תאריך", "ימים", "סכום מקורי", "יתרה פתוחה (FIFO)",
                                        "שורה בלוח"])
    for b in balances:
        if b.debt <= 0:
            continue
        for t, rem in b.open_transactions:
            ws.append([b.customer_name, t.doc_number, t.doc_date.strftime("%d/%m/%Y") if t.doc_date else "",
                       (as_of - t.doc_date).days if t.doc_date else "", _f(t.amount), _f(rem), t.row_ref])
    finish(ws, [32, 14, 12, 8, 14, 16, 14], money_cols=(5, 6))

    # 4. מסמכים – עקבות ביקורת
    ws = sheet("מסמכים", ["לקוח", "סוג (מנורמל)", "סוג כפי שבלוח", "מס' מסמך", "תאריך", "סכום בלוח",
                          "השפעה על החוב", "קבוצה", "שורה בלוח"])
    for b in balances:
        for d in b.documents:
            ws.append([b.customer_name, DOC_TYPE_HE[d.doc_type], d.raw_type, d.doc_number,
                       d.doc_date.strftime("%d/%m/%Y") if d.doc_date else "", _f(d.amount), _f(d.effect or Decimal(0)),
                       d.group, d.row_ref])
    finish(ws, [32, 16, 18, 12, 12, 14, 14, 16, 14], money_cols=(6, 7))

    # 5. בעיות נתונים
    ws = sheet("בעיות נתונים", ["חומרה", "קוד", "לקוח", "תיאור", "שורה בלוח"])
    order = {"error": 0, "warning": 1, "info": 2}
    for i in sorted(issues, key=lambda x: order.get(x.severity, 9)):
        ws.append([_SEV_HE.get(i.severity, i.severity), i.code, i.customer, i.message, i.row_ref])
    finish(ws, [10, 18, 28, 90, 14])

    # 6. פרטי הרצה
    ws = sheet("פרטי הרצה", ["פרמטר", "ערך"])
    for k, v in [("לוח", board), ("תאריך גיול", as_of.strftime("%d/%m/%Y")), ("לקוחות", len(balances)),
                 ("מסמכים שנספרו", sum(len(b.documents) for b in balances)),
                 ("שגיאות נתונים", sum(i.severity == "error" for i in issues)),
                 ("נוסחה", "חוב = חשבונות עסקה − חשבוניות מס − חשבוניות מס קבלה + זיכויים"),
                 ("גיול", "הקצאת FIFO של החשבוניות (בניכוי זיכויים) לחשבונות העסקה הוותיקים – אומדן")]:
        ws.append([k, v])
    finish(ws, [18, 80])

    if not str(path).endswith(".xlsx") and wb.worksheets:
        path = Path(str(path) + ".xlsx")
    wb.save(path)
    return Path(path)


def console_summary(balances: list[CustomerBalance], issues: list[Issue], top: int = 20) -> str:
    from collections import Counter
    c = Counter(b.priority for b in balances)
    total = sum((b.debt for b in balances if b.debt > 0), Decimal(0))
    lines = [f"לקוחות: {len(balances)} | סה\"כ חוב פתוח: {total:,.2f} ₪",
             "  " + " | ".join(f"{k}: {c.get(k, 0)}" for k in ("דחוף", "חריג", "לטיפול", "מעקב", "תקין")),
             f"בעיות נתונים: {sum(i.severity == 'error' for i in issues)} שגיאות, "
             f"{sum(i.severity == 'warning' for i in issues)} אזהרות", ""]
    for b in [b for b in balances if b.priority in ("דחוף", "חריג", "לטיפול")][:top]:
        lines.append(f"[{b.priority}] {b.customer_name}: {b.debt:,.2f} ₪ – {'; '.join(b.reasons)}")
    return "\n".join(lines)
