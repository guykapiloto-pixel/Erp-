"""Section 62A of the Income Tax Ordinance (after Amendment 277, from 1.1.2025).

Sources:
- Income Tax Execution Directive 9/2026 (15.9.2026), s.2-3.
- Draft Income Tax Circular XX/2025 on s.62A (Nov 2025): s.2-6 and appendices C-G (worked examples).

Order (draft circular s.3.6 and fn.12): old s.62A(a) first, then (a1) on the remainder, then (a2), (a3).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from ..context import Ctx
from ..models import CompanyInput, Shareholder
from ..money import ZERO, fmt, fmt_rate, pos

STAGE = "s62a"


@dataclass
class Holder:
    """Shareholder view used for 62A tests."""
    sh: Shareholder
    key: str            # individual_id / company:<id> / external:<name>
    group: str          # relatives group key (or own key)
    rights: Decimal     # rate 0-1
    control: Decimal    # rate 0-1


@dataclass
class S62AState:
    effort_revenue: Decimal = ZERO          # R_eff (incl. partnerships >= 10%)
    effort_taxable: Decimal = ZERO          # T_eff
    other_taxable: Decimal = ZERO           # T_other ('other income' after its expenses)
    rp_added: Decimal = ZERO
    profitability: Decimal | None = None
    applies_a1: bool = False
    reason_a1: str = ""
    attributed: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))   # section -> total
    attributed_to: dict[str, dict[str, Decimal]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    remaining_effort_taxable: Decimal = ZERO   # effort taxable left in company after a_old / a1
    a2_company_part: Decimal = ZERO
    a3_company_part: Decimal = ZERO            # dividend income staying in company (exempt s.126(b))


def _holders(c: CompanyInput) -> list[Holder]:
    out = []
    for sh in c.shareholders:
        if sh.individual_id:
            key = sh.individual_id
        elif sh.company_id:
            key = f"company:{sh.company_id}"
        else:
            key = f"external:{sh.external_name or '?'}"
        rights = sh.profit_rights_pct / Decimal(100)
        control = (sh.control_pct if sh.control_pct is not None else sh.profit_rights_pct) / Decimal(100)
        out.append(Holder(sh=sh, key=key, group=sh.relatives_group or key, rights=rights, control=control))
    return out


def _holders_lt(c: CompanyInput, ctx: Ctx) -> list[Holder]:
    """Shareholders with look-through of holding companies to the individuals behind them.
    s.62A(d): an active / material holder holds 'directly or indirectly'. Effective rights = product along the
    chain; the indirect holder inherits the personal-effort / residency flags of their row in the parent."""
    merged: dict[str, Holder] = {}
    others: list[Holder] = []

    def add(sh: Shareholder, rights: Decimal, control: Decimal, effort: bool, seen: frozenset) -> None:
        if sh.individual_id:
            prev = merged.get(sh.individual_id)
            syn = sh.model_copy(update={"profit_rights_pct": rights * 100, "control_pct": control * 100,
                                        "personal_effort": sh.personal_effort or effort})
            if prev:
                syn = syn.model_copy(update={
                    "profit_rights_pct": prev.sh.profit_rights_pct + rights * 100,
                    "control_pct": (prev.sh.control_pct or 0) + control * 100,
                    "personal_effort": prev.sh.personal_effort or syn.personal_effort,
                    "salary_from_company": prev.sh.salary_from_company if prev.sh is not sh else sh.salary_from_company})
            merged[sh.individual_id] = Holder(sh=syn, key=sh.individual_id, group=syn.relatives_group or sh.individual_id,
                                              rights=syn.profit_rights_pct / 100, control=syn.control_pct / 100)
        elif sh.company_id and sh.company_id not in seen and ctx.company(sh.company_id):
            parent = ctx.company(sh.company_id)
            for psh in parent.shareholders:
                pr = psh.profit_rights_pct / 100
                pc = (psh.control_pct if psh.control_pct is not None else psh.profit_rights_pct) / 100
                add(psh, rights * pr, control * pc, effort or sh.personal_effort, seen | {sh.company_id})
        else:
            key = f"external:{sh.external_name or sh.company_id or '?'}"
            others.append(Holder(sh=sh, key=key, group=sh.relatives_group or key, rights=rights, control=control))

    for sh in c.shareholders:
        r = sh.profit_rights_pct / 100
        k = (sh.control_pct if sh.control_pct is not None else sh.profit_rights_pct) / 100
        add(sh, r, k, False, frozenset({c.id}))
    return list(merged.values()) + others


def _group_control(holders: list[Holder]) -> dict[str, Decimal]:
    g: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for h in holders:
        g[h.group] += h.control
    return g


def active_shareholders(c: CompanyInput, ctx: Ctx) -> list[Holder]:
    """'Active shareholder' (s.62A(d); draft circular 3.5.2): Israeli-resident individual who
    (a) holds >=30% of any means of control, alone or together with relatives (conclusive presumption), or
    (b) whose personal effort generates the company's income (works, manages, signs) - regardless of holding."""
    thr = ctx.p.rate("s62a.active_shareholder_control")
    holders = _holders_lt(c, ctx)
    gc = _group_control(holders)
    return [h for h in holders
            if h.sh.individual_id and h.sh.resident and (gc[h.group] >= thr or h.sh.personal_effort)]


