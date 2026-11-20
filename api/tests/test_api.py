import os, tempfile
os.environ["TAXAPP_DATA"] = tempfile.mkdtemp()
from fastapi.testclient import TestClient
from api.app import app

c = TestClient(app)
REQ = {"tax_year": 2025, "individuals": [{"id": "A"}], "companies": [{"id": "C",
       "shareholders": [{"individual_id": "A", "profit_rights_pct": 100}], "effort_revenue": 1000,
       "effort_expenses": 400, "accumulated_profits_prev": 800000}]}

def test_calculate_and_history():
    r = c.post("/api/calculate", json={"request": REQ, "client_id": "x"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["companies"][0]["attributed_by_section"]["a1"] == "350.00"
    assert c.get(f"/api/runs/{body['run_id']}").status_code == 200
    assert len(c.get("/api/runs", params={"client_id": "x"}).json()) == 1

def test_validation_422():
    bad = {**REQ, "companies": [{"id": "C", "shareholders": [{"individual_id": "Z", "profit_rights_pct": 100}]}]}
    assert c.post("/api/calculate", json={"request": bad}).status_code == 422

def test_clients_crud_and_xlsx():
    cid = c.post("/api/clients", json={"name": "לקוח", "request": REQ}).json()["id"]
    assert c.get(f"/api/clients/{cid}").json()["name"] == "לקוח"
    x = c.post("/api/export/xlsx", json={"request": REQ})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    c.delete(f"/api/clients/{cid}")
    assert c.get(f"/api/clients/{cid}").status_code == 404

def test_scenario():
    r = c.post("/api/scenarios/salary-dividend", json={"request": REQ, "company_id": "C", "individual_id": "A", "steps": 4})
    assert r.status_code == 200 and len(r.json()["points"]) == 5

def test_transitional_endpoints():
    r = c.post("/api/transitional/asset-transfer", json={"depreciated_cost": 100, "distributable_profits": 50, "shareholder_credit_balance": 20})
    assert r.status_code == 200 and r.json()["totals"]["top_rate_income"] == "30.00"
    r = c.post("/api/transitional/later-sale", json={"real_gain": 1000, "acquisition_date": "2026-01-01", "transfer_date": "2025-01-01", "sale_date": "2027-01-01"})
    assert r.status_code == 422
