"""Decimal helpers. All engine arithmetic uses Decimal; floats are never used."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def D(value) -> Decimal:
    """Convert int/str/Decimal/float to Decimal (floats via str to avoid binary noise)."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def pct(value) -> Decimal:
    """Percent number (e.g. 23) to a rate (0.23)."""
    return D(value) / HUNDRED


def r2(value: Decimal) -> Decimal:
    """Round to agorot (2 decimal places) for presentation."""
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pos(value: Decimal) -> Decimal:
    return value if value > ZERO else ZERO


def fmt(value: Decimal) -> str:
    """Thousands-separated, 2 decimals, for formulas in the trace."""
    v = r2(value)
    if v == v.to_integral_value():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def fmt_rate(rate: Decimal) -> str:
    return f"{(D(rate) * HUNDRED).normalize():f}%"
