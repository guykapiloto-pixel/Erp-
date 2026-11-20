"""Component tests. Expected values are computed by hand in the comments."""
from decimal import Decimal as Dm

import pytest

from taxengine import CalcRequest, ValidationError, calculate


def run(year=2025, individuals=None, companies=None, **options):
    return calculate(CalcRequest.model_validate({
        "tax_year": year, "individuals": individuals or [], "companies": companies or [], "options": options}))


def test_brackets_and_credit_points_2025():
    # 84,120×10% = 8,412 | 36,600×14% = 5,124 | 73,080×20% = 14,616 | 75,480×31% = 23,398.80 | 30,720×35% = 10,752
    # = 62,302.80 − 2.25 × 2,904 (6,534) = 55,768.80
    i = run(individuals=[{"id": "A", "salary_external": 300_000}]).individuals[0]
    assert i.bracket_tax == Dm("62302.80")
    assert i.gross_tax == Dm("55768.80")
    assert i.marginal_rate == Dm("35.00")


def test_female_extra_credit_point():
    i = run(individuals=[{"id": "A", "gender": "female", "salary_external": 300_000}]).individuals[0]
    assert i.gross_tax == Dm("55768.80") - Dm("1452.00")   # 0.5 × 2,904


def test_passive_income_starts_at_31pct():
    # 50,000 rent on top of 0 exertion income: whole amount at max(rate, 31%) = 15,500; credit points offset it
    i = run(individuals=[{"id": "A", "rental_income_taxable": 50_000, "credit_points": 0}]).individuals[0]
    assert i.bracket_tax == Dm("15500.00")
    # age 60+: regular brackets -> 5,000
    i = run(individuals=[{"id": "A", "rental_income_taxable": 50_000, "credit_points": 0, "age": 62}]).individuals[0]
    assert i.bracket_tax == Dm("5000.00")


def test_surtax_with_capital_component():
    # total 1,200,000; above 721,560 = 478,440 → 3% = 14,353.20; capital 200,000 (stacked on top) × 2% = 4,000
    i = run(individuals=[{"id": "A", "salary_external": 1_000_000, "dividends_external": 200_000,
                          "dividends_external_material": True}]).individuals[0]
    assert i.surtax == Dm("14353.20")
    assert i.surtax_capital == Dm("4000.00")
    assert i.special_rate_tax == Dm("60000.00")


def _s81_company(div):
    return {"id": "C", "shareholders": [{"individual_id": "A", "profit_rights_pct": 100}],
            "effort_revenue": 1_000_000, "effort_expenses": 900_000, "dividends_declared": div,
            "s81": {"accumulated_profits_tax_alt": 2_100_000, "accumulated_profits_accounting_alt": 2_000_000,
                    "deductible_expenses": 900_000, "depreciated_assets_cost": 500_000}}


def test_s81b_tax_2026():
    # AP = min(2.1M, 2.0M) = 2.0M; shield = max(750K, 900K, 500K) = 900K; EP = 1.1M
    # min dividend = min(6% × 2.0M = 120K, 50% × 1.1M = 550K) = 120K; dividend 50K → taxable 1.05M × 2% = 21,000
    c = run(year=2026, individuals=[{"id": "A"}], companies=[_s81_company(50_000)]).companies[0]
    assert c.s81_excess_profits == Dm("1100000.00")
    assert c.s81_min_dividend_to_avoid == Dm("120000.00")
    assert c.s81_tax == Dm("21000.00")


def test_s81b_exempt_by_distribution():
    c = run(year=2026, individuals=[{"id": "A"}], companies=[_s81_company(120_000)]).companies[0]
    assert c.s81_tax == 0 and "6%" in c.s81_exemption
    # 2025: 5% is enough → 100K
    c = run(year=2025, individuals=[{"id": "A"}], companies=[_s81_company(100_000)]).companies[0]
    assert c.s81_tax == 0 and "5%" in c.s81_exemption


def test_s81b_below_threshold():
    comp = _s81_company(0)
    comp["s81"] = {"accumulated_profits_tax_alt": 700_000}
    c = run(year=2026, individuals=[{"id": "A"}], companies=[comp]).companies[0]
    assert not c.s81_applies and c.s81_tax == 0


def test_chain_notional_dividend_main_track():
    # Sub (100% held by Parent, 100% held by A) pays 100,000 to Parent: 35% withheld = 35,000;
    # notional dividend 100,000 to A as material holder (30%) = 30,000 tax; credit 35,000
    r = run(individuals=[{"id": "A", "credit_points": 0}], companies=[
        {"id": "P", "shareholders": [{"individual_id": "A", "profit_rights_pct": 100}]},
        {"id": "S", "shareholders": [{"company_id": "P", "profit_rights_pct": 100}], "dividends_declared": 100_000},
    ])
    s = next(c for c in r.companies if c.id == "S")
    assert s.notional_dividend_withholding == Dm("35000.00")
    a = r.individuals[0]
    assert a.special_rate_income["dividend_30"] == Dm("100000.00")
    assert a.credits_and_prepayments["ניכוי 35% – דיבידנד רעיוני"] == Dm("35000.00")


