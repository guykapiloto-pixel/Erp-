"""Mutable state shared by the pipeline stages for a single calculation run."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Alert, CalcRequest, CompanyInput, IndividualInput
from .money import ZERO
from .params import Params
from .trace import Trace


@dataclass
class IncomeBuckets:
    """Income flowing to an individual from modelled companies (added to their own inputs)."""
    salary_from_companies: Decimal = ZERO
    salary_controlling: Decimal = ZERO     # part paid to a controlling shareholder of a few-company (BL rates differ)
    notional_65_used: Decimal = ZERO
    attributed: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))  # section -> amount
    dividends_regular: Decimal = ZERO      # 25%
    dividends_material: Decimal = ZERO     # 30%
    dividends_62a3: Decimal = ZERO         # 25% by law
    notional_dividends_regular: Decimal = ZERO
    notional_dividends_material: Decimal = ZERO
    dividend_withholding: Decimal = ZERO
    notional_withholding: Decimal = ZERO
    corp_tax_credit_62a: Decimal = ZERO    # dividend alternative - corporate tax offset
    dividend_alt_income: Decimal = ZERO    # amount reported in field 084 (subject to 23% cap)


@dataclass
class Ctx:
    req: CalcRequest
    p: Params
    trace: Trace = field(default_factory=Trace)
    alerts: list[Alert] = field(default_factory=list)
    buckets: dict[str, IncomeBuckets] = field(default_factory=lambda: defaultdict(IncomeBuckets))
    # dividends flowing into parent companies: parent_id -> list of (source_company_id, amount, withheld_35)
    intercompany_dividends: dict[str, list[tuple[str, Decimal, Decimal]]] = field(default_factory=lambda: defaultdict(list))

    @property
    def year(self) -> int:
        return self.req.tax_year

    def individual(self, iid: str) -> IndividualInput | None:
        return next((i for i in self.req.individuals if i.id == iid), None)

    def company(self, cid: str) -> CompanyInput | None:
        return next((c for c in self.req.companies if c.id == cid), None)

    def alert(self, code: str, severity: str, entity: str, message: str, ref: str = "") -> None:
        self.alerts.append(Alert(code=code, severity=severity, entity=entity, message=message, ref=ref))
