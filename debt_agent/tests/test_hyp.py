"""Hyp collections analysis – synthetic Hyp CSV + board snapshot, expected values computed by hand.

Snapshot 19/11/2026, as-of 23/11/2026.
  אלפא (h1): T1001 10,000 (1/3) paid by IR4001; T1002 5,000 (1/6) open.  Formula 15,000−10,000 = 5,000 = Hyp → gap 0.
             oldest 175 days, net 5,000 ≥ urgent_min → דחוף. Last payment 10/03/2026 → no-payment reason.
  בטא (h2, auto charge): T1003 12,000 annual, closed manually; IR 1,000 ×2; T1004 1,000 open (13 days).
             Formula 13,000−2,000 = 11,000, Hyp 1,000 → gap +10,000. Auto + young doc → חיוב אוטומטי.
  גמא (h3): T1005 2,360 open (1/8); IR4004 2,360 on 1/9 → possibly paid → net 0 → לבדיקה.
             R8001 500 then R8002 −500 → reversal pair.
  דלתא (not in board, ח.פ 44444444): T1006 3,000 open, listed on the board under id 0 with the name "גמא" →
             attributed by the document to דלתא, 53 days, net 3,000 → לטיפול.
  אפסילון (h4): T1007 4,000 open (1/10); IR4006 1,500 issued 21/11 (after snapshot) → net 2,500, paying → לבדיקה.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal as D

import pytest

from debtcheck import hyp

HEAD = ["מספר מסמך", "סוג מסמך", "תאריך הפקה", "תאריך מסמך", "שם לקוח", "ת.ז/ ח.פ של הלקוח", "אימייל לקוח",
        "טלפון לקוח", "סכום", "סכום המע\"מ", "סכום ללא מע\"מ", "נוצר על ידי", "סה\"כ", "כ.אשראי", "הערה למסמך"]
DOCS = [
    ("1001", hyp.T, "01/03/2026", "אלפא בע\"מ", "511111111", "10000"),
    ("4001", hyp.IR, "10/03/2026", "אלפא בע\"מ", "511111111", "10000"),
    ("1002", hyp.T, "01/06/2026", "אלפא בע\"מ", "511111111", "5000"),
    ("1003", hyp.T, "01/01/2026", "בטא", "022222222", "12000"),
    ("4002", hyp.IR, "15/10/2026", "בטא", "022222222", "1000"),
    ("4003", hyp.IR, "05/11/2026", "בטא", "022222222", "1000"),
    ("1004", hyp.T, "10/11/2026", "בטא", "022222222", "1000"),
    ("1005", hyp.T, "01/08/2026", "גמא", "033333333", "2360"),
    ("4004", hyp.IR, "01/09/2026", "גמא", "033333333", "2360"),
    ("8001", hyp.R, "05/09/2026", "גמא", "033333333", "500"),
    ("8002", hyp.R, "06/09/2026", "גמא", "033333333", '"-500"'),
    ("1006", hyp.T, "01/10/2026", "דלתא", "44444444", "3000"),
    ("1007", hyp.T, "01/10/2026", "אפסילון", "55555555", "4000"),
    ("4006", hyp.IR, "21/11/2026", "אפסילון", "55555555", "1500"),
    # --- ספירה כפולה והעבודה של יעל ---
    ("1008", hyp.T, "01/09/2026", "זטא", "66666666", "6000"),      # חשבון עסקה נשאר פתוח...
    ("5001", hyp.I, "05/09/2026", "זטא", "66666666", "6000"),      # ...אף שהופקה חשבונית מס נפרדת → לא חוב
    ("1009", hyp.T, "01/09/2026", "חת", "77777777", "3000"),       # יעל בדקה: תקין
    ("1010", hyp.T, "01/11/2026", "טת", "88888888", "2000"),       # חיוב קבוע שנכשל
    ("1011", hyp.T, "01/10/2026", "יוד", "99999999", "8000"),      # שיק דחוי 3,000 + ממתין לגיא
    ("5002", hyp.I, "01/10/2026", "כף", "10101010", "4000"),       # חשבונית מס פתוחה ב-Hyp – לאימות
]


@pytest.fixture
def setup(tmp_path):
    p = tmp_path / "report.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        for num, typ, dt, name, crn, total in DOCS:
            amt = total.strip('"')
            bv, vat = (str(round(float(amt) / 1.18, 2)), str(round(float(amt) - float(amt) / 1.18, 2))) \
                if typ != hyp.R else ("", "")
            w.writerow([num, typ, dt, dt, name, crn, "", "050", bv, vat, "0" if bv else "", "UI", total,
                        amt if typ in (hyp.IR, hyp.R) else "", ""])
    b = tmp_path / "board"
    (b / "hyp").mkdir(parents=True)
    (b / "custList").mkdir()
    (b / "cfile").mkdir()
    (b / "contacts").mkdir()
    for d in ("checks", "failed", "cheques", "clients"):
        (b / d).mkdir()
    snap = "2026-11-19T14:00:00+02:00"
    custs = [{"h": 1, "n": "אלפא בע\"מ", "crn": "511111111", "ph": "03-1"}, {"h": 2, "n": "בטא", "crn": "22222222"},
             {"h": 3, "n": "גמא", "crn": "33333333"}, {"h": 4, "n": "אפסילון", "crn": "55555555"},
             {"h": 5, "n": "זטא", "crn": "66666666"}, {"h": 6, "n": "חת", "crn": "77777777"},
             {"h": 7, "n": "טת", "crn": "88888888"}, {"h": 8, "n": "יוד", "crn": "99999999"},
             {"h": 9, "n": "כף", "crn": "10101010"}]
    od = [[1, [["2026-06-01", 1002, 300, 5000, 5000, "x/1002", "", 4237.29, 762.71]]],
          [2, [["2026-11-10", 1004, 300, 1000, 1000, "", "", 847.46, 152.54]]],
          [3, [["2026-08-01", 1005, 300, 2360, 2360, "", "", 2000, 360]]],
          [0, [["2026-10-01", 1006, 300, 3000, 3000, "", "", 2542.37, 457.63]]],
          [4, [["2026-10-01", 1007, 300, 4000, 4000, "", "", 3389.83, 610.17]]],
          [5, [["2026-09-01", 1008, 300, 6000, 6000, "", "", 5084.75, 915.25]]],
          [6, [["2026-09-01", 1009, 300, 3000, 3000, "", "", 2542.37, 457.63]]],
          [7, [["2026-11-01", 1010, 300, 2000, 2000, "", "", 1694.92, 305.08]]],
          [8, [["2026-10-01", 1011, 300, 8000, 8000, "", "", 6779.66, 1220.34]]],
          [9, [["2026-10-01", 5002, 305, 4000, 4000, "", "", 3389.83, 610.17]]]]
    files = {
        "hyp/opendocs.json": {"asOf": snap, "base": "https://s3/", "rows": od},
        "hyp/open.json": {"asOf": snap, "total": 38360, "rows": [[1, "אלפא בע\"מ", 5000], [2, "בטא", 1000],
                                                                 [3, "גמא", 2360], [0, "גמא", 3000],
                                                                 [4, "אפסילון", 4000], [5, "זטא", 6000], [6, "חת", 3000],
                                                                 [7, "טת", 2000], [8, "יוד", 8000], [9, "כף", 4000]]},
        "hyp/auto.json": {"asOf": snap, "ids": [2, 7]},
        "checks/hx.json": {"name": "חת", "status": "ok", "note": "חשבונית לדוח שטרם הוגש"},
        "failed/c8.json": {"hypId": 7, "name": "טת", "lastFail": "2026-11-10", "status": "open", "fails": [{"date": "2026-11-10"}]},
        "cheques/q1.json": {"hypId": 8, "client": "יוד", "amount": 3000, "status": "pending", "dueDate": "2026-12-10"},
        "cfile/h8.json": {"hypId": 8, "name": "יוד", "review": "גיא קפילוטו", "demanded": 8000},
        "clients/x1.json": {"hypId": 8, "name": "יוד", "cat": "problem", "status": "open", "note": "לא עונה"},
        "hyp/bk.json": {"asOf": snap, "rows": [[1, "30001"]]},
        "custList/meta.json": {"chunks": 1, "count": 9},
        "cfile/h1.json": {"hypId": 1, "nextContact": "2026-11-25", "lastContact": "2026-11-18", "lastNote": "הבטיח לשלם"},
        "contacts/h1_2026-11-20_x.json": {"hypId": 1, "date": "2026-11-20", "channel": "טלפון"},
        "hyp/pay.json": {"asOf": snap, "rows": [[3, [["2026-09-01", 2360, 4004]]], [4, [["2026-11-18", 700, 4010]]]]},
        "custList/c0.json": {"rows": custs},
    }
    for k, v in files.items():
        (b / k).write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    cfg = {"alerts": {"min_debt": 1, "urgent_amount": 20000, "urgent_min_amount": 5000, "urgent_days": 90,
                      "followup_days": 30, "auto_charge_grace_days": 45, "recent_payment_days": 60,
                      "no_payment_days": 120, "formula_gap_tolerance": 100}}
    docs, issues = hyp.load_hyp_csv(p)
    board = hyp.load_board(b)
    custs_, more, summary = hyp.analyze(docs, board, cfg, date(2026, 11, 23))
    return {c.name: c for c in custs_}, issues + more, summary, docs, board, cfg


def test_loads_all_rows_including_quoted_negative(setup):
    _, issues, _, docs = setup[:4]
    assert len(docs) == len(DOCS)
    assert not [i for i in issues if i.code == "BAD_ROW"]
    assert [d.total for d in docs if d.num == "8002"] == [D("-500")]


def test_totals_reconcile(setup):
    c, issues, s = setup[:3]
    assert s["open_total"] == D(38360) == s["board_total"]
    assert not [i for i in issues if i.code == "BOARD_TOTAL_DIFF"]


def test_alpha(setup):
    a = setup[0]['אלפא בע"מ']
    assert a.formula == D(5000) and a.open_debt == D(5000) and a.gap == 0
    assert a.oldest_days == 175 and a.net_to_collect == D(5000) and a.priority == "דחוף"
    assert a.bk == "30001" and a.phone == "03-1"
    assert any("תשלום אחרון לפני 258 ימים" in r for r in a.reasons)


def test_beta_auto_and_gap(setup):
    b = setup[0]["בטא"]
    assert b.formula == D(11000) and b.open_debt == D(1000) and b.gap == D(10000)
    assert b.closed_tx == D(12000) and b.priority == "חיוב קבוע"


def test_gamma_possibly_paid_and_reversal(setup):
    g = setup[0]["גמא"]
    assert g.possibly_paid == D(2360) and g.net_to_collect == 0 and g.priority == "לסגירה ב-Hyp"
    assert g.double_counted == D(2360)
    assert g.open_docs[0].possibly_paid_by.num == "4004"
    assert len(g.reversals) == 1 and g.reversals[0][0].num == "8001"
    assert g.last_payment.num == "4004"     # הקבלה שבוטלה אינה "תשלום אחרון"


def test_orphan_open_doc_attributed_by_document(setup):
    c, issues = setup[:2]
    d = c["דלתא"]
    assert d.open_debt == D(3000) and d.hyp_id is None and d.priority == "לטיפול"
    assert c["גמא"].open_debt == D(2360)    # לא קיבל את המסמך של דלתא למרות השם בלוח
    assert any(i.code == "OPEN_WITHOUT_CUSTOMER" and "דלתא" in i.message for i in issues)
    assert any(i.code == "NOT_IN_BOARD" and i.customer == "דלתא" for i in issues)


def test_payment_after_snapshot(setup):
    e = setup[0]["אפסילון"]
    # 4010 (700) קיים רק בלוח ונכנס להיסטוריה; 4006 מ-21/11 אחרי תמונת הלוח – לא בנוסחה
    assert e.formula == D(3300)
    # חוב = min(פתוח 4,000, נוסחה 3,300) − 1,500 שהתקבלו אחרי עדכון הלוח = 1,800
    assert e.double_counted == D(700)
    assert e.paid_after_snapshot == D(1500) and e.net_to_collect == D(1800) and e.priority == "לטיפול"


def test_report_writes(setup, tmp_path):
    import openpyxl
    from debtcheck import hyp_report
    c, issues, s = setup[:3]
    out = hyp_report.write(tmp_path / "r.xlsx", list(c.values()), issues, s)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["רשימת השבוע", "סיכום", "למי לפנות", "פירוק חוב", "נספר כפול", "מסמכים פתוחים",
                             "בעיות נתונים", "שיטה"]
    names = [r[3] for r in wb["למי לפנות"].iter_rows(min_row=2, values_only=True)]
    assert names[0] == 'אלפא בע"מ'
    week = [r[2] for r in wb["רשימת השבוע"].iter_rows(min_row=3, values_only=True)]
    # היום: דלתא, טת, אפסילון (לא תועדה פנייה); אלפא – 25/11 כפי שיעל קבעה בלוח
    assert set(week[:3]) == {"דלתא", "טת", "אפסילון"} and week[3] == 'אלפא בע"מ' and len(week) == 4


def test_when_to_contact(setup):
    c = setup[0]
    a, d = c['אלפא בע"מ'], c["דלתא"]
    assert a.last_contact == date(2026, 11, 20) and a.next_contact == date(2026, 11, 25)
    assert a.contact_on == date(2026, 11, 25) and a.when.startswith("25/11/2026 (מועד שנקבע בלוח")
    assert d.contact_on == date(2026, 11, 23) and d.when.startswith("היום (לא תועדה פנייה")
    assert c["גמא"].contact_on is None and "לא לפנות ללקוח" in c["גמא"].when
    assert hyp.week_end(date(2026, 11, 23)) == date(2026, 11, 26)
    assert hyp.next_workday(date(2026, 11, 27), set()) == date(2026, 11, 29)   # שישי → ראשון


def test_cadence_from_last_contact():
    cu = hyp.Customer("h:9", 9, "x", priority="דחוף", action="פנייה ללקוח", last_contact=date(2026, 11, 10))
    hyp._schedule(cu, {}, date(2026, 11, 23))
    assert cu.contact_on == date(2026, 11, 23)          # 10/11 + 7 = 17/11 כבר עבר → היום
    cu = hyp.Customer("h:9", 9, "x", priority="לטיפול", action="פנייה ללקוח", last_contact=date(2026, 11, 19))
    hyp._schedule(cu, {}, date(2026, 11, 23))
    assert cu.contact_on == date(2026, 12, 3)           # 19/11 + 14 = 3/12 (חמישי)


def test_board_only_mode(setup):
    """בלי קובץ Hyp: החוב והתשלומים מהלוח בלבד; התשלום 4004 מהלוח מזהה את המסמך של גמא כ"ייתכן ששולם"."""
    custs, issues, summary = hyp.analyze([], setup[4], setup[5], date(2026, 11, 23))
    c = {x.name: x for x in custs}
    assert summary["open_total"] == D(38360)
    assert c["גמא"].possibly_paid == D(2360) and c["גמא"].gap == 0
    assert c["אפסילון"].last_payment.num == "4010"


def test_capacity_spread():
    """קיבולת 4 בשבוע של 4 ימי עבודה (ב'-ה') → לקוח אחד ליום, לפי ציון; מועד שנקבע בלוח נשמר; העודף לשבוע הבא."""
    as_of = date(2026, 11, 23)
    cs = []
    for i in range(6):
        c = hyp.Customer(f"h:{i}", i, f"c{i}", priority="דחוף", action="פנייה ללקוח", score=100 - i)
        c.contact_on, c.when = as_of, "היום (לא תועדה פנייה)"
        cs.append(c)
    fixed = hyp.Customer("h:9", 9, "fixed", priority="מעקב", action="פנייה ללקוח", score=1,
                         next_contact=date(2026, 11, 24))
    fixed.contact_on, fixed.when = date(2026, 11, 24), "24/11/2026 (מועד שנקבע בלוח)"
    hyp._spread(cs + [fixed], {"weekly_capacity": 4}, as_of)
    got = {c.name: c.contact_on for c in cs + [fixed]}
    assert got["fixed"] == date(2026, 11, 24)
    assert got["c0"] == date(2026, 11, 23) and got["c1"] == date(2026, 11, 25) and got["c2"] == date(2026, 11, 26)
    assert got["c3"] == got["c4"] == got["c5"] == date(2026, 11, 29)     # ראשון הבא
    assert "חריגה מקיבולת" in cs[5].when


def test_no_double_count_and_yaels_work(setup):
    """חוב לא נספר פעמיים, והחלטות שיעל כבר קיבלה בלוח גוברות על החישוב."""
    c = setup[0]
    z = c["זטא"]            # חשבון עסקה פתוח 6,000 + חשבונית מס 6,000 שלא שויכה → נוסחה 0 → אין חוב
    assert z.formula == 0 and z.double_counted == D(6000) and z.net_to_collect == 0 and z.priority == "לסגירה ב-Hyp"
    assert c["חת"].priority == "נבדק – תקין" and c["חת"].contact_on is None and c["חת"].collectible == 0
    t = c["טת"]             # חיוב קבוע, אבל החיוב נכשל וטרם טופל → כן לפנות
    assert t.auto_charge and t.priority == "לטיפול" and t.contact_on is not None and "נכשל" in t.reasons[0]
    y = c["יוד"]            # 8,000 − שיק דחוי 3,000 = 5,000; מתויג לבדיקה מול גיא → לא פונים
    assert y.net_to_collect == D(5000) and y.priority == "ממתין להנהלה" and y.contact_on is None
    assert y.demanded == D(8000) and any("לקוח בעייתי" in r for r in y.reasons)
    k = c["כף"]             # חשבונית מס פתוחה: לא לגבייה, לאימות
    assert k.tax_unverified == D(4000) and k.net_to_collect == 0 and k.priority == "ממתין להנהלה"
    total = sum(x.collectible for x in c.values())
    # אלפא 5,000 + דלתא 3,000 + אפסילון 1,800 + טת 2,000
    assert total == D(11800)


def test_tax_invoice_as_debt_option(setup):
    custs, _, _ = hyp.analyze(setup[3], setup[4], dict(setup[5], tax_invoice_open_is_debt=True), date(2026, 11, 23))
    k = {x.name: x for x in custs}["כף"]
    assert k.net_to_collect == D(4000) and k.tax_unverified == 0
