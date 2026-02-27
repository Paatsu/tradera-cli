from __future__ import annotations

from tradera_cli.formatters import (
    normalize_categories_rows,
    normalize_search_rows,
    to_json,
    to_jsonl,
    to_table,
)


def test_to_json_and_jsonl() -> None:
    assert '"name": "Å"' in to_json({"name": "Å"})
    assert to_jsonl([{"a": 1}, {"a": 2}]) == '{"a": 1}\n{"a": 2}'


def test_to_table_with_rows_and_empty() -> None:
    empty = to_table([], ["id"])
    assert empty == "No results"

    table = to_table([{"id": 1, "name": "Alpha"}], ["id", "name"])
    assert "id" in table
    assert "Alpha" in table


def test_normalize_search_rows_items_and_result() -> None:
    direct = normalize_search_rows(
        {
            "items": [
                {
                    "itemId": 7,
                    "shortDescription": "Camera",
                    "buyNowPrice": 100,
                    "currency": "EUR",
                    "endDate": "2026-01-01",
                    "itemUrl": "/i/7",
                }
            ]
        }
    )
    assert direct[0]["itemId"] == 7
    assert direct[0]["title"] == "Camera"

    nested = normalize_search_rows(
        {
            "result": {
                "items": [
                    {
                        "id": 9,
                        "title": "Phone",
                        "nextBid": 50,
                        "endTime": "2026-01-02",
                        "itemLink": "/i/9",
                    }
                ]
            }
        }
    )
    assert nested[0]["itemId"] == 9
    assert nested[0]["currency"] == "SEK"


def test_normalize_categories_rows_all_input_types() -> None:
    from_categories = normalize_categories_rows({"categories": [{"id": 1, "name": "A", "level": 1}]})
    assert from_categories[0] == {"id": 1, "name": "A", "level": 1}

    from_items = normalize_categories_rows({"items": [{"categoryId": 2, "title": "B"}]})
    assert from_items[0] == {"id": 2, "name": "B", "level": ""}

    from_list = normalize_categories_rows([{"id": 3, "name": "C", "level": 2}])
    assert from_list[0]["id"] == 3

    assert normalize_categories_rows("invalid") == []
