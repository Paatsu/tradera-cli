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
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not match:
            raise TraderaApiError(f"Could not parse {context}")

        try:
            data = json.loads(match.group(1))
        except ValueError as exc:
            raise TraderaApiError(f"Invalid {context}") from exc

        if not isinstance(data, dict):
            raise TraderaApiError(f"Unexpected {context}")
        return data

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

        data = self._next_data_from_html(html, "search page response")

        discover = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("discover")
        if not isinstance(discover, dict):
            raise TraderaApiError("Unexpected search page data")
        return discover

    def item(self, item_id: int) -> dict[str, Any]:
        try:
            return self._item_from_page(item_id)
        except TraderaApiError:
            data = self._request("GET", f"/ajax/item/{item_id}")
        if not isinstance(data, dict):
            raise TraderaApiError(f"Unexpected item response for item {item_id}")
        return data

    def _item_page_state(self, item_id: int) -> dict[str, Any]:
        html = self._request("GET", f"/item/{item_id}")
        if not isinstance(html, str):
            raise TraderaApiError(f"Unexpected item page response for item {item_id}")

        data = self._next_data_from_html(html, f"item page response for item {item_id}")

        view_item = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialState", {})
            .get("views", {})
            .get("viewItem", {})
        )
        if not isinstance(view_item, dict):
            raise TraderaApiError(f"Unexpected item page data for item {item_id}")
        return view_item

    def _item_from_page(self, item_id: int) -> dict[str, Any]:
        view_item = self._item_page_state(item_id)
        item_details = view_item.get("itemDetails")
        if not isinstance(item_details, dict) or not item_details:
            raise TraderaApiError(f"Unexpected item response for item {item_id}")

        data = dict(item_details)
        bid_info = view_item.get("bidInfo")
        if isinstance(bid_info, dict):
            if bid_info.get("bidCount") is not None:
                data.setdefault("bidCount", bid_info.get("bidCount"))
            if bid_info.get("leadingBidAmount") is not None:
                data.setdefault("leadingBid", bid_info.get("leadingBidAmount"))
            if bid_info.get("nextValidBidAmount") is not None:
                data.setdefault("nextBid", bid_info.get("nextValidBidAmount"))

        purchase_info = view_item.get("purchaseInfo")
        if isinstance(purchase_info, dict) and purchase_info.get("finalPrice") is not None:
            data.setdefault("price", purchase_info.get("finalPrice"))
            data.setdefault("finalPrice", purchase_info.get("finalPrice"))

        data.setdefault("currency", "SEK")
        return data

    def item_payment_calculations(self, item_id: int) -> dict[str, Any]:
        item_details = self._item_page_state(item_id).get("itemDetails", {})
        if not isinstance(item_details, dict):
            raise TraderaApiError(f"Unexpected payment calculations for item {item_id}")
        payment_calculations = item_details.get("paymentCalculations", {})
        if not isinstance(payment_calculations, dict):
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
