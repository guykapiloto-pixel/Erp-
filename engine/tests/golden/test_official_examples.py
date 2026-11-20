"""Golden tests: every expected number comes from an official Tax Authority example.

S = draft Income Tax Circular XX/2025 on s.62A (Nov 2025), appendices C-G.
D = Income Tax Execution Directive 9/2026 (15.9.2026).
"""
from decimal import Decimal as Dm

import pytest

from taxengine import CalcRequest, calculate


def run(year=2025, individuals=None, companies=None, **options):
    return calculate(CalcRequest.model_validate({
        "tax_year": year, "individuals": individuals or [], "companies": companies or [], "options": options}))


def holder(iid, pct, **kw):
    return {"individual_id": iid, "profit_rights_pct": pct, **kw}


def co(cid, shareholders, **kw):
    return {"id": cid, "shareholders": shareholders, **kw}


def comp(res, cid):
    return next(c for c in res.companies if c.id == cid)


def ind(res, iid):
    return next(i for i in res.individuals if i.id == iid)


# G1 – S appendix E ex.1: architects 1,000 revenue / 400 expenses, rent 300/100 is 'other income', surplus 800K
def test_g1_architects_single_holder():
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100, personal_effort=True)],
            effort_revenue=1000, effort_expenses=400, other_income=300, other_expenses=100,
            accumulated_profits_prev=800_000)])
    c = comp(r, "C")
    assert c.s62a1_applies
    assert c.profitability_rate == Dm("60.00")
    assert c.attributed_by_section["a1"] == Dm("350.00")
    # company keeps 250 from the effort activity + 200 net rent
    assert c.taxable_income == Dm("450.00")


# G2 – S appendix E ex.2: two holders 60/40
def test_g2_two_holders_60_40():
    r = run(individuals=[{"id": "A"}, {"id": "B"}], companies=[co("C", [holder("A", 60), holder("B", 40)],
            effort_revenue=1000, effort_expenses=400, accumulated_profits_prev=800_000)])
    c = comp(r, "C")
    assert c.attributed_to["A"]["a1"] == Dm("210.00")
    assert c.attributed_to["B"]["a1"] == Dm("140.00")
    assert c.taxable_income == Dm("250.00")


# G3 – S appendix E ex.2, company B: 2,000 / 350, own surplus 300K but holder B has 800K elsewhere -> not excluded
def test_g3_company_b_holder_of_profits():
    r = run(individuals=[{"id": "B"}], companies=[co("CB", [holder("B", 100, other_material_holdings_profits=[800_000])],
            effort_revenue=2000, effort_expenses=350, accumulated_profits_prev=300_000)])
    c = comp(r, "CB")
    assert c.s62a1_applies
    assert c.attributed_by_section["a1"] == Dm("1150.00")
    assert c.taxable_income == Dm("500.00")


# G4 – S appendix F ex.1: partnership share 15% -> included in effort activity (300 / 225)
def test_g4_partnership_at_least_10pct():
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], accumulated_profits_prev=900_000,
            partnerships=[{"name": "P", "share_pct": 15, "effort_revenue_share": 300, "effort_taxable_share": 225}])])
    c = comp(r, "C")
    assert c.profitability_rate == Dm("75.00")
    assert c.attributed_by_section["a1"] == Dm("150.00")
    assert c.taxable_income == Dm("75.00")


# G5 – S appendix F ex.2: partnership share 5% -> 55%/45%
@pytest.mark.parametrize("extra_rev,salary,exp_ind,exp_co", [
    (0, 0, "41.25", "33.75"),
    (200, 199, "41.25", "34.75"),   # salary fully absorbed by the other business income
    (200, 201, "40.25", "33.75"),   # 1 of excess salary reduces the 55%
    (0, 10, "31.25", "33.75"),      # business loss of 10 offsets the individual's 55%
])
def test_g5_partnership_below_10pct(extra_rev, salary, exp_ind, exp_co):
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100, salary_from_company=salary)],
            effort_revenue=extra_rev, effort_expenses=salary, accumulated_profits_prev=900_000,
            partnerships=[{"name": "P", "share_pct": 5, "effort_revenue_share": 100, "effort_taxable_share": 75}])])
    c = comp(r, "C")
    assert c.attributed_by_section.get("a2", Dm(0)) == Dm(exp_ind)
    assert c.taxable_income == Dm(exp_co)


# G6 – S appendix C(1): (90 + 30 related payments, not declared) / 250 = 48%
def test_g6_profitability_with_related_payments():
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], effort_revenue=250, effort_expenses=160,
            related_party_payments=30, related_party_declared=False, accumulated_profits_prev=800_000)])
    c = comp(r, "C")
    assert c.profitability_rate == Dm("48.00")
    assert c.s62a1_applies
    # related payments affect only the test, not the attributed amount: 90 - 25% x 250 = 27.5
    assert c.attributed_by_section["a1"] == Dm("27.50")
    assert any(a.code == "RELATED_PAYMENTS" for a in r.alerts)


