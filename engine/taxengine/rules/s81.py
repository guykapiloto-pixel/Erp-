"""Sections 81A-81F: additional 2% tax on undistributed ('excess') profits of a few-company.

Sources: Income Tax Execution Directive 9/2026 s.4-4.1 (appendix 1281); Circular 7/2025.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..context import Ctx
from ..models import CompanyInput
from ..money import ZERO, fmt, fmt_rate, pos
from .corporate import CorpState

STAGE = "s81"
REF = "ס' 81ב; הוראת ביצוע 9/2026 ס' 4.1 (נספח 1281)"


@dataclass
class S81State:
    applies: bool = False
    accumulated: Decimal = ZERO
    excess: Decimal = ZERO
    taxable: Decimal = ZERO
    tax: Decimal = ZERO
    exemption: str = ""
    min_dividend_to_avoid: Decimal = ZERO


def apply_81b(c: CompanyInput, ctx: Ctx, cs: CorpState, loss_in_year: Decimal) -> S81State:
    ent = f"company:{c.id}"
    s = S81State()
    if not c.is_few_company:
        s.exemption = "אינה חברת מעטים"
        return s
    i = c.s81
    # accumulated profits = lower of the tax and accounting alternatives (Directive 9/2026 s.4.1 part B)
    alts = [a for a in (i.accumulated_profits_tax_alt, i.accumulated_profits_accounting_alt) if a is not None]
    s.accumulated = min(alts) if alts else c.accumulated_profits_prev
    ctx.trace.add(ent, STAGE, "accumulated", "רווחים נצברים לתום השנה הקודמת", s.accumulated,
                  "הנמוך מבין: חלופת מס " + (fmt(i.accumulated_profits_tax_alt) if i.accumulated_profits_tax_alt is not None else "—")
                  + " / חלופה חשבונאית " + (fmt(i.accumulated_profits_accounting_alt) if i.accumulated_profits_accounting_alt is not None else "—"),
                  "ס' 81א 'רווחים נצברים'; הוראת ביצוע 9/2026 ס' 4.1 חלק ב")
    thr = ctx.p.num("s81.applicability_threshold")
    if s.accumulated < thr:
        s.exemption = f"רווחים נצברים מתחת ל-{fmt(thr)} ₪ – אין חובת נספח 1281"
        ctx.trace.add(ent, STAGE, "not_applicable", "ס' 81ב – תחולה", False, s.exemption, REF)
        if s.accumulated > thr * Decimal("0.8"):
            ctx.alert("S81B_NEAR", "info", ent, f"רווחים נצברים ({fmt(s.accumulated)} ₪) קרובים לסף 750 אלף ₪.", REF)
        return s

    s.applies = True
    # ── shields (s.81C), measured at the end of the tested year ──
    shield_cash = ctx.p.num("s81.cash_shield") * i.cash_shield_share_pct / 100
    shield_assets = i.depreciated_assets_cost if i.exempt_profits_option == 2 else ZERO
    shields = {"מגן כספי": shield_cash, "מגן הוצאות": i.deductible_expenses, "מגן נכסים": shield_assets}
    which, shield = max(shields.items(), key=lambda kv: kv[1])
    s.excess = pos(s.accumulated - i.exempt_accumulated_profits - shield)
    ctx.trace.add(ent, STAGE, "excess", "רווחים עודפים", s.excess,
                  f"max(0, {fmt(s.accumulated)} − {fmt(i.exempt_accumulated_profits)} (פטורים, חלופה {i.exempt_profits_option}) − "
                  f"{fmt(shield)} ({which}: max(כספי {fmt(shield_cash)}; הוצאות {fmt(i.deductible_expenses)}; נכסים {fmt(shield_assets)})))",
                  "ס' 81א, 81ג; חוזר 7/2025; נספח 1281 חלק ג",
                  "חלופה 1 לרווחים פטורים מוותרת על מגן הנכסים (ס' 81ג(ג))" if i.exempt_profits_option == 1 else "")

    div = i.dividends_qualifying if i.dividends_qualifying is not None else cs.qualifying_dividend_81b
    ctx.trace.add(ent, STAGE, "qualifying_dividend", "דיבידנד ששולם בגינו מס בשנת המס (לעניין 81ב)", div,
                  "דיבידנדים ליחידים + דיבידנד בשרשור במסלול ראשי/חלופי; ללא 'חלופת הדיבידנד' של 62א",
                  "ס' 81ב(ב)(3); הוראת ביצוע 9/2026 ס' 3.3.2")

    # ── 20% transitional track (LAW-3343 s.5, tax years 2025-2030) ──
    excess_for_tax = s.excess
    rem = i.start_date_profits_remaining
    t20 = ctx.p.num("s81.transitional_20pct_track") / 100
    track20 = False
    if rem and 2025 <= ctx.year <= 2030 and div >= t20 * rem:
        track20 = True
        excess_for_tax = pos(s.excess - rem)
        ctx.trace.add(ent, STAGE, "track20", "מסלול 20% (הוראת מעבר): הפחתת יתרת הרווחים ליום התחילה", excess_for_tax,
                      f"דיבידנד {fmt(div)} ≥ 20% × {fmt(rem)}; {fmt(s.excess)} − {fmt(rem)}", "ס' 5 לחוק (ס\"ח 3343); חוזר 7/2025")

    min_pct = ctx.p.rate("s81.min_distribution_of_accumulated")
    min_ex = ctx.p.rate("s81.min_distribution_of_excess")
    need_acc = min_pct * s.accumulated
    need_ex = min_ex * excess_for_tax
    s.min_dividend_to_avoid = min(need_acc, need_ex) if excess_for_tax > 0 else ZERO
    ctx.trace.add(ent, STAGE, "min_dividend", "דיבידנד מינימלי לפטור", s.min_dividend_to_avoid,
                  f"min({fmt_rate(min_pct)} × {fmt(s.accumulated)} = {fmt(need_acc)}; {fmt_rate(min_ex)} × {fmt(excess_for_tax)} = {fmt(need_ex)})",
                  "ס' 81ב(ב)")

    exemptions = []
    if excess_for_tax == 0:
        exemptions.append("אין רווחים עודפים" + (" (אחרי מסלול 20%)" if track20 else ""))
    if div >= need_acc:
        exemptions.append(f"חולק דיבידנד ≥ {fmt_rate(min_pct)} מהרווחים הנצברים")
    elif excess_for_tax > 0 and div > need_ex:
        exemptions.append(f"חולק דיבידנד > {fmt_rate(min_ex)} מהרווחים העודפים")
    ratio = ctx.p.rate("s81.loss_exemption_ratio")
    if loss_in_year > ratio * s.accumulated:
        exemptions.append(f"הפסד שוטף בשנת המס ({fmt(loss_in_year)}) עולה על {fmt_rate(ratio)} מהרווחים הנצברים")

    if exemptions:
        s.exemption = "; ".join(exemptions)
        ctx.trace.add(ent, STAGE, "exempt", "פטור מתוספת המס", True, s.exemption, REF)
        return s

    s.taxable = pos(excess_for_tax - div)
    rate = ctx.p.rate("s81.extra_tax_rate")
    s.tax = rate * s.taxable
    ctx.trace.add(ent, STAGE, "taxable", "יתרת רווחים עודפים לפי ס' 81ב(א) (שדה 073)", s.taxable,
                  f"{fmt(excess_for_tax)} − {fmt(div)}", REF)
    ctx.trace.add(ent, STAGE, "tax", "תוספת מס 2%", s.tax, f"{fmt_rate(rate)} × {fmt(s.taxable)}", "ס' 81ב(א)",
                  "אינה מותרת בניכוי ואינה ניתנת לזיכוי כנגד מס חברות; אין מקדמות")
    gap = pos(s.min_dividend_to_avoid - div)
    ctx.alert("S81B_DUE", "critical", ent,
              f"צפויה תוספת מס 2% בסך {fmt(s.tax)} ₪. חלוקת דיבידנד נוספת (ששולם בגינה מס) של כ-{fmt(gap)} ₪ בשנת המס "
              f"תבטל אותה. מועד התשלום: מועד הגשת הדוח לפי ס' 132 (31.5.{ctx.year + 1} או ארכת מייצג) או תום השנה העוקבת – "
              f"המוקדם; לאחריו הפרשי הצמדה וריבית.", "ס' 81ב, 81ו(ג)")
    return s
