"""CRM integration boundary.

The engine never talks to a CRM directly. A CRM is plugged in by implementing `CRMAdapter`:
- `list_clients()`       – clients available for calculation
- `get_client(id)`       – map the CRM record to a CalcRequest payload (dict)
- `push_result(id, res)` – write the summary back (e.g. fields / an item update / a note)

`JsonFileAdapter` is the test double used until the real CRM is chosen: each client is a JSON file holding a
CalcRequest payload, and results are written next to it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class CRMAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def list_clients(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_client(self, client_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def push_result(self, client_id: str, summary: dict[str, Any]) -> None: ...


class JsonFileAdapter(CRMAdapter):
    name = "json-file"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, client_id: str) -> Path:
        safe = "".join(ch for ch in client_id if ch.isalnum() or ch in "-_")
        if not safe:
            raise KeyError(client_id)
        return self.root / f"{safe}.json"

    def list_clients(self) -> list[dict[str, Any]]:
        out = []
        for f in sorted(self.root.glob("*.json")):
            if f.name.endswith(".result.json"):
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": f.stem, "name": data.get("name", f.stem)})
        return out

    def get_client(self, client_id: str) -> dict[str, Any]:
        p = self._path(client_id)
        if not p.exists():
            raise KeyError(client_id)
        return json.loads(p.read_text(encoding="utf-8"))["request"]

    def push_result(self, client_id: str, summary: dict[str, Any]) -> None:
        self._path(client_id).with_suffix(".result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def summarize(result) -> dict[str, Any]:
    """Compact summary suitable for CRM fields."""
    return {
        "tax_year": result.tax_year,
        "total_tax_burden": str(result.total_tax_burden),
        "companies": [{"id": c.id, "corporate_tax": str(c.corporate_tax), "s62a1_applies": c.s62a1_applies,
                       "s81_tax": str(c.s81_tax), "balance_due": str(c.balance_due)} for c in result.companies],
        "individuals": [{"id": i.id, "gross_tax": str(i.gross_tax), "balance_due": str(i.balance_due),
                         "marginal_rate": str(i.marginal_rate)} for i in result.individuals],
        "critical_alerts": [a.message for a in result.alerts if a.severity == "critical"],
    }