def _distribute(ctx: Ctx, st: S62AState, c: CompanyInput, section: str, amount: Decimal,
                recipients: list[Holder], label: str, ref: str) -> Decimal:
    """Attribute `amount` to recipients by their share in profit rights. Returns total attributed."""
    ent = f"company:{c.id}"
    total = ZERO
    for h in recipients:
        part = amount * h.rights
        st.attributed_to[h.sh.individual_id][section] += part
        ctx.buckets[h.sh.individual_id].attributed[section] += part
        total += part
        ctx.trace.add(ent, STAGE, f"{section}_to_{h.sh.individual_id}", f"{label} – {h.sh.individual_id}",
                      part, f"{fmt(amount)} × {fmt_rate(h.rights)} (זכויות ברווחים)", ref)
    st.attributed[section] += total
    return total


def _expense_split(c: CompanyInput, ctx: Ctx, st: S62AState) -> None:
    """Revenue/expense split between personal-exertion activity and 'other income' (s.62A(c1);
    draft circular 3.3.3.3: specific attribution first, then pro-rata by revenue like s.18(c))."""
    ent = f"company:{c.id}"
    p_rev = sum((p.effort_revenue_share for p in c.partnerships if p.share_pct >= ctx.p.num("s62a.partnership_min_share")), ZERO)
    p_tax = sum((p.effort_taxable_share for p in c.partnerships if p.share_pct >= ctx.p.num("s62a.partnership_min_share")), ZERO)
    direct_rev = c.effort_revenue
    total_rev = direct_rev + c.other_income
    shared_eff = c.shared_expenses * direct_rev / total_rev if total_rev > 0 else ZERO
    shared_oth = c.shared_expenses - shared_eff

    st.effort_revenue = direct_rev + p_rev
    st.effort_taxable = direct_rev - c.effort_expenses - shared_eff + p_tax
    st.other_taxable = c.other_income - c.other_expenses - shared_oth
    ref = "ס' 62א(ג1); טיוטת חוזר 62א ס' 3.3.3"
    if c.shared_expenses:
        ctx.trace.add(ent, STAGE, "shared_expense_effort", "הוצאות משותפות שיוחסו לפעילות עתירת יגיעה אישית", shared_eff,
                      f"{fmt(c.shared_expenses)} × {fmt(direct_rev)} / {fmt(total_rev)}", ref)
    if p_rev:
        ctx.trace.add(ent, STAGE, "partnerships_ge10", "חלק בשותפויות (≥10%) שנכלל בפעילות", p_tax,
                      f"מחזור {fmt(p_rev)}, הכנסה חייבת {fmt(p_tax)}", "ס' 62א(א1)(2)(ב)(1); טיוטת חוזר ס' 4.2")
    ctx.trace.add(ent, STAGE, "effort_revenue", "הכנסה מפעילות עתירת יגיעה אישית (R)", st.effort_revenue,
                  f"{fmt(direct_rev)} + {fmt(p_rev)}", "ס' 62א(ד) – הגדרה שיורית: הכנסה שאינה 'הכנסה אחרת'")
    ctx.trace.add(ent, STAGE, "effort_taxable", "הכנסה חייבת מפעילות עתירת יגיעה אישית (T)", st.effort_taxable,
                  f"{fmt(direct_rev)} − {fmt(c.effort_expenses)} − {fmt(shared_eff)} + {fmt(p_tax)}", ref)
    ctx.trace.add(ent, STAGE, "other_taxable", "הכנסה חייבת מ'הכנסה אחרת'", st.other_taxable,
                  f"{fmt(c.other_income)} − {fmt(c.other_expenses)} − {fmt(shared_oth)}", "ס' 62א(ד) 'הכנסה אחרת'")


