"""Board export source (Excel / CSV).

A monday "Export board to Excel" file is not a flat table: it starts with the board name, and each group appears as
a title row followed by its own header row, its items and an empty row. The reader therefore looks for header rows
(rows that contain all the required column titles from the config) and reads data rows until the next empty row.
A flat table with a single header row is the same case with one block. The first header cell (monday: "Name") is
also exposed as "item_name".
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..normalize import norm_text


_SUB_MARKERS = {"Subitems", "Subitem", "תתי פריטים", "תתי-פריטים", "תת פריטים", "פריטי משנה"}


def _required_titles(cfg: dict) -> set[str]:
    cols = cfg["columns"]
    if cfg.get("layout", "documents") == "summary":
        req = {norm_text(v) for v in cfg["summary_columns"].values() if v}
    else:
        req = {norm_text(cols[k]) for k in ("doc_type", "amount") if cols.get(k)}
    req |= {norm_text(cols[k]) for k in ("customer",) if cols.get(k)}
    req.discard("item_name")
    req.discard("parent_name")
    return req


def _load_matrix(path: Path) -> tuple[str, list[list[Any]]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1255"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("קידוד CSV לא מזוהה (נתמך: UTF-8, Windows-1255)")
        return path.stem, list(csv.reader(text.splitlines()))
    raise ValueError(f"סוג קובץ לא נתמך: {path.suffix}")


def read_rows(path: str | Path, cfg: dict) -> tuple[str, list[dict[str, Any]]]:
    path = Path(path)
    title, matrix = _load_matrix(path)
    required = _required_titles(cfg)
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    group = ""
    board_name = title
    in_sub = False
    for i, raw in enumerate(matrix, start=1):
        cells = ["" if v is None else v for v in raw]
        texts = [norm_text(v) for v in cells]
        non_empty = [t for t in texts if t]
        if not non_empty:
            header = None
            continue
        if required and required.issubset(set(texts)):
            header, in_sub = texts, False
            continue
        if texts[0] in _SUB_MARKERS:          # כותרת תתי-פריטים בייצוא monday
            in_sub = True
            continue
        if in_sub and not texts[0]:           # שורת תת-פריט (מוזחת עמודה אחת)
            continue
        in_sub = False
        if header is None:
            if len(non_empty) == 1:
                if i == 1:
                    board_name = non_empty[0]
                group = non_empty[0]
            continue
        row: dict[str, Any] = {"__ref__": f"שורה {i}", "__group__": group}
        for h, v in zip(header, cells):
            if h and h not in row:
                row[h] = v
        row.setdefault("item_name", cells[0] if cells else "")
        rows.append(row)
    if not rows and required:
        raise ValueError(f"לא נמצאה בקובץ שורת כותרות המכילה את העמודות: {', '.join(sorted(required))}")
    return board_name, rows
