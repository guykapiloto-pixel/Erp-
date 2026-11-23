"""Reading the open documents themselves: download the Hyp PDF copy of each open document and extract its line items.

The board keeps a link to the PDF copy of every open document (hyp/opendocs: copyPath). The PDF text holds the item
lines ("פריטים": מק"ט, פירוט, כמות, מחיר, סכום), which say what the charge is for (דו"ח 25, מאזן 2025, הנה"ח 01-12/26...).
Downloads are cached on disk (customer data – never inside the repository).
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")
_MONEY = r"-?₪-?[\d,]+\.\d\d"
_ITEM = re.compile(rf"^\s*({_MONEY})\s+({_MONEY})\s+(-?[\d,]+\.\d+)\s+(.*?)\s*$")
_ITEM2 = re.compile(rf"^\s*(?:לפני הנחה)?\s*({_MONEY})\s+(-?[\d,]+\.\d+)\s+(.*?)\s*$")


def _num(s: str) -> Decimal:
    return Decimal(s.replace("₪", "").replace(",", ""))


def parse_pdf_text(text: str) -> dict:
    """-> {"items": [{"desc", "sku", "qty", "price", "amount"}], "note": str}. amount is before VAT."""
    lines = [_BIDI.sub("", ln).rstrip() for ln in text.splitlines()]
    items, note, mode, title, prev = [], [], None, "", ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("פריטים"):
            mode = "items"
            # כותרת המסמך: השורה שמעל "פריטים", אם אינה שורת סוג ומספר המסמך
            title = "" if re.search(r"מספר\s+\d+$", prev) else prev
            continue
        if mode is None and s:
            prev = s
        if s.startswith("הערה מצורפת"):
            mode = "note"
            continue
        if mode == "items":
            if s.startswith("סה\"כ") or s.startswith("מע\"מ") or s.startswith("הנחה") or s.startswith("עיגול"):
                if s.startswith("סה\"כ:") or s.startswith("סה\"כ לתשלום"):
                    mode = None
                continue
            m = _ITEM.match(ln)
            if m:
                rest = m.group(4)
                sku = ""
                ms = re.search(r"\s{2,}(\S+)$", rest)
                if ms:
                    sku, rest = ms.group(1), rest[:ms.start()]
                items.append({"desc": re.sub(r"\s+", " ", rest).strip(), "sku": sku, "qty": str(_num(m.group(3))),
                              "price": str(_num(m.group(2))), "amount": str(_num(m.group(1)))})
            elif _ITEM2.match(ln):
                # שורה עם הנחת שורה: "לפני הנחה  ₪מחיר כמות  פירוט  מק"ט" – הסכום נטו מופיע בשורות הבאות
                m2 = _ITEM2.match(ln)
                rest, sku = m2.group(3), ""
                ms = re.search(r"\s{2,}(\S+)$", rest)
                if ms:
                    sku, rest = ms.group(1), rest[:ms.start()]
                price, qty = _num(m2.group(1)), _num(m2.group(2))
                items.append({"desc": re.sub(r"\s+", " ", rest).strip(), "sku": sku, "qty": str(qty),
                              "price": str(price), "amount": str(price * qty), "discounted": True})
            elif re.fullmatch(_MONEY, s) and items and items[-1].get("discounted") and not s.startswith("₪-") \
                    and not s.startswith("-"):
                items[-1]["amount"] = str(_num(s))        # הסכום האחרון בבלוק ההנחה הוא הנטו
            elif s and items and not s.startswith("סכום") and "₪" not in s and "הנחת שורה" not in s:
                items[-1]["desc"] = (items[-1]["desc"] + " " + re.sub(r"\s+", " ", s)).strip()   # המשך תיאור
        elif mode == "note" and s and "www.hyp.co.il" not in s and not re.fullmatch(r"\d+/\d+", s):
            note.append(s)
    for i in items:
        i.pop("discounted", None)
        i["desc"] = re.sub(r"\s*הופק על ידי www\.hyp\.co\.il.*$", "", i["desc"]).strip()
    return {"items": items, "note": " ".join(note), "title": title}


def _fetch_one(url: str, pdf: Path) -> str:
    if not pdf.exists() or pdf.stat().st_size < 500:
        req = urllib.request.Request(url, headers={"User-Agent": "debtcheck"})
        with urllib.request.urlopen(req, timeout=40) as r:
            pdf.write_bytes(r.read())
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=60).stdout


def load_items(open_docs: list[tuple[str, str, str]], cache_dir: str | Path, workers: int = 12) -> tuple[dict, list]:
    """open_docs: [(type, number, url)]. Returns ({(type, number): parsed}, [(type, number, error)])."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    idx_path = cache / "items.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    errors, todo = [], []
    for typ, num, url in open_docs:
        k = f"{typ}|{num}"
        if k not in idx and url:
            todo.append((k, url))

    def work(t):
        k, url = t
        try:
            return k, parse_pdf_text(_fetch_one(url, cache / (re.sub(r"\W", "_", k) + ".pdf"))), None
        except Exception as e:  # noqa: BLE001 – כל כשל הורדה/פענוח מדווח ואינו עוצר את הריצה
            return k, None, f"{type(e).__name__}: {e}"

    if todo:
        with ThreadPoolExecutor(workers) as ex:
            for k, parsed, err in ex.map(work, todo):
                if parsed is not None:
                    idx[k] = parsed
                else:
                    errors.append((*k.split("|"), err))
        idx_path.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return {tuple(k.split("|")): v for k, v in idx.items()}, errors