def test_nii_employee_2026():
    # 10,000/month: 7,703 × 4.27% + 2,297 × 12.17% = 608.463/month × 12 = 7,301.556
    i = run(year=2026, individuals=[{"id": "A", "salary_external": 120_000}]).individuals[0]
    assert i.nii_employee == Dm("7301.56")


def test_brackets_2026_widened():
    # 2026: 20% bracket up to 228,000 → 228,000 salary: 8,412 + 5,124 + 107,280×20% (21,456) = 34,992
    i = run(year=2026, individuals=[{"id": "A", "salary_external": 228_000, "credit_points": 0}]).individuals[0]
    assert i.bracket_tax == Dm("34992.00")


def test_validation_errors():
    with pytest.raises(ValidationError):
        run(companies=[{"id": "C", "shareholders": [{"individual_id": "X", "profit_rights_pct": 100}]}])
    with pytest.raises(ValidationError):
        run(individuals=[{"id": "A"}], companies=[{"id": "C", "shareholders": [
            {"individual_id": "A", "profit_rights_pct": 70}, {"external_name": "Z", "profit_rights_pct": 40}]}])


def test_unsupported_year():
    with pytest.raises(ValueError):
        run(year=2023)


# ── changes after official-source verification ──

def test_controlling_shareholder_nii_rates_2026():
    # salary 120,000 from own few-company (100%): 7,703 × 4.25% + 2,297 × 11.96% = 327.3775 + 274.7212 = 602.0987 × 12
    r = run(year=2026, individuals=[{"id": "A"}], companies=[{"id": "C", "shareholders": [
        {"individual_id": "A", "profit_rights_pct": 100, "salary_from_company": 120_000}],
        "effort_revenue": 500_000, "effort_expenses": 120_000}])
    assert r.individuals[0].nii_employee == Dm("7225.18")


def test_s81b_20pct_track_and_option1():
    comp = _s81_company(250_000)
    comp["s81"]["start_date_profits_remaining"] = 1_000_000   # 250K >= 20% → excess 1.1M − 1.0M = 100K; 250K > 50% → exempt
    c = run(year=2026, individuals=[{"id": "A"}], companies=[comp]).companies[0]
    assert c.s81_tax == 0
    comp = _s81_company(0)
    comp["s81"] = {"accumulated_profits_tax_alt": 2_000_000, "depreciated_assets_cost": 1_500_000, "exempt_profits_option": "1"}
    c = run(year=2026, individuals=[{"id": "A"}], companies=[comp]).companies[0]
    # option 1 forfeits the asset shield → cash shield 750K → excess 1.25M → 2% = 25,000
    assert c.s81_excess_profits == Dm("1250000.00") and c.s81_tax == Dm("25000.00")


def test_notional_65_rule():
    # actual dividend 100,000 (material), stack balance 65,000 → only 35,000 taxed at 30% = 10,500
    i = run(individuals=[{"id": "A", "dividends_external": 100_000, "dividends_external_material": True,
                          "notional_65_balance": 65_000}]).individuals[0]
    assert i.special_rate_tax == Dm("10500.00")


def test_transitional_calculators():
    from datetime import date
    from taxengine.transitional import AssetTransferIn, LaterSaleIn, asset_transfer, later_sale
    # circular 03/2025: cost 100, profits 50, shareholder loan 20 → dividend 50, offset 20, top-rate 30
    o = asset_transfer(AssetTransferIn(depreciated_cost=100, distributable_profits=50, shareholder_credit_balance=20))
    assert (o.totals["dividend"], o.totals["offset"], o.totals["top_rate_income"]) == (Dm(50), Dm(20), Dm(30))
    o = later_sale(LaterSaleIn(real_gain=1000, acquisition_date=date(2015, 1, 1), transfer_date=date(2025, 1, 1),
                               sale_date=date(2030, 1, 1)))
    # 3653 / 5479 days before transfer
    assert o.totals["pre_transfer_gain"] == Dm("666.73")


def test_62a1_lookthrough_holding_company():
    # A holds 100% of holding company H, which holds 100% of operating company S → A is an indirect active holder
    r = run(individuals=[{"id": "A"}], companies=[
        {"id": "H", "shareholders": [{"individual_id": "A", "profit_rights_pct": 100}]},
        {"id": "S", "shareholders": [{"company_id": "H", "profit_rights_pct": 100}],
         "effort_revenue": 1000, "effort_expenses": 400, "accumulated_profits_prev": 800_000}])
    s = next(c for c in r.companies if c.id == "S")
    assert s.s62a1_applies
    assert s.attributed_to["A"]["a1"] == Dm("350.00")
