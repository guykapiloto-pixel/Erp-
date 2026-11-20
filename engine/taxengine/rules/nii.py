"""Bituach Leumi (NII) and health tax – annual estimate from monthly thresholds.

Rules / simplifications:
- income assumed evenly spread over 12 months;
- regular salary takes the reduced band first, then salary of a controlling shareholder in a few-company
  (its own rates), then self-employed income, then income not from work;
- income attributed under s.62A is charged as self-employed income (BTL insurance circular 1487, 29.11.2021:
  the attributed amount is added to self-employed income). No post-Amendment-277 BTL update was found, so the
  result is flagged as an estimate. 62A(a3) deemed dividend is not charged (dividend exempt, s.350(a)(6)).
"""
from __future__ import annotations

from decimal import Decimal

from ..context import Ctx, IncomeBuckets
from ..models import IndividualInput, IndividualResult
from ..money import ZERO, fmt, fmt_rate, pos

STAGE = "nii"
REF = "חוק הביטוח הלאומי, לוח י'; חוק ביטוח בריאות ממלכתי ס' 14"


def _two_band(amount_m: Decimal, start_m: Decimal, thr_m: Decimal, max_m: Decimal, r_low: Decimal, r_high: Decimal) -> Decimal:
    """Monthly contribution for income occupying [start, start+amount], capped at max."""
    end = min(start_m + amount_m, max_m)
    if end <= start_m:
        return ZERO
    low = pos(min(end, thr_m) - start_m)
    high = pos(end - max(start_m, thr_m))
    return low * r_low + high * r_high


def _both(r: dict[str, Decimal]) -> tuple[Decimal, Decimal]:
    return r["ni_reduced"] + r.get("health_reduced", ZERO), r["ni_full"] + r.get("health_full", ZERO)


def compute_nii(ind: IndividualInput, b: IncomeBuckets, ctx: Ctx, res: IndividualResult) -> None:
    p = ctx.p
    ent = f"individual:{ind.id}"
    thr = p.num("nii.reduced_threshold_monthly")
    mx = p.num("nii.max_insurable_monthly")

    regular_m = (ind.salary_external + b.salary_from_companies - b.salary_controlling) / 12
    ctrl_m = b.salary_controlling / 12
    attributed = b.attributed["a_old"] + b.attributed["a1"] + b.attributed["a2"]
    self_m = (ind.business_income + ind.other_exertion_income + attributed) / 12
    passive_m = (ind.rental_income_taxable + ind.other_passive_income) / 12 if ind.nii_passive_liable else ZERO

    lo, hi = _both(p.rates("nii.employee"))
    e1 = _two_band(regular_m, ZERO, thr, mx, lo, hi) * 12
    lo, hi = _both(p.rates("nii.controlling_employee"))
    e2 = _two_band(ctrl_m, regular_m, thr, mx, lo, hi) * 12
    lo, hi = _both(p.rates("nii.self_employed"))
    s = _two_band(self_m, regular_m + ctrl_m, thr, mx, lo, hi) * 12
    lo, hi = _both(p.rates("nii.passive"))
    pa = _two_band(passive_m, regular_m + ctrl_m + self_m, thr, mx, lo, hi) * 12

    er, cer = p.rates("nii.employer"), p.rates("nii.controlling_employer")
    company_regular_m = (b.salary_from_companies - b.salary_controlling) / 12
    employer = (_two_band(company_regular_m, ZERO, thr, mx, er["ni_reduced"], er["ni_full"])
                + _two_band(ctrl_m, company_regular_m, thr, mx, cer["ni_reduced"], cer["ni_full"])) * 12

    res.nii_employee, res.nii_self_employed, res.nii_passive, res.nii_employer_cost = e1 + e2, s, pa, employer
    res.nii_is_estimate = bool(attributed) or bool(pa)
    if e1:
        ctx.trace.add(ent, STAGE, "employee", "ב\"ל ובריאות – שכיר (חלק עובד)", e1,
                      f"שכר חודשי {fmt(regular_m)}: עד {fmt(thr)} × {fmt_rate(_both(p.rates('nii.employee'))[0])}, "
                      f"עד {fmt(mx)} × {fmt_rate(_both(p.rates('nii.employee'))[1])}; × 12", REF)
    if e2:
        ctx.trace.add(ent, STAGE, "controlling", "ב\"ל ובריאות – בעל שליטה בחברת מעטים (חלק עובד)", e2,
                      f"שכר חודשי {fmt(ctrl_m)} מעל {fmt(regular_m)}; שיעורי בעל שליטה", REF)
    if s:
        ctx.trace.add(ent, STAGE, "self_employed", "ב\"ל ובריאות – עצמאי / הכנסה מיוחסת", s,
                      f"הכנסה חודשית {fmt(self_m)} (כולל מיוחס 62א {fmt(attributed / 12)}), מעל שכר {fmt(regular_m + ctrl_m)}",
                      "חוזר ב\"ל 1487 (29.11.2021); " + REF,
                      "הערכה: ב\"ל לא פרסם עדכון לתיקון 277; לפי חוזר 1487 ההכנסה המיוחסת מחויבת כהכנסת עצמאי" if attributed else "")
    if pa:
        ctx.trace.add(ent, STAGE, "passive", "ב\"ל ובריאות – הכנסה שאינה מעבודה", pa, f"{fmt(passive_m)} לחודש", REF)
    if employer:
        ctx.trace.add(ent, STAGE, "employer", "ב\"ל – חלק מעביד (עלות לחברה)", employer, "", REF)
    if regular_m + ctrl_m + self_m > mx:
        ctx.alert("NII_CEILING", "info", ent, f"הכנסה חודשית מעבודה {fmt(regular_m + ctrl_m + self_m)} ₪ עוברת את תקרת ב\"ל ({fmt(mx)}).", REF)
