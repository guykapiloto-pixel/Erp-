"""Command line.

  python -m debtcheck run     --config config.yaml [--file export.xlsx] [--out report.xlsx] [--as-of 2026-11-22]
                              [--customer "שם"]  (פירוט מלא ללקוח בודד)
  python -m debtcheck inspect --config config.yaml   (רשימת עמודות הלוח, למילוי המיפוי)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from decimal import Decimal

import yaml

from .engine import compute
from .normalize import customer_key, norm_text, rows_to_documents, summary_rows_to_documents
from .report import console_summary, write_excel


def load_config(path: str | Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for k in ("columns", "doc_types"):
        if k not in cfg:
            raise SystemExit(f"חסר '{k}' בקובץ ההגדרות")
    return cfg


def load_rows(cfg: dict, file: str | None):
    if file:
        from .sources.file import read_rows
        return read_rows(file, cfg)
    if cfg.get("source", {}).get("type") == "file":
        from .sources.file import read_rows
        return read_rows(cfg["source"]["path"], cfg)
    from .sources.monday import fetch_rows
    return fetch_rows(cfg)


def run(cfg: dict, rows, *, as_of: date):
    if cfg.get("layout", "documents") == "summary":
        docs, issues = summary_rows_to_documents(rows, cfg)
    else:
        docs, issues = rows_to_documents(rows, cfg)
    balances, more = compute(docs, cfg, as_of)
    return balances, issues + more


def _customer_detail(b) -> str:
    out = [f"לקוח: {b.customer_name}  (מפתח: {b.customer_key})", f"עדיפות: {b.priority} – {'; '.join(b.reasons)}",
           f"חשבונות עסקה        {b.transactions:>14,.2f}  ({b.counts.get('transaction', 0)} מסמכים)",
           f"(−) חשבוניות מס      {b.tax_invoices:>14,.2f}  ({b.counts.get('tax_invoice', 0)})",
           f"(−) חשבוניות מס קבלה {b.tax_invoice_receipts:>14,.2f}  ({b.counts.get('tax_invoice_receipt', 0)})",
           f"(+) זיכויים          {b.credits:>14,.2f}  ({b.counts.get('credit', 0)})",
           f"= יתרת חוב           {b.debt:>14,.2f}", "", "מסמכים:"]
    for d in b.documents:
        out.append(f"  {d.doc_date.strftime('%d/%m/%Y') if d.doc_date else '----------'}  {d.raw_type:<18} "
                   f"{d.doc_number:<10} {d.amount:>12,.2f}   [{d.row_ref}]")
    if b.open_transactions:
        out += ["", "חשבונות עסקה פתוחים (FIFO):"]
        out += [f"  {t.doc_number or t.row_ref}  {t.doc_date or ''}  יתרה {r:,.2f}" for t, r in b.open_transactions]
    return "\n".join(out)


def _run_hyp(a, cfg) -> int:
    from . import hyp, hyp_report
    docs, issues = hyp.load_hyp_csv(a.csv) if a.csv else ([], [])
    board = hyp.load_board(a.board)
    doc_items = None
    if a.pdf_cache:
        from . import docitems
        base = board["opendocs"].get("base", "")
        want = []
        for _h, rows in board["opendocs"]["rows"]:
            for x in rows:
                u = x[5] if len(x) > 5 and x[5] else ""
                want.append((hyp.BOARD_TYPE.get(int(x[2]), str(x[2])), str(x[1]),
                             u if str(u).startswith("http") else (base + u if u else "")))
        doc_items, errs = docitems.load_items(want, a.pdf_cache)
        for typ, num, err in errs:
            issues.append(hyp.Issue("warning", "DOC_NOT_READ", f"העתק המסמך לא נקרא ({err}) – לא סווג", "", f"{typ} {num}"))
    pay_items = None
    if a.pay_cache and docs:
        from . import docitems
        base = board["opendocs"].get("base", "")
        acct = next((str(x[5]).split("/")[0] for _h, rows in board["opendocs"]["rows"] for x in rows
                     if len(x) > 5 and x[5] and not str(x[5]).startswith("http")), "")
        want = [(d.type, d.num, docitems.doc_url(base, acct, d.type, d.issued.year, d.uuid))
                for d in docs if d.type != hyp.T and d.uuid]
        pay_items, errs = docitems.load_items(want, a.pay_cache, workers=24, keep_pdf=False)
        for typ, num, err in errs:
            issues.append(hyp.Issue("warning", "DOC_NOT_READ", f"מסמך התשלום לא נקרא ({err})", "", f"{typ} {num}"))
    custs, more, summary = hyp.analyze(docs, board, cfg, a.as_of, doc_items, pay_items)
    issues += more
    if a.board_json:
        from . import board_export
        board_export.write(a.board_json, custs, issues, summary)
    if a.customer:
        q = norm_text(a.customer)
        hits = [c for c in custs if q in c.name or q == c.crn or q == str(c.hyp_id)]
        for c in hits:
            s = c.sums
            print(f"לקוח: {c.name} | ח.פ {c.crn} | Hyp {c.hyp_id} | {c.priority}")
            print(f"  חשבונות עסקה {s[hyp.T]:>13,.2f}\n  חשבוניות מס {s[hyp.I]:>14,.2f}\n"
                  f"  חשבוניות מס קבלה {s[hyp.IR]:>9,.2f}\n  קבלות {s[hyp.R]:>20,.2f}\n  זיכויים {s[hyp.C]:>18,.2f}")
            print(f"  חוב לפי הנוסחה {c.formula:>11,.2f}\n  חוב פתוח ב-Hyp {c.open_debt:>11,.2f}  (פער {c.gap:,.2f})")
            print(f"  לגבייה נטו {c.net_to_collect:>15,.2f}")
            for o in sorted(c.open_docs, key=lambda o: o.doc_date):
                pp = f"  ← ייתכן ששולם: {o.possibly_paid_by.type} {o.possibly_paid_by.num}" if o.possibly_paid_by else ""
                print(f"    {o.doc_date:%d/%m/%Y} {o.type} {o.num} יתרה {o.remaining:,.2f}{pp}")
                for ic, amt, due in o.lines:
                    print(f"        · {ic.desc or '(ללא פירוט)'}: {amt:,.2f}, מגיע {due:,.2f} – {ic.reason}")
            print("  " + " | ".join(c.reasons), "\n")
        return 0 if hits else 1
    path = hyp_report.write(a.out, custs, issues, summary,
                            gap_tol=Decimal(str(cfg.get("alerts", {}).get("formula_gap_tolerance", 100))))
    from collections import Counter
    pr = Counter(c.priority for c in custs)
    print(f"לקוחות {summary['customers']} | חוב פתוח ב-Hyp {summary['open_total']:,.0f} ₪ "
          f"(בלוח {summary['board_total']:,.0f})")
    print("  " + " | ".join(f"{k}: {v}" for k, v in pr.most_common()))
    print(f"בעיות נתונים: {sum(i.severity == 'error' for i in issues)} שגיאות, "
          f"{sum(i.severity == 'warning' for i in issues)} אזהרות\nדוח: {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="debtcheck")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--file")
    r.add_argument("--out", default="debt_report.xlsx")
    r.add_argument("--json")
    r.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    r.add_argument("--customer")
    h = sub.add_parser("hyp", help="ניתוח גבייה: היסטוריית מסמכי Hyp + מסמכים פתוחים מהלוח")
    h.add_argument("--config", required=True)
    h.add_argument("--csv", help="דוח מסמכים מ-Hyp (report.csv). בלעדיו – הלוח בלבד, ללא בקרת הנוסחה")
    h.add_argument("--board", required=True, help="תיקיית תמונת מצב של הלוח (hyp/*.json, custList/*.json)")
    h.add_argument("--out", default="collections_report.xlsx")
    h.add_argument("--pdf-cache", help="תיקיית מטמון להעתקי המסמכים הפתוחים (קריאת שורות הפירוט מהמסמכים עצמם)")
    h.add_argument("--pay-cache", help="תיקיית מטמון למסמכי התשלום (קריאת השיוך \"עבור חשבונית עסקה מספר\")")
    h.add_argument("--board-json", help="תיקייה לכתיבת תוצאות הסוכן בפורמט של הלוח (agent/meta, agent/r*)")
    h.add_argument("--as-of", type=date.fromisoformat)
    h.add_argument("--customer")
    i = sub.add_parser("inspect")
    i.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)

    if a.cmd == "hyp":
        return _run_hyp(a, cfg)

    if a.cmd == "inspect":
        from .sources.monday import iter_columns
        for cid, title in iter_columns(cfg):
            print(f"{cid:<30} {title}")
        return 0

    board, rows = load_rows(cfg, a.file)
    balances, issues = run(cfg, rows, as_of=a.as_of)
    if a.customer:
        q = norm_text(a.customer)
        keys = {customer_key(q), customer_key("", q)}
        hit = [b for b in balances if b.customer_key in keys or q in b.customer_name]
        if not hit:
            print(f"לא נמצא לקוח '{q}'", file=sys.stderr)
            return 1
        for b in hit:
            print(_customer_detail(b), "\n")
        for iss in issues:
            if any(iss.customer == b.customer_name for b in hit):
                print(f"[{iss.severity}] {iss.message} {iss.row_ref}")
        return 0

    path = write_excel(a.out, balances, issues, board=board, as_of=a.as_of)
    print(console_summary(balances, issues))
    print(f"\nדוח: {path}")
    if a.json:
        Path(a.json).write_text(json.dumps([{
            "customer": b.customer_name, "priority": b.priority, "debt": str(b.debt),
            "transactions": str(b.transactions), "tax_invoices": str(b.tax_invoices),
            "tax_invoice_receipts": str(b.tax_invoice_receipts), "credits": str(b.credits),
            "oldest_open_days": b.oldest_open_days, "reasons": b.reasons} for b in balances],
            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
