"""Individual income tax: graduated brackets, passive income from 31%, special rates, surtax, credits."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..context import Ctx, IncomeBuckets
from ..models import IndividualInput, IndividualResult
from ..money import ZERO, fmt, fmt_rate, pos

STAGE = "individual"


def tax_on_slice(start: Decimal, amount: Decimal, brackets: list[tuple[Decimal | None, Decimal]],
                 min_rate: Decimal = ZERO) -> tuple[Decimal, list[str]]:
    """Tax on income occupying [start, start+amount] of the bracket ladder; each bracket rate is
    raised to `min_rate` (s.121(a)(1) – non-exertion income starts at 31%)."""
    tax = ZERO
    parts: list[str] = []
    lo = ZERO
    end = start + amount
    for upper, rate in brackets:
        hi = upper if upper is not None else Decimal("1e18")
        seg_lo, seg_hi = max(lo, start), min(hi, end)
        if seg_hi > seg_lo:
            r = max(rate, min_rate)
            t = (seg_hi - seg_lo) * r
            tax += t
            parts.append(f"{fmt(seg_hi - seg_lo)}×{fmt_rate(r)}")
        lo = hi
        if lo >= end:
            break
    return tax, parts


def marginal_bracket(level: Decimal, brackets) -> Decimal:
    lo = ZERO
    for upper, rate in brackets:
        if upper is None or level <= upper:
            return rate
        lo = upper
    return brackets[-1][1]


@dataclass
class IndivIncome:
    exertion: Decimal = ZERO
    passive: Decimal = ZERO
    special: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)   # name -> (amount, rate)
    capital_sources: Decimal = ZERO


def compute_individual(ind: IndividualInput, b: IncomeBuckets, ctx: Ctx) -> IndividualResult:
    p = ctx.p
    ent = f"individual:{ind.id}"
    res = IndividualResult(id=ind.id, name=ind.name)
    brackets = p.brackets()

    # ── 1. classify ──
    attributed = sum(b.attributed.values(), ZERO)
    gross_exertion = (ind.salary_external + b.salary_from_companies + ind.business_income
                      + ind.other_exertion_income + attributed)
    exertion = pos(gross_exertion - ind.deductions)
    ctx.trace.add(ent, STAGE, "exertion", "הכנסה מיגיעה אישית", exertion,
                  f"משכורת חיצונית {fmt(ind.salary_external)} + משכורת מחברות {fmt(b.salary_from_companies)} + "
                  f"עסק {fmt(ind.business_income)} + אחרת {fmt(ind.other_exertion_income)} + מיוחס 62א {fmt(attributed)}"
                  + (f" − ניכויים {fmt(ind.deductions)}" if ind.deductions else ""),
                  "ס' 2(1), 2(2); ס' 62א")
    for sec, amt in b.attributed.items():
        if amt:
            ctx.trace.add(ent, STAGE, f"attr_{sec}", f"הכנסה מיוחסת לפי 62א – {sec}", amt, "", "ס' 62א; טופס 1362")
    passive = ind.rental_income_taxable + ind.other_passive_income
    age60 = ind.age is not None and ind.age >= 60
    min_rate = ZERO if age60 else p.rate("income_tax.passive_min_rate")

    special: dict[str, tuple[Decimal, Decimal]] = {}
    r_div, r_div_m = p.rate("income_tax.dividend_rate"), p.rate("income_tax.dividend_rate_material")
    div_reg = b.dividends_regular + b.notional_dividends_regular + (ZERO if ind.dividends_external_material else ind.dividends_external)
    div_mat = b.dividends_material + b.notional_dividends_material + (ind.dividends_external if ind.dividends_external_material else ZERO)
    if div_reg: special["dividend_25"] = (div_reg, r_div)
    if div_mat: special["dividend_30"] = (div_mat, r_div_m)
    if b.dividends_62a3: special["dividend_62a3"] = (b.dividends_62a3, p.rate("s62a.a3_dividend_rate"))
    if ind.capital_gains_real:
        special["capital_gain"] = (ind.capital_gains_real, p.rate(
            "income_tax.capital_gain_rate_material" if ind.capital_gains_material else "income_tax.capital_gain_rate"))
    if ind.interest_unlinked: special["interest_15"] = (ind.interest_unlinked, p.rate("income_tax.interest_rate_unlinked"))
    if ind.interest_linked: special["interest_25"] = (ind.interest_linked, p.rate("income_tax.interest_rate_linked"))

    # ── 2. graduated tax: exertion first, passive stacked on top ──
    t_ex, parts_ex = tax_on_slice(ZERO, exertion, brackets)
    t_pa, parts_pa = tax_on_slice(exertion, passive, brackets, min_rate)
    ctx.trace.add(ent, STAGE, "bracket_tax_exertion", "מס לפי מדרגות – יגיעה אישית", t_ex, " + ".join(parts_ex) or "0", "ס' 121")
    if passive:
        ctx.trace.add(ent, STAGE, "bracket_tax_passive", "מס על הכנסה שאינה מיגיעה אישית (מעל ההכנסה מיגיעה)", t_pa,
                      " + ".join(parts_pa), "ס' 121(א)(1)" + (" – גיל 60+: מדרגות רגילות" if age60 else " – מינימום 31%"))
    bracket_tax = t_ex + t_pa

    # credit points + credits (limited to bracket tax)
    if ind.credit_points is not None:
        points = ind.credit_points
    else:
        points = p.num("income_tax.base_credit_points_resident") if ind.israeli_resident else ZERO
        if ind.gender.value == "female" and ind.israeli_resident:
            points += p.num("income_tax.extra_credit_points_female")
    cp_value = points * p.num("income_tax.credit_point_annual")
    donation_credit = p.rate("income_tax.donation_credit_rate") * ind.donations
    credits = cp_value + ind.tax_credits + donation_credit
    used_credits = min(credits, bracket_tax)
    ctx.trace.add(ent, STAGE, "credit_points", "נקודות זיכוי וזיכויים", used_credits,
                  f"{points} נק' × {fmt(p.num('income_tax.credit_point_annual'))} = {fmt(cp_value)}"
                  + (f" + זיכויים {fmt(ind.tax_credits)}" if ind.tax_credits else "")
                  + (f" + תרומות 35% {fmt(donation_credit)}" if ind.donations else "")
                  + (f"; מוגבל למס במדרגות {fmt(bracket_tax)}" if credits > bracket_tax else ""),
                  "ס' 34–36א, 45א, 46")

    # special rates
    special_tax = ZERO
    for name, (amt, rate) in special.items():
        t = amt * rate
        special_tax += t
        ctx.trace.add(ent, STAGE, f"special_{name}", f"הכנסה בשיעור מיוחד – {name}", t,
                      f"{fmt(amt)} × {fmt_rate(rate)}", "ס' 125ב, 91, 125ג, 62א(א3)")
    special_total = sum((a for a, _ in special.values()), ZERO)

    # ── 3. surtax (s.121B): 3% on all taxable income above threshold + 2% on capital-source part above it ──
    total = exertion + passive + special_total
    thr = p.num("income_tax.surtax_threshold")
    above = pos(total - thr)
    surtax = p.rate("income_tax.surtax_rate") * above
    capital = passive + special_total             # stacked on top of exertion income
    cap_above = min(capital, above)
    surtax_cap = p.rate("income_tax.surtax_capital_extra_rate") * cap_above
    if above:
        ctx.trace.add(ent, STAGE, "surtax", "מס יסף 3%", surtax,
                      f"{fmt_rate(p.rate('income_tax.surtax_rate'))} × ({fmt(total)} − {fmt(thr)})", "ס' 121ב(א)")
        ctx.alert("SURTAX", "warning", ent,
                  f"הכנסה חייבת {fmt(total)} ₪ עוברת את תקרת מס יסף ({fmt(thr)}): מס יסף {fmt(surtax)} ₪"
                  + (f" + 2% על הכנסה הונית {fmt(surtax_cap)} ₪." if surtax_cap else "."), "ס' 121ב")
    if surtax_cap:
        ctx.trace.add(ent, STAGE, "surtax_capital", "מס יסף נוסף 2% – הכנסה ממקורות הוניים", surtax_cap,
                      f"2% × min(הכנסה הונית {fmt(capital)}; עודף מעל התקרה {fmt(above)})", "ס' 121ב(א1)")

    gross = bracket_tax - used_credits + special_tax + surtax + surtax_cap
    ctx.trace.add(ent, STAGE, "gross_tax", "חבות מס כוללת", gross,
                  f"{fmt(bracket_tax)} − {fmt(used_credits)} + {fmt(special_tax)} + {fmt(surtax)} + {fmt(surtax_cap)}", "")

    # ── 4. prepayments / offsets ──
    corp_credit = min(b.corp_tax_credit_62a, p.rate("corporate.corporate_tax_rate") * b.dividend_alt_income)
    pre = {
        "ניכוי במקור (שכר/אחר)": ind.tax_withheld,
        "ניכוי במקור מדיבידנד": b.dividend_withholding,
        "ניכוי 35% – דיבידנד רעיוני": b.notional_withholding,
        "מס חברות שקוזז – חלופת הדיבידנד (שדה 100)": corp_credit,
        "מקדמות": ind.advances_paid,
    }
    pre = {k: v for k, v in pre.items() if v}
    for k, v in pre.items():
        ctx.trace.add(ent, STAGE, f"prepaid_{k}", k, v, "", "הוראת ביצוע 9/2026 ס' 3.4" if "חלופת" in k else "")
    balance = gross - sum(pre.values(), ZERO)
    ctx.trace.add(ent, STAGE, "balance", "יתרה לתשלום (שלילי = החזר)", balance,
                  f"{fmt(gross)} − {fmt(sum(pre.values(), ZERO))}", "")

    # ── 5. rates ──
    top = exertion + passive
    m = marginal_bracket(top, brackets)
    if passive and not age60:
        m = max(m, min_rate)
    if total > thr:
        m += p.rate("income_tax.surtax_rate")
    res.exertion_income = exertion
    res.passive_bracket_income = passive
    res.special_rate_income = {k: v[0] for k, v in special.items()}
    res.taxable_income_total = total
    res.bracket_tax = bracket_tax
    res.credit_points_value = used_credits
    res.special_rate_tax = special_tax
    res.surtax = surtax
    res.surtax_capital = surtax_cap
    res.gross_tax = gross
    res.credits_and_prepayments = pre
    res.balance_due = balance
    res.marginal_rate = m * 100
    res.effective_rate = (gross / total * 100) if total else ZERO
    return res
