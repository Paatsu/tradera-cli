from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

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
                "user-agent": "tradera-cli/0.1.1",
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
        page_filters: dict[str, str] = {}
        if search_type:
            page_filters["searchType"] = search_type
        if normalized_item_status in {"Sold", "Unsold"}:
            page_filters["itemStatus"] = normalized_item_status
        if condition:
            page_filters["af-condition"] = condition
        if item_type and item_type != "All":
            page_filters["itemType"] = item_type
        if from_price is not None:
            page_filters["fromPrice"] = str(from_price)
        if to_price is not None:
            page_filters["toPrice"] = str(to_price)
        if allowed_buyer_regions:
            page_filters["allowedBuyerRegions"] = ALLOWED_BUYER_REGIONS[allowed_buyer_regions]
        if counties:
            page_filters["counties"] = ";".join(counties)

        if page_filters:
            return self._search_page(
                query=query,
                page=page,
                sort_by=sort_by,
                language_code_iso2=language_code_iso2,
                filters=page_filters,
            )

        payload: dict[str, Any] = {
            "isCsaSearchQuery": False,
            "query": query,
            "page": page,
            "pageSize": page_size,
            "sortBy": sort_by,
            "languageCodeIso2": language_code_iso2.lower(),
            "shippingCountryCodeIso2": shipping_country_code_iso2.upper(),
            "automaticTranslationPreferred": automatic_translation_preferred,
            "attributeFilters": [],
            "categoryPath": [],
            "currentCategoryId": 0,
            "filterCounties": None,
            "filterCategories": {},
            "filterPrice": {},
            "filters": {},
            "headerText": None,
            "internalSearch": {"showSearchBar": False},
            "introText": None,
            "isSavedSearchEmailEnabled": False,
            "isShopOwnedByCurrentMember": False,
            "items": [],
            "relatedItems": [],
            "itemsOnDisplay": [],
            "mainText": None,
            "pagination": None,
            "totalItems": 0,
            "searchLanguages": [],
            "itemsMatchedViewModel": None,
            "suggestion": None,
        }
        return self._request("POST", "/api/webapi/discover/web/independent-search", json=payload)

    def _search_page(
        self,
        query: str,
        page: int,
        sort_by: str,
        language_code_iso2: str,
        filters: dict[str, str],
    ) -> dict[str, Any]:
        params = {
            "q": query,
            "paging": page,
            "sortBy": sort_by,
            "languageCodeIso2": language_code_iso2.lower(),
        }
        params.update(filters)
        html = self._request("GET", f"/search?{urlencode(params)}")
        if not isinstance(html, str):
            raise TraderaApiError("Unexpected search page response")

        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not match:
            raise TraderaApiError("Could not parse search page response")

        try:
            data = json.loads(match.group(1))
        except ValueError as exc:
            raise TraderaApiError("Invalid search page data") from exc

        discover = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("discover")
        if not isinstance(discover, dict):
            raise TraderaApiError("Unexpected search page data")
        return discover

    def item(self, item_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/ajax/item/{item_id}")
        if not isinstance(data, dict):
            raise TraderaApiError(f"Unexpected item response for item {item_id}")
        return data

    def categories(self, level: int = 1, lang: str = "sv") -> Any:
        return self._request("GET", f"/api/categories/{level}?languageCodeIso2={lang}&next=1")


def parse_item_id(value: str) -> int:
    if value.isdigit():
        return int(value)
    match = re.search(r"/(\d{6,})", value)
    if not match:
        raise ValueError(f"Could not parse item id from: {value}")
    return int(match.group(1))
