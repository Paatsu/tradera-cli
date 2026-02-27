from __future__ import annotations

import argparse
import sys
from typing import Any

from .api import TraderaApiError, TraderaClient, parse_item_id
from .formatters import (
    normalize_categories_rows,
    normalize_search_rows,
    to_json,
    to_jsonl,
    to_table,
)


def _print_output(raw: Any, rows: list[dict[str, Any]], fmt: str, columns: list[str]) -> None:
    if fmt == "json":
        print(to_json(raw))
        return
    if fmt == "jsonl":
        print(to_jsonl(rows))
        return
    print(to_table(rows, columns))


def cmd_search(args: argparse.Namespace) -> int:
    client = TraderaClient()
    data = client.search(
        query=args.query,
        page=args.page,
        page_size=args.page_size,
        sort_by=args.sort,
        language_code_iso2=args.lang,
        shipping_country_code_iso2=args.country,
        automatic_translation_preferred=not args.no_translate,
        item_status=args.item_status,
        condition=args.condition,
        item_type=args.item_type,
        from_price=args.from_price,
        to_price=args.to_price,
        allowed_buyer_regions=args.allowed_buyer_regions,
        counties=args.counties,
        search_type=args.search_type,
    )
    rows = normalize_search_rows(data)
    _print_output(
        raw=data,
        rows=rows,
        fmt=args.format,
        columns=["itemId", "title", "price", "currency", "endDate", "url"],
    )
    return 0


def cmd_item(args: argparse.Namespace) -> int:
    client = TraderaClient()
    item_id = parse_item_id(args.item)
    data = client.item(item_id)
    if args.format == "table":
        row = {
            "itemId": data.get("itemId") or data.get("id") or item_id,
            "title": data.get("shortDescription") or data.get("title") or "",
            "price": data.get("buyNowPrice") or data.get("nextBid") or data.get("price") or "",
            "currency": data.get("currency") or "SEK",
            "seller": (data.get("seller") or {}).get("alias") if isinstance(data.get("seller"), dict) else "",
        }
        print(to_table([row], ["itemId", "title", "price", "currency", "seller"]))
    else:
        print(to_json(data))
    return 0


def cmd_categories(args: argparse.Namespace) -> int:
    client = TraderaClient()
    data = client.categories(level=args.level, lang=args.lang)
    rows = normalize_categories_rows(data)
    _print_output(raw=data, rows=rows, fmt=args.format, columns=["id", "name", "level"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradera", description="Tradera CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search listings")
    search.add_argument("query", help="Search query")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--page-size", type=int, default=50)
    search.add_argument("--sort", default="Relevance")
    search.add_argument("--lang", default="sv")
    search.add_argument("--country", default="SE")
    search.add_argument("--item-status", choices=["Active", "Sold", "Unsold"])
    search.add_argument("--condition", choices=["Oanvänt", "Mycket gott skick", "Gott skick", "Okej skick", "Defekt"])
    search.add_argument("--item-type", choices=["All", "Auction", "FixedPrice", "ContactOnly"])
    search.add_argument("--from-price", type=int)
    search.add_argument("--to-price", type=int)
    search.add_argument("--allowed-buyer-regions", choices=["sweden", "eu", "international"])
    search.add_argument("--counties", nargs="+")
    search.add_argument("--search-type", choices=["ExactSearch"])
    search.add_argument("--no-translate", action="store_true")
    search.add_argument("--format", choices=["table", "json", "jsonl"], default="table")
    search.set_defaults(func=cmd_search)

    item = subparsers.add_parser("item", help="Get item details")
    item.add_argument("item", help="Item id or item URL")
    item.add_argument("--format", choices=["table", "json"], default="json")
    item.set_defaults(func=cmd_item)

    categories = subparsers.add_parser("categories", help="List categories by level")
    categories.add_argument("--level", type=int, default=1)
    categories.add_argument("--lang", default="sv")
    categories.add_argument("--format", choices=["table", "json", "jsonl"], default="table")
    categories.set_defaults(func=cmd_categories)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = args.func(args)
    except (TraderaApiError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)