def _old_62a(c: CompanyInput, ctx: Ctx, st: S62AState, rev: Decimal, tax: Decimal) -> tuple[Decimal, Decimal]:
    """Old s.62A(a): controller as officer / employee-like services. Returns reduced (R', T')."""
    o = c.old_62a
    if not o or (o.revenue == 0 and o.taxable == 0):
        return rev, tax
    ent = f"company:{c.id}"
    thr = ctx.p.rate("s62a.profitability_threshold")
    excess = pos(o.taxable - thr * o.revenue)
    full = pos(o.taxable)
    mode = ctx.req.options.old_62a_mode
    amount = excess if mode == "excess_25" else full
    ctx.trace.add(ent, STAGE, "a_old_amount", "ס' 62א(א) – הכנסה המיוחסת לבעל השליטה", amount,
                  (f"max(0, {fmt(o.taxable)} − {fmt_rate(thr)} × {fmt(o.revenue)})" if mode == "excess_25"
                   else f"{fmt(o.taxable)} (ייחוס מלא)"),
                  "ס' 62א(א); טיוטת חוזר ס' 2",
                  "שיטת המשרד: עודף מעל 25% מהמחזור" if mode == "excess_25" else "שיטה סטטוטורית: ייחוס מלא")
    if mode == "excess_25" and full > excess:
        ctx.alert("S62A_OLD_POLICY_GAP", "warning", ent,
                  f"ס' 62א(א) חושב לפי מדיניות 'עודף מעל 25%'. לפי לשון החוק הייחוס מלא ({fmt(full)} ₪); "
                  f"הפרש הכנסה שלא יוחסה: {fmt(full - excess)} ₪.", "ס' 62א(א)")
    if o.controller_id:
        h = next((h for h in _holders_lt(c, ctx) if h.sh.individual_id == o.controller_id), None)
        recipients = [Holder(sh=h.sh, key=h.key, group=h.group, rights=Decimal(1), control=h.control)] if h else []
    else:
        recipients = active_shareholders(c, ctx)
    _distribute(ctx, st, c, "a_old", amount, recipients, "ייחוס לפי 62א(א)", "ס' 62א(א)")
    # draft circular 3.6.1: income attributed under (a) is removed from revenue and taxable before (a1)
    r2_ = rev - o.revenue
    t2_ = tax - o.taxable
    ctx.trace.add(ent, STAGE, "a1_base_after_old", "בסיס ל-62א(א1) אחרי הפחתת פעילות 62א(א)", t2_,
                  f"R' = {fmt(rev)} − {fmt(o.revenue)} = {fmt(r2_)}; T' = {fmt(tax)} − {fmt(o.taxable)} = {fmt(t2_)}",
                  "טיוטת חוזר ס' 3.6.1")
    # in excess_25 mode the non-attributed part of that activity stays taxable in the company
    st.remaining_effort_taxable += o.taxable - amount
    return r2_, t2_


