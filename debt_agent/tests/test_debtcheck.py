"""Tests on synthetic data with hand-computed expected values (NOT real board data).

As-of date 22/11/2026. Day counts: 01/07→144, 01/09→82, 01/10→52, 10/11→12, 01/11→21, 17/11→5.
"""
from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest
import yaml

from debtcheck.cli import main, run
from debtcheck.normalize import customer_key, parse_amount, parse_date, rows_to_documents
from debtcheck.sources import file as file_src
from debtcheck.sources import monday as monday_src

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 22)


@pytest.fixture
def cfg():
    c = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    c["columns"].update({"customer": "item_name", "doc_type": "סוג מסמך", "amount": "סכום", "date": "תאריך",
                         "doc_number": "מספר מסמך", "status": "סטטוס", "contact": "טלפון"})
    return c


H = ["Name", "סוג מסמך", "מספר מסמך", "תאריך", "סכום", "סטטוס", "טלפון"]
GROUP1 = [
    ["אלפא בע\"מ", "חשבון עסקה", "101", "01/07/2026", "₪10,000.00", "", "050-1111111"],
    ["אלפא בע\"מ", "חשבון עסקה", "102", "01/09/2026", 5000, "", ""],
    ["אלפא בע\"מ", "חשבון עסקה", "103", "2026-11-01", "3,000", "", ""],
    ["אלפא בע\"מ", "חשבונית מס/קבלה", "9001", "05/07/2026", "10000", "", ""],
    ["אלפא בע\"מ", "חשבונית זיכוי", "7001", "10/07/2026", "-500", "", ""],
    ["בטא", "חשבון עסקה", "201", "10/11/2026", "2000", "", ""],
    ["בטא", "חשבונית מס", "9002", "15/11/2026", "2000", "", ""],
]
GROUP2 = [
    ["בטא בעמ", "חשבון עסקה", "202", "01/10/2026", "1000", "", ""],
    ["דלתא", "חשבון עסקה", "301", "01/10/2026", "1000", "", ""],
    ["דלתא", "חשבונית מס", "9003", "02/10/2026", "1500", "", ""],
    ["הדר", "חשבון עסקה", "401", "17/11/2026", "25,000", "", ""],
    ["ורד", "חשבון עסקה", "501", "01/11/2026", "abc", "", ""],          # סכום לא קריא
    ["ורד", "חשבונית פרופורמה", "502", "01/11/2026", "700", "", ""],     # סוג לא מוכר
    ["ורד", "חשבון עסקה", "503", "01/11/2026", "900", "מבוטל", ""],      # מבוטל
    ["ורד", "קבלה", "504", "05/11/2026", "400", "", ""],                 # לא בהגדרת החוב
    ["ורד", "חשבון עסקה", "505", "01/11/2026", "(1,200)", "", ""],       # סכום שלילי בסוגריים
    ["זהב", "חשבון עסקה", "101", "01/11/2026", "300", "", ""],           # מספר כפול (101)
    ["גמא תעשיות", "חשבון עסקה", "601", "", "800", "", ""],              # ללא תאריך
    ["גמא תעשיה", "חשבון עסקה", "602", "01/11/2026", "200", "", ""],
]


