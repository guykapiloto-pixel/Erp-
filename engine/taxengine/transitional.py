"""Temporary provision – s.6 of the Economic Efficiency Law (taxation of undistributed profits), 5785-2024
(LAW-3343), and Income Tax & Real Estate Circular 03/2025.

A few-company could start liquidation in 2025, or (asset-transfer track) transfer assets to a material shareholder
by 30.11.2025, with tax deferral and no purchase tax. The window has closed; these calculators serve
(a) checking what was reported for 2025 and (b) the later sale of a transferred asset, which is taxed under a
linear split for years to come.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from .money import ZERO, D, fmt, fmt_rate, pos, r2
from .params import load_params

REF = "ס' 6 לחוק ההתייעלות (מיסוי רווחים לא מחולקים) התשפ\"ה-2024; חוזר 03/2025"
TOP_RATE = Decimal("0.47")


class Step(BaseModel):
    label: str
    formula: str = ""
    value: Decimal | str
    ref: str = ""


class Out(BaseModel):
    steps: list[Step]
    totals: dict[str, Decimal]
    notes: list[str] = Field(default_factory=list)


def _div_rate(material: bool, year: int = 2025) -> Decimal:
    p = load_params(year)
    return p.rate("income_tax.dividend_rate_material" if material else "income_tax.dividend_rate")


# ───────────── liquidation track ─────────────

class LiquidationIn(BaseModel):
    distributable_profits: Decimal = Field(description="Company 'profits fit for distribution' (s.94B), from incorporation")
    holding_pct: Decimal = Field(description="Holder's share %")
    value_transferred: Decimal = Field(description="Market value of assets transferred to this holder")
    material: bool = True
    company_cost_of_assets: Decimal | None = Field(default=None, description="Cost basis option 1: company's depreciated cost (total)")
    holder_share_cost: Decimal | None = Field(default=None, description="Cost basis option 2: holder's cost of the shares")


def liquidation(i: LiquidationIn) -> Out:
    steps: list[Step] = []
    h = i.holding_pct / 100
    profits_share = i.distributable_profits * h
    dividend = min(i.value_transferred, pos(profits_share))
    rate = _div_rate(i.material)
    tax = dividend * rate
    deferred = pos(i.value_transferred - dividend)
    steps += [
        Step(label="חלק בעל המניות ברווחים הראויים לחלוקה", formula=f"{fmt(i.distributable_profits)} × {fmt_rate(h)}", value=r2(profits_share), ref="ס' 94ב"),
        Step(label="הכנסת דיבידנד במועד ההעברה (ס' 2(4))", formula=f"min(שווי מועבר {fmt(i.value_transferred)}; {fmt(profits_share)})", value=r2(dividend), ref=REF),
        Step(label="מס דיבידנד", formula=f"{fmt(dividend)} × {fmt_rate(rate)} (+ מס יסף לפי הכנסת היחיד)", value=r2(tax), ref="ס' 125ב"),
        Step(label="שווי שמיסויו נדחה עד המימוש", formula=f"{fmt(i.value_transferred)} − {fmt(dividend)}", value=r2(deferred), ref=REF),
    ]
    totals = {"dividend_income": r2(dividend), "dividend_tax": r2(tax), "deferred_value": r2(deferred)}
    if i.company_cost_of_assets is not None:
        c1 = i.company_cost_of_assets * h
        steps.append(Step(label="יתרת מחיר מקורי – חלופה 1 (עלות החברה × שיעור החזקה)", formula=f"{fmt(i.company_cost_of_assets)} × {fmt_rate(h)}", value=r2(c1), ref="חוזר 03/2025"))
        totals["cost_basis_option1"] = r2(c1)
    if i.holder_share_cost is not None:
        steps.append(Step(label="יתרת מחיר מקורי – חלופה 2 (עלות המניות, מחולקת לפי שווי הנכסים)", formula=f"{fmt(i.holder_share_cost)} × שווי נכס / שווי כולל", value=r2(i.holder_share_cost), ref="חוזר 03/2025"))
        totals["cost_basis_option2_total"] = r2(i.holder_share_cost)
    return Out(steps=steps, totals=totals, notes=[
        "הבחירה בין חלופות יתרת המחיר המקורי אחידה לכל הנכסים ולכל בעלי המניות.",
        "רווחים עד המועד הקבוע בס' 94ב(א)(2) ממוסים בשיעור שבאותו סעיף – יש לפצל ידנית אם רלוונטי.",
    ])


# ───────────── asset-transfer track ─────────────

class AssetTransferIn(BaseModel):
    depreciated_cost: Decimal = Field(description="Asset depreciated cost / remaining original price at transfer")
    secured_bank_loan: Decimal = Decimal(0)
    distributable_profits: Decimal
    shareholder_credit_balance: Decimal = Field(default=Decimal(0), description="Specific shareholder credit balance that funded the asset (to 31.12.2024)")
    material: bool = True
    accumulated_profits_2024: Decimal | None = Field(default=None, description="For the 5% check of the 2025 s.81B exemption")


def asset_transfer(i: AssetTransferIn) -> Out:
    base = pos(i.depreciated_cost - i.secured_bank_loan)
    dividend = min(base, pos(i.distributable_profits))
    excess = base - dividend
    offset = min(excess, i.shareholder_credit_balance)
    top = excess - offset
    rate = _div_rate(i.material)
    tax = dividend * rate + top * TOP_RATE
    steps = [
        Step(label="בסיס ההכנסה (ס' 2(4))", formula=f"עלות מופחתת {fmt(i.depreciated_cost)} − הלוואה מובטחת {fmt(i.secured_bank_loan)}", value=r2(base), ref="ס' 6(ג) להוראת השעה"),
        Step(label="דיבידנד – עד הרווחים הראויים לחלוקה", formula=f"min({fmt(base)}; {fmt(i.distributable_profits)})", value=r2(dividend), ref=REF),
        Step(label="קיזוז יתרת זכות ספציפית של בעל המניות", formula=f"min({fmt(excess)}; {fmt(i.shareholder_credit_balance)})", value=r2(offset), ref="חוזר 03/2025"),
        Step(label="יתרה בשיעור המס השולי המרבי", formula=f"{fmt(excess)} − {fmt(offset)}", value=r2(top), ref="ס' 121"),
        Step(label="מס במועד ההעברה", formula=f"{fmt(dividend)} × {fmt_rate(rate)} + {fmt(top)} × 47%", value=r2(tax), ref=REF),
    ]
    totals = {"dividend": r2(dividend), "offset": r2(offset), "top_rate_income": r2(top), "tax": r2(tax)}
    notes = ["מס יסף (3% + 2% הוני) מחושב ברמת היחיד בנוסף."]
    if i.accumulated_profits_2024:
        ok = dividend >= Decimal("0.05") * i.accumulated_profits_2024
        steps.append(Step(label="פטור מתוספת 81ב לשנת 2025 (דיבידנד ≥ 5% מהרווחים הנצברים לסוף 2024)",
                          formula=f"{fmt(dividend)} ≥ 5% × {fmt(i.accumulated_profits_2024)}", value="כן" if ok else "לא", ref="חוזר 03/2025"))
    return Out(steps=steps, totals=totals, notes=notes)


# ───────────── later sale of a transferred asset ─────────────

class LaterSaleIn(BaseModel):
    real_gain: Decimal = Field(description="Real capital gain / real betterment (after inflationary amount)")
    acquisition_date: date
    transfer_date: date = Field(description="Transfer date / liquidation start date")
    sale_date: date
    material: bool = False
    real_estate: bool = False
    inventory: bool = False


def later_sale(i: LaterSaleIn) -> Out:
    if not (i.acquisition_date <= i.transfer_date < i.sale_date):
        raise ValueError("Dates must satisfy acquisition <= transfer < sale")
    if i.inventory:
        return Out(steps=[Step(label="מלאי – כל הרווח בשיעור מס שולי (ללא פיצול)", value=r2(i.real_gain), ref="חוזר 03/2025")],
                   totals={"marginal_rate_income": r2(i.real_gain)}, notes=["המס מחושב במדרגות ס' 121 ברמת היחיד."])
    total_days = D((i.sale_date - i.acquisition_date).days)
    pre_days = D((i.transfer_date - i.acquisition_date).days)
    post_days = D((i.sale_date - i.transfer_date).days)
    pre = i.real_gain * pre_days / total_days
    post = i.real_gain - pre
    post_rate = Decimal("0.25") if i.real_estate else (Decimal("0.30") if i.material else Decimal("0.25"))
    tax_pre, tax_post = pre * TOP_RATE, pos(post) * post_rate
    steps = [
        Step(label="רווח עד מועד ההעברה (לינארי)", formula=f"{fmt(i.real_gain)} × {pre_days} / {total_days} ימים", value=r2(pre), ref=REF),
        Step(label="מס על החלק שעד ההעברה – שיעור שולי מרבי, ללא קיזוז הפסדים", formula=f"{fmt(pre)} × 47%", value=r2(tax_pre), ref="ס' 121"),
        Step(label="רווח לאחר ההעברה", formula=f"{fmt(i.real_gain)} × {post_days} / {total_days} ימים", value=r2(post), ref=REF),
        Step(label="מס על החלק שלאחר ההעברה", formula=f"{fmt(post)} × {fmt_rate(post_rate)}", value=r2(tax_post),
             ref="ס' 48א לחוק מיסוי מקרקעין" if i.real_estate else "ס' 91"),
        Step(label="סה\"כ מס (לפני מס יסף)", formula=f"{fmt(tax_pre)} + {fmt(tax_post)}", value=r2(tax_pre + tax_post)),
    ]
    return Out(steps=steps, totals={"pre_transfer_gain": r2(pre), "post_transfer_gain": r2(post), "tax": r2(tax_pre + tax_post)},
               notes=["הפיצולים הלינאריים הרגילים (91(ב1), 48א(ב1)/(ב2)) אינם חלים; פטורי דירת מגורים (פרק חמישי 1) אינם חלים.",
                      "דיווח: סמל עסקה 77 קוד 09 (מקרקעין: 50 קוד 09); דיווח ותשלום תוך 30 יום.",
                      "מס יסף 3% + 2% (הוני) מחושב ברמת היחיד."])
