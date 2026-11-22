"""monday.com GraphQL source.

Reads every item of the board with cursor pagination (items_page / next_items_page, up to 500 per page) and returns
rows as {column title: text, column id: text, "item_name": name, "__ref__": item id, "__group__": group title}.
Formula / mirror / connect-boards columns return an empty `text` in the API, so `display_value` is requested for them.
If `source.use_subitems` is true, every subitem is a row and the parent item name is exposed as "parent_name".
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

API_URL = "https://api.monday.com/v2"
API_VERSION = "2025-04"

_CV = """column_values { id text type
  ... on FormulaValue { display_value }
  ... on MirrorValue { display_value }
  ... on BoardRelationValue { display_value } }"""

_ITEM = "id name group { title } " + _CV
_ITEM_SUB = _ITEM + " subitems { id name " + _CV + " }"

_FIRST = """query ($board: [ID!], $limit: Int!) { boards(ids: $board) { name
  columns { id title } items_page(limit: $limit) { cursor items { %s } } } }"""
_NEXT = """query ($cursor: String!, $limit: Int!) { next_items_page(cursor: $cursor, limit: $limit) {
  cursor items { %s } } }"""
_SUB_COLUMNS = """query ($board: [ID!]) { boards(ids: $board) { columns(types: [subtasks]) { settings_str } } }"""
_COLUMNS = """query ($ids: [ID!]) { boards(ids: $ids) { columns { id title } } }"""


class MondayError(RuntimeError):
    pass


class MondayClient:
    def __init__(self, token: str | None = None, *, transport=None, max_retries: int = 5):
        self.token = token or os.environ.get("MONDAY_API_TOKEN", "")
        if not self.token and transport is None:
            raise MondayError("חסר MONDAY_API_TOKEN (Profile > Developers > API token)")
        self._transport = transport or self._http
        self.max_retries = max_retries

    def _http(self, payload: dict) -> dict:
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), method="POST", headers={
            "Authorization": self.token, "Content-Type": "application/json", "API-Version": API_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return {"__retry_after__": int(e.headers.get("Retry-After", "30"))}
            raise MondayError(f"HTTP {e.code}: {e.read()[:300]!r}") from e

    def query(self, q: str, variables: dict) -> dict:
        for attempt in range(self.max_retries):
            res = self._transport({"query": q, "variables": variables})
            if "__retry_after__" in res:
                time.sleep(res["__retry_after__"])
                continue
            errs = res.get("errors") or ([res] if res.get("error_code") else [])
            if errs:
                text = json.dumps(errs, ensure_ascii=False)
                if any(k in text for k in ("Complexity", "RATE_LIMIT", "rate limit")) and attempt < self.max_retries - 1:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                raise MondayError(text[:500])
            return res["data"]
        raise MondayError("monday: חריגה ממספר הניסיונות החוזרים")


def _cv_text(cv: dict) -> str:
    t = cv.get("text")
    if t in (None, "") and cv.get("display_value") not in (None, ""):
        t = cv["display_value"]
    return t or ""


def _row(item: dict, titles: dict[str, str], group: str, parent: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {"__ref__": item["id"], "__group__": group, "item_name": item.get("name", ""),
                           "parent_name": parent}
    for cv in item.get("column_values", []):
        txt = _cv_text(cv)
        row[cv["id"]] = txt
        title = titles.get(cv["id"])
        if title and title not in row:
            row[title] = txt
    return row


def fetch_rows(cfg: dict, client: MondayClient | None = None) -> tuple[str, list[dict[str, Any]]]:
    src = cfg["source"]
    board = str(src["board_id"])
    limit = int(src.get("page_size", 500))
    subs = bool(src.get("use_subitems", False))
    client = client or MondayClient()

    item_q = _ITEM_SUB if subs else _ITEM
    data = client.query(_FIRST % item_q, {"board": [board], "limit": limit})
    boards = data.get("boards") or []
    if not boards:
        raise MondayError(f"הלוח {board} לא נמצא או שאין הרשאה אליו")
    b = boards[0]
    titles = {c["id"]: c["title"] for c in b["columns"]}
    sub_titles: dict[str, str] = {}
    if subs:
        sub_titles = _subitem_titles(client, board)

    rows: list[dict[str, Any]] = []
    page = b["items_page"]
    while True:
        for it in page["items"]:
            g = (it.get("group") or {}).get("title", "")
            if subs:
                for s in it.get("subitems") or []:
                    rows.append(_row(s, sub_titles, g, it["name"]))
            else:
                rows.append(_row(it, titles, g))
        if not page.get("cursor"):
            break
        page = client.query(_NEXT % item_q, {"cursor": page["cursor"], "limit": limit})["next_items_page"]
    return b["name"], rows


def _subitem_titles(client: MondayClient, board: str) -> dict[str, str]:
    data = client.query(_SUB_COLUMNS, {"board": [board]})
    cols = data["boards"][0]["columns"]
    if not cols:
        return {}
    ids = json.loads(cols[0]["settings_str"]).get("boardIds", [])
    if not ids:
        return {}
    d = client.query(_COLUMNS, {"ids": [str(i) for i in ids]})
    return {c["id"]: c["title"] for c in d["boards"][0]["columns"]}


def iter_columns(cfg: dict, client: MondayClient | None = None) -> Iterator[tuple[str, str]]:
    """For `debtcheck inspect`: list (id, title) of the board columns to fill in the config."""
    client = client or MondayClient()
    d = client.query(_COLUMNS, {"ids": [str(cfg["source"]["board_id"])]})
    for c in d["boards"][0]["columns"]:
        yield c["id"], c["title"]
