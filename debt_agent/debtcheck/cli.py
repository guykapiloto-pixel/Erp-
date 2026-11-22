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
    i = sub.add_parser("inspect")
    i.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)

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
