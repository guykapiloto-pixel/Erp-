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
    shield_cash = ctx.p.num("s81.cash_shield")
    shield = max(shield_cash, i.deductible_expenses, i.depreciated_assets_cost)
    which = {shield_cash: "מגן כספי", i.deductible_expenses: "מגן הוצאות", i.depreciated_assets_cost: "מגן נכסים"}[shield]
    s.excess = pos(s.accumulated - i.exempt_accumulated_profits - shield)
    ctx.trace.add(ent, STAGE, "excess", "רווחים עודפים", s.excess,
                  f"max(0, {fmt(s.accumulated)} − {fmt(i.exempt_accumulated_profits)} (פטורים) − {fmt(shield)} ({which}: "
                  f"max(750,000; הוצאות {fmt(i.deductible_expenses)}; נכסים {fmt(i.depreciated_assets_cost)})))",
                  "ס' 81א, 81ג; נספח 1281 חלק ג")

    div = i.dividends_qualifying if i.dividends_qualifying is not None else cs.qualifying_dividend_81b
    ctx.trace.add(ent, STAGE, "qualifying_dividend", "דיבידנד שחולק בשנת המס (לעניין 81ב)", div,
                  "דיבידנדים רגילים + דיבידנד לחברה בשרשור ששולם בגינו מס; ללא 'חלופת הדיבידנד' של 62א",
                  "ס' 81ב(ב); הוראת ביצוע 9/2026 ס' 3.3.2")

    min_pct = ctx.p.rate("s81.min_distribution_of_accumulated")
    min_ex = ctx.p.rate("s81.min_distribution_of_excess")
    need_acc = min_pct * s.accumulated
    need_ex = min_ex * s.excess
    s.min_dividend_to_avoid = min(need_acc, need_ex) if s.excess > 0 else ZERO
    ctx.trace.add(ent, STAGE, "min_dividend", "דיבידנד מינימלי לפטור", s.min_dividend_to_avoid,
                  f"min({fmt_rate(min_pct)} × {fmt(s.accumulated)} = {fmt(need_acc)}; {fmt_rate(min_ex)} × {fmt(s.excess)} = {fmt(need_ex)})",
                  "ס' 81ב(ב)")

    exemptions = []
    if s.excess == 0:
        exemptions.append("אין רווחים עודפים")
    if div >= need_acc:
        exemptions.append(f"חולק דיבידנד ≥ {fmt_rate(min_pct)} מהרווחים הנצברים")
    elif s.excess > 0 and div >= need_ex:
        exemptions.append(f"חולק דיבידנד ≥ {fmt_rate(min_ex)} מהרווחים העודפים")
    ratio = ctx.p.rate("s81.loss_exemption_ratio")
    if loss_in_year > ratio * s.accumulated:
        exemptions.append(f"הפסד בשנת המס ({fmt(loss_in_year)}) עולה על {fmt_rate(ratio)} מהרווחים הנצברים")
    t20 = ctx.p.raw_value("s81.transitional_2025_distribution")
    if ctx.year == 2025 and t20 is not None and i.trapped_profits_31_12_2024:
        need20 = Decimal(t20) / 100 * i.trapped_profits_31_12_2024
        if div >= need20:
            exemptions.append(f"הוראת מעבר 2025: חולקו ≥ {t20}% מהרווחים הכלואים ליום 31.12.2024 ({fmt(need20)})")

    if exemptions:
        s.exemption = "; ".join(exemptions)
        ctx.trace.add(ent, STAGE, "exempt", "פטור מתוספת המס", True, s.exemption, REF)
        return s

    s.taxable = pos(s.excess - div)
    rate = ctx.p.rate("s81.extra_tax_rate")
    s.tax = rate * s.taxable
    ctx.trace.add(ent, STAGE, "taxable", "יתרת רווחים עודפים לפי ס' 81ב(א) (שדה 073)", s.taxable,
                  f"{fmt(s.excess)} − {fmt(div)}", REF)
    ctx.trace.add(ent, STAGE, "tax", "תוספת מס 2%", s.tax, f"{fmt_rate(rate)} × {fmt(s.taxable)}", "ס' 81ב(א)")
    gap = pos(s.min_dividend_to_avoid - div)
    dl = ctx.p.raw_value("s81.report_deadline")
    ctx.alert("S81B_DUE", "critical", ent,
              f"צפויה תוספת מס 2% בסך {fmt(s.tax)} ₪. חלוקת דיבידנד נוספת של {fmt(gap)} ₪ "
              f"(עד {fmt(s.min_dividend_to_avoid)} ₪ בסה\"כ) תבטל אותה. מועד דיווח המסלול: {dl[3:]}.{dl[:2]}.{ctx.year + 1}; "
              f"לאחריו – תוספת המס בלבד, בצירוף הפרשי הצמדה וריבית.", REF)
    return s
