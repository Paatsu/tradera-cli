from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from requests import RequestException


BASE_URL = "https://www.tradera.com"
ALLOWED_BUYER_REGIONS = {
    "sweden": "sweden;eu;international",
    "eu": "eu;international",
    "international": "international",
}


class TraderaApiError(RuntimeError):
    pass


@dataclass
class TraderaClient:
    base_url: str = BASE_URL
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if "json" in kwargs:
            headers.setdefault("content-type", "application/json")

        needs_token = path.startswith("/api/webapi/") or path.startswith("/ajax/")
        if needs_token and path != "/api/webapi/auth/web/client/token":
            self._ensure_client_token()

        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=self.timeout_seconds, headers=headers, **kwargs)
        except RequestException as exc:
            raise TraderaApiError(f"Request failed for {path}: {exc}") from exc

        if response.status_code in {400, 401} and needs_token:
            self._ensure_client_token(force=True)
            try:
                response = self.session.request(method, url, timeout=self.timeout_seconds, headers=headers, **kwargs)
            except RequestException as exc:
                raise TraderaApiError(f"Request retry failed for {path}: {exc}") from exc

        if response.status_code >= 400:
            raise TraderaApiError(f"{response.status_code} {response.reason}: {path}")
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except ValueError as exc:
                raise TraderaApiError(f"Invalid JSON response from {path}") from exc
        return response.text

    def _next_data_from_html(self, html: str, context: str) -> dict[str, Any]:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if not match:
            raise TraderaApiError(f"Could not parse {context}")

        try:
            data = json.loads(match.group(1))
        except ValueError as exc:
            raise TraderaApiError(f"Invalid {context}") from exc

        if not isinstance(data, dict):
            raise TraderaApiError(f"Unexpected {context}")
        return data

    def _extract_json_ld_product(self, html: str) -> dict[str, Any] | None:
        # Find all JSON-LD script blocks
        scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for script_content in scripts:
            try:
                data = json.loads(script_content)
                # JSON-LD can be a list of objects or a single object
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        offers = item.get("offers")
                        offer_data = offers if isinstance(offers, dict) else (offers[0] if isinstance(offers, list) and offers else {})

                        availability = offer_data.get("availability", "")
                        status = "Unknown"
                        if "InStock" in availability:
                            status = "Ongoing"
                        elif "OutOfStock" in availability:
                            status = "Ended"

                        return {
                            "itemId": item.get("sku"),
                            "title": item.get("name"),
                            "shortDescription": item.get("name"),
                            "description": item.get("description"),
                            "price": offer_data.get("price"),
                            "buyNowPrice": offer_data.get("price"),
                            "fixedPrice": offer_data.get("price"),
                            "leadingBid": offer_data.get("price"),
                            "openingBid": offer_data.get("price"),
                            "currency": offer_data.get("priceCurrency", "SEK"),
                            "mainImage": item.get("image"),
                            "status": status,
                        }
            except (ValueError, TypeError):
                continue
        return None

    def _ensure_client_token(self, force: bool = False) -> None:
        if not force and self.session.cookies.get("trd_at"):
            return
        try:
            response = self.session.post(
                f"{self.base_url}/api/webapi/auth/web/client/token",
                timeout=self.timeout_seconds,
                headers={"content-type": "application/json", "accept": "application/json"},
            )
        except RequestException as exc:
            raise TraderaApiError(f"Failed to establish anonymous client token: {exc}") from exc
        if response.status_code >= 400:
            raise TraderaApiError("Failed to establish anonymous client token")

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "Relevance",
        language_code_iso2: str = "sv",
        shipping_country_code_iso2: str = "SE",
        automatic_translation_preferred: bool = True,
        item_status: str | None = None,
        condition: str | None = None,
        item_type: str | None = None,
        from_price: int | None = None,
        to_price: int | None = None,
        allowed_buyer_regions: str | None = None,
        counties: list[str] | None = None,
        search_type: str | None = None,
    ) -> dict[str, Any]:
        normalized_item_status = item_status or "Active"
        filters: dict[str, str] = {}
        if search_type:
            filters["searchType"] = search_type
        if normalized_item_status in {"Sold", "Unsold"}:
            filters["itemStatus"] = normalized_item_status
        if condition:
            filters["af-condition"] = condition
        if item_type and item_type != "All":
            filters["itemType"] = item_type
        if from_price is not None:
            filters["fromPrice"] = str(from_price)
        if to_price is not None:
            filters["toPrice"] = str(to_price)
        if allowed_buyer_regions:
            filters["allowedBuyerRegions"] = ALLOWED_BUYER_REGIONS[allowed_buyer_regions]
        if counties:
            filters["counties"] = ";".join(counties)

        return self._search_page(
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            language_code_iso2=language_code_iso2,
            filters=filters,
        )

    def _search_page(
        self,
        query: str,
        page: int,
        page_size: int,
        sort_by: str,
        language_code_iso2: str,
        filters: dict[str, str],
    ) -> dict[str, Any]:
        params = {
            "q": query,
            "paging": page,
            "pageSize": page_size,
            "sortBy": sort_by,
            "languageCodeIso2": language_code_iso2.lower(),
        }
        params.update(filters)
        html = self._request("GET", f"/search?{urlencode(params)}")
        if not isinstance(html, str):
            raise TraderaApiError("Unexpected search page response")

        try:
            data = self._next_data_from_html(html, "search page response")
        except TraderaApiError:
            # Fallback to scraping the HTML for search results
            items = []
            # Find all item links: /item/{catId}/{itemId}/{slug}
            links = re.findall(r'href="/item/([0-9]+)/([0-9]+)/([^"]*)"', html)

            if not links:
                raise TraderaApiError("Could not parse search page response")

            # To avoid duplicates
            seen_ids = set()
            for cat_id, item_id, slug in links:
                if item_id not in seen_ids:
                    items.append({
                        "itemId": item_id,
                        "title": slug.replace("-", " ").replace("_", " ").capitalize(),
                        "url": f"/item/{cat_id}/{item_id}/{slug}",
                        "price": "Unknown",
                        "currency": "SEK",
                        "endDate": None,
                    })
                    seen_ids.add(item_id)

            return {"items": items}

        discover = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("discover")
        if not isinstance(discover, dict):
            raise TraderaApiError("Unexpected search page data")
        return discover

    def item(self, item_id: int) -> dict[str, Any]:
        # Fetch the item page and parse streaming response for item data
        html = self._request("GET", f"/item/{item_id}")
        if not isinstance(html, str):
            raise TraderaApiError(f"Unexpected item page response for item {item_id}")

        # Extract item details from Next.js streaming response
        item_details = self._extract_item_details_from_streaming(html, item_id)
        if not item_details:
            # Fallback to JSON-LD extraction
            json_ld_data = self._extract_json_ld_product(html)
            if json_ld_data:
                json_ld_data.setdefault("currency", "SEK")
                return json_ld_data
            raise TraderaApiError(f"Could not parse item details for item {item_id}")

        # Extract bid info from streaming response
        bid_info = self._extract_bid_info_from_streaming(html)
        if bid_info:
            item_details["bidCount"] = bid_info.get("bidCount")
            item_details["leadingBid"] = bid_info.get("leadingBidAmount")
            item_details["nextBid"] = bid_info.get("nextValidBidAmount")

        # Extract payment calculations from streaming response
        payment_calculations = self._extract_payment_calculations_from_streaming(html)
        if payment_calculations:
            item_details["paymentCalculations"] = payment_calculations

        item_details.setdefault("currency", "SEK")
        return item_details

    def _extract_item_details_from_streaming(self, html: str, item_id: int) -> dict[str, Any] | None:
        """Extract item details from Next.js streaming response."""
        import re
        import json

        # Find the streaming data part
        stream_pos = html.find("self.__next_f.push")
        if stream_pos < 0:
            return None

        streaming = html[stream_pos:]

        # Find itemDetails in streaming data
        item_details_pos = streaming.find("itemDetails")
        if item_details_pos < 0:
            return None

        # Extract the JSON object starting from itemDetails
        start = max(0, item_details_pos - 50)
        end = min(len(streaming), item_details_pos + 30000)
        chunk = streaming[start:end]

        # Find the start of the object
        obj_start = chunk.find("{")
        if obj_start < 0:
            return None

        # Parse by counting braces
        brace_count = 0
        for i, ch in enumerate(chunk[obj_start:], obj_start):
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_str = chunk[obj_start:i+1]
                    # Unescape JSON string
                    json_str = json_str.replace("\\\\", "\\").replace('\\"', '"').replace("\\/", "/")
                    try:
                        data = json.loads(json_str)
                        # The data structure is {"item": {"itemDetails": {...}, ...}, ...}
                        # Extract the itemDetails from the nested structure
                        if isinstance(data, dict):
                            item_obj = data.get("item")
                            if isinstance(item_obj, dict):
                                return item_obj.get("itemDetails", {})
                            return data.get("itemDetails", data)
                        return {}
                    except Exception:
                        return None
        return None

    def _extract_bid_info_from_streaming(self, html: str) -> dict[str, Any] | None:
        """Extract bid info from Next.js streaming response."""
        import re
        import json

        stream_pos = html.find("self.__next_f.push")
        if stream_pos < 0:
            return None

        streaming = html[stream_pos:]
        bid_info_pos = streaming.find("bidInfo")
        if bid_info_pos < 0:
            return None

        start = max(0, bid_info_pos - 50)
        end = min(len(streaming), bid_info_pos + 5000)
        chunk = streaming[start:end]

        obj_start = chunk.find("{")
        if obj_start < 0:
            return None

        brace_count = 0
        for i, ch in enumerate(chunk[obj_start:], obj_start):
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_str = chunk[obj_start:i+1]
                    json_str = json_str.replace("\\\\", "\\").replace('\\"', '"').replace("\\/", "/")
                    try:
                        return json.loads(json_str)
                    except Exception:
                        return None
        return None

    def _extract_payment_calculations_from_streaming(self, html: str) -> dict[str, Any] | None:
        """Extract payment calculations from Next.js streaming response."""
        import re
        import json

        stream_pos = html.find("self.__next_f.push")
        if stream_pos < 0:
            return None

        streaming = html[stream_pos:]
        pc_pos = streaming.find("paymentCalculations")
        if pc_pos < 0:
            return None

        # Find the opening brace for the paymentCalculations object
        # It should be after "paymentCalculations":
        colon_pos = streaming.find(":", pc_pos)
        if colon_pos < 0:
            return None
        obj_start = streaming.find("{", colon_pos)
        if obj_start < 0:
            return None

        # Parse by counting braces
        brace_count = 0
        for i, ch in enumerate(streaming[obj_start:], obj_start):
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_str = streaming[obj_start:i+1]
                    json_str = json_str.replace("\\\\", "\\").replace('\\"', '"').replace("\\/", "/")
                    try:
                        return json.loads(json_str)
                    except Exception:
                        return None
        return None

    def item_payment_calculations(self, item_id: int) -> dict[str, Any]:
        html = self._request("GET", f"/item/{item_id}")
        if not isinstance(html, str):
            raise TraderaApiError(f"Unexpected item page response for item {item_id}")

        payment_calculations = self._extract_payment_calculations_from_streaming(html)
        if not payment_calculations:
            raise TraderaApiError(f"Unexpected payment calculations for item {item_id}")
        return payment_calculations

    def categories(self, level: int = 1, lang: str = "sv") -> Any:
        return self._request("GET", f"/api/categories/{level}?languageCodeIso2={lang}&next=1")


def parse_item_id(value: str) -> int:
    if value.isdigit():
        return int(value)
    parsed = urlparse(value)
    path = parsed.path or value
    segments = [segment for segment in path.split("/") if segment]

    if "item" in segments:
        item_index = segments.index("item")
        numeric_after_item = [segment for segment in segments[item_index + 1 :] if segment.isdigit()]
        if len(numeric_after_item) >= 2:
            return int(numeric_after_item[1])
        if numeric_after_item:
            return int(numeric_after_item[0])

    matches = re.findall(r"(\d{6,})", value)
    if not matches:
        raise ValueError(f"Could not parse item id from: {value}")
    return int(matches[-1])
