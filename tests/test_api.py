from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import requests
import pytest

from tradera_cli.api import TraderaApiError, TraderaClient, parse_item_id


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
        json_data: object | None = None,
        text: str = "",
        bad_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.headers = headers or {}
        self._json_data = json_data
        self.text = text
        self._bad_json = bad_json

    def json(self) -> object:
        if self._bad_json:
            raise ValueError("bad json")
        return self._json_data


class FakeSession:
    def __init__(
        self,
        request_results: list[FakeResponse | Exception] | None = None,
        post_results: list[FakeResponse | Exception] | None = None,
    ) -> None:
        self.request_results = request_results or []
        self.post_results = post_results or []
        self.request_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.request_calls.append({"method": method, "url": url, **kwargs})
        result = self.request_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        result = self.post_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_request_returns_json_and_sets_content_type() -> None:
    client = TraderaClient()
    fake = FakeSession(
        request_results=[
            FakeResponse(headers={"content-type": "application/json"}, json_data={"ok": True})
        ]
    )
    client.session = fake

    result = client._request("POST", "/public", json={"a": 1})

    assert result == {"ok": True}
    assert fake.request_calls[0]["headers"] == {"content-type": "application/json"}


def test_request_returns_text_for_non_json_response() -> None:
    client = TraderaClient()
    fake = FakeSession(request_results=[FakeResponse(headers={"content-type": "text/html"}, text="hello")])
    client.session = fake

    result = client._request("GET", "/public")

    assert result == "hello"


def test_request_ensures_token_and_retries_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TraderaClient()
    fake = FakeSession(
        request_results=[
            FakeResponse(status_code=401, reason="Unauthorized", headers={"content-type": "application/json"}),
            FakeResponse(headers={"content-type": "application/json"}, json_data={"ok": 1}),
        ]
    )
    client.session = fake

    calls: list[bool] = []

    def fake_ensure(force: bool = False) -> None:
        calls.append(force)

    monkeypatch.setattr(client, "_ensure_client_token", fake_ensure)

    result = client._request("GET", "/api/webapi/discover/web/independent-search")

    assert result == {"ok": 1}
    assert calls == [False, True]


def test_request_raises_for_http_error() -> None:
    client = TraderaClient()
    fake = FakeSession(request_results=[FakeResponse(status_code=500, reason="Server Error")])
    client.session = fake

    with pytest.raises(TraderaApiError, match="500 Server Error"):
        client._request("GET", "/public")


def test_request_wraps_request_exception() -> None:
    client = TraderaClient()
    fake = FakeSession(request_results=[requests.RequestException("boom")])
    client.session = fake

    with pytest.raises(TraderaApiError, match="Request failed"):
        client._request("GET", "/public")


def test_request_wraps_retry_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TraderaClient()
    fake = FakeSession(
        request_results=[
            FakeResponse(status_code=400, reason="Bad Request"),
            requests.RequestException("retry boom"),
        ]
    )
    client.session = fake
    monkeypatch.setattr(client, "_ensure_client_token", lambda force=False: None)

    with pytest.raises(TraderaApiError, match="Request retry failed"):
        client._request("GET", "/ajax/item/123")


def test_request_raises_on_bad_json() -> None:
    client = TraderaClient()
    fake = FakeSession(request_results=[FakeResponse(headers={"content-type": "application/json"}, bad_json=True)])
    client.session = fake

    with pytest.raises(TraderaApiError, match="Invalid JSON response"):
        client._request("GET", "/public")


def test_ensure_client_token_skips_when_cookie_exists() -> None:
    client = TraderaClient()
    fake = FakeSession()
    fake.cookies["trd_at"] = "token"
    client.session = fake

    client._ensure_client_token()

    assert fake.post_calls == []


def test_ensure_client_token_success_and_force() -> None:
    client = TraderaClient()
    fake = FakeSession(post_results=[FakeResponse(status_code=200)])
    fake.cookies["trd_at"] = "token"
    client.session = fake

    client._ensure_client_token(force=True)

    assert len(fake.post_calls) == 1


def test_ensure_client_token_wraps_request_exception() -> None:
    client = TraderaClient()
    fake = FakeSession(post_results=[requests.RequestException("nope")])
    client.session = fake

    with pytest.raises(TraderaApiError, match="Failed to establish anonymous client token"):
        client._ensure_client_token()


def test_ensure_client_token_raises_on_http_error() -> None:
    client = TraderaClient()
    fake = FakeSession(post_results=[FakeResponse(status_code=500)])
    client.session = fake

    with pytest.raises(TraderaApiError, match="Failed to establish anonymous client token"):
        client._ensure_client_token()


def test_search_builds_payload() -> None:
    client = TraderaClient()
    captured: dict[str, object] = {}

    def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return {"items": []}

    client._request = fake_request  # type: ignore[method-assign]

    result = client.search("kamera", page=2, page_size=10, sort_by="EndDate")

    assert result == {"items": []}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/webapi/discover/web/independent-search"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["query"] == "kamera"
    assert payload["page"] == 2
    assert payload["pageSize"] == 10
    assert payload["sortBy"] == "EndDate"


def test_search_uses_search_page_for_sold_items() -> None:
    client = TraderaClient()
    captured: dict[str, object] = {}
    next_data = {
        "props": {
            "pageProps": {
                "initialState": {
                    "discover": {
                        "items": [{"itemId": 42, "isActive": False}],
                        "filters": {"itemStatus": {"selectedValue": "Sold"}},
                    }
                }
            }
        }
    }

    def fake_request(method: str, path: str, **_kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(next_data)}"
            "</script>"
        )

    client._request = fake_request  # type: ignore[method-assign]

    result = client.search("kamera", page=3, sort_by="EndDate", item_status="Sold")

    assert result["items"][0]["itemId"] == 42
    assert captured["method"] == "GET"
    parsed = urlparse(str(captured["path"]))
    assert parsed.path == "/search"
    assert parse_qs(parsed.query) == {
        "q": ["kamera"],
        "paging": ["3"],
        "sortBy": ["EndDate"],
        "languageCodeIso2": ["sv"],
        "itemStatus": ["Sold"],
    }


