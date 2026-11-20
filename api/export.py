"""Excel export of a calculation result (summary, trace, alerts, parameters)."""
from __future__ import annotations

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADER = PatternFill("solid", fgColor="1F3A5F")
HFONT = Font(color="FFFFFF", bold=True)


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list]):
    ws = wb.create_sheet(title)
    ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HEADER, HFONT
    for r in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in r])
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(12, width + 2), 80)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, float):
                c.number_format = "#,##0.00"
            c.alignment = Alignment(wrap_text=True, vertical="top")
    return ws


def result_to_xlsx(result, client_name: str = "") -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    rows = [["שנת מס", result.tax_year], ["לקוח", client_name], ["נטל מס כולל", result.total_tax_burden]]
    for c in result.companies:
        rows += [[f"חברה {c.id} – {c.name}", ""], ["  62א(א1) חל", "כן" if c.s62a1_applies else "לא"],
                 ["  שיעור רווחיות %", c.profitability_rate], ["  הכנסה חייבת", c.taxable_income],
                 ["  מס חברות", c.corporate_tax], ["  תוספת מס 81ב", c.s81_tax], ["  יתרה לתשלום", c.balance_due]]
        for sec, v in c.attributed_by_section.items():
            rows.append([f"  ייחוס {sec}", v])
    for i in result.individuals:
        rows += [[f"יחיד {i.id} – {i.name}", ""], ["  הכנסה חייבת כוללת", i.taxable_income_total],
                 ["  חבות מס", i.gross_tax], ["  מס יסף", i.surtax + i.surtax_capital], ["  יתרה לתשלום", i.balance_due],
                 ["  ב\"ל ובריאות", i.nii_employee + i.nii_self_employed + i.nii_passive],
                 ["  שיעור מס שולי %", i.marginal_rate], ["  שיעור מס אפקטיבי %", i.effective_rate]]
    _sheet(wb, "סיכום", ["פריט", "ערך"], rows)
    _sheet(wb, "פירוק חישוב", ["ישות", "שלב", "תיאור", "נוסחה", "ערך", "מקור", "הערה"],
           [[s["entity"], s["stage"], s["label"], s["formula"], s["value"] if not isinstance(s["value"], bool)
             else ("כן" if s["value"] else "לא"), s["ref"], s["note"]] for s in result.trace])
    _sheet(wb, "התראות", ["חומרה", "קוד", "ישות", "הודעה", "מקור"],
           [[a.severity, a.code, a.entity, a.message, a.ref] for a in result.alerts])
    _sheet(wb, "פרמטרים", ["פרמטר", "סטטוס", "מקור"], [[p.path, p.status, p.source] for p in result.params_used])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
