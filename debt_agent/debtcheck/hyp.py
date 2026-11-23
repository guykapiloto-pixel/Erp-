"""Collections analysis from Hyp (EasyCount): full document history (CSV report) + open-document status (board).

Two sources, each answering what the other cannot:
  * Hyp "documents report" CSV  – every document since inception (type, number, dates, customer, amounts, payment means)
                                  but NO status: it does not say whether a transaction account is still open.
  * Board snapshot ("יעל EK-גבייה", synced from Hyp) – the open documents per Hyp customer id with the remaining
                                  amount, customer list (id, ח.פ, contacts), active automatic charges.

Debt (primary) = remaining amount of open documents in Hyp (transaction accounts + unpaid tax invoices).
The user's formula  T − I − IR + C  is computed from the history next to it, and the gap between the two is explained
per customer – it is a control, not the debt (see docs: transaction accounts are also closed manually without payment).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .normalize import norm_text, parse_amount

D0 = Decimal("0")
T, I, IR, R, C = "חשבונית עסקה", "חשבונית מס", "חשבונית מס קבלה", "קבלה", "חשבונית זיכוי"
KNOWN_TYPES = {T, I, IR, R, C}
BOARD_TYPE = {300: T, 305: I, 320: IR, 330: C, 400: R}
PAY_MEANS = ["מזומן", "המחאה", "כ.אשראי", "ה.בנקאית", "ה. קבע בנקאית", "אפליקציות תשלום", "אחר", "שווה כסף", "ניכוי מס"]
AGING = [(0, 30, "0-30"), (31, 90, "31-90"), (91, 180, "91-180"), (181, 365, "181-365"), (366, 10**6, "365+")]


def bucket(days: int) -> str:
    for lo, hi, n in AGING:
        if lo <= days <= hi:
            return n
    return "עתידי"


def _d(s: str) -> date | None:
    s = norm_text(s)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _crn(s: str) -> str:
    s = re.sub(r"\D", "", norm_text(s))
    return s.lstrip("0")


def name_key(s: str) -> str:
    s = norm_text(s)
    s = re.sub(r"\b(בע\"?מ|בעמ)\b", "", s)
    return re.sub(r"[\s\"'.,\-()]", "", s).lower()


# ---------------------------------------------------------------- data classes

@dataclass
class HypDoc:
    num: str
    type: str
    issued: date
    doc_date: date
    name: str
    crn: str
    total: Decimal
    before_vat: Decimal
    vat: Decimal
    created_by: str
    note: str
    email: str = ""
    phone: str = ""
    means: dict = field(default_factory=dict)
    line: int = 0


@dataclass
class OpenDoc:
    hyp_id: int
    type: str
    num: str
    doc_date: date
    remaining: Decimal
    total: Decimal
    before_vat: Decimal
    description: str
    url: str
    possibly_paid_by: HypDoc | None = None


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    customer: str = ""
    ref: str = ""


@dataclass
class Customer:
    key: str
    hyp_id: int | None
    name: str
    crn: str = ""
    phone: str = ""
    email: str = ""
    contact: str = ""
    bk: str = ""
    auto_charge: bool = False
    docs: list = field(default_factory=list)          # HypDoc (history up to the snapshot)
    later_docs: list = field(default_factory=list)    # HypDoc issued after the snapshot
    open_docs: list = field(default_factory=list)     # OpenDoc
    sums: Counter = field(default_factory=Counter)    # per type, Decimal
    # derived
    open_debt: Decimal = D0
    open_tx: Decimal = D0
    open_tax: Decimal = D0
    possibly_paid: Decimal = D0
    paid_after_snapshot: Decimal = D0
    net_to_collect: Decimal = D0
    formula: Decimal = D0
    gap: Decimal = D0
    closed_tx: Decimal = D0
    partial_applied: Decimal = D0
    oldest_open: date | None = None
    oldest_days: int | None = None
    aging: dict = field(default_factory=dict)
    last_payment: HypDoc | None = None
    paid_12m: Decimal = D0
    action: str = ""
    # מעקב פניות (מהלוח)
    last_contact: date | None = None
    next_contact: date | None = None
    last_note: str = ""
    pay_day: int | None = None
    pay_freq: str = ""
    pay_method: str = ""
    contact_on: date | None = None
    hidden: bool = False
    handler: str = ""
    # מה שיעל כבר עשתה בלוח
    demanded: Decimal | None = None       # סכום שנדרש מהלקוח
    check_status: str = ""                # בדיקת יתרה: ok / followup / gap / closed
    check_note: str = ""
    review_with: str = ""                 # ממתין לתשובת גיא / דקל
    tags: list = field(default_factory=list)          # רשימות חריגים בלוח
    failed_charge: date | None = None     # חיוב אוטומטי שנכשל וטרם טופל
    cheques_pending: Decimal = D0         # שיקים דחויים שבידינו
    collectible: Decimal = D0             # נטו לגבייה אם הלקוח ברשימת הפנייה, אחרת 0
    double_counted: Decimal = D0          # חוב פתוח ב-Hyp שכבר מכוסה בחשבוניות/תשלומים שלא שויכו
    has_history: bool = True
    tax_is_debt: bool = False
    tax_unverified: Decimal = D0          # חשבוניות מס פתוחות ב-Hyp – לאימות שהתקבל תשלום
    when: str = ""
    reversals: list = field(default_factory=list)     # (קבלה מקורית | None, קבלה שלילית)
    score: float = 0.0
    priority: str = ""
    reasons: list = field(default_factory=list)
    excluded: bool = False


# ---------------------------------------------------------------- loaders

def load_hyp_csv(path: str | Path) -> tuple[list[HypDoc], list[Issue]]:
    issues: list[Issue] = []
    docs: list[HypDoc] = []
    raw = Path(path).read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp1255"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("קידוד הקובץ לא מזוהה")
    reader = csv.DictReader(text.splitlines(keepends=True))
    need = {"מספר מסמך", "סוג מסמך", "תאריך הפקה", "תאריך מסמך", "שם לקוח", "ת.ז/ ח.פ של הלקוח", 'סה"כ'}
    missing = need - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"חסרות עמודות בקובץ Hyp: {', '.join(sorted(missing))}")
    seen: set = set()
    for i, r in enumerate(reader, start=2):
        typ = norm_text(r["סוג מסמך"])
        total = parse_amount(r['סה"כ'])
        issued, ddate = _d(r["תאריך הפקה"]), _d(r["תאריך מסמך"])
        ref = f"{typ} {r['מספר מסמך']}"
        if typ not in KNOWN_TYPES:
            issues.append(Issue("error", "UNKNOWN_TYPE", f"סוג מסמך לא מוכר '{typ}' – לא נספר", r["שם לקוח"], ref))
            continue
        if total is None or issued is None or ddate is None:
            issues.append(Issue("error", "BAD_ROW", "סכום/תאריך לא קריא – לא נספר", r["שם לקוח"], ref))
            continue
        k = (typ, norm_text(r["מספר מסמך"]))
        if k in seen:
            issues.append(Issue("error", "DUPLICATE_DOC", "מסמך כפול בקובץ – נספר פעם אחת", r["שם לקוח"], ref))
            continue
        seen.add(k)
        means = {m: parse_amount(r.get(m)) or D0 for m in PAY_MEANS if r.get(m) not in (None, "")}
        bv = (parse_amount(r.get("סכום")) or D0) + (parse_amount(r.get('סכום ללא מע"מ')) or D0)
        vat = parse_amount(r.get('סכום המע"מ')) or D0
        if typ != R and (bv or vat) and abs(bv + vat - total) > Decimal("1"):
            issues.append(Issue("warning", "VAT_MISMATCH",
                                f"סכום לפני מע\"מ + מע\"מ ({bv + vat:,.2f}) שונה מהסה\"כ ({total:,.2f})", r["שם לקוח"], ref))
        if typ in (IR, R) and means and abs(sum(means.values()) - total) > Decimal("0.05"):
            issues.append(Issue("warning", "MEANS_MISMATCH", "סכום אמצעי התשלום שונה מהסה\"כ", r["שם לקוח"], ref))
        docs.append(HypDoc(k[1], typ, issued, ddate, norm_text(r["שם לקוח"]), _crn(r["ת.ז/ ח.פ של הלקוח"]), total, bv,
                           vat, norm_text(r.get("נוצר על ידי")), norm_text(r.get("הערה למסמך")),
                           norm_text(r.get("אימייל לקוח")), norm_text(r.get("טלפון לקוח")), means, i))
    return docs, issues


def _iso(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _load_json(p: Path) -> dict:
    j = json.loads(p.read_text(encoding="utf-8"))
    return j.get("data", j) if isinstance(j, dict) and "data" in j and isinstance(j["data"], dict) else j


def load_board(snapshot_dir: str | Path) -> dict:
    """Snapshot of the board database (ArtifactData export: <dir>/hyp/*.json, <dir>/custList/*.json)."""
    root = Path(snapshot_dir)
    hyp = {p.stem: _load_json(p) for p in (root / "hyp").glob("*.json")}
    meta = _load_json(root / "custList" / "meta.json")
    custs = []
    for i in range(int(meta.get("chunks", 0))):
        custs.extend(_load_json(root / "custList" / f"c{i}.json").get("rows", []))
    warnings = []
    if len(custs) != int(meta.get("count", len(custs))):
        warnings.append(Issue("warning", "BOARD_CUSTLIST_COUNT", f"רשימת הלקוחות בלוח מכילה {len(custs)} לקוחות, "
                              f"והמונה בלוח מציין {meta.get('count')} – ייתכן שהרשימה לא סונכרנה במלואה"))
    for need in ("open", "opendocs"):
        if need not in hyp:
            raise ValueError(f"חסר hyp/{need} בתמונת הלוח")
    as_of = datetime.fromisoformat(hyp["opendocs"]["asOf"]).date()
    return {"as_of": as_of, "as_of_raw": hyp["opendocs"]["asOf"], "open": hyp["open"], "opendocs": hyp["opendocs"],
            "auto": set(map(int, (hyp.get("auto") or {}).get("ids", []))),
            "bk": {int(r[0]): str(r[1]) for r in (hyp.get("bk") or {}).get("rows", []) if r[1]},
            "customers": custs, "warnings": warnings, "pay": hyp.get("pay"),
            "cfile": _load_coll(root / "cfile"), "contacts": list(_load_coll(root / "contacts").values()),
            "checks": list(_load_coll(root / "checks").values()), "lists": list(_load_coll(root / "clients").values()),
            "failed": list(_load_coll(root / "failed").values()), "cheques": list(_load_coll(root / "cheques").values())}


def _load_coll(d: Path) -> dict:
    return {p.stem: _load_json(p) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}


# ---------------------------------------------------------------- analysis

ACTIONS = {"דחוף": "פנייה ללקוח", "לטיפול": "פנייה ללקוח", "מעקב": "פנייה ללקוח",
           "לסגירה ב-Hyp": "סגירת מסמך ב-Hyp", "ממתין להנהלה": "ממתין לגיא/דקל", "נבדק – תקין": "ללא פעולה",
           "חיוב קבוע": "ללא פעולה", "מוחרג": "ללא פעולה", "תקין": ""}
ORDER = ["דחוף", "לטיפול", "מעקב", "ממתין להנהלה", "לסגירה ב-Hyp", "חיוב קבוע", "נבדק – תקין", "מוחרג", "תקין"]

def analyze(docs: list[HypDoc], board: dict, cfg: dict, as_of: date | None = None
            ) -> tuple[list[Customer], list[Issue], dict]:
    a = cfg.get("alerts", {})
    gap_tol = Decimal(str(a.get("formula_gap_tolerance", 100)))
    excluded_ids = {int(x) for x in cfg.get("exclude_hyp_ids", [])}
    snap = board["as_of"]
    as_of = as_of or snap
    issues: list[Issue] = list(board.get("warnings", []))

    # customers from the board
    custs: dict[str, Customer] = {}
    by_crn: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    for c in board["customers"]:
        h = int(c["h"])
        cu = Customer(f"h:{h}", h, norm_text(c.get("n")), _crn(c.get("crn", "")), norm_text(c.get("ph")),
                      norm_text(c.get("em")), norm_text(c.get("ct")), board["bk"].get(h, ""), h in board["auto"])
        cu.excluded = h in excluded_ids
        custs[cu.key] = cu
        if cu.crn:
            by_crn[cu.crn].append(h)
        by_name[name_key(cu.name)].append(h)

    def resolve(doc_name: str, crn: str) -> str:
        if crn and by_crn.get(crn):
            hs = by_crn[crn]
            if len(hs) == 1:
                return f"h:{hs[0]}"
            nk = name_key(doc_name)
            pick = [h for h in hs if name_key(custs[f'h:{h}'].name) == nk]
            if len(pick) == 1:
                return f"h:{pick[0]}"
        nk = name_key(doc_name)
        hs = by_name.get(nk, [])
        if len(hs) == 1:
            return f"h:{hs[0]}"
        return f"crn:{crn}" if crn else f"name:{nk}"

    unresolved = Counter()
    owner: dict = {}
    for d in docs:
        key = resolve(d.name, d.crn)
        if key not in custs:
            custs[key] = Customer(key, None, d.name, d.crn)
            unresolved[key] += 1
        cu = custs[key]
        owner[(d.type, d.num)] = key
        (cu.docs if d.issued <= snap else cu.later_docs).append(d)
        if not cu.phone and d.phone:
            cu.phone = d.phone
        if not cu.email and d.email:
            cu.email = d.email
    has_history = bool(docs)
    # תשלומים מהלוח (hyp/pay) – משלימים את התקופה שאחרי קובץ ה-CSV, או מחליפים אותו כשאין קובץ
    known = {(d.type, d.num) for d in docs}
    known_nums = {d.num for d in docs if d.type in (IR, R)}
    added_pay = 0
    for h, plist in ((board.get("pay") or {}).get("rows") or []):
        key = f"h:{int(h)}"
        if key not in custs:
            continue
        cu = custs[key]
        for p in plist:
            num = str(p[2])
            if num in known_nums:
                continue
            typ = R if num.startswith("8") else IR
            dd = date.fromisoformat(p[0])
            cu.docs.append(HypDoc(num, typ, dd, dd, cu.name, cu.crn, Decimal(str(p[1])), D0, D0, "board", ""))
            added_pay += 1

    # מעקב פניות של מנהלת הגבייה (כרטיס לקוח + יומן פניות בלוח)
    for k, f in (board.get("cfile") or {}).items():
        h = f.get("hypId")
        cu = custs.get(f"h:{int(h)}") if h else None
        if not cu:
            continue
        cu.next_contact = _iso(f.get("nextContact"))
        cu.last_contact = _iso(f.get("lastContact"))
        cu.last_note = norm_text(f.get("lastNote"))
        cu.pay_day = int(f["payDay"]) if str(f.get("payDay") or "").isdigit() else None
        cu.pay_freq = norm_text(f.get("payFreq"))
        cu.pay_method = norm_text(f.get("payMethod"))
        cu.hidden = bool(f.get("hideOpen"))
        cu.handler = norm_text(f.get("owner") or f.get("partner") or "")
    for c in board.get("contacts") or []:
        h = c.get("hypId")
        cu = custs.get(f"h:{int(h)}") if h else None
        dd = _iso(c.get("date"))
        if cu and dd and (cu.last_contact is None or dd > cu.last_contact):
            cu.last_contact = dd

    by_nk: dict = defaultdict(list)
    for cu in custs.values():
        by_nk[name_key(cu.name)].append(cu)

    def find(hid, name):
        if hid and f"h:{int(hid)}" in custs:
            return custs[f"h:{int(hid)}"]
        m = by_nk.get(name_key(name or ""), [])
        return m[0] if len(m) == 1 else None

    for k, f in (board.get("cfile") or {}).items():
        cu = find(f.get("hypId"), f.get("name"))
        if not cu:
            continue
        if f.get("demanded") is not None:
            cu.demanded = Decimal(str(f["demanded"]))
        cu.review_with = norm_text(f.get("review"))
        dc = f.get("debtCheck") or {}
        if dc.get("st"):
            cu.check_status, cu.check_note = ("ok" if dc["st"] == "ok" else "gap"), norm_text(dc.get("note"))
    for ck in board.get("checks") or []:
        cu = find(None, ck.get("name"))
        if cu is None:
            if ck.get("status") in ("ok", "closed", "followup", "gap"):
                issues.append(Issue("info", "CHECK_NOT_MATCHED", f"בדיקת יתרה בלוח ({ck.get('status')}) ללקוח שלא זוהה",
                                    norm_text(ck.get("name"))))
            continue
        if ck.get("status") and ck["status"] != "todo":
            cu.check_status, cu.check_note = ck["status"], norm_text(ck.get("note"))
    LIST_HE = {"exceptions": "לקוח חריג", "problem": "לקוח בעייתי", "pension": "חוב שירותי פנסיה"}
    for r in board.get("lists") or []:
        if r.get("archived") or r.get("status") == "done" or r.get("cat") not in LIST_HE:
            continue
        cu = find(r.get("hypId"), r.get("name"))
        if cu:
            cu.tags.append(LIST_HE[r["cat"]] + (f": {norm_text(r.get('note'))[:80]}" if r.get("note") else ""))
    for x in board.get("failed") or []:
        cu = find(x.get("hypId"), x.get("name"))
        lf = _iso(x.get("lastFail"))
        handled = x.get("status") == "handled" and (not x.get("handledAt") or str(x["handledAt"])[:10] >= str(lf))
        if cu and lf and not handled:
            cu.failed_charge = lf
    for q in board.get("cheques") or []:
        cu = find(q.get("hypId"), q.get("client"))
        if cu and q.get("status") == "pending":
            cu.cheques_pending += Decimal(str(q.get("amount") or 0))

    for key, n in unresolved.items():
        cu = custs[key]
        issues.append(Issue("warning", "NOT_IN_BOARD", f"{n} מסמכים של לקוח שלא נמצא ברשימת הלקוחות בלוח "
                                                      f"(ח.פ {cu.crn or '—'})", cu.name))
    multi = {k: v for k, v in by_crn.items() if len(v) > 1}
    for crn, hs in multi.items():
        issues.append(Issue("warning", "CRN_SHARED", f"ח.פ {crn} משויך ל-{len(hs)} כרטיסי לקוח ב-Hyp: "
                            + " | ".join(custs[f'h:{h}'].name for h in hs), custs[f"h:{hs[0]}"].name))

    # open documents (board)
    csv_index = {(d.type, d.num): d for d in docs}
    names_open = {int(r[0] or 0): r[1] for r in board["open"]["rows"]}
    base = board["opendocs"].get("base", "")
    orphan = Counter()
    for h, rows in board["opendocs"]["rows"]:
        h = int(h or 0)
        for x in rows:
            typ = BOARD_TYPE.get(int(x[2]), str(x[2]))
            num = str(x[1])
            src = csv_index.get((typ, num))
            # מזהה הלקוח ב-Hyp (מהלוח) הוא הקישור הקובע. כשהוא חסר (0) או לא מוכר – משייכים לפי הלקוח שעל המסמך
            board_key = f"h:{h}" if h else None
            doc_key = resolve(src.name, src.crn) if src else None
            if board_key and board_key in custs:
                key = board_key
            else:
                key = doc_key or board_key or resolve(names_open.get(0, ""), "")
            if key not in custs:
                custs[key] = Customer(key, None, src.name if src else names_open.get(h, "ללא כרטיס לקוח"),
                                      src.crn if src else "")
            cu = custs[key]
            if src is not None and owner.get((typ, num)) not in (None, key):
                # המסמך רשום ב-Hyp על כרטיס הלקוח הזה אך בקובץ מופיע בשם אחר: ההיסטוריה עוברת עם המסמך,
                # אחרת חשבון העסקה הפתוח חסר בנוסחה של הלקוח
                prev = custs[owner[(typ, num)]]
                for lst in (prev.docs, prev.later_docs):
                    if src in lst:
                        lst.remove(src)
                cu.docs.append(src)
                owner[(typ, num)] = key
            if not h:
                orphan[cu.name] += 1
            elif doc_key and doc_key != key:
                issues.append(Issue("warning", "OPEN_CUSTOMER_MISMATCH", f"{typ} {num}: כרטיס הלקוח ב-Hyp הוא "
                                    f"'{cu.name}' אך השם על המסמך '{src.name}' (ח.פ {src.crn or '—'}) – לוודא שהחוב "
                                    "רשום על הלקוח הנכון", cu.name, num))
            elif board_key and board_key not in custs:
                issues.append(Issue("info", "NEW_CUSTOMER", f"לקוח {h} אינו ברשימת הלקוחות של הלוח (נוסף אחרי הסנכרון)"
                                    f" – שויך לפי המסמך ל-'{cu.name}'", cu.name, num))
            url = x[5] if len(x) > 5 and x[5] else ""
            if url and not str(url).startswith("http"):
                url = base + url
            od = OpenDoc(h, typ, num, date.fromisoformat(x[0]), Decimal(str(x[3])), Decimal(str(x[4])),
                         Decimal(str(x[7])) if len(x) > 7 and x[7] not in (None, "") else D0,
                         x[6] if len(x) > 6 else "", url)
            cu.open_docs.append(od)
            if src is None and has_history:
                issues.append(Issue("error", "OPEN_NOT_IN_CSV", f"מסמך פתוח {typ} {num} לא קיים בקובץ Hyp",
                                    cu.name, num))
            elif src is not None and abs(src.total - od.total) > Decimal("0.5"):
                issues.append(Issue("error", "OPEN_AMOUNT_DIFF", f"{typ} {num}: סכום בלוח {od.total:,.2f} "
                                    f"ובקובץ {src.total:,.2f}", cu.name, num))
    if orphan:
        issues.append(Issue("error", "OPEN_WITHOUT_CUSTOMER",
                            f"{sum(orphan.values())} מסמכים פתוחים רשומים בלוח ללא כרטיס לקוח (מזהה 0, בשם "
                            f"'{names_open.get(0, '')}'). לפי Hyp הם שייכים ל-{len(orphan)} לקוחות: "
                            + ", ".join(f"{n} ({k})" for n, k in orphan.most_common()) + " – שויכו לפי המסמך"))

    # per customer
    out = []
    for cu in custs.values():
        cu.has_history = has_history
        cu.tax_is_debt = bool(cfg.get("tax_invoice_open_is_debt", False))
        _compute(cu, as_of, snap)
        if not has_history:
            cu.formula, cu.gap = cu.open_debt, D0      # אין היסטוריה מלאה – בקרת הנוסחה לא רלוונטית
        _classify(cu, a, gap_tol, as_of)
        cu.action = ACTIONS.get(cu.priority, "")
        _schedule(cu, cfg, as_of)
        if cu.docs or cu.open_docs:
            out.append(cu)

    _spread(out, cfg, as_of)
    order = {k: i for i, k in enumerate(ORDER)}
    out.sort(key=lambda c: (order.get(c.priority, 9), -c.score, -c.open_debt))

    board_total = Decimal(str(board["open"].get("total", 0)))
    calc_total = sum((c.open_debt for c in out), D0)
    if abs(board_total - calc_total) > Decimal("2"):
        issues.append(Issue("error", "BOARD_TOTAL_DIFF", f"סך החוב הפתוח שחושב {calc_total:,.2f} שונה מהסה\"כ בלוח "
                                                         f"{board_total:,.2f}"))
    summary = {"snapshot": board["as_of_raw"], "as_of": as_of, "board_total": board_total, "open_total": calc_total,
               "customers": len(out), "docs": len(docs), "board_payments_added": added_pay,
               "history": "קובץ Hyp מלא" if has_history else "הלוח בלבד (ללא בקרת נוסחה)",
               "week_end": week_end(as_of)}
    return out, issues, summary


def _compute(cu: Customer, as_of: date, snap: date) -> None:
    for d in cu.docs:
        cu.sums[d.type] += d.total
    s = cu.sums
    cu.formula = s[T] - s[I] - s[IR] + s[C]
    cu.open_debt = sum((o.remaining for o in cu.open_docs), D0)
    cu.open_tx = sum((o.remaining for o in cu.open_docs if o.type == T), D0)
    cu.open_tax = sum((o.remaining for o in cu.open_docs if o.type != T), D0)
    cu.partial_applied = sum((o.total - o.remaining for o in cu.open_docs), D0)
    open_tx_nums = {o.num for o in cu.open_docs if o.type == T}
    cu.closed_tx = sum((d.total for d in cu.docs if d.type == T and d.num not in open_tx_nums), D0)
    cu.gap = cu.formula - cu.open_debt

    allpays = sorted([d for d in cu.docs + cu.later_docs if d.type in (IR, R)], key=lambda d: (d.doc_date, d.num))
    # קבלה שלילית (החזר / שיק חוזר) מבטלת קבלה קודמת באותו סכום – שתיהן יוצאות מהתאמת התשלומים
    cancelled: set = set()
    for n in [p for p in allpays if p.total < 0]:
        cancelled.add(id(n))
        prev = [p for p in allpays if p.total > 0 and id(p) not in cancelled and abs(p.total + n.total) < Decimal("0.5")
                and p.doc_date <= n.doc_date]
        if prev:
            cancelled.add(id(prev[-1]))
            cu.reversals.append((prev[-1], n))
        else:
            cu.reversals.append((None, n))
    pays = [p for p in allpays if id(p) not in cancelled]
    if pays:
        cu.last_payment = pays[-1]
    cu.paid_12m = sum((p.total for p in allpays if (as_of - p.doc_date).days <= 365), D0)

    # open documents that a later payment of the same amount may have settled (not linked in Hyp)
    used: set = set()
    for o in sorted(cu.open_docs, key=lambda o: (o.doc_date, o.num)):
        cand = [p for p in pays if p.total > 0 and id(p) not in used and abs(p.total - o.remaining) < Decimal("0.5")
                and p.doc_date >= o.doc_date]
        if cand:
            p = cand[0]
            used.add(id(p))
            o.possibly_paid_by = p
            cu.possibly_paid += o.remaining
    cu.paid_after_snapshot = sum((p.total for p in pays if p.issued > snap and id(p) not in used), D0)
    if cu.has_history:
        # מניעת ספירה כפולה: חשבון עסקה שנשאר פתוח ב-Hyp למרות שכבר הופקה בגינו חשבונית מס / חשבונית מס קבלה
        # שלא שויכה אליו. החוב = min(חשבונות עסקה פתוחים, הנוסחה ברמת הלקוח): עסקה − מס − מס קבלה + זיכוי.
        # חשבונית מס מופקת עם קבלת התשלום (בסיס מזומן), ולכן חשבונית מס שפתוחה ב-Hyp אינה חוב לגבייה אלא
        # פריט לאימות – אלא אם הוגדר tax_invoice_open_is_debt.
        if cu.tax_is_debt:
            base = max(D0, min(cu.open_tx, cu.formula + cu.open_tax)) + cu.open_tax
        else:
            base = max(D0, min(cu.open_tx, cu.formula))
            cu.tax_unverified = cu.open_tax
        cu.double_counted = cu.open_debt - cu.tax_unverified - base
        cu.possibly_paid = min(cu.possibly_paid, cu.double_counted)      # מידע בלבד – כבר כלול בקיזוז
    else:
        base = max(cu.open_debt - cu.possibly_paid, D0)
    cu.net_to_collect = max(base - cu.paid_after_snapshot - cu.cheques_pending, D0)

    aging: dict = defaultdict(lambda: D0)
    for o in cu.open_docs:
        aging[bucket((as_of - o.doc_date).days)] += o.remaining
    cu.aging = dict(aging)
    if cu.open_docs:
        cu.oldest_open = min(o.doc_date for o in cu.open_docs)
        cu.oldest_days = (as_of - cu.oldest_open).days


def _classify(cu, a, gap_tol, as_of):
    """סיווג לפי החוב נטו ולפי מה שיעל כבר עשתה בלוח. הסדר קובע: החלטה שלה גוברת על חישוב."""
    min_debt = Decimal(str(a.get("min_debt", 1)))
    urgent_amount = Decimal(str(a.get("urgent_amount", 10000)))
    urgent_min = Decimal(str(a.get("urgent_min_amount", 5000)))
    urgent_days = int(a.get("urgent_days", 90))
    followup_days = int(a.get("followup_days", 30))
    no_pay_days = int(a.get("no_payment_days", 120))
    r = cu.reasons
    net, days = cu.net_to_collect, cu.oldest_days or 0
    lp = cu.last_payment
    since_pay = (as_of - lp.doc_date).days if lp else None
    cu.score = float(net) * (1 + min(days, 730) / 365)

    # הקשר – מופיע תמיד
    if cu.double_counted > gap_tol:
        r.append(f"ב-Hyp פתוח {cu.open_debt:,.0f} ₪, מתוכם {cu.double_counted:,.0f} ₪ כבר מכוסים בחשבוניות/תשלומים "
                 "שלא שויכו לחשבון העסקה – לסגור ב-Hyp")
    if cu.cheques_pending:
        r.append(f"שיקים דחויים בידינו {cu.cheques_pending:,.0f} ₪")
    if cu.paid_after_snapshot:
        r.append(f"התקבלו {cu.paid_after_snapshot:,.0f} ₪ אחרי עדכון הלוח")
    if cu.open_tax:
        r.append(f"חשבונית מס פתוחה ב-Hyp {cu.open_tax:,.0f} ₪ – לוודא שהתקבל תשלום"
                 + ("" if cu.tax_unverified else " (נספרת כחוב)"))
    for t in cu.tags:
        r.append(t)
    if cu.check_status in ("followup", "gap") and cu.check_note:
        r.append(f"בדיקת יעל: {cu.check_note[:120]}")
    for orig, neg in cu.reversals:
        r.append(f"קבלה שלילית {neg.num} ({neg.total:,.0f}) {neg.doc_date:%d/%m/%Y} – החזר/שיק חוזר")
    if lp is None and cu.has_history:
        r.append("לא התקבל אף תשלום")
    elif since_pay is not None and since_pay >= no_pay_days:
        r.append(f"תשלום אחרון לפני {since_pay} ימים")

    if cu.excluded or cu.hidden:
        cu.priority = "מוחרג"
        r.insert(0, "מוחרג לפי הגדרה" if cu.excluded else "הוסתר מרשימת החוב הפתוח בלוח")
    elif cu.open_debt < min_debt:
        cu.priority = "תקין"
    elif cu.check_status in ("ok", "closed"):
        cu.priority = "נבדק – תקין"
        r.insert(0, "יעל בדקה: תקין, ירד מיתרת החייבים" + (f" ({cu.check_note[:100]})" if cu.check_note else ""))
    elif cu.failed_charge:
        cu.priority = "דחוף" if net >= urgent_min else "לטיפול"
        r.insert(0, f"חיוב אוטומטי נכשל ב-{cu.failed_charge:%d/%m/%Y} וטרם טופל – לגבייה {net:,.0f} ₪")
    elif cu.auto_charge:
        cu.priority = "חיוב קבוע"
        r.insert(0, "בחיוב קבוע חודשי – לא נספר ביתרת החייבים (כמו בלוח)")
    elif net < min_debt and cu.tax_unverified >= min_debt:
        cu.priority = "ממתין להנהלה"
        r.insert(0, "אין חשבון עסקה לגבייה; חשבונית מס פתוחה – לאימות מול הנהלת החשבונות")
    elif net < min_debt:
        cu.priority = "לסגירה ב-Hyp"
        r.insert(0, "אין חוב לגבייה: המסמך הפתוח כבר מכוסה – לסגור ב-Hyp, לא לפנות ללקוח")
    elif cu.review_with:
        cu.priority = "ממתין להנהלה"
        r.insert(0, f"ממתין לתשובת {cu.review_with} – לגבייה {net:,.0f} ₪")
    else:
        if net >= urgent_amount or (days >= urgent_days and net >= urgent_min):
            cu.priority = "דחוף"
        elif days >= followup_days:
            cu.priority = "לטיפול"
        else:
            cu.priority = "מעקב"
        r.insert(0, f"לגבייה {net:,.0f} ₪" + (f" (נדרש בלוח {cu.demanded:,.0f})" if cu.demanded is not None
                                               and abs(cu.demanded - net) > 1 else "")
                 + f", מסמך פתוח ותיק {days} ימים")
    if cu.priority not in ("דחוף", "לטיפול", "מעקב"):
        cu.collectible = D0
    else:
        cu.collectible = net


# ---------------------------------------------------------------- when to contact

def is_workday(d: date, holidays: set) -> bool:
    return d.weekday() not in (4, 5) and d not in holidays          # שישי=4, שבת=5


def next_workday(d: date, holidays: set) -> date:
    from datetime import timedelta
    while not is_workday(d, holidays):
        d += timedelta(days=1)
    return d


def week_end(d: date) -> date:
    """יום חמישי של השבוע (שבוע עבודה א'–ה')."""
    from datetime import timedelta
    return d + timedelta(days=(3 - d.weekday()) % 7)


def _schedule(cu: Customer, cfg: dict, as_of: date) -> None:
    """מתי לפנות: מועד שקבעה מנהלת הגבייה גובר; אחרת פנייה אחרונה + מחזור לפי עדיפות; לא פנו מעולם – היום."""
    from datetime import timedelta
    if cu.action != "פנייה ללקוח":
        cu.when = "" if cu.action in ("", "ללא פעולה") else "לא לפנות ללקוח – " + cu.action
        return
    hol = {date.fromisoformat(str(x)) for x in cfg.get("holidays", [])}
    cadence = {"דחוף": 7, "לטיפול": 14, "מעקב": 30}
    cadence.update(cfg.get("contact_cadence_days") or {})
    today = next_workday(as_of, hol)
    if cu.next_contact:
        due, src = cu.next_contact, "מועד שנקבע בלוח"
    elif cu.last_contact:
        due, src = cu.last_contact + timedelta(days=int(cadence.get(cu.priority, 14))), \
            f"פנייה אחרונה {cu.last_contact:%d/%m} + {cadence.get(cu.priority, 14)} ימים"
    else:
        due, src = today, "לא תועדה פנייה"
    if cu.pay_day and cu.pay_freq and not cu.next_contact:
        # לקוח שמשלם בתאריך קבוע: לא לפנות לפני יום התשלום הקרוב + 2
        pd_ = date(as_of.year, as_of.month, min(cu.pay_day, 28))
        if pd_ >= as_of:
            due = max(due, pd_ + timedelta(days=2))
            src += f"; משלם ב-{cu.pay_day} לחודש"
    due = next_workday(max(due, today) if due < today else due, hol)
    cu.contact_on = due
    late = (as_of - cu.next_contact).days if cu.next_contact and cu.next_contact < as_of else 0
    cu.when = ("היום" if due <= today else f"{due:%d/%m/%Y}") + f" ({src}" + (f", באיחור {late} ימים" if late else "") + ")"


def _spread(custs: list, cfg: dict, as_of: date) -> None:
    """פיזור הפניות לפי קיבולת שבועית: מועדים שקבעה מנהלת הגבייה נשמרים; השאר מתמלאים לפי עדיפות וציון,
    יום אחר יום, והעודף עובר לשבוע הבא."""
    import math
    from datetime import timedelta
    cap = int(cfg.get("weekly_capacity", 60))
    hol = {date.fromisoformat(str(x)) for x in cfg.get("holidays", [])}
    wk = week_end(as_of)
    days, d = [], next_workday(as_of, hol)
    while d <= wk:
        days.append(d)
        d = next_workday(d + timedelta(days=1), hol)
    if not days:
        return
    due = [c for c in custs if c.contact_on and c.contact_on <= wk]
    fixed = [c for c in due if c.next_contact and c.next_contact >= as_of]
    flex = [c for c in due if c not in fixed]
    rank = {"דחוף": 0, "לטיפול": 1, "מעקב": 2}
    flex.sort(key=lambda c: (c.contact_on, rank.get(c.priority, 3), -c.score))
    flex.sort(key=lambda c: (rank.get(c.priority, 3), -c.score))
    per_day = max(1, math.ceil(cap / len(days)))
    load = {d: sum(1 for c in fixed if c.contact_on == d) for d in days}
    nxt = next_workday(wk + timedelta(days=1), hol)
    for c in flex:
        slot = next((d for d in days if d >= c.contact_on and load[d] < per_day), None) \
            if c.contact_on >= days[0] else next((d for d in days if load[d] < per_day), None)
        if slot is None:
            c.contact_on = nxt
            c.when = f"{nxt:%d/%m/%Y} (חריגה מקיבולת השבוע – {cap} פניות)" + c.when[c.when.find(" ("):] \
                if " (" in c.when else f"{nxt:%d/%m/%Y}"
            continue
        load[slot] += 1
        if slot != c.contact_on:
            label = "היום" if slot == days[0] else f"{slot:%d/%m/%Y}"
            c.when = label + c.when[c.when.find(" ("):] if " (" in c.when else label
        c.contact_on = slot
