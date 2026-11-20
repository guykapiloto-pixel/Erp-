"""Calculation trace: every number the engine produces is recorded with its formula and legal source."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from .money import r2


class Step(BaseModel):
    entity: str                      # e.g. "company:C1" / "individual:I1"
    stage: str                       # pipeline stage, e.g. "s62a1"
    key: str                         # machine key, e.g. "attributed_income"
    label: str                       # Hebrew label shown to the user
    formula: str = ""                # human-readable formula with substituted values
    value: Decimal | str | bool | None = None
    ref: str = ""                    # legal / circular reference
    note: str = ""


class Trace(BaseModel):
    steps: list[Step] = Field(default_factory=list)

    def add(self, entity: str, stage: str, key: str, label: str, value: Any = None,
            formula: str = "", ref: str = "", note: str = "") -> Any:
        v = r2(value) if isinstance(value, Decimal) else value
        self.steps.append(Step(entity=entity, stage=stage, key=key, label=label, formula=formula,
                               value=v, ref=ref, note=note))
        return value

    def for_entity(self, entity: str) -> list[Step]:
        return [s for s in self.steps if s.entity == entity]
