"""Document-level classification: is a fee that was issued in a transaction account already owed?  As-of 23/11/2026."""
from datetime import date
from decimal import Decimal as D

import pytest

from debtcheck import docitems, hyp
from debtcheck.classify import classify_item, kind_of, parse_period, parse_year

AS_OF = date(2026, 11, 23)
CFG = {"not_due_from_year": 2025, "prorate_future_periods": True}


def cl(desc, sku="", title="", issued=date(2026, 3, 1), filed=(), override=None):
    return classify_item(desc, sku, title, issued, AS_OF, filed_years=set(filed), override=override, cfg=CFG)


@pytest.mark.parametrize("text,exp", [("הנהלת חשבונות 01-12/26", (2026, 1, 12)), ("שכ\"ט 09/2026", (2026, 9, 9)),
                                      ("הנהלת חשבונות 1-3/ 26", (2026, 1, 3)), ("12/25 הפרשי תלושים", (2025, 12, 12)),
                                      ("דו\"ח ושרות שנתי 25", None)])
def test_parse_period(text, exp):
    assert parse_period(text) == exp


@pytest.mark.parametrize("text,exp", [("דו\"ח ושרות שנתי 25", 2025), ("מאזן 2025", 2025), ("מאזן 25הפרש תשלום", 2025),
                                      ("הנהלת חשבונות 26", 2026), ("מאזן", None), ("שכ\"ט 09/2026", None)])
def test_parse_year(text, exp):
    assert parse_year(text) == exp


def test_kinds():
    assert kind_of("דו\"ח ושרות שנתי 25", "102") == "annual" and kind_of("מאזן", "103") == "balance"
    assert kind_of("ביקורת 25", "1111") == "balance" and kind_of("הנהלת חשבונות 26", "101") == "period"
    assert kind_of("שכ\"ט הנה\"ח ודו\"ח 03/26", "107") == "period" and kind_of("התחשבנות", "81") == "other"


def test_annual_report_and_balance():
    assert cl("דו\"ח ושרות שנתי 24", "102").status == "due"                      # שנה שנסגרה
    r = cl("דו\"ח ושרות שנתי 25", "102")
    assert r.status == "not_due" and r.due_share == 0 and "אין תיעוד" in r.reason   # 2025, לא ידוע שהוגש
    assert cl("דו\"ח ושרות שנתי 25", "102", filed=[2025]).status == "due"         # הדוח שודר
    assert cl("מאזן 2026", "103").status == "not_due"                              # שנת המס טרם הסתיימה
    assert cl("מאזן 2026", "103", filed=[2026]).status == "not_due"
    assert cl("מאזן", "103", title="מאזן 25").year == 2025                          # שנה מכותרת המסמך
    g = cl("מאזן", "103", issued=date(2026, 2, 1))                                 # בלי שנה: השנה שקדמה להפקה
    assert g.year == 2025 and g.status == "not_due" and "משוערת" in g.reason
    assert cl("מאזן", "103", issued=date(2025, 3, 1)).status == "due"               # 2024


def test_period_fees_prorated():
    assert cl("הנהלת חשבונות 01-12/26", "101").due_share == D(11) / D(12)          # עד נובמבר כולל
    assert cl("הנהלת חשבונות 26", "101").due_share == D(11) / D(12)                # שנתי ללא חודשים
    assert cl("שכ\"ט 12/2026", "107").status == "not_due"
    assert cl("שכ\"ט 10/26", "107").due_share == 1 and cl("הנהלת חשבונות 25", "101").due_share == 1
    assert cl("ניהול תיק ניכויים", "106").due_share == 1


def test_override_and_unknown():
    assert cl("דו\"ח ושרות שנתי 25", "102", override="due").due_share == 1
    assert cl("הנהלת חשבונות 10/26", "101", override="not_due").due_share == 0
    u = cl("", "", "")
    assert u.status == "unknown" and u.due_share == 1


PDF_TEXT = """
‫חשבונית עסקה מספר ‪92572‬‬
                                                  ‫01-12/26‬
                                                  ‫פריטים:‬
      ‫סכום‬            ‫מחיר‬         ‫כמות‬                               ‫פירוט‬                                ‫מק"ט‬
        ‫₪600.00‬         ‫₪600.00 1.00‬                              ‫הנהלת חשבונות 2025‬            ‫101‬
         ‫לפני הנחה‬    ‫₪1,500.00 1.00‬                             ‫דו"ח ושרות שנתי 2024‬          ‫102‬
        ‫₪1,500.00‬                                                     ‫קיזוז יתרת זכות‬
        ‫הנחת שורה‬
         ‫₪-603.39‬
        ‫₪896.61‬
      ‫סה"כ חייב במע"מ: ₪1,496.61‬
        ‫מע"מ 18.00%: ₪269.39‬
     ‫סה"כ: ₪1,766.00‬
‫הערה מצורפת:‬
‫פרטי חשבון בנק‬
"""


def test_pdf_parsing_with_line_discount():
    p = docitems.parse_pdf_text(PDF_TEXT)
    assert p["title"] == "01-12/26"
    assert [(i["desc"].split(" קיזוז")[0], i["sku"], i["amount"]) for i in p["items"]] == [
        ("הנהלת חשבונות 2025", "101", "600.00"), ("דו\"ח ושרות שנתי 2024", "102", "896.61")]


def test_document_split_and_customer_net():
    """מסמך אחד, 3 שורות: הנה"ח 2026 (11/12 מגיע), דו"ח 25 (טרם מגיע), דו"ח 24 (מגיע)."""
    o = hyp.OpenDoc(1, hyp.T, "1", date(2026, 1, 10), D(3540), D(3540), D(3000), "", "")
    parsed = {"title": "", "items": [{"desc": "הנהלת חשבונות 26", "sku": "101", "amount": "1200"},
                                     {"desc": "דו\"ח ושרות שנתי 25", "sku": "102", "amount": "1000"},
                                     {"desc": "דו\"ח ושרות שנתי 24", "sku": "102", "amount": "800"}]}
    hyp._classify_doc(o, parsed, AS_OF, set(), None, CFG, classify_item)
    # יתרה כולל מע"מ: 1,416 / 1,180 / 944.  מגיע: 1,416×11/12=1,298 + 0 + 944 = 2,242
    assert [a for _, a, _ in o.lines] == [D("1416.00"), D("1180.00"), D("944.00")]
    assert o.due == D("2242.00") and o.not_due == D("1298.00") and o.due + o.not_due == o.remaining