def _profitability(c: CompanyInput, ctx: Ctx, st: S62AState, rev: Decimal, tax: Decimal) -> Decimal | None:
    ent = f"company:{c.id}"
    rp = c.related_party_payments if not c.related_party_declared else ZERO
    st.rp_added = rp
    if c.related_party_payments and not c.related_party_declared:
        ctx.alert("RELATED_PAYMENTS", "warning", ent,
                  f"תשלומים לחברה קשורה ({fmt(c.related_party_payments)} ₪) ללא הצהרה בטופס 1122 – נוספו לחישוב שיעור הרווחיות.",
                  "ס' 62א(ד) 'תשלומים לחברה קשורה'; טיוטת חוזר ס' 3.3.4")
    if rev <= 0:
        return None
    pr = (tax + rp) / rev
    ctx.trace.add(ent, STAGE, "profitability_year", f"שיעור רווחיות {ctx.year}", pr,
                  f"({fmt(tax)} + {fmt(rp)} תשלומים לחברה קשורה) / {fmt(rev)} = {fmt_rate(pr.quantize(Decimal('0.0001')))}",
                  "ס' 62א(ד) 'שיעור רווחיות'; טיוטת חוזר ס' 3.2.3")
    opt = ctx.req.options.use_2025_average
    if ctx.year == 2025 and ctx.p.raw_value("s62a.allow_2023_2025_average") and opt != "no":
        hist = c.profitability_history
        if 2023 in hist and 2024 in hist:
            rates = []
            for y in (2023, 2024):
                h = hist[y]
                rates.append((h.effort_taxable + h.related_party_payments) / h.effort_revenue if h.effort_revenue else ZERO)
            rates.append(pr)
            avg = sum(rates, ZERO) / 3
            ctx.trace.add(ent, STAGE, "profitability_avg", "ממוצע שיעור רווחיות 2023–2025 (הוראת מעבר)", avg,
                          " + ".join(fmt_rate(r.quantize(Decimal('0.0001'))) for r in rates) + " / 3",
                          "ס' 5(ה) להוראות המעבר; טיוטת חוזר ס' 3.2.3, נספח ג'")
            thr = ctx.p.rate("s62a.profitability_threshold")
            use_avg = opt == "yes" or (opt == "auto" and avg <= thr < pr)
            if use_avg:
                ctx.alert("S62A1_AVG_2025", "info", ent,
                          f"נבחרה חלופת הממוצע 2023–2025 ({fmt_rate(avg.quantize(Decimal('0.0001')))}), "
                          f"המיטיבה מול שיעור השנה ({fmt_rate(pr.quantize(Decimal('0.0001')))}). יש לצרף נייר עבודה לדוח.",
                          "הוראת ביצוע 9/2026 ס' 3")
                return avg
        elif opt == "yes":
            ctx.alert("S62A1_AVG_MISSING", "warning", ent, "נבחר ממוצע 2023–2025 אך חסרים נתוני 2023/2024.")
    return pr


def _excluded(c: CompanyInput, ctx: Ctx) -> tuple[bool, str]:
    """Exclusions of s.62A(a1)(2)(c) (draft circular s.3.4)."""
    thr_hold = ctx.p.rate("s62a.active_shareholder_control")          # 'material holder' = 30%
    thr_profit = ctx.p.num("s62a.retained_profits_threshold")
    holders = _holders_lt(c, ctx)
    gc = _group_control(holders)
    material = [h for h in holders if gc[h.group] >= thr_hold]
    own = c.accumulated_profits_prev if c.accumulated_profits_prev > 0 else ZERO
    if material:
        holders_of_profits = []
        for h in material:
            total = own + sum((x for x in h.sh.other_material_holdings_profits if x > 0), ZERO)
            if total > thr_profit:
                holders_of_profits.append((h.key, total))
        if not holders_of_profits:
            return True, (f"מוחרג (ס' 62א(א1)(2)(ג)): לאף מחזיק מהותי אין רווחים נצברים מצטברים מעל {fmt(thr_profit)} ₪ "
                          f"בכל חברות המעטים שבהן הוא מחזיק מהותי")
        return False, "קיים 'מחזיק בעל רווחים': " + ", ".join(f"{k} ({fmt(v)} ₪)" for k, v in holders_of_profits)
    controls_other = any(h.sh.controls_other_active_company for h in holders)
    if not controls_other and c.accumulated_profits_prev <= thr_profit:
        return True, (f"מוחרג: אין מחזיק מהותי, אין בעל שליטה בחברה פעילה אחרת, ורווחים נצברים "
                      f"({fmt(c.accumulated_profits_prev)}) ≤ {fmt(thr_profit)} ₪")
    return False, "אין מחזיק מהותי, אך לא מתקיימים שני תנאי ההחרגה"


