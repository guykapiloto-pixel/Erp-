"""Collection work lists: missing months between paid months (the case reported on the board: 12/24 never charged)."""
from datetime import date
from decimal import Decimal as D

from debtcheck import hyp, lists


def test_missing_month_between_paid_months():
    c = hyp.Customer("h:1", 1, "גן", priority="תקין")
    c.payments = [(date(2024, m, 1), D(8190), f"חשבונית מס {m} מ-15/{m:02d}/2024 (הנה\"ח {m}.24)") for m in (9, 10, 11)]
    c.payments += [(date(2025, m, 1), D(8260), f"חשבונית מס 2{m} מ-09/0{m + 1}/2025 (הנה\"ח {m}/25)") for m in (1, 2)]
    out = {l.key: l for l in lists.build([c], date(2025, 3, 20), {}, {}, {})}
    gaps = out["gaps"].rows
    assert len(gaps) == 1 and gaps[0][2] == "12/24"          # 12/24 חסר; 03/25 עוד לא הסתיים
    assert out["now"].rows == []
