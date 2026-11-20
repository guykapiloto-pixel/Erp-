"""Input / output models. Amounts are annual ILS unless stated otherwise."""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Money = Decimal
Percent = Decimal  # 0-100


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Gender(str, Enum):
    male = "male"
    female = "female"


# ───────────────────────────── Individual ─────────────────────────────

class IndividualInput(_Base):
    id: str
    name: str = ""
    gender: Gender = Gender.male
    israeli_resident: bool = True
    age: int | None = Field(default=None, description="Age at year end; >=60 lets passive income use lower brackets (s.121)")
    credit_points: Decimal | None = Field(default=None, description="Total credit points; default = resident base (+female extra)")

    # personal-exertion income (graduated brackets)
    salary_external: Money = Field(default=Decimal(0), description="Gross salary from employers outside the model")
    business_income: Money = Field(default=Decimal(0), description="Net self-employed income (s.2(1))")
    other_exertion_income: Money = Field(default=Decimal(0))

    # non-exertion income on graduated brackets (min 31% unless age >= 60)
    rental_income_taxable: Money = Field(default=Decimal(0), description="Rental income taxed at brackets (not 10% track)")
    other_passive_income: Money = Field(default=Decimal(0))

    # special-rate income
    dividends_external: Money = Field(default=Decimal(0), description="Dividends from companies outside the model")
    dividends_external_material: bool = Field(default=False, description="Material shareholder (>=10%) in the paying company")
    capital_gains_real: Money = Field(default=Decimal(0))
    capital_gains_material: bool = False
    interest_unlinked: Money = Field(default=Decimal(0))
    interest_linked: Money = Field(default=Decimal(0))

    deductions: Money = Field(default=Decimal(0), description="Deductions from taxable income (e.g. s.47 pension, study fund)")
    tax_credits: Money = Field(default=Decimal(0), description="Direct tax credits in ILS (pension s.45A, etc.)")
    donations: Money = Field(default=Decimal(0), description="Donations eligible under s.46 (35% credit)")

    tax_withheld: Money = Field(default=Decimal(0), description="Income tax withheld at source (salary, interest, etc.)")
    advances_paid: Money = Field(default=Decimal(0))
    nii_paid: Money = Field(default=Decimal(0), description="NII + health already paid/withheld")
    nii_passive_liable: bool = Field(default=False, description="Charge NII on passive income (only if not working - estimate)")


# ───────────────────────────── Company ─────────────────────────────

class Shareholder(_Base):
    individual_id: str | None = Field(default=None, description="Individual in this request")
    company_id: str | None = Field(default=None, description="Parent company in this request (holding chain)")
    external_name: str | None = Field(default=None, description="Holder not modelled (e.g. non-resident, public)")
    profit_rights_pct: Percent = Field(description="% of rights to profits")
    control_pct: Percent | None = Field(default=None, description="Highest % in any means of control (default = profit rights)")
    relatives_group: str | None = Field(default=None, description="Same key = relatives counted as one (s.76(d)(1))")
    personal_effort: bool = Field(default=False, description="Works / provides services / manages / signatory in the company")
    salary_from_company: Money = Field(default=Decimal(0), description="Gross salary paid by this company (already in expenses)")
    resident: bool = True
    # data for the 'holder of profits' exclusion test (s.62A(a1)(2)(c))
    other_material_holdings_profits: list[Money] = Field(default_factory=list,
        description="Accumulated profits (end of prior year) of OTHER few-companies where holder has >=30%")
    controls_other_active_company: bool = False


class Partnership(_Base):
    name: str
    share_pct: Percent = Field(description="Company share in the partnership on 31.12")
    effort_revenue_share: Money = Field(description="Company share of partnership revenue from personal-exertion activity")
    effort_taxable_share: Money = Field(description="Company share of partnership taxable income from that activity")
    from_controller_effort: bool = Field(default=True, description="Partnership income derives from the controller's effort")


class DividendReceived(_Base):
    payer_name: str
    amount: Money
    company_controls_payer: bool = Field(description="This few-company is a controlling shareholder of the payer")
    payer_income_from_controller_effort: bool = Field(description="Payer income derives from our controller's personal effort")
    controller_id: str | None = Field(default=None, description="Individual the 55% is attributed to (default: active holders)")


class ProfitabilityYear(_Base):
    effort_revenue: Money
    effort_taxable: Money
    related_party_payments: Money = Decimal(0)


class Old62A(_Base):
    """Income from the controller acting as officer / employee-like services (s.62A(a) 'old')."""
    revenue: Money = Decimal(0)
    taxable: Money = Decimal(0)
    controller_id: str | None = None


class S81Input(_Base):
    accumulated_profits_tax_alt: Money | None = Field(default=None, description="Tax alternative, end of prior year")
    accumulated_profits_accounting_alt: Money | None = Field(default=None, description="Accounting alternative, end of prior year")
    exempt_accumulated_profits: Money = Decimal(0)
    deductible_expenses: Money = Field(default=Decimal(0), description="Expense shield (allowed deductible expenses)")
    depreciated_assets_cost: Money = Field(default=Decimal(0), description="Asset shield (depreciated cost at year end)")
    trapped_profits_31_12_2024: Money | None = Field(default=None, description="For 2025 20% transitional exemption")
    dividends_qualifying: Money | None = Field(default=None,
        description="Dividends counted for s.81B(b); default = regular dividends declared (excl. 62A dividend alternative)")


