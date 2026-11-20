"""Bituach Leumi (NII) and health tax – annual estimate from monthly thresholds.

Simplifications (flagged as estimate in the output):
- income assumed evenly spread over 12 months;
- employee income uses the reduced band first, self-employed income uses what remains;
- income attributed under s.62A is treated as self-employed income (pending BTL confirmation, user decision #2).
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


def compute_nii(ind: IndividualInput, b: IncomeBuckets, ctx: Ctx, res: IndividualResult) -> None:
    p = ctx.p
    ent = f"individual:{ind.id}"
    thr = p.num("nii.reduced_threshold_monthly")
    mx = p.num("nii.max_insurable_monthly")
    emp = p.rates("nii.employee")
    er = p.rates("nii.employer")
    se = p.rates("nii.self_employed")

    salary_m = (ind.salary_external + b.salary_from_companies) / 12
    attributed = sum((v for k, v in b.attributed.items()), ZERO)
    self_m = (ind.business_income + ind.other_exertion_income + attributed) / 12
    passive_m = (ind.rental_income_taxable + ind.other_passive_income) / 12 if ind.nii_passive_liable else ZERO

    e = _two_band(salary_m, ZERO, thr, mx, emp["ni_reduced"] + emp["health_reduced"], emp["ni_full"] + emp["health_full"]) * 12
    s = _two_band(self_m, salary_m, thr, mx, se["ni_reduced"] + se["health_reduced"], se["ni_full"] + se["health_full"]) * 12
    pa = _two_band(passive_m, salary_m + self_m, thr, mx, se["ni_reduced"] + se["health_reduced"], se["ni_full"] + se["health_full"]) * 12
    employer = _two_band(b.salary_from_companies / 12, ZERO, thr, mx, er["ni_reduced"], er["ni_full"]) * 12

    res.nii_employee, res.nii_self_employed, res.nii_passive, res.nii_employer_cost = e, s, pa, employer
    res.nii_is_estimate = bool(attributed) or bool(pa) or (salary_m > 0 and self_m > 0)
    if e:
        ctx.trace.add(ent, STAGE, "employee", "ב\"ל ובריאות – שכיר (חלק עובד)", e,
                      f"שכר חודשי {fmt(salary_m)}: עד {fmt(thr)} × {fmt_rate(emp['ni_reduced'] + emp['health_reduced'])}, "
                      f"עד {fmt(mx)} × {fmt_rate(emp['ni_full'] + emp['health_full'])}; × 12", REF)
    if s:
        ctx.trace.add(ent, STAGE, "self_employed", "ב\"ל ובריאות – עצמאי / הכנסה מיוחסת", s,
                      f"הכנסה חודשית {fmt(self_m)} (כולל מיוחס 62א {fmt(attributed / 12)}), מעל שכר {fmt(salary_m)}", REF,
                      "הערכה: סיווג הכנסה מיוחסת לפי 62א(א1) טרם אומת מול ב\"ל" if attributed else "")
    if pa:
        ctx.trace.add(ent, STAGE, "passive", "ב\"ל ובריאות – הכנסה שאינה מעבודה (הערכה)", pa, f"{fmt(passive_m)} לחודש", REF)
    if employer:
        ctx.trace.add(ent, STAGE, "employer", "ב\"ל – חלק מעביד (עלות לחברה)", employer, "", REF)
    if salary_m + self_m > mx:
        ctx.alert("NII_CEILING", "info", ent, f"הכנסה חודשית מעבודה {fmt(salary_m + self_m)} ₪ עוברת את תקרת ב\"ל ({fmt(mx)}).", REF)
