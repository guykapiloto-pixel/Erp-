"""Year-versioned tax parameters. Values live in YAML, never in code.

Each access is recorded so the engine can flag results that depend on unverified values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..money import D

_DIR = Path(__file__).parent
SUPPORTED_YEARS = (2025, 2026)


@dataclass
class ParamUse:
    path: str
    status: str
    source: str


@dataclass
class Params:
    year: int
    raw: dict
    used: dict[str, ParamUse] = field(default_factory=dict)

    def _leaf(self, path: str) -> dict:
        node: Any = self.raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Missing tax parameter '{path}' for {self.year}")
            node = node[part]
        if not isinstance(node, dict) or "value" not in node:
            raise KeyError(f"Parameter '{path}' is not a leaf")
        self.used[path] = ParamUse(path, node.get("status", "unverified"), node.get("source", ""))
        return node

    def raw_value(self, path: str) -> Any:
        return self._leaf(path)["value"]

    def num(self, path: str) -> Decimal:
        return D(self.raw_value(path))

    def rate(self, path: str) -> Decimal:
        """Percent parameter as a rate (23 -> 0.23)."""
        return self.num(path) / Decimal(100)

    def rates(self, path: str) -> dict[str, Decimal]:
        return {k: D(v) / Decimal(100) for k, v in self.raw_value(path).items()}

    def brackets(self) -> list[tuple[Decimal | None, Decimal]]:
        return [(None if b["upper"] is None else D(b["upper"]), D(b["rate"]) / Decimal(100))
                for b in self.raw_value("income_tax.brackets")]

    def unverified_used(self) -> list[ParamUse]:
        return [u for u in self.used.values() if u.status != "verified"]


@lru_cache(maxsize=None)
def _load_raw(year: int) -> dict:
    path = _DIR / f"{year}.yaml"
    if not path.exists():
        raise ValueError(f"Tax year {year} is not supported (supported: {SUPPORTED_YEARS})")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_params(year: int) -> Params:
    """Fresh Params object per calculation (usage tracking is per run)."""
    return Params(year=year, raw=_load_raw(year))
