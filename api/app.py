"""REST API around the tax engine. Run: uvicorn api.app:app --reload (from repo root)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taxengine import CalcRequest, CalcResult, ValidationError, calculate  # noqa: E402
from taxengine.params import SUPPORTED_YEARS, _load_raw  # noqa: E402
from taxengine.scenarios import ScenarioResult, salary_dividend_scan  # noqa: E402
from taxengine import transitional as tr  # noqa: E402

from api.export import result_to_xlsx  # noqa: E402
from crm.adapter import JsonFileAdapter, summarize  # noqa: E402

DATA = Path(os.environ.get("TAXAPP_DATA", ROOT / "api" / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "taxapp.sqlite3"
crm = JsonFileAdapter(DATA / "crm")

app = FastAPI(title="Tax Engine API", version="0.1.0")


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT, request TEXT, updated TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, client_id TEXT, created TEXT, tax_year INT,"
                " request TEXT, result TEXT)")
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _calc(req: CalcRequest) -> CalcResult:
    try:
        return calculate(req)
    except ValidationError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


# ───────────── reference data ─────────────

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/years")
def years():
    return {"years": list(SUPPORTED_YEARS)}


@app.get("/api/params/{year}")
def params(year: int):
    try:
        return _load_raw(year)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ───────────── calculation ─────────────

class CalcBody(BaseModel):
    request: CalcRequest
    client_id: str | None = None


@app.post("/api/calculate")
def calc(body: CalcBody):
    res = _calc(body.request)
    run_id = uuid.uuid4().hex[:12]
    with closing(db()) as con, con:
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (run_id, body.client_id, now(), body.request.tax_year,
                    body.request.model_dump_json(), res.model_dump_json()))
    return {"run_id": run_id, "result": json.loads(res.model_dump_json())}


@app.get("/api/runs")
def runs(client_id: str | None = None, limit: int = 50):
    with closing(db()) as con:
        q = "SELECT id, client_id, created, tax_year FROM runs"
        args: tuple = ()
        if client_id:
            q += " WHERE client_id = ?"
            args = (client_id,)
        rows = con.execute(q + " ORDER BY created DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    with closing(db()) as con:
        r = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not r:
        raise HTTPException(404, "run not found")
    return {"id": r["id"], "client_id": r["client_id"], "created": r["created"],
            "request": json.loads(r["request"]), "result": json.loads(r["result"])}


@app.post("/api/export/xlsx")
def export_xlsx(body: CalcBody):
    res = _calc(body.request)
    name = body.client_id or "client"
    return Response(result_to_xlsx(res, name),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="tax-{body.request.tax_year}.xlsx"'})


class ScenarioBody(BaseModel):
    request: CalcRequest
    company_id: str
    individual_id: str
    steps: int = 20
    distribute: bool = True


@app.post("/api/scenarios/salary-dividend", response_model=ScenarioResult)
def scenario(body: ScenarioBody):
    try:
        return salary_dividend_scan(body.request, body.company_id, body.individual_id,
                                    steps=max(2, min(body.steps, 50)), distribute=body.distribute)
    except (ValueError, StopIteration) as e:
        raise HTTPException(422, str(e) or "company/individual not found")


# ───────────── temporary provision (2025 liquidation / asset transfer) ─────────────

@app.post("/api/transitional/liquidation", response_model=tr.Out)
def t_liq(body: tr.LiquidationIn):
    return tr.liquidation(body)


@app.post("/api/transitional/asset-transfer", response_model=tr.Out)
def t_asset(body: tr.AssetTransferIn):
    return tr.asset_transfer(body)


@app.post("/api/transitional/later-sale", response_model=tr.Out)
def t_sale(body: tr.LaterSaleIn):
    try:
        return tr.later_sale(body)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ───────────── saved clients ─────────────

class ClientBody(BaseModel):
    name: str
    request: CalcRequest


@app.get("/api/clients")
def list_clients():
    with closing(db()) as con:
        return [dict(r) for r in con.execute("SELECT id, name, updated FROM clients ORDER BY updated DESC")]


@app.get("/api/clients/{cid}")
def get_client(cid: str):
    with closing(db()) as con:
        r = con.execute("SELECT * FROM clients WHERE id = ?", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "client not found")
    return {"id": r["id"], "name": r["name"], "updated": r["updated"], "request": json.loads(r["request"])}


@app.put("/api/clients/{cid}")
def put_client(cid: str, body: ClientBody):
    with closing(db()) as con, con:
        con.execute("INSERT INTO clients VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
                    " request=excluded.request, updated=excluded.updated",
                    (cid, body.name, body.request.model_dump_json(), now()))
    return {"id": cid}


@app.post("/api/clients")
def create_client(body: ClientBody):
    return put_client(uuid.uuid4().hex[:10], body)


@app.delete("/api/clients/{cid}")
def delete_client(cid: str):
    with closing(db()) as con, con:
        con.execute("DELETE FROM clients WHERE id = ?", (cid,))
    return {"deleted": cid}


# ───────────── CRM (test adapter until a CRM is chosen) ─────────────

@app.get("/api/crm/clients")
def crm_clients():
    return {"adapter": crm.name, "clients": crm.list_clients()}


@app.post("/api/crm/clients/{cid}/calculate")
def crm_calculate(cid: str):
    try:
        req = CalcRequest.model_validate(crm.get_client(cid))
    except KeyError:
        raise HTTPException(404, "client not found in CRM")
    res = _calc(req)
    summary = summarize(res)
    crm.push_result(cid, summary)
    return summary


# ───────────── static web app ─────────────

WEB = ROOT / "web" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(WEB / "index.html")