# G7 – S appendix C(2): 2025 average 7% / 11% / 40% = 19% -> not applicable in 2025
def test_g7_average_2023_2025():
    hist = {2023: {"effort_revenue": 165, "effort_taxable": 11},
            2024: {"effort_revenue": 180, "effort_taxable": 20}}
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], effort_revenue=250, effort_expenses=160,
            related_party_payments=10, related_party_declared=False, profitability_history=hist,
            accumulated_profits_prev=800_000)])
    c = comp(r, "C")
    assert not c.s62a1_applies
    assert any(a.code == "S62A1_AVG_2025" for a in r.alerts)
    # same data in 2026 -> no average option -> applies
    r26 = run(year=2026, individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], effort_revenue=250,
              effort_expenses=160, related_party_payments=10, related_party_declared=False,
              profitability_history=hist, accumulated_profits_prev=800_000)])
    assert comp(r26, "C").s62a1_applies


# G8 – S appendix D: holder of profits across companies (500K + 700K) / losses not netted / no material holder
def test_g8_exclusions():
    base = dict(effort_revenue=1000, effort_expenses=400)
    r = run(individuals=[{"id": "A"}], companies=[co("CA", [holder("A", 100, other_material_holdings_profits=[700_000])],
            accumulated_profits_prev=500_000, **base)])
    assert comp(r, "CA").s62a1_applies
    r = run(individuals=[{"id": "A"}], companies=[co("CA", [holder("A", 100, other_material_holdings_profits=[-2_000_000])],
            accumulated_profits_prev=500_000, **base)])
    assert not comp(r, "CA").s62a1_applies       # loss of the other company is ignored, 500K < 750K
    # four unrelated 25% holders, no material holder, surplus < 750K, no other active company -> excluded
    r = run(individuals=[{"id": x} for x in "ABCD"], companies=[co("C", [holder(x, 25, personal_effort=True) for x in "ABCD"],
            accumulated_profits_prev=700_000, **base)])
    assert not comp(r, "C").s62a1_applies


# G9 – D s.3.4: 'dividend alternative' on 1,000,000 -> corp tax 172,500, dividend 577,500, w/h 30% 173,250
def test_g9_dividend_alternative():
    r = run(individuals=[{"id": "A", "credit_points": 0}],
            companies=[co("C", [holder("A", 100)], effort_revenue=1_000_000, accumulated_profits_prev=800_000)],
            reporting_alternative="dividend")
    c = comp(r, "C")
    assert c.attributed_by_section["a1"] == Dm("750000.00")
    assert c.taxable_income == Dm("1000000.00")
    assert c.dividend_withholding == Dm("173250.00")
    i = ind(r, "A")
    assert i.exertion_income == Dm("750000.00")
    assert i.credits_and_prepayments["מס חברות שקוזז – חלופת הדיבידנד (שדה 100)"] == Dm("172500.00")
    assert i.credits_and_prepayments["ניכוי במקור מדיבידנד"] == Dm("173250.00")


# G10 – S appendix G: old 62A(a), 2,000 officer income, full attribution + dividend alternative
def test_g10_old_62a_full_dividend_alt():
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], effort_revenue=2000,
            old_62a={"revenue": 2000, "taxable": 2000, "controller_id": "A"}, accumulated_profits_prev=0)],
            reporting_alternative="dividend", old_62a_mode="full")
    c = comp(r, "C")
    assert c.attributed_by_section["a_old"] == Dm("2000.00")
    assert c.corporate_tax == Dm("460.00")
    assert c.dividend_withholding == Dm("462.00")
    # with a 47% marginal rate: 940 - 460 - 462 = 18 (example ignores brackets); check the credits instead
    i = ind(r, "A")
    assert sum(i.credits_and_prepayments.values()) == Dm("922.00")


def test_old_62a_office_policy_excess_25():
    """User decision #1: old 62A(a) computed as excess above 25% of turnover (alert shows statutory gap)."""
    r = run(individuals=[{"id": "A"}], companies=[co("C", [holder("A", 100)], effort_revenue=1000, effort_expenses=200,
            old_62a={"revenue": 1000, "taxable": 800, "controller_id": "A"}, accumulated_profits_prev=0)])
    c = comp(r, "C")
    assert c.attributed_by_section["a_old"] == Dm("550.00")
    assert c.taxable_income == Dm("250.00")
    assert any(a.code == "S62A_OLD_POLICY_GAP" for a in r.alerts)
