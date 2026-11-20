"""Salary-vs-dividend scan for an owner-managed company (spec s.6.5).

For each salary level S (0 .. pre-salary profit), the company pays S to the owner, the employer NII on it is a
deductible expense, and the year's after-tax profit is distributed as a dividend (or retained). The full pipeline
runs for every point, so 62A attribution, s.81B, surtax and NII are all reflected in the total burden.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from .models import CalcRequest
from .money import ZERO, pos, r2
from .params import load_params
from .pipeline import calculate
from .rules.nii import _two_band


class ScenarioPoint(BaseModel):
    salary: Decimal
    dividend: Decimal
    corporate_tax: Decimal
    s81_tax: Decimal
    income_tax: Decimal
    nii_total: Decimal
    total_tax: Decimal
    owner_net: Decimal
    effective_rate: Decimal
    s62a1_applies: bool


class ScenarioResult(BaseModel):
    company_id: str
    individual_id: str
    profit_before_owner_salary: Decimal
    total_profit_before_owner_salary: Decimal
    points: list[ScenarioPoint]
    best: ScenarioPoint


def _employer_nii(salary: Decimal, year: int, controlling: bool = False) -> Decimal:
    p = load_params(year)
    er = p.rates("nii.controlling_employer" if controlling else "nii.employer")
    return _two_band(salary / 12, ZERO, p.num("nii.reduced_threshold_monthly"), p.num("nii.max_insurable_monthly"),
                     er["ni_reduced"], er["ni_full"]) * 12


def salary_dividend_scan(req: CalcRequest, company_id: str, individual_id: str, steps: int = 20,
                         distribute: bool = True) -> ScenarioResult:
    base = req.model_copy(deep=True)
    comp = next(c for c in base.companies if c.id == company_id)
    sh = next(s for s in comp.shareholders if s.individual_id == individual_id)
    other_expenses = comp.effort_expenses - sh.salary_from_company
    profit = comp.effort_revenue - other_expenses          # effort profit before the owner's salary
    if profit <= 0:
        raise ValueError("No positive profit before owner salary to allocate")
    owner_rights = sh.profit_rights_pct / Decimal(100)
    total_profit = profit + comp.other_income - comp.other_expenses - comp.shared_expenses   # denominator for the rate
    ctrl = comp.is_few_company and (sh.control_pct if sh.control_pct is not None else sh.profit_rights_pct) >= 10

    points: list[ScenarioPoint] = []
    for k in range(steps + 1):
        s_gross = profit * k / steps
        # salary + employer NII must fit within profit
        while s_gross > 0 and s_gross + _employer_nii(s_gross, req.tax_year, ctrl) > profit:
            s_gross -= profit / (steps * 10)
        s_gross = r2(pos(s_gross))
        r = base.model_copy(deep=True)
        c = next(x for x in r.companies if x.id == company_id)
        h = next(x for x in c.shareholders if x.individual_id == individual_id)
        h.salary_from_company = s_gross
        c.effort_expenses = other_expenses + s_gross + _employer_nii(s_gross, req.tax_year, ctrl)
        c.dividends_declared = ZERO
        first = calculate(r)
        cr = next(x for x in first.companies if x.id == company_id)
        div = r2(pos(cr.taxable_income - cr.corporate_tax)) if distribute else ZERO
        c.dividends_declared = div
        res = calculate(r)
        cr = next(x for x in res.companies if x.id == company_id)
        ir = next(x for x in res.individuals if x.id == individual_id)
        nii = ir.nii_employee + ir.nii_self_employed + ir.nii_passive + ir.nii_employer_cost
        total = cr.total_tax + ir.gross_tax + nii
        attributed = sum(cr.attributed_to.get(individual_id, {}).values(), ZERO)
        owner_net = s_gross + div * owner_rights + attributed - ir.gross_tax - (nii - ir.nii_employer_cost)
        points.append(ScenarioPoint(
            salary=s_gross, dividend=div, corporate_tax=cr.corporate_tax, s81_tax=cr.s81_tax, income_tax=ir.gross_tax,
            nii_total=r2(nii), total_tax=r2(total), owner_net=r2(owner_net),
            effective_rate=r2(total / total_profit * 100) if total_profit > 0 else Decimal(0), s62a1_applies=cr.s62a1_applies))
    best = min(points, key=lambda p: p.total_tax)
    return ScenarioResult(company_id=company_id, individual_id=individual_id, profit_before_owner_salary=r2(profit), total_profit_before_owner_salary=r2(total_profit),
                          points=points, best=best)
