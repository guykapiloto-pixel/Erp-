"""Runs the calculation stages in a fixed order (spec s.3)."""
from __future__ import annotations

from decimal import Decimal

from .context import Ctx
from .models import CalcRequest, CalcResult, CompanyInput, CompanyResult, ParamRef
from .money import ZERO, fmt, pos, r2
from .params import load_params
from .rules.corporate import corporate_tax
from .rules.individual import compute_individual
from .rules.nii import compute_nii
from .rules.s62a import apply_62a
from .rules.s81 import apply_81b


class ValidationError(ValueError):
    pass


def validate(req: CalcRequest) -> None:
    errors: list[str] = []
    iids = [i.id for i in req.individuals]
    cids = [c.id for c in req.companies]
    for name, ids in (("individual", iids), ("company", cids)):
        dup = {x for x in ids if ids.count(x) > 1}
        if dup:
            errors.append(f"Duplicate {name} id(s): {sorted(dup)}")
    for c in req.companies:
        total = sum((s.profit_rights_pct for s in c.shareholders), Decimal(0))
        if total > 100:
            errors.append(f"Company {c.id}: profit rights sum to {total}% (>100%)")
        for s in c.shareholders:
            refs = [x for x in (s.individual_id, s.company_id, s.external_name) if x]
            if len(refs) != 1:
                errors.append(f"Company {c.id}: each shareholder needs exactly one of individual_id/company_id/external_name")
            if s.individual_id and s.individual_id not in iids:
                errors.append(f"Company {c.id}: unknown individual '{s.individual_id}'")
            if s.company_id and s.company_id not in cids:
                errors.append(f"Company {c.id}: unknown parent company '{s.company_id}'")
            if s.company_id == c.id:
                errors.append(f"Company {c.id} cannot hold itself")
    if errors:
        raise ValidationError("; ".join(errors))


def _order(req: CalcRequest) -> list[CompanyInput]:
    """Subsidiaries before parents (a parent is a company that appears as a shareholder)."""
    by_id = {c.id: c for c in req.companies}
    done: list[str] = []
    visiting: set[str] = set()

    def visit(cid: str) -> None:
        if cid in done:
            return
        if cid in visiting:
            raise ValidationError(f"Circular holding structure at company {cid}")
        visiting.add(cid)
        # children = companies held by cid
        for child in req.companies:
            if any(s.company_id == cid for s in child.shareholders):
                visit(child.id)
        visiting.discard(cid)
        done.append(cid)

    for c in req.companies:
        visit(c.id)
    return [by_id[x] for x in done]


def calculate(req: CalcRequest) -> CalcResult:
    validate(req)
    ctx = Ctx(req=req, p=load_params(req.tax_year))
    companies: list[CompanyResult] = []

    for c in _order(req):
        ent = f"company:{c.id}"
        for sh in c.shareholders:
            if sh.individual_id and sh.salary_from_company:
                ctx.buckets[sh.individual_id].salary_from_companies += sh.salary_from_company
        st = apply_62a(c, ctx)
        cs = corporate_tax(c, ctx, st)
        loss_in_year = pos(-cs.taxable)
        s81 = apply_81b(c, ctx, cs, loss_in_year)
        total = cs.corporate_tax + s81.tax
        turnover = c.effort_revenue + c.other_income
        cr = CompanyResult(
            id=c.id, name=c.name,
            s62a1_applies=st.applies_a1, s62a1_reason=st.reason_a1,
            profitability_rate=None if st.profitability is None else r2(st.profitability * 100),
            attributed_by_section={k: r2(v) for k, v in st.attributed.items() if v},
            attributed_to={i: {k: r2(v) for k, v in secs.items() if v} for i, secs in st.attributed_to.items()},
            taxable_income=r2(cs.taxable), corporate_tax=r2(cs.corporate_tax),
            s81_applies=s81.applies, s81_excess_profits=r2(s81.excess), s81_taxable=r2(s81.taxable),
            s81_tax=r2(s81.tax), s81_exemption=s81.exemption, s81_min_dividend_to_avoid=r2(s81.min_dividend_to_avoid),
            dividend_withholding=r2(cs.dividend_withholding), notional_dividend_withholding=r2(cs.notional_withholding),
            total_tax=r2(total), advances_paid=r2(c.advances_paid), balance_due=r2(total - c.advances_paid),
            suggested_advance_rate_pct=r2(cs.corporate_tax / turnover * 100) if turnover > 0 else None,
        )
        ctx.trace.add(ent, "advances", "balance", "יתרת מס לחברה (מס חברות + 81ב − מקדמות)", total - c.advances_paid,
                      f"{fmt(cs.corporate_tax)} + {fmt(s81.tax)} − {fmt(c.advances_paid)}", "ס' 175")
        if c.advance_rate_pct is not None and cr.suggested_advance_rate_pct is not None:
            if abs(c.advance_rate_pct - cr.suggested_advance_rate_pct) >= Decimal("0.5"):
                ctx.alert("ADVANCE_RATE", "info", ent,
                          f"שיעור המקדמות הנוכחי {c.advance_rate_pct}% לעומת שיעור מחושב {cr.suggested_advance_rate_pct}%.", "ס' 175")
        attributed_total = sum(st.attributed.values(), ZERO)
        if attributed_total and ctx.req.options.reporting_alternative == "attribution" and c.advances_paid > total:
            ctx.alert("ADVANCES_MISMATCH", "warning", ent,
                      f"שולמו מקדמות בחברה ({fmt(c.advances_paid)}) מעבר למס שנותר בה ({fmt(total)}), בעוד "
                      f"{fmt(attributed_total)} ₪ יוחסו ליחידים. ניתן לבקש הקפאת חוב ביחיד ל-3 חודשים.",
                      "הוראת ביצוע 9/2026 ס' 3.3.1")
        companies.append(cr)

    individuals = []
    for ind in req.individuals:
        b = ctx.buckets[ind.id]
        res = compute_individual(ind, b, ctx)
        compute_nii(ind, b, ctx, res)
        individuals.append(res)

    for u in ctx.p.unverified_used():
        ctx.alert("PARAM_UNVERIFIED", "info", "params", f"פרמטר '{u.path}' בסטטוס '{u.status}' – {u.source}")

    burden = sum((c.total_tax for c in companies), ZERO) + sum(
        (i.gross_tax + i.nii_employee + i.nii_self_employed + i.nii_passive + i.nii_employer_cost for i in individuals), ZERO)

    def _r(obj):
        for k, v in obj.__dict__.items():
            if isinstance(v, Decimal):
                setattr(obj, k, r2(v))
            elif isinstance(v, dict):
                setattr(obj, k, {kk: r2(vv) if isinstance(vv, Decimal) else vv for kk, vv in v.items()})
        return obj

    return CalcResult(
        tax_year=req.tax_year,
        companies=companies,
        individuals=[_r(i) for i in individuals],
        alerts=ctx.alerts,
        trace=[s.model_dump() for s in ctx.trace.steps],
        params_used=[ParamRef(path=u.path, status=u.status, source=u.source) for u in ctx.p.used.values()],
        total_tax_burden=r2(burden),
    )