class CompanyInput(_Base):
    id: str
    name: str = ""
    is_few_company: bool = Field(default=True, description="'חברת מעטים' per s.76")
    shareholders: list[Shareholder]

    # P&L split by activity type
    effort_revenue: Money = Field(default=Decimal(0), description="Revenue from personal-exertion activity (not 'other income')")
    effort_expenses: Money = Field(default=Decimal(0), description="Expenses specifically attributable to that activity (incl. salaries)")
    other_income: Money = Field(default=Decimal(0), description="'Other income' per s.62A(d): interest, rent, dividends, asset sales...")
    other_expenses: Money = Decimal(0)
    shared_expenses: Money = Field(default=Decimal(0), description="Expenses not specifically attributable; allocated by revenue ratio")
    exempt_dividends_received: Money = Field(default=Decimal(0), description="Inter-company dividends exempt under s.126(b), excl. 62A(a3) items")
    loss_carryforward: Money = Field(default=Decimal(0), description="Carried-forward business losses (not against special income)")

    related_party_payments: Money = Decimal(0)
    related_party_declared: bool = Field(default=True, description="Form 1122 declaration submitted")
    profitability_history: dict[int, ProfitabilityYear] = Field(default_factory=dict, description="For the 2025 average option")
    old_62a: Old62A | None = None
    partnerships: list[Partnership] = Field(default_factory=list)
    dividends_received_62a3: list[DividendReceived] = Field(default_factory=list)

    accumulated_profits_prev: Money = Field(default=Decimal(0), description="Accumulated profits at end of prior year (s.77(a))")
    s81: S81Input = Field(default_factory=S81Input)

    dividends_declared: Money = Field(default=Decimal(0), description="Regular dividend declared in the year (split by profit rights)")
    dividend_to_parent_track: Literal["main", "alternative", "exempt"] = Field(default="main",
        description="Dividend to a parent company: main = 35% withholding + notional dividend; alternative; exempt = s.126(b) only")
    advances_paid: Money = Decimal(0)
    advance_rate_pct: Percent | None = Field(default=None, description="Current advance rate on turnover")


# ───────────────────────────── Request / options ─────────────────────────────

class Options(_Base):
    old_62a_mode: Literal["excess_25", "full"] = Field(default="excess_25",
        description="excess_25 = office policy (excess above 25% of turnover); full = statutory 100% attribution")
    reporting_alternative: Literal["attribution", "dividend"] = Field(default="attribution",
        description="s.62A(c2): attribution with expense in company, or 'dividend alternative' (c2)(5)")
    use_2025_average: Literal["auto", "yes", "no"] = "auto"


class CalcRequest(_Base):
    tax_year: int
    individuals: list[IndividualInput] = Field(default_factory=list)
    companies: list[CompanyInput] = Field(default_factory=list)
    options: Options = Field(default_factory=Options)


# ───────────────────────────── Output ─────────────────────────────

class Alert(_Base):
    code: str
    severity: Literal["info", "warning", "critical"]
    entity: str
    message: str
    ref: str = ""


class CompanyResult(_Base):
    id: str
    name: str
    s62a1_applies: bool = False
    s62a1_reason: str = ""
    profitability_rate: Decimal | None = None
    attributed_by_section: dict[str, Decimal] = Field(default_factory=dict)   # 'a_old','a1','a2','a3'
    attributed_to: dict[str, dict[str, Decimal]] = Field(default_factory=dict)  # individual_id -> section -> amount
    taxable_income: Decimal = Decimal(0)
    corporate_tax: Decimal = Decimal(0)
    s81_applies: bool = False
    s81_excess_profits: Decimal = Decimal(0)
    s81_taxable: Decimal = Decimal(0)
    s81_tax: Decimal = Decimal(0)
    s81_exemption: str = ""
    s81_min_dividend_to_avoid: Decimal = Decimal(0)
    dividend_withholding: Decimal = Decimal(0)
    notional_dividend_withholding: Decimal = Decimal(0)
    total_tax: Decimal = Decimal(0)
    advances_paid: Decimal = Decimal(0)
    balance_due: Decimal = Decimal(0)
    suggested_advance_rate_pct: Decimal | None = None


class IndividualResult(_Base):
    id: str
    name: str
    exertion_income: Decimal = Decimal(0)
    passive_bracket_income: Decimal = Decimal(0)
    special_rate_income: dict[str, Decimal] = Field(default_factory=dict)
    taxable_income_total: Decimal = Decimal(0)
    bracket_tax: Decimal = Decimal(0)
    credit_points_value: Decimal = Decimal(0)
    special_rate_tax: Decimal = Decimal(0)
    surtax: Decimal = Decimal(0)
    surtax_capital: Decimal = Decimal(0)
    gross_tax: Decimal = Decimal(0)
    credits_and_prepayments: dict[str, Decimal] = Field(default_factory=dict)
    balance_due: Decimal = Decimal(0)
    nii_employee: Decimal = Decimal(0)
    nii_self_employed: Decimal = Decimal(0)
    nii_passive: Decimal = Decimal(0)
    nii_employer_cost: Decimal = Decimal(0)
    nii_is_estimate: bool = False
    marginal_rate: Decimal = Decimal(0)
    effective_rate: Decimal = Decimal(0)


class ParamRef(_Base):
    path: str
    status: str
    source: str


class CalcResult(_Base):
    tax_year: int
    companies: list[CompanyResult]
    individuals: list[IndividualResult]
    alerts: list[Alert]
    trace: list  # list[Step] serialised
    params_used: list[ParamRef]
    total_tax_burden: Decimal
