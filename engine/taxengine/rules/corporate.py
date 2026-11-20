"""Company-level tax: corporate tax, 62A reporting alternative, dividend distributions and holding chains."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..context import Ctx
from ..models import CompanyInput
from ..money import ZERO, fmt, fmt_rate, pos
from .s62a import S62AState, _group_control, _holders

STAGE = "corporate"


@dataclass
class CorpState:
    taxable: Decimal = ZERO
    exempt_income: Decimal = ZERO
    corporate_tax: Decimal = ZERO
    dividend_alt_amount: Decimal = ZERO      # dividends paid under 62A(c2)(5) - not counted for s.81B
    regular_dividend: Decimal = ZERO
    qualifying_dividend_81b: Decimal = ZERO
    dividend_withholding: Decimal = ZERO
    notional_withholding: Decimal = ZERO


def _material(control: Decimal, ctx: Ctx) -> bool:
    return control >= Decimal("0.10")   # 'material shareholder' s.88 – 10% of any means of control


def corporate_tax(c: CompanyInput, ctx: Ctx, st: S62AState) -> CorpState:
    ent = f"company:{c.id}"
    cs = CorpState()
    rate = ctx.p.rate("corporate.corporate_tax_rate")
    alt = ctx.req.options.reporting_alternative == "dividend"
    attributed_income = st.attributed["a_old"] + st.attributed["a1"] + st.attributed["a2"]

    base = st.remaining_effort_taxable + st.other_taxable + st.a2_company_part
    if alt:
        base += attributed_income
    loss_used = min(c.loss_carryforward, pos(base))
    cs.taxable = base - loss_used
    cs.exempt_income = st.a3_company_part + c.exempt_dividends_received
    ctx.trace.add(ent, STAGE, "taxable", "הכנסה חייבת במס חברות", cs.taxable,
                  f"{fmt(st.remaining_effort_taxable)} (יגיעה אישית שנותרה) + {fmt(st.other_taxable)} (הכנסה אחרת) + "
                  f"{fmt(st.a2_company_part)} (45% שותפות)" + (f" + {fmt(attributed_income)} (חלופת דיבידנד)" if alt else "")
                  + (f" − {fmt(loss_used)} (הפסד מועבר)" if loss_used else ""),
                  "ס' 126(א)")
    if loss_used and attributed_income:
        ctx.alert("LOSS_VS_SPECIAL_INCOME", "info", ent,
                  "הפסד מועבר קוזז רק כנגד הכנסה שלא יוחסה; לפי ס' 62א(ג1) אין לקזז הפסד מפעילות אחרת כנגד הכנסה מיוחדת.",
                  "טיוטת חוזר ס' 3.3.3.4")
    cs.corporate_tax = rate * pos(cs.taxable)
    ctx.trace.add(ent, STAGE, "corporate_tax", "מס חברות", cs.corporate_tax,
                  f"{fmt_rate(rate)} × {fmt(pos(cs.taxable))}", "ס' 126(א)")
    if cs.exempt_income:
        ctx.trace.add(ent, STAGE, "exempt_income", "הכנסה פטורה (דיבידנד בין-חברתי)", cs.exempt_income, "",
                      "ס' 126(ב)")

    if alt and attributed_income > 0:
        _dividend_alternative(c, ctx, st, cs, rate)
    _regular_dividends(c, ctx, cs)
    return cs


def _dividend_alternative(c: CompanyInput, ctx: Ctx, st: S62AState, cs: CorpState, rate: Decimal) -> None:
    """s.62A(c2)(5) - income stays in the company, corporate tax paid, dividend distributed; the holder is
    taxed at marginal rates on the attributed amount and credits the corporate tax (capped at 23%) and the
    dividend withholding (Directive 9/2026 s.3.3.2, 3.4; example: 750,000 -> div 577,500, w/h 173,250)."""
    ent = f"company:{c.id}"
    gc = _group_control(_holders(c))
    holders = {h.sh.individual_id: h for h in _holders(c) if h.sh.individual_id}
    for iid, secs in st.attributed_to.items():
        amt = secs["a_old"] + secs["a1"] + secs["a2"]
        if amt <= 0:
            continue
        h = holders.get(iid)
        material = h is not None and _material(gc[h.group], ctx)
        wrate = ctx.p.rate("income_tax.dividend_rate_material" if material else "income_tax.dividend_rate")
        corp = rate * amt
        div = amt - corp
        wh = wrate * div
        b = ctx.buckets[iid]
        b.corp_tax_credit_62a += corp
        b.dividend_withholding += wh
        b.dividend_alt_income += amt
        cs.dividend_alt_amount += div
        cs.dividend_withholding += wh
        ctx.trace.add(ent, STAGE, f"div_alt_{iid}", f"חלופת הדיבידנד – {iid}", div,
                      f"דיבידנד {fmt(amt)} − מס חברות {fmt(corp)} = {fmt(div)}; ניכוי במקור {fmt_rate(wrate)} = {fmt(wh)}",
                      "ס' 62א(ג2)(5); הוראת ביצוע 9/2026 ס' 3.3.2")
    ctx.alert("S62A_DIV_ALT", "info", ent,
              "נבחרה 'חלופת הדיבידנד': הדיבידנד אינו נחשב חלוקה לעניין ס' 81ב(ב).", "הוראת ביצוע 9/2026 ס' 3.3.2")


def final_individuals(ctx: Ctx, company_id: str, share: Decimal, seen: frozenset = frozenset()) -> list[tuple[str, Decimal]]:
    """Look-through: (individual_id, effective share) of everyone up the chain above `company_id`."""
    c = ctx.company(company_id)
    if c is None or company_id in seen:
        return []
    out: list[tuple[str, Decimal]] = []
    for sh in c.shareholders:
        s = share * sh.profit_rights_pct / Decimal(100)
        if sh.individual_id:
            out.append((sh.individual_id, s))
        elif sh.company_id:
            out.extend(final_individuals(ctx, sh.company_id, s, seen | {company_id}))
    return out


def _regular_dividends(c: CompanyInput, ctx: Ctx, cs: CorpState) -> None:
    ent = f"company:{c.id}"
    if c.dividends_declared <= 0:
        return
    cs.regular_dividend = c.dividends_declared
    gc = _group_control(_holders(c))
    for h in _holders(c):
        amt = c.dividends_declared * h.rights
        if amt <= 0:
            continue
        if h.sh.individual_id:
            material = _material(gc[h.group], ctx)
            wrate = ctx.p.rate("income_tax.dividend_rate_material" if material else "income_tax.dividend_rate")
            wh = wrate * amt
            b = ctx.buckets[h.sh.individual_id]
            if material:
                b.dividends_material += amt
            else:
                b.dividends_regular += amt
            b.dividend_withholding += wh
            cs.dividend_withholding += wh
            cs.qualifying_dividend_81b += amt
            ctx.trace.add(ent, STAGE, f"div_{h.sh.individual_id}", f"דיבידנד ל-{h.sh.individual_id}", amt,
                          f"{fmt(c.dividends_declared)} × {fmt_rate(h.rights)}; ניכוי במקור {fmt_rate(wrate)} = {fmt(wh)}",
                          "ס' 125ב; ס' 161")
        elif h.sh.company_id:
            _dividend_to_parent(c, ctx, cs, h.sh.company_id, amt)
        else:
            cs.qualifying_dividend_81b += amt   # e.g. non-resident / public holder - tax handled by payer rules
            ctx.trace.add(ent, STAGE, f"div_ext_{h.key}", f"דיבידנד לבעל מניות חיצוני {h.key}", amt, "", "")


def _dividend_to_parent(c: CompanyInput, ctx: Ctx, cs: CorpState, parent_id: str, amt: Decimal) -> None:
    """Dividend to a parent company. Exempt in the parent under s.126(b); counts for s.81B only if tax was paid
    on it (regulations under s.81B(b)(3)(c)): main track = 35% withholding and a notional dividend attributed up
    the chain to the final individual holders (taxed 25%/30%, credit for the 35%)."""
    ent = f"company:{c.id}"
    track = c.dividend_to_parent_track
    ref = "ס' 81ב(ב)(3)(ג); תקנות מ\"ה (דיבידנדים ששולם מס בשל חלוקתם) תשפ\"ה-2025; הוראת ביצוע 9/2026 ס' 5"
    if track == "exempt":
        ctx.intercompany_dividends[parent_id].append((c.id, amt, ZERO))
        ctx.trace.add(ent, STAGE, f"div_parent_{parent_id}", f"דיבידנד לחברת האם {parent_id} (פטור, ללא מסלול 81ב)", amt,
                      "פטור לפי ס' 126(ב); אינו נחשב חלוקה לעניין ס' 81ב", "ס' 126(ב)")
        ctx.alert("S81B_CHAIN_EXEMPT", "warning", ent,
                  f"דיבידנד של {fmt(amt)} ₪ לחברת אם ללא תשלום מס – אינו מקטין את הרווחים העודפים לעניין ס' 81ב.", ref)
        return
    w = ctx.p.rate("s81.notional_dividend_withholding")
    withheld = w * amt if track == "main" else ZERO
    cs.notional_withholding += withheld
    cs.qualifying_dividend_81b += amt
    ctx.intercompany_dividends[parent_id].append((c.id, amt, withheld))
    ctx.trace.add(ent, STAGE, f"div_parent_{parent_id}", f"דיבידנד לחברת האם {parent_id} – מסלול {'ראשי' if track == 'main' else 'חלופי'}",
                  amt, f"ניכוי במקור {fmt_rate(w)} × {fmt(amt)} = {fmt(withheld)}" if track == "main"
                  else "פטור מניכוי – הדיבידנד מועבר לבעל המניות הסופי באותה שנה ומנוכה ממנו המס", ref)
    if track != "main":
        return
    # notional dividend to the final individual holders
    finals = final_individuals(ctx, parent_id, Decimal(1))
    for iid, s in finals:
        nd = amt * s
        if nd <= 0:
            continue
        material = s >= Decimal("0.10")
        b = ctx.buckets[iid]
        if material:
            b.notional_dividends_material += nd
        else:
            b.notional_dividends_regular += nd
        b.notional_withholding += withheld * s
        ctx.trace.add(ent, STAGE, f"notional_{iid}", f"דיבידנד רעיוני לבעל המניות הסופי {iid}", nd,
                      f"{fmt(amt)} × {fmt_rate(s)} (החזקה אפקטיבית); זיכוי 35%: {fmt(withheld * s)}",
                      "תקנה 3(א); הוראת ביצוע 9/2026 ס' 5.4 (שדות 123/127)")
    ctx.alert("NOTIONAL_DIVIDEND", "info", ent,
              f"דיבידנד רעיוני: {fmt(amt)} ₪ יוחסו לבעלי המניות הסופיים. דיבידנד בפועל שיחולק בעתיד ממקור זה – "
              f"65% ממנו ייחשב כלא חולק (תקנה 3(ה)); יש לעדכן את 'המחסנית' בטופס 1301.", ref)
