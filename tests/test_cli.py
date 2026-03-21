from __future__ import annotations

import argparse

import pytest

import tradera_cli.cli as cli
from tradera_cli.api import TraderaApiError


class DummyClient:
    def __init__(self, payload: dict | list | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def search(self, **_kwargs: object) -> dict:
        if self.error:
            raise self.error
        return self.payload or {"items": []}

    def item(self, _item_id: int) -> dict:
        if self.error:
            raise self.error
        return self.payload or {}

    def item_payment_calculations(self, _item_id: int) -> dict:
        if self.error:
            raise self.error
        return {}

    def categories(self, **_kwargs: object) -> list:
        if self.error:
            raise self.error
        return self.payload or []


def test_print_output_json(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_output(raw={"a": 1}, rows=[], fmt="json", columns=[])
    out = capsys.readouterr().out
    assert '"a": 1' in out


def test_print_output_jsonl(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_output(raw={}, rows=[{"a": 1}], fmt="jsonl", columns=["a"])
    out = capsys.readouterr().out.strip()
    assert out == '{"a": 1}'


def test_print_output_table(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_output(raw={}, rows=[{"a": "x"}], fmt="table", columns=["a"])
    out = capsys.readouterr().out
    assert "a" in out
    assert "x" in out


def test_cmd_search_and_no_translate(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: dict[str, object] = {}

    class SearchClient(DummyClient):
        def search(self, **kwargs: object) -> dict:
            calls.update(kwargs)
            return {"items": [{"id": 1, "title": "A"}]}

    monkeypatch.setattr(cli, "TraderaClient", SearchClient)
    args = argparse.Namespace(
        query="camera",
        page=1,
        page_size=2,
        sort="Relevance",
        lang="sv",
        country="SE",
        item_status="Sold",
        condition="Oanvänt",
        item_type="FixedPrice",
        from_price=100,
        to_price=500,
        allowed_buyer_regions="eu",
        counties=["Stockholm", "Uppsala"],
        search_type="ExactSearch",
        no_translate=True,
        format="table",
    )

    code = cli.cmd_search(args)

    assert code == 0
    assert calls["automatic_translation_preferred"] is False
    assert calls["item_status"] == "Sold"
    assert calls["condition"] == "Oanvänt"
    assert calls["item_type"] == "FixedPrice"
    assert calls["from_price"] == 100
    assert calls["to_price"] == 500
    assert calls["allowed_buyer_regions"] == "eu"
    assert calls["counties"] == ["Stockholm", "Uppsala"]
    assert calls["search_type"] == "ExactSearch"
    out = capsys.readouterr().out
    assert "itemId" in out


def test_cmd_item_table_json_and_jsonl(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class ItemClient(DummyClient):
        def item(self, _item_id: int) -> dict:
            return {
                "itemId": 12,
                "shortDescription": "Demo",
                "buyNowPrice": 99,
                "currency": "SEK",
                "buyerProtectionInfo": {"totalPrice": 109, "fee": 10},
                "seller": {"alias": "john"},
            }

        def item_payment_calculations(self, _item_id: int) -> dict:
            return {}

    monkeypatch.setattr(cli, "TraderaClient", ItemClient)

    table_args = argparse.Namespace(item="12", format="table")
    assert cli.cmd_item(table_args) == 0
    table_out = capsys.readouterr().out
    assert "seller" in table_out
    assert "john" in table_out
    assert "buyerProtectionTotal" in table_out
    assert "109" in table_out
    assert "10" in table_out

    json_args = argparse.Namespace(item="12", format="json")
    assert cli.cmd_item(json_args) == 0
    json_out = capsys.readouterr().out
    assert '"itemId": 12' in json_out
    assert '"buyerProtectionTotal": 109' in json_out
    assert '"buyerProtectionFee": 10' in json_out

    jsonl_args = argparse.Namespace(item="12", format="jsonl")
    assert cli.cmd_item(jsonl_args) == 0
    jsonl_out = capsys.readouterr().out.strip()
    assert '"itemId": 12' in jsonl_out
    assert '"buyerProtectionTotal": 109' in jsonl_out
    assert '"buyerProtectionFee": 10' in jsonl_out
    assert "\n" not in jsonl_out


def test_cmd_item_table_handles_non_dict_seller(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class ItemClient(DummyClient):
        def item(self, _item_id: int) -> dict:
            return {"id": 33, "title": "No seller dict", "seller": "none"}

        def item_payment_calculations(self, _item_id: int) -> dict:
            return {}

    monkeypatch.setattr(cli, "TraderaClient", ItemClient)

    args = argparse.Namespace(item="33", format="table")
    assert cli.cmd_item(args) == 0
    out = capsys.readouterr().out
    assert "No seller dict" in out


def test_cmd_item_table_supports_hyphenated_buyer_protection_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class ItemClient(DummyClient):
        def item(self, _item_id: int) -> dict:
            return {
                "id": 44,
                "title": "With fee",
                "buyer-protection-info": {"priceTotal": 220, "serviceFee": 20},
            }

        def item_payment_calculations(self, _item_id: int) -> dict:
            return {}

    monkeypatch.setattr(cli, "TraderaClient", ItemClient)

    args = argparse.Namespace(item="44", format="table")
    assert cli.cmd_item(args) == 0
    out = capsys.readouterr().out
    assert "buyerProtectionTotal" in out
    assert "220" in out
    assert "20" in out


def test_cmd_item_table_uses_payment_calculations_for_bid_total(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class ItemClient(DummyClient):
        def item(self, _item_id: int) -> dict:
            return {
                "itemId": 55,
                "shortDescription": "Auction item",
                "leadingBid": 4690,
                "bidCount": 1,
                "currency": "SEK",
                "seller": {"alias": "john"},
            }

        def item_payment_calculations(self, _item_id: int) -> dict:
            return {"paymentAmountForBid": 4927}

    monkeypatch.setattr(cli, "TraderaClient", ItemClient)

    args = argparse.Namespace(item="55", format="table")
    assert cli.cmd_item(args) == 0
    out = capsys.readouterr().out
    assert "buyerProtectionTotal" in out
    assert "4927" in out
    assert "237" in out
    assert "4690" in out


def test_cmd_categories_jsonl(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class CategoriesClient(DummyClient):
        def categories(self, **_kwargs: object) -> list:
            return [{"id": 1, "name": "Cat", "level": 1}]

    monkeypatch.setattr(cli, "TraderaClient", CategoriesClient)
    args = argparse.Namespace(level=1, lang="sv", format="jsonl")

    code = cli.cmd_categories(args)

    assert code == 0
    out = capsys.readouterr().out.strip()
    assert '"name": "Cat"' in out


def test_build_parser_has_expected_program() -> None:
    parser = cli.build_parser()
    assert parser.prog == "tradera"


def test_main_success_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "TraderaClient", lambda: DummyClient(payload={"items": []}))

    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "phone", "--format", "json"])

    assert exc.value.code == 0


def test_main_tradera_error_exits_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "TraderaClient", lambda: DummyClient(error=TraderaApiError("boom")))

    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "phone"])

    assert exc.value.code == 2
    assert "Error: boom" in capsys.readouterr().err


def test_main_value_error_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["item", "not-an-id"])

    assert exc.value.code == 2
    assert "Error:" in capsys.readouterr().err