def _controllers_count(c: CompanyInput, ctx: Ctx) -> int:
    thr = ctx.p.rate("s62a.controller_min_holding")
    gc = _group_control(_holders_lt(c, ctx))
    return max(1, sum(1 for v in gc.values() if v >= thr))


def apply_62a(c: CompanyInput, ctx: Ctx) -> S62AState:
    ent = f"company:{c.id}"
    st = S62AState()
    _expense_split(c, ctx, st)

    rev, tax = _old_62a(c, ctx, st, st.effort_revenue, st.effort_taxable)

    # ── s.62A(a1) applicability ──
    thr_pr = ctx.p.rate("s62a.profitability_threshold")
    reasons: list[str] = []
    applies = True
    if not c.is_few_company:
        applies, reasons = False, ["החברה אינה חברת מעטים (ס' 76)"]
    n = _controllers_count(c, ctx)
    cap = ctx.p.num("s62a.revenue_cap_per_controller") * n
    rev_ok = rev < cap
    ctx.trace.add(ent, STAGE, "revenue_test", "תנאי ההכנסות", rev_ok,
                  f"{fmt(rev)} < 30,000,000 × {n} בעלי שליטה = {fmt(cap)}", "ס' 62א(א1)(1); טיוטת חוזר ס' 3.2.2")
    if not rev_ok:
        applies = False
        reasons.append("מחזור הפעילות עולה על תקרת 30 מיליון × מספר בעלי השליטה")
    pr = _profitability(c, ctx, st, rev, tax)
    st.profitability = pr
    if pr is None or pr <= thr_pr:
        applies = False
        reasons.append(f"שיעור רווחיות {'—' if pr is None else fmt_rate(pr.quantize(Decimal('0.0001')))} אינו עולה על 25%")
        if pr is not None and pr > Decimal("0.20"):
            ctx.alert("S62A1_NEAR", "info", ent, f"שיעור הרווחיות ({fmt_rate(pr.quantize(Decimal('0.0001')))}) קרוב לסף 25%.",
                      "ס' 62א(א1)")
    excl, excl_reason = _excluded(c, ctx)
    ctx.trace.add(ent, STAGE, "exclusion_test", "בדיקת החרגות", excl, excl_reason, "ס' 62א(א1)(2)(ג); טיוטת חוזר ס' 3.4")
    if excl:
        applies = False
        reasons.append(excl_reason)

    remaining = tax
    if applies:
        # statute (Amendment 277, s.62A(a1)(1)): T − 25% × (R − payments to a related company)
        rp = st.rp_added
        attr_total = pos(tax - thr_pr * (rev - rp))
        ctx.trace.add(ent, STAGE, "a1_attributable", "ס' 62א(א1) – הכנסה חייבת לייחוס", attr_total,
                      f"max(0, {fmt(tax)} − {fmt_rate(thr_pr)} × ({fmt(rev)} − {fmt(rp)} תשלומים לחברה קשורה))",
                      "ס' 62א(א1)(1) (ס\"ח 3343); טיוטת חוזר נספח ה'; הוראת ביצוע 9/2026 ס' 3.3.1")
        actives = active_shareholders(c, ctx)
        if not actives:
            ctx.alert("S62A1_NO_ACTIVE", "warning", ent, "הסעיף חל אך לא זוהה בעל מניות פעיל – לא בוצע ייחוס.")
        got = _distribute(ctx, st, c, "a1", attr_total, actives, "ייחוס לפי 62א(א1)", "ס' 62א(א1)(1)")
        remaining = tax - got
        st.reason_a1 = f"כל התנאים מתקיימים; ייחוס {fmt(got)} ₪ לפי T − 25% × (R − RP)"
        ctx.alert("S62A1_APPLIES", "critical", ent,
                  f"ס' 62א(א1) חל: {fmt(got)} ₪ מיוחסים לבעלי המניות הפעילים וממוסים במס שולי; "
                  f"{fmt(remaining)} ₪ נותרים בחברה.", "ס' 62א(א1)")
    else:
        st.reason_a1 = "; ".join(reasons)
    st.applies_a1 = applies
    st.remaining_effort_taxable += remaining
    ctx.trace.add(ent, STAGE, "a1_result", "ס' 62א(א1) – תחולה", applies, st.reason_a1, "ס' 62א(א1)")

    _apply_a2(c, ctx, st)
    _apply_a3(c, ctx, st)
    return st