def _write_monday_export(path: Path):
    """Mimics monday "Export board to Excel": board title, group title, header per group, blank separators,
    and a subitems block that must be skipped."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["יעל EK-גבייה"])
    ws.append([])
    ws.append(["קבוצה א"])
    ws.append(H)
    for r in GROUP1:
        ws.append(r)
    ws.append(["Subitems", "Name", "Status"])
    ws.append(["", "תת פריט", "חשבון עסקה"])
    ws.append([])
    ws.append(["קבוצה ב"])
    ws.append(H)
    for r in GROUP2:
        ws.append(r)
    wb.save(path)


@pytest.fixture
def result(cfg, tmp_path):
    p = tmp_path / "export.xlsx"
    _write_monday_export(p)
    board, rows = file_src.read_rows(p, cfg)
    assert board == "יעל EK-גבייה"
    balances, issues = run(cfg, rows, as_of=AS_OF)
    return {b.customer_name: b for b in balances}, issues, rows


# ---------- normalisation ----------

@pytest.mark.parametrize("raw,exp", [("₪1,234.50", D("1234.50")), ("(500)", D("-500")), ("1500-", D("-1500")),
                                     ("-1,000", D("-1000")), (" 2 000 ", D("2000")), (1234.5, D("1234.50")),
                                     ("1,234 ש\"ח", D("1234")), ("−1,000", D("-1000")), ("abc", None),
                                     ("", None), ("1.2.3", None)])
def test_parse_amount(raw, exp):
    assert parse_amount(raw) == exp


@pytest.mark.parametrize("raw,exp", [("01/07/2026", date(2026, 7, 1)), ("2026-11-01", date(2026, 11, 1)),
                                     ("1.9.26", date(2026, 9, 1)), ("", None), ("לא תאריך", None)])
def test_parse_date(raw, exp):
    assert parse_date(raw) == exp


def test_customer_key_merges_legal_suffix_and_quotes():
    assert customer_key('בטא בע"מ') == customer_key("בטא בעמ") == customer_key("  בטא ") == customer_key("בטא בע״מ")
    assert customer_key("x", "051-234567") == customer_key("y", "51234567")  # ח.פ. גובר על שם


# ---------- reading the export ----------

def test_export_reader_skips_titles_and_subitems(result):
    _, _, rows = result
    assert len(rows) == len(GROUP1) + len(GROUP2)
    assert {r["__group__"] for r in rows} == {"קבוצה א", "קבוצה ב"}
    assert not any(r["item_name"] == "" for r in rows)


# ---------- the debt formula ----------

def test_alpha_formula_and_fifo_aging(result):
    a = result[0]['אלפא בע"מ']
    # 18,000 − 0 − 10,000 + 500 = 8,500 (הזיכוי רשום -500, נלקח בערך מוחלט ומתווסף)
    assert (a.transactions, a.tax_invoices, a.tax_invoice_receipts, a.credits) == (D(18000), 0, D(10000), D(500))
    assert a.debt == D(8500)
    # FIFO: מאגר הסגירה 10,000−500=9,500 → עסקה 101 נשארת 500, 102 פתוחה 5,000, 103 פתוחה 3,000
    assert [(t.doc_number, r) for t, r in a.open_transactions] == [("101", D(500)), ("102", D(5000)), ("103", D(3000))]
    assert a.aging == {"91-180": D(500), "61-90": D(5000), "0-30": D(3000)}
    assert a.oldest_open_days == 144
    assert a.priority == "דחוף"
    assert a.contact == "050-1111111"


def test_beta_merged_across_spellings_and_fifo_order(result):
    b = result[0]["בטא"]
    assert b.debt == D(1000)          # 3,000 − 2,000
    # החשבונית סוגרת קודם את העסקה הוותיקה (01/10), לכן היתרה הפתוחה היא של 10/11 – 12 ימים
    assert [(t.doc_number, r) for t, r in b.open_transactions] == [("201", D(1000))]
    assert b.oldest_open_days == 12 and b.priority == "מעקב"
    assert any(i.code == "NAME_VARIANTS" for i in result[1])


def test_negative_balance_flagged(result):
    d = result[0]["דלתא"]
    assert d.debt == D(-500) and d.priority == "חריג"


def test_urgent_by_amount(result):
    h = result[0]["הדר"]
    assert h.debt == D(25000) and h.oldest_open_days == 5 and h.priority == "דחוף"


def test_bad_rows_reported_not_counted(result):
    balances, issues, _ = result
    v = balances["ורד"]
    assert v.debt == D(-1200)                 # רק השורה בסוגריים נספרה
    codes = {(i.code, i.customer) for i in issues}
    for code in ("BAD_AMOUNT", "UNKNOWN_TYPE", "CANCELLED", "IGNORED_TYPE", "NEGATIVE_AMOUNT"):
        assert (code, "ורד") in codes, code


def test_duplicate_doc_number(result):
    assert any(i.code == "DUPLICATE_DOC" and "101" in i.message for i in result[1])


def test_no_date_and_similar_names(result):
    balances, issues, _ = result
    g = balances["גמא תעשיות"]
    assert g.debt == D(800) and g.oldest_open_days is None and g.priority == "לטיפול"
    assert g.aging == {"ללא תאריך": D(800)}
    assert any(i.code == "BAD_DATE" for i in issues)
    assert any(i.code == "SIMILAR_NAMES" and "גמא" in i.message for i in issues)


def test_totals_reconcile_to_documents(result):
    """Control: Σ debts == Σ document effects, and Σ aging == debt per customer."""
    balances = result[0]
    for b in balances.values():
        assert sum(d.effect for d in b.documents) == b.debt
        if b.debt > 0:
            assert sum(b.aging.values()) == b.debt, b.customer_name


def test_credit_sign_as_is(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["credit_sign"] = "as_is"
    rows = [{"__ref__": "1", "item_name": "X", "סוג מסמך": "חשבון עסקה", "סכום": "1000", "תאריך": "01/11/2026"},
            {"__ref__": "2", "item_name": "X", "סוג מסמך": "זיכוי", "סכום": "-200", "תאריך": "02/11/2026"}]
    (b,), _ = run(cfg, rows, as_of=AS_OF)
    assert b.debt == D(800)


def test_summary_layout(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["layout"] = "summary"
    rows = [{"__ref__": "1", "item_name": "לקוח", "חשבונות עסקה": "10,000", "חשבוניות מס": "3,000",
             "חשבוניות מס קבלה": "4,000", "זיכויים": "500"}]
    (b,), issues = run(cfg, rows, as_of=AS_OF)
    assert b.debt == D(3500) and b.priority == "לטיפול"   # ללא תאריכים → אין גיול


# ---------- monday API source ----------

def test_monday_pagination_and_formula_columns(cfg):
    calls = []

    def transport(payload):
        calls.append(payload)
        cv = lambda t, amt: [{"id": "type", "text": t, "type": "status"},
                             {"id": "sum", "text": "", "display_value": amt, "type": "formula"},
                             {"id": "date4", "text": "2026-11-01", "type": "date"}]
        if "next_items_page" in payload["query"]:
            return {"data": {"next_items_page": {"cursor": None, "items": [
                {"id": "3", "name": "לקוח א", "group": {"title": "g"}, "column_values": cv("חשבונית מס", "400")}]}}}
        return {"data": {"boards": [{"name": "יעל EK-גבייה", "columns": [
            {"id": "type", "title": "סוג מסמך"}, {"id": "sum", "title": "סכום"}, {"id": "date4", "title": "תאריך"}],
            "items_page": {"cursor": "abc", "items": [
                {"id": "1", "name": "לקוח א", "group": {"title": "g"}, "column_values": cv("חשבון עסקה", "1000")},
                {"id": "2", "name": "לקוח א", "group": {"title": "g"}, "column_values": cv("זיכוי", "100")}]}}]}}

    client = monday_src.MondayClient(transport=transport)
    board, rows = monday_src.fetch_rows({"source": {"board_id": "123", "page_size": 2}}, client)
    assert board == "יעל EK-גבייה" and len(rows) == 3 and len(calls) == 2
    assert calls[1]["variables"]["cursor"] == "abc"
    (b,), _ = run(cfg, rows, as_of=AS_OF)
    assert b.debt == D(700)   # 1,000 − 400 + 100


def test_monday_retries_on_complexity(monkeypatch):
    monkeypatch.setattr(monday_src.time, "sleep", lambda s: None)
    seq = [{"errors": [{"message": "ComplexityException"}]}, {"data": {"ok": 1}}]
    c = monday_src.MondayClient(transport=lambda p: seq.pop(0))
    assert c.query("q", {}) == {"ok": 1}


# ---------- end to end ----------

def test_cli_end_to_end(cfg, tmp_path, capsys):
    exp = tmp_path / "export.xlsx"
    _write_monday_export(exp)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "report.xlsx"
    assert main(["run", "--config", str(cfg_path), "--file", str(exp), "--out", str(out),
                 "--as-of", "2026-11-22"]) == 0
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["למי לפנות", "פירוק חוב", "חשבונות עסקה פתוחים", "מסמכים", "בעיות נתונים", "פרטי הרצה"]
    first = [r for r in wb["למי לפנות"].iter_rows(min_row=2, values_only=True)]
    assert first[0][0] == "דחוף" and {first[0][1], first[1][1]} == {"הדר", 'אלפא בע"מ'}
    assert main(["run", "--config", str(cfg_path), "--file", str(exp), "--customer", "אלפא",
                 "--as-of", "2026-11-22"]) == 0
    assert "8,500.00" in capsys.readouterr().out


def test_random_scale_cross_check(cfg):
    """1,000 customers × ~20 docs: debt equals an independent recomputation, aging always sums to the debt,
    and the run is fast enough for the full board."""
    import random
    import time
    from collections import defaultdict
    rnd = random.Random(7)
    labels = {"חשבון עסקה": 1, "חשבונית מס": -1, "חשבונית מס קבלה": -1, "זיכוי": 1}
    rows, expected = [], defaultdict(D)
    for c in range(1000):
        for j in range(rnd.randint(1, 40)):
            lab = rnd.choice(list(labels))
            amt = D(rnd.randint(1, 5_000_000)) / 100
            raw = -amt if lab == "זיכוי" and rnd.random() < .5 else amt
            rows.append({"__ref__": f"{c}-{j}", "item_name": f"לקוח {c:04d}", "סוג מסמך": lab,
                         "סכום": f"{raw:,.2f}", "תאריך": f"{rnd.randint(1, 28):02d}/{rnd.randint(1, 11):02d}/2026"})
            expected[f"לקוח {c:04d}"] += labels[lab] * amt
    t = time.perf_counter()
    balances, issues = run(cfg, rows, as_of=AS_OF)
    elapsed = time.perf_counter() - t
    assert len(balances) == 1000
    for b in balances:
        assert b.debt == expected[b.customer_name]
        if b.debt > 0:
            assert sum(b.aging.values()) == b.debt
    assert not any(i.code == "SIMILAR_NAMES" for i in issues)   # שמות שנבדלים רק במספר – לקוחות שונים
    assert elapsed < 3, elapsed