def test_search_uses_search_page_for_condition_filter() -> None:
    client = TraderaClient()
    captured: dict[str, object] = {}
    next_data = {
        "props": {
            "pageProps": {
                "initialState": {
                    "discover": {
                        "items": [{"itemId": 99}],
                        "attributeFilters": [{"parameter": "af-condition", "selectedValues": ["Oanvänt"]}],
                    }
                }
            }
        }
    }

    def fake_request(method: str, path: str, **_kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(next_data, ensure_ascii=False)}"
            "</script>"
        )

    client._request = fake_request  # type: ignore[method-assign]

    result = client.search("kamera", condition="Oanvänt")

    assert result["items"][0]["itemId"] == 99
    assert captured["method"] == "GET"
    parsed = urlparse(str(captured["path"]))
    assert parsed.path == "/search"
    assert parse_qs(parsed.query) == {
        "q": ["kamera"],
        "paging": ["1"],
        "sortBy": ["Relevance"],
        "languageCodeIso2": ["sv"],
        "af-condition": ["Oanvänt"],
    }


def test_search_uses_search_page_for_additional_page_filters() -> None:
    client = TraderaClient()
    captured: dict[str, object] = {}
    next_data = {
        "props": {
            "pageProps": {
                "initialState": {
                    "discover": {
                        "items": [{"itemId": 77}],
                        "filters": {
                            "itemType": {"selectedValue": "FixedPrice"},
                            "allowedBuyerRegions": {"selectedValue": "eu;international"},
                        },
                        "filterPrice": {
                            "fromPrice": {"parameter": "fromPrice", "value": 100},
                            "toPrice": {"parameter": "toPrice", "value": 500},
                        },
                        "filterCounties": {"selectedValues": ["Stockholm", "Uppsala"]},
                    }
                }
            }
        }
    }

    def fake_request(method: str, path: str, **_kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(next_data, ensure_ascii=False)}"
            "</script>"
        )

    client._request = fake_request  # type: ignore[method-assign]

    result = client.search(
        "kamera",
        item_type="FixedPrice",
        from_price=100,
        to_price=500,
        allowed_buyer_regions="eu",
        counties=["Stockholm", "Uppsala"],
    )

    assert result["items"][0]["itemId"] == 77
    assert captured["method"] == "GET"
    parsed = urlparse(str(captured["path"]))
    assert parsed.path == "/search"
    assert parse_qs(parsed.query) == {
        "q": ["kamera"],
        "paging": ["1"],
        "sortBy": ["Relevance"],
        "languageCodeIso2": ["sv"],
        "itemType": ["FixedPrice"],
        "fromPrice": ["100"],
        "toPrice": ["500"],
        "allowedBuyerRegions": ["eu;international"],
        "counties": ["Stockholm;Uppsala"],
    }


def test_search_uses_search_page_for_search_type() -> None:
    client = TraderaClient()
    captured: dict[str, object] = {}
    next_data = {
        "props": {
            "pageProps": {
                "initialState": {
                    "discover": {
                        "items": [{"itemId": 88}],
                        "queryParams": {"q": "kamera", "searchType": "ExactSearch"},
                    }
                }
            }
        }
    }

    def fake_request(method: str, path: str, **_kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(next_data)}"
            "</script>"
        )

    client._request = fake_request  # type: ignore[method-assign]

    result = client.search("kamera", search_type="ExactSearch")

    assert result["items"][0]["itemId"] == 88
    assert captured["method"] == "GET"
    parsed = urlparse(str(captured["path"]))
    assert parsed.path == "/search"
    assert parse_qs(parsed.query) == {
        "q": ["kamera"],
        "paging": ["1"],
        "sortBy": ["Relevance"],
        "languageCodeIso2": ["sv"],
        "searchType": ["ExactSearch"],
    }


def test_search_page_raises_when_next_data_is_missing() -> None:
    client = TraderaClient()
    client._request = lambda *_args, **_kwargs: "<html></html>"  # type: ignore[method-assign]

    with pytest.raises(TraderaApiError, match="Could not parse search page response"):
        client.search("kamera", item_status="Unsold")


def test_item_returns_dict_or_raises() -> None:
    client = TraderaClient()
    client._request = lambda *_args, **_kwargs: {"itemId": 123}  # type: ignore[method-assign]
    assert client.item(123)["itemId"] == 123

    client._request = lambda *_args, **_kwargs: "not a dict"  # type: ignore[method-assign]
    with pytest.raises(TraderaApiError, match="Unexpected item response"):
        client.item(123)


def test_categories_calls_expected_path() -> None:
    client = TraderaClient()
    captured: dict[str, str] = {}

    def fake_request(method: str, path: str, **_kwargs: object) -> list[dict[str, object]]:
        captured["method"] = method
        captured["path"] = path
        return [{"id": 1}]

    client._request = fake_request  # type: ignore[method-assign]

    result = client.categories(level=2, lang="en")

    assert result == [{"id": 1}]
    assert captured == {"method": "GET", "path": "/api/categories/2?languageCodeIso2=en&next=1"}


def test_parse_item_id_from_digits_and_url_and_invalid() -> None:
    assert parse_item_id("123456") == 123456
    assert parse_item_id("https://www.tradera.com/item/123456789/test") == 123456789
    with pytest.raises(ValueError, match="Could not parse item id"):
        parse_item_id("https://www.tradera.com/item/no-id")