def _apply_a2(c: CompanyInput, ctx: Ctx, st: S62AState) -> None:
    """s.62A(a2): partnership share < 10% from controller's effort - 55% to controller, 45% stays.
    Draft circular 4.3.2 + appendix F ex.2: salary paid to the controller offsets the company's other
    business income first; any remaining loss reduces the 55%."""
    ent = f"company:{c.id}"
    min_share = ctx.p.num("s62a.partnership_min_share")
    rate = ctx.p.rate("s62a.a2_attribution_rate")
    small = [p for p in c.partnerships if p.share_pct < min_share and p.from_controller_effort]
    for p in c.partnerships:
        if p.share_pct < min_share and not p.from_controller_effort:
            st.other_taxable += p.effort_taxable_share
    if not small:
        return
    p_t = sum((p.effort_taxable_share for p in small), ZERO)
    gross = rate * p_t
    # company's non-partnership result so far (effort remaining + other); a loss here offsets the 55%
    non_part = st.remaining_effort_taxable + st.other_taxable
    offset = pos(-non_part)
    net = pos(gross - offset)
    ctx.trace.add(ent, STAGE, "a2_gross", "ס' 62א(א2) – 55% מההכנסה החייבת מהשותפות", gross,
                  f"{fmt_rate(rate)} × {fmt(p_t)}", "ס' 62א(א2); טיוטת חוזר ס' 4.3.2")
    if offset:
        ctx.trace.add(ent, STAGE, "a2_offset", "קיזוז הפסד/משכורת עודפת מפעילות אחרת של החברה", offset,
                      f"max(0, −({fmt(non_part)}))", "טיוטת חוזר נספח ו' דוגמה 2")
        # the loss is consumed by the controller's attribution
        st.remaining_effort_taxable += min(offset, gross)
    actives = active_shareholders(c, ctx)
    _distribute(ctx, st, c, "a2", net, actives, "ייחוס לפי 62א(א2)", "ס' 62א(א2)")
    st.a2_company_part = p_t - gross
    ctx.trace.add(ent, STAGE, "a2_company", "ס' 62א(א2) – 45% נותרים בחברה", st.a2_company_part,
                  f"{fmt(p_t)} − {fmt(gross)}", "ס' 62א(א2)")


def _apply_a3(c: CompanyInput, ctx: Ctx, st: S62AState) -> None:
    """s.62A(a3): dividend to the few-company from a company it does NOT control, whose income derives
    from our controller's effort: 55% is the individual's dividend income at 25%; 45% stays in company."""
    ent = f"company:{c.id}"
    rate = ctx.p.rate("s62a.a3_attribution_rate")
    for d in c.dividends_received_62a3:
        if d.company_controls_payer or not d.payer_income_from_controller_effort:
            st.a3_company_part += d.amount
            ctx.trace.add(ent, STAGE, f"a3_na_{d.payer_name}", f"דיבידנד מ-{d.payer_name} – 62א(א3) לא חל", d.amount,
                          "החברה בעלת שליטה במחלקת או שההכנסה אינה מיגיעת בעל השליטה", "ס' 62א(א3)")
            continue
        part = rate * d.amount
        if d.controller_id:
            h = next((h for h in _holders_lt(c, ctx) if h.sh.individual_id == d.controller_id), None)
            recipients = [Holder(sh=h.sh, key=h.key, group=h.group, rights=Decimal(1), control=h.control)] if h else []
        else:
            recipients = active_shareholders(c, ctx)
        for h in recipients:
            amt = part * h.rights
            st.attributed_to[h.sh.individual_id]["a3"] += amt
            ctx.buckets[h.sh.individual_id].dividends_62a3 += amt
            ctx.trace.add(ent, STAGE, f"a3_to_{h.sh.individual_id}", f"62א(א3) – דיבידנד המיוחס ל-{h.sh.individual_id}",
                          amt, f"{fmt_rate(rate)} × {fmt(d.amount)} × {fmt_rate(h.rights)}", "ס' 62א(א3); טיוטת חוזר ס' 5")
            st.attributed["a3"] += amt
        st.a3_company_part += d.amount - part
