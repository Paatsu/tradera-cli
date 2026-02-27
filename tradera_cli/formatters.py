from __future__ import annotations

import json
from typing import Any


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def to_jsonl(items: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in items)


def to_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "No results"

    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(str(row.get(column, ""))))

    def line(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[col]) for value, col in zip(values, columns))

    header = line(columns)
    sep = "-+-".join("-" * widths[col] for col in columns)
    body = [line([str(row.get(col, "")) for col in columns]) for row in rows]
    return "\n".join([header, sep, *body])


def normalize_search_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items") or data.get("result", {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "itemId": item.get("itemId") or item.get("id"),
                "title": item.get("shortDescription") or item.get("title") or "",
                "price": item.get("buyNowPrice") or item.get("nextBid") or item.get("price") or "",
                "currency": item.get("currency") or "SEK",
                "endDate": item.get("endDate") or item.get("endTime") or "",
                "url": item.get("itemUrl") or item.get("itemLink") or "",
            }
        )
    return rows


def normalize_categories_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        categories = data.get("categories") or data.get("items") or []
    elif isinstance(data, list):
        categories = data
    else:
        categories = []

    rows: list[dict[str, Any]] = []
    for category in categories:
        rows.append(
            {
                "id": category.get("id") or category.get("categoryId"),
                "name": category.get("name") or category.get("title") or "",
                "level": category.get("level") or "",
            }
        )
    return rows
